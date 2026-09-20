"""Files de travail calculées : aucune mutation des documents métier à la lecture."""
import hashlib
import json
import uuid
from types import SimpleNamespace
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Count, Min
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import models as M, services, domain
from .auth import assert_acces_societe, assert_role


TYPES = {
    'req_validation': ('Réquisitions', 'Valider la demande', 'approbation', 'Autorisation de la dépense'),
    'req_precision': ('Réquisitions', 'Répondre à la demande de précisions', 'requisitions', 'Reprise de la validation'),
    'ordre_emission': ('Trésorerie', 'Émettre l’ordre de dépense', 'approbation', 'Validation de la sortie de fonds'),
    'ordre_validation': ('Trésorerie', 'Valider la sortie de fonds', 'approbation', 'Mise à disposition du paiement'),
    'ordre_paiement': ('Trésorerie', 'Exécuter le paiement autorisé', 'caisse-exec', 'Paiement du bénéficiaire'),
    'avance_justification': ('Trésorerie', 'Justifier l’avance', 'avances', 'Régularisation de l’avance'),
    'transfert_validation': ('Trésorerie', 'Confirmer le transfert', 'transferts', 'Disponibilité des fonds à destination'),
    'compta_validation': ('Comptabilité', 'Contrôler et comptabiliser la pièce', 'compta', 'Fiabilité des états financiers'),
    'inventaire_validation': ('Stocks', 'Valider le comptage', 'inventaires', 'Ajustement des stocks et des écarts'),
    'reception_facture': ('Achats', 'Rapprocher la réception et la facture fournisseur', 'receptions', 'Régularisation du compte fournisseur'),
    'pointage_validation': ('Ressources humaines', 'Contrôler les pointages saisis', 'rh', 'Contrôle de la paie'),
    'rh_instruction': ('Ressources humaines', 'Instruire la demande d’avance sur salaire', 'rh-finances', 'Accord et validation du financement'),
    'rh_dette': ('Ressources humaines', 'Valider le dossier de financement', 'rh-finances', 'Étape suivante du financement'),
    'rh_versement': ('Ressources humaines', 'Verser l’avance ou le prêt approuvé', 'rh-paiements', 'Versement à l’agent'),
    'paie_controle': ('Ressources humaines', 'Préparer et contrôler la paie', 'rh-mensuel', 'Validation DFI de la paie'),
    'paie_validation': ('Ressources humaines', 'Valider la paie contrôlée', 'rh-mensuel', 'Comptabilisation et paiement des salaires'),
    'paie_paiement': ('Ressources humaines', 'Régler les bulletins validés', 'rh-mensuel', 'Clôture de la paie'),
    'paie_cloture': ('Ressources humaines', 'Clôturer la paie réglée', 'rh-mensuel', 'Achèvement du cycle mensuel'),
    'course_validation': ('Transport', 'Valider la fiche de course', 'courses', 'Autorisation du départ'),
    'course_facture': ('Transport', 'Facturer la course livrée', 'courses', 'Créance et encaissement du transport'),
    'maintenance_execution': ('Maintenance', 'Traiter l’intervention ouverte', 'maintenance-interventions', 'Disponibilité du véhicule ou de l’engin'),
    'flotte_document': ('Maintenance', 'Vérifier le renouvellement du document', 'flotte-documents', 'Validité des documents de la flotte'),
    'hotel_arrivee': ('Hôtel', 'Confirmer l’arrivée ou régulariser la réservation', 'hotel-reception', 'Occupation et compte du séjour'),
    'hotel_depart': ('Hôtel', 'Vérifier le départ ou prolonger le séjour', 'hotel-reception', 'Facturation et disponibilité de la chambre'),
    'vente_facture': ('Ventes', 'Facturer les quantités disponibles à facturer', 'devis', 'Créance et encaissement client'),
    'tva_suivi': ('Comptabilité', 'Compléter le suivi de dépôt de TVA', 'tva', 'Traçabilité de la déclaration mensuelle'),
}
PREFIX = 'pilotage.delai.'
LOCAL = ZoneInfo(settings.TIME_ZONE)


def ident(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Société invalide.')


def instant(value, local=False):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.max)
        local = True
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL if local else timezone.utc)
    return value.astimezone(timezone.utc)


def regles(sid):
    rows = list(M.Parametre.objects.filter(societe_id=sid, cle__startswith=PREFIX).order_by('cle', 'id'))
    version = hashlib.sha256(json.dumps([(str(r.id), r.cle, r.valeur) for r in rows]).encode()).hexdigest()
    result = {}
    for row in rows:
        code = row.cle[len(PREFIX):]
        if code not in TYPES:
            continue
        try:
            p = json.loads(row.valeur)
            a, b = p['relance_h'], p['escalade_h']
            if type(a) is int and type(b) is int and 1 <= a < b <= 8760:
                result[code] = p
        except (ValueError, KeyError, TypeError):
            pass
    return result, version


@api_view(['GET', 'PUT'])
@transaction.atomic
def parametres(request):
    sid = ident(request.query_params.get('societe_id'))
    assert_role(assert_acces_societe(request.user, sid), {'DFI'})
    if request.method == 'PUT':
        # Sérialise les modifications, y compris sur SQLite, sans changer la société.
        M.Societe.objects.filter(id=sid).update(nom=F('nom'))
    old, version = regles(sid)
    if request.method == 'PUT':
        p = request.data
        if not isinstance(p, dict) or p.get('version') != version:
            return Response({'detail': 'Les délais ont changé. Rouvrez les paramètres avant de les modifier.'}, status=409)
        values = p.get('regles')
        if not isinstance(values, dict) or set(values) - set(TYPES):
            raise ValidationError('Règles de délai invalides.')
        for code, value in values.items():
            if value is None:
                continue
            if not isinstance(value, dict) or set(value) != {'relance_h', 'escalade_h'}:
                raise ValidationError('Indiquez les deux délais en heures.')
            a, b = value['relance_h'], value['escalade_h']
            if type(a) is not int or type(b) is not int or not 1 <= a < b <= 8760:
                raise ValidationError('Relance : au moins 1 h ; remontée DFI : après la relance, au plus 8 760 h.')
        for code, value in values.items():
            qs = M.Parametre.objects.filter(societe_id=sid, cle=PREFIX + code)
            qs.delete()
            if value is not None:
                M.Parametre.objects.create(societe_id=sid, cle=PREFIX + code, valeur=json.dumps(value), type_valeur='json')
        services.enregistrer_audit(request.user.id, 'DELAIS_PILOTAGE', 'societe', sid, old, values)
        old, version = regles(sid)
    return Response({'version': version, 'regles': old, 'types': {k: {'module': v[0], 'action': v[1]} for k, v in TYPES.items()}})


class FileTravail:
    def __init__(self, sid, now):
        self.sid, self.now, self.items = sid, now, []
        self.regles, _ = regles(sid)
        self.users, self.roles = {}, {}
        role_rows = list(M.Role.objects.values('id', 'code', 'herite_de'))
        parents = {r['code']: r['herite_de'] for r in role_rows}
        role_codes = {r['id']: r['code'] for r in role_rows}
        self.paliers = {}
        for a in M.UtilisateurSociete.objects.filter(societe_id=sid, utilisateur__actif=True).select_related('utilisateur', 'role'):
            uid = str(a.utilisateur_id)
            self.users[uid] = {'id': uid, 'nom': ' '.join(filter(None, [a.utilisateur.prenom, a.utilisateur.nom]))}
            codes = self.roles.setdefault(uid, set())
            code = a.role.code
            while code and code not in codes:
                codes.add(code)
                code = parents.get(code)
        # Une seule lecture de l'historique des changements d'étape de cette société.
        reqs = M.Requisition.objects.filter(societe_id=sid, statut__in=['soumise', 'en_attente_info', 'demande_validee']).values_list('id', flat=True)
        odps = M.OrdreDepense.objects.filter(societe_id=sid, statut__in=['a_valider', 'valide']).values_list('id', flat=True)
        ids = [str(x) for x in reqs] + [str(x) for x in odps]
        self.decisions = {}
        for v in M.Validation.objects.filter(document_id__in=ids).values('document_type', 'document_id', 'etape', 'role_attendu_id', 'decision'):
            code = role_codes.get(v['role_attendu_id'])
            if code:
                self.decisions.setdefault((v['document_type'], v['document_id'], v['etape']), {})[code] = v['decision']
        self.transitions = {}
        for a in M.AuditLog.objects.filter(enregistrement_id__in=ids, action__in=['VALIDATE', 'DEMANDE_PRECISIONS', 'REPONSE_PRECISIONS']).order_by('horodatage', 'id'):
            statut = (a.nouvelle_valeur or {}).get('statut')
            if a.action == 'VALIDATE' and statut not in ['demande_validee', 'valide']:
                continue  # Une validation partielle ne remet pas le compteur des autres à zéro.
            if a.action == 'DEMANDE_PRECISIONS':
                statut = 'en_attente_info'
            if a.action == 'REPONSE_PRECISIONS':
                statut = 'soumise'
            if statut:
                self.transitions[(a.table_cible, a.enregistrement_id, statut)] = a.horodatage

    def candidats(self, roles=(), exclure=()):
        excludes = {str(x) for x in exclure}
        return [u for u, codes in self.roles.items() if codes & set(roles) and u not in excludes]

    def ajouter(self, code, obj, roles=(), personne=None, exclure=(), debut=None, echeance=None,
                detail='', reference=None, suffix='', blocage='', base='Création du dossier', local=False):
        module, action, view, impact = TYPES[code]
        if personne is not None:
            ids = [str(personne)] if str(personne) in self.users else []
            affectation = 'nominative'
        else:
            ids = self.candidats(roles, exclure)
            affectation = 'equipe'
        start = instant(debut if debut is not None else getattr(obj, 'created_at', None), local)
        due = instant(echeance)
        rule = self.regles.get(code)
        reminder = start + timedelta(hours=rule['relance_h']) if start and rule else None
        escalation = start + timedelta(hours=rule['escalade_h']) if start and rule else None
        level = 'a_traiter'
        if reminder and self.now >= reminder:
            level = 'relance'
        if escalation and self.now >= escalation:
            level = 'escalade'
        late = bool(due and self.now > due)
        # Une échéance métier existante reste prioritaire sur les délais de suivi.
        if late:
            level = 'escalade'
        if blocage or not ids:
            level = 'a_attribuer'
        self.items.append({
            'id': f'{code}:{obj.id}:{suffix}', 'document_id': str(obj.id), 'type': code, 'module': module,
            'action': action, 'reference': reference or getattr(obj, 'numero', str(obj.id)[:8]),
            'detail': detail, 'impact': impact, 'vue': view, 'affectation': affectation,
            'responsables': [self.users[u] for u in ids], 'roles': sorted(roles),
            'debut': start.isoformat() if start else None, 'base_date': base,
            'age_heures': round(max(0, (self.now-start).total_seconds()/3600), 1) if start else None,
            'echeance': due.isoformat() if due else None, 'echeance_depassee': late,
            'relance_at': reminder.isoformat() if reminder else None, 'escalade_at': escalation.isoformat() if escalation else None,
            'niveau': level, 'blocage': blocage or ('Aucun utilisateur actif habilité : affectation à vérifier.' if not ids else ''),
        })

    def validation(self, obj, type_doc, etape, code, montant, exclure=()):
        key = (type_doc, etape)
        if key not in self.paliers:
            self.paliers[key] = services.load_paliers(type_doc, etape, self.sid)
        paliers = self.paliers[key]
        try:
            p = domain.resolve_palier(montant, paliers)
        except ValueError:
            p = None
            # Même repli que services.palier_pour_montant pour les demandes uniquement.
            if type_doc == 'requisition' and paliers:
                candidats = [p for p in paliers if p.montant_min_usd <= montant]
                p = max(candidats, key=lambda p: p.montant_min_usd) if candidats else paliers[0]
        if not p or not p.approbateurs:
            self.ajouter(code, obj, blocage='Circuit de validation absent ou sans approbateur : vérifier le paramétrage.')
            return
        decisions = self.decisions.get((type_doc, obj.id, etape), {})
        remaining = [a for a in p.approbateurs if decisions.get(a.role_code) not in ('valide', 'rejete')]
        if domain.est_pleinement_approuve(p, decisions) or any(x == 'rejete' for x in decisions.values()) or not remaining:
            self.ajouter(code, obj, blocage='Les décisions et le statut du dossier sont à rapprocher avant toute intervention.')
            return
        for a in remaining:
            debut = self.transitions.get((type_doc, str(obj.id), obj.statut))
            self.ajouter(code, obj, roles=[a.role_code], exclure=exclure, suffix=a.role_code,
                debut=debut, base='Retour aux validateurs' if debut else 'Création du dossier',
                detail=f'{a.role_code} · '+('une validation alternative peut suffire' if a.mode == 'seul' else 'validation conjointe'))

    def construire(self):
        sid = self.sid
        self.operations()
        for r in M.Requisition.objects.filter(societe_id=sid, statut__in=['soumise', 'en_attente_info', 'demande_validee']):
            debut = self.transitions.get(('requisition', str(r.id), r.statut))
            if r.statut == 'en_attente_info':
                self.ajouter('req_precision', r, personne=r.initiateur_id, debut=debut, base='Demande de précisions' if debut else 'Création du dossier (date d’étape indisponible)')
            elif r.statut == 'demande_validee':
                self.ajouter('ordre_emission', r, roles=['DFI'], debut=debut, base='Validation de la demande' if debut else 'Création du dossier (date d’étape indisponible)')
            else:
                self.validation(r, 'requisition', 'demande', 'req_validation', r.montant_total_usd, [r.initiateur_id])
        for o in M.OrdreDepense.objects.filter(societe_id=sid, statut__in=['a_valider', 'valide']):
            if o.statut == 'a_valider':
                self.validation(o, 'ordre_depense', 'sortie_fonds', 'ordre_validation', o.montant_autorise_usd)
            elif o.montant_autorise_usd-o.montant_paye_usd > 0.01:
                debut = self.transitions.get(('ordre_depense', str(o.id), 'valide'))
                self.ajouter('ordre_paiement', o, roles=['COMPTABLE', 'DFI'] if o.mode_paiement == 'banque' else ['CAISSIER_CENTRAL', 'CAISSIER_VENDEUR'], debut=debut,
                    base='Validation de la sortie' if debut else 'Création du dossier (date d’étape indisponible)', detail='Règlement bancaire' if o.mode_paiement == 'banque' else 'Règlement en caisse')
        tiers = {t.id: t for t in M.Tiers.objects.filter(Q(societe_id=sid) | Q(societe_id__isnull=True))}
        for a in M.Avance.objects.filter(societe_id=sid, statut__in=['a_justifier', 'en_retard']):
            t = tiers.get(a.beneficiaire_tiers_id)
            self.ajouter('avance_justification', a, personne=t.utilisateur_id if t and t.utilisateur_id else 'externe',
                debut=a.date_octroi, echeance=a.echeance_justif, base='Octroi de l’avance', detail='Bénéficiaire : '+(t.nom if t else 'à vérifier'),
                blocage='' if t and t.utilisateur_id else 'Bénéficiaire sans compte utilisateur lié : organiser le suivi de la justification.')
        for t in M.Transfert.objects.filter(societe_id=sid, statut='a_valider'):
            self.ajouter('transfert_validation', t, roles=['CAISSIER_CENTRAL', 'CAISSIER_VENDEUR', 'DFI'] if t.dest_type == 'caisse' else ['COMPTABLE', 'DFI'])
        for e in M.Ecriture.objects.filter(societe_id=sid, statut='en_attente'):
            self.ajouter('compta_validation', e, roles=['COMPTABLE', 'DFI'], detail=e.libelle or '')
        for i in M.InventaireDepot.objects.filter(societe_id=sid, statut='brouillon'):
            self.ajouter('inventaire_validation', i, roles=['COMPTABLE', 'DFI'])
        for r in M.Reception.objects.filter(societe_id=sid).exclude(statut__in=['facturee', 'annulee', 'annule']):
            self.ajouter('reception_facture', r, roles=['COMPTABLE', 'DFI'], detail='Vérifier la disponibilité de la facture fournisseur ; une attente externe n’est pas une faute de saisie.')
        # Pointages regroupés par jour, sans exposer les données personnelles de chaque agent.
        for row in M.RHPointage.objects.filter(societe_id=sid, statut='brouillon').values('jour').annotate(nombre=Count('id'), debut=Min('created_at')).order_by('jour'):
            group = SimpleNamespace(id=uuid.uuid5(sid, 'pointages:'+str(row['jour'])), created_at=row['debut'])
            self.ajouter('pointage_validation', group, roles=['RH', 'DRH', 'DFI'], reference='Pointages du '+str(row['jour']), detail=f'{row["nombre"]} pointage(s) à contrôler', local=True)
        for d in M.RHDemande.objects.filter(societe_id=sid, nature='avance_salaire', statut='soumis'):
            self.ajouter('rh_instruction', d, roles=['RH', 'DRH', 'DFI'], reference='Demande RH · '+str(d.id)[:8], local=True)
        for d in M.RHDette.objects.filter(societe_id=sid, statut__in=['attente_dfi', 'attente_drh', 'attente_direction', 'approuve']).select_related('agent'):
            if d.statut == 'approuve':
                if d.nature != 'recouvrement':
                    self.ajouter('rh_versement', d, roles=['CAISSIER_CENTRAL', 'CAISSIER_VENDEUR'], debut=d.decisions[-1].get('date') if d.decisions else None, local=True)
            else:
                roles = {'attente_dfi': ['DFI'], 'attente_drh': ['DRH'], 'attente_direction': ['DG', 'ADMIN']}[d.statut]
                self.ajouter('rh_dette', d, roles=roles, exclure=[d.agent.utilisateur_id]+[x.get('utilisateur_id') for x in d.decisions],
                    debut=d.decisions[-1].get('date') if d.decisions else None, detail=d.statut.replace('_', ' '), local=True,
                    base='Entrée dans l’étape' if d.decisions else 'Création du dossier')
        for p in M.RHPaieMois.objects.filter(societe_id=sid, statut__in=['brouillon', 'controle', 'valide']):
            opts = {'reference': 'Paie '+p.mois, 'local': True}
            if p.statut == 'brouillon':
                self.ajouter('paie_controle', p, roles=['RH', 'DRH'], **opts)
            elif p.statut == 'controle':
                ctrl = next((x for x in reversed(p.decisions) if x['action'] == 'controler'), {})
                self.ajouter('paie_validation', p, roles=['DFI'], exclure=[ctrl.get('utilisateur_id')], debut=ctrl.get('date'), base='Contrôle RH', **opts)
            else:
                bs = M.RHBulletin.objects.filter(periode=p).exclude(id__in=M.RHPaiement.objects.values('bulletin_id'))
                unpaid = sum(1 for b in bs if float(b.resultat.get('net_a_payer', 0)) != 0)
                last_payment = M.RHPaiement.objects.filter(bulletin__periode=p).order_by('-created_at').first() if not unpaid else None
                self.ajouter('paie_paiement' if unpaid else 'paie_cloture', p,
                    roles=['CAISSIER_CENTRAL', 'CAISSIER_VENDEUR', 'COMPTABLE'] if unpaid else ['DFI'],
                    detail=f'{unpaid} bulletin(s) à régler' if unpaid else 'Tous les bulletins sont réglés ou à net nul',
                    debut=last_payment.created_at if last_payment else (p.decisions[-1].get('date') if p.decisions else None),
                    base='Dernier paiement du mois' if last_payment else 'Dernière décision du mois', **opts)
        return self.items

    def operations(self):
        """Opérations planifiées déjà présentes, sans inventer d'obligations périodiques."""
        from .transport_views import ROLES as TRANSPORT, ROLES_MAINT, _role_validation
        from .hotel_views import ROLES as HOTEL
        from .documents_views import ROLES as DOCUMENTS, JOURS_ALERTE
        from .ventes_views import _facturable
        sid, today = self.sid, self.now.astimezone(LOCAL).date()
        for c in M.Course.objects.filter(societe_id=sid, statut__in=['brouillon', 'livree']):
            if c.statut == 'brouillon':
                role = _role_validation(sid)
                candidats = self.candidats([role])
                exclus = [u for u in candidats if not self.roles[u] & TRANSPORT]
                self.ajouter('course_validation', c, roles=[role], exclure=exclus)
            elif not c.facture_id:
                self.ajouter('course_facture', c, roles=TRANSPORT, debut=c.heure_retour,
                    base='Retour de la course' if c.heure_retour else 'Création du dossier (date de retour indisponible)')
        for i in M.InterventionCamion.objects.filter(societe_id=sid, statut__in=['planifiee', 'en_cours']):
            if i.statut == 'planifiee' and i.date_prevue and i.date_prevue > today:
                continue
            self.ajouter('maintenance_execution', i, roles=ROLES_MAINT,
                debut=i.date_prevue if i.statut == 'planifiee' else i.date_signalement,
                base='Date prévue de l’intervention' if i.statut == 'planifiee' else 'Signalement de l’intervention',
                detail='Intervention planifiée à démarrer' if i.statut == 'planifiee' else 'Intervention en cours : suivre son achèvement, sans clôture anticipée')
        for d in M.DocumentFlotte.objects.filter(societe_id=sid, date_expiration__lte=today+timedelta(days=JOURS_ALERTE)):
            self.ajouter('flotte_document', d, roles=DOCUMENTS, debut=d.date_expiration-timedelta(days=JOURS_ALERTE),
                echeance=d.date_expiration, reference=d.numero or d.libelle, detail=d.libelle,
                base=f'Entrée dans la période de vigilance du module ({JOURS_ALERTE} jours avant expiration)')
        for s in M.Sejour.objects.filter(societe_id=sid).filter(Q(statut='reservee', date_arrivee__lte=today)|Q(statut='arrivee', date_depart_prevue__lte=today)):
            arrivee = s.statut == 'reservee'
            jour = s.date_arrivee if arrivee else s.date_depart_prevue
            self.ajouter('hotel_arrivee' if arrivee else 'hotel_depart', s, roles=HOTEL, debut=jour, echeance=jour,
                base='Journée d’arrivée prévue' if arrivee else 'Journée de départ prévue',
                detail='Vérifier la situation réelle avec la réception ; aucune arrivée ou sortie automatique.')
        devis = list(M.Devis.objects.filter(societe_id=sid, statut='confirme', commande_origine_id__isnull=True))
        lignes = {}
        for l in M.LigneDevis.objects.filter(devis_id__in=[d.id for d in devis]):
            lignes.setdefault(l.devis_id, []).append(l)
        articles = M.Article.objects.in_bulk([l.article_id for ls in lignes.values() for l in ls if l.article_id])
        for d in devis:
            if any(_facturable(l, articles.get(l.article_id)) > 0 for l in lignes.get(d.id, [])):
                self.ajouter('vente_facture', d, roles=['COMPTABLE', 'DFI'], debut=d.date_confirmation,
                    base='Confirmation de commande (date de mise à disposition à vérifier)',
                    detail='Commande client hors circuit intersociétés. Vérifier les pièces avant facturation.')
        for p in M.PreparationTVA.objects.filter(societe_id=sid, mois__lt=today.strftime('%Y-%m')):
            if not p.donnees.get('reference_depot') or not p.donnees.get('date_depot'):
                self.ajouter('tva_suivi', p, roles=['COMPTABLE', 'DFI'], reference='TVA '+p.mois, debut=p.updated_at,
                    base='Dernière sauvegarde du dossier TVA', detail='Un dossier existe sans référence complète de dépôt. Vérifier le dépôt réel ; aucune échéance fiscale n’est déduite ici.')


@api_view(['GET'])
def taches(request):
    sid = ident(request.query_params.get('societe_id'))
    roles = assert_acces_societe(request.user, sid)
    team = request.query_params.get('portee', 'moi') == 'equipe'
    if team:
        assert_role(roles, {'DFI'})
    if request.query_params.get('portee', 'moi') not in ['moi', 'equipe']:
        raise ValidationError('Périmètre invalide.')
    now = datetime.now(timezone.utc)
    f = FileTravail(sid, now)
    rows = f.construire()
    if not team:
        rows = [r for r in rows if any(x['id'] == str(request.user.id) for x in r['responsables'])]
    order = {'a_attribuer': 0, 'escalade': 1, 'relance': 2, 'a_traiter': 3}
    rows.sort(key=lambda r: (order[r['niveau']], -(r['age_heures'] or 0), r['id']))
    stats = {k: sum(r['niveau'] == k for r in rows) for k in order}
    stats.update(total=len(rows), dossiers=len({r['document_id'] for r in rows}))
    result = {'actualise_a': now.isoformat(), 'societe_id': str(sid), 'supervision': 'DFI' in roles,
              'portee': 'equipe' if team else 'moi', 'compteurs': stats}
    if request.query_params.get('resume') != '1':
        result.update(taches=rows, utilisateurs=list(f.users.values()) if team else [f.users.get(str(request.user.id), {'id': str(request.user.id), 'nom': request.user.nom})])
    response = Response(result)
    response['Cache-Control'] = 'private, no-store'
    return response
