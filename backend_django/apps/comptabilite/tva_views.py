"""Préparation mensuelle TVA à partir des écritures ; aucune déclaration déposée."""
import calendar
import re
from datetime import date
from decimal import Decimal
from django.db.models import Q
from django.db import transaction
from django.db.models import F
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from core.auth import assert_acces_societe, assert_role
from apps.comptabilite import services as comptabilite
from core import services as services
from apps.comptabilite.models import LigneEcriture, PreparationTVA
from apps.commercial.models import Facture, LigneFacture, FraisFacture
from core.models import Tiers, Societe
from core.views import _societe_param


def periode_mensuelle(value):
    if not re.fullmatch(r'\d{4}-\d{2}', value or ''):
        raise ValidationError('Choisissez un mois au format AAAA-MM.')
    try:
        an, mois = map(int, value.split('-'))
        return date(an, mois, 1), date(an, mois, calendar.monthrange(an, mois)[1])
    except ValueError:
        raise ValidationError('Mois invalide.')


@api_view(['GET'])
def preparation(request):
    sid = _societe_param(request)
    assert_role(assert_acces_societe(request.user, sid), {'DFI', 'COMPTABLE'})
    mois = request.query_params.get('mois', date.today().strftime('%Y-%m'))
    return Response(rapport_tva(sid, mois))


def rapport_tva(sid, mois):
    du, au = periode_mensuelle(mois)
    collecte = comptabilite._compte('tva_collectee', sid)
    deduction = comptabilite._compte('tva_deductible', sid)
    if not collecte or not deduction or collecte.startswith(deduction) or deduction.startswith(collecte):
        raise ValidationError('Les comptes TVA collectée et déductible doivent être distincts, sans recouvrement.')
    lignes = LigneEcriture.objects.select_related('ecriture').filter(
        societe_id=sid, ecriture__societe_id=sid,
        ecriture__date_ecriture__range=(du, au)).filter(
            Q(compte_numero__startswith=collecte) | Q(compte_numero__startswith=deduction)
        ).exclude(ecriture__statut__in=['annulee', 'annule']).order_by('ecriture__date_ecriture', 'ecriture__numero', 'ordre')
    totals = {s: {'collectee': Decimal(0), 'deductible': Decimal(0)} for s in ['valide', 'en_attente']}
    details = []
    for l in lignes:
        e = l.ecriture
        kind = 'collectee' if l.compte_numero.startswith(collecte) else 'deductible'
        signe = 1 if l.sens == ('C' if kind == 'collectee' else 'D') else -1
        montant = l.montant_usd * signe
        statut = 'valide' if e.statut == 'valide' else 'en_attente'
        totals[statut][kind] += montant
        details.append({'date': e.date_ecriture.isoformat(), 'piece': e.numero,
            'reference': e.numero_piece or '', 'compte': l.compte_numero, 'nature': kind,
            'sens': l.sens, 'montant_usd': str(l.montant_usd), 'net_usd': str(montant),
            'statut': e.statut, 'libelle': l.libelle_ligne or e.libelle})
    factures = list(Facture.objects.filter(societe_id=sid, date_facture__range=(du, au),
        type__in=['vente', 'avoir_vente', 'achat', 'avoir_achat']).exclude(statut='annulee').order_by('date_facture', 'numero'))
    noms = dict(Tiers.objects.filter(id__in=[f.tiers_id for f in factures]).values_list('id', 'nom'))
    taux = {}
    facs = {f.id: f for f in factures}
    for modele in (LigneFacture, FraisFacture):
        for l in modele.objects.filter(facture_id__in=facs):
            f = facs[l.facture_id]
            sens = 'achats' if f.type in ['achat', 'avoir_achat'] else 'ventes'
            cle = (sens, l.taux_tva)
            groupe = taux.setdefault(cle, {'ht': Decimal(0), 'tva': Decimal(0)})
            signe = -1 if f.type.startswith('avoir') else 1
            groupe['ht'] += signe*l.montant_ht
            groupe['tva'] += signe*l.montant_tva
    return {'mois': mois, 'du': du.isoformat(), 'au': au.isoformat(), 'devise': 'USD',
        'comptes': {'collectee': collecte, 'deductible': deduction},
        'totaux': {s: {k: str(v) for k, v in values.items()} for s, values in totals.items()},
        'solde_mouvements_usd': str(totals['valide']['collectee'] - totals['valide']['deductible']),
        'ventilation_taux': [{'sens': sens, 'taux': str(t), 'ht_usd': str(v['ht']), 'tva_usd': str(v['tva'])} for (sens, t), v in sorted(taux.items())],
        'lignes': details, 'factures': [{'numero': f.numero, 'date': f.date_facture.isoformat(),
            'type': f.type, 'tiers': noms.get(f.tiers_id, '?'), 'statut': f.statut,
            'ht_usd': str(f.total_ht * (-1 if f.type.startswith('avoir') else 1)),
            'tva_usd': str(f.total_tva * (-1 if f.type.startswith('avoir') else 1))} for f in factures],
        'note': 'État préparatoire en USD. Le solde des mouvements comptables ne constitue pas le montant fiscal à payer. Vérifier les justificatifs, la déductibilité, les régularisations, le crédit antérieur et la conversion dans la devise déclarative avant dépôt.'}


@api_view(['GET', 'POST'])
@transaction.atomic
def dossier(request):
    sid = _societe_param(request)
    assert_role(assert_acces_societe(request.user, sid), {'DFI', 'COMPTABLE'})
    mois = request.query_params.get('mois', date.today().strftime('%Y-%m'))
    periode_mensuelle(mois)
    if request.method == 'POST':
        Societe.objects.filter(id=sid).update(nom=F('nom'))
    p = PreparationTVA.objects.filter(societe_id=sid, mois=mois).first()
    if request.method == 'POST':
        data = request.data or {}
        if data.get('revision', 0) != (p.revision if p else 0):
            return Response({'detail': 'Ce dossier a été modifié par un autre utilisateur. Rechargez-le avant d’enregistrer.'}, status=409)
        notes = str(data.get('notes') or '').strip()
        if len(notes) > 10000: raise ValidationError('Notes trop longues.')
        suivi = {}
        for key in ['credit_anterieur_cdf', 'montant_declare_cdf']:
            raw = data.get(key)
            if raw in (None, ''): suivi[key] = ''; continue
            try:
                val = Decimal(str(raw))
                if not val.is_finite() or val < 0: raise ValueError
                suivi[key] = str(val.quantize(Decimal('0.01')))
            except Exception: raise ValidationError('Montant CDF invalide.')
        suivi['reference_depot'] = str(data.get('reference_depot') or '').strip()[:120]
        suivi['date_depot'] = str(data.get('date_depot') or '').strip()
        if bool(suivi['reference_depot']) != bool(suivi['date_depot']):
            raise ValidationError('Renseignez ensemble la référence et la date du dépôt déjà effectué.')
        if suivi['date_depot']:
            try:
                jour = date.fromisoformat(suivi['date_depot'])
                if jour > date.today(): raise ValueError
            except ValueError: raise ValidationError('Date de dépôt invalide ou future.')
        snapshot = rapport_tva(sid, mois)
        donnees = {**suivi, 'notes': notes, 'etat': snapshot}
        if p:
            p.donnees = donnees; p.revision += 1
        else: p = PreparationTVA(societe_id=sid, mois=mois, donnees=donnees)
        p.updated_by = request.user.id; p.updated_at = services.maintenant(); p.save()
        services.enregistrer_audit(request.user.id, 'PREPARE_TVA', 'preparation_tva', p.id, None,
            {'mois': mois, 'revision': p.revision, 'reference_depot': suivi['reference_depot']})
    return Response({'revision': p.revision if p else 0, 'donnees': p.donnees if p else {},
        'updated_at': p.updated_at.isoformat() if p and p.updated_at else None})
