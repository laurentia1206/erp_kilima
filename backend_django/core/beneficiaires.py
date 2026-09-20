"""Répertoire commun à l'autorisation DFI et à la remise effective des fonds."""
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .auth import assert_acces_societe, assert_role
from .catalogue import tiers_visibles, tiers_disponible, normaliser, verrouiller_catalogue, verifier_doublon, DoublonCatalogue
from .models import Tiers, Utilisateur, UtilisateurSociete
from . import services

ROLES={'DFI','COMPTABLE','CAISSIER_CENTRAL','CAISSIER_VENDEUR'}


def agents_societe(sid):
    ids=UtilisateurSociete.objects.filter(societe_id=sid).values_list('utilisateur_id',flat=True)
    return Utilisateur.objects.filter(id__in=ids,actif=True).order_by('nom','prenom')


def agent_nom(agent):
    return ' '.join(x for x in [agent.nom,agent.prenom] if x).strip()


def repertoire(sid):
    from .commercial_views import _tiers_dict
    tiers=list(tiers_visibles(sid).filter(actif=True).order_by('nom'))
    out=[_tiers_dict(t) for t in tiers]
    linked={str(t.utilisateur_id) for t in tiers if t.utilisateur_id}
    for agent in agents_societe(sid):
        if str(agent.id) not in linked:
            out.append({'id':'agent:'+str(agent.id),'code':'AGENT','nom':agent_nom(agent),'type':'agent',
                        'societe_id':str(sid),'actif':True,'utilisateur_id':str(agent.id),'agent_existant':True})
    return sorted(out,key=lambda item:normaliser(item['nom']))


def resoudre(reference,sid):
    """Résout une sélection. Appel dans la transaction du document/paiement."""
    if not reference:
        raise ValidationError('Sélectionnez le bénéficiaire de ce paiement.')
    if str(reference).startswith('agent:'):
        try: agent=agents_societe(sid).filter(id=str(reference)[6:]).first()
        except (ValueError,TypeError,DjangoValidationError): agent=None
        if not agent:raise ValidationError('Cet agent ne fait pas partie des agents actifs de cette société.')
        verrouiller_catalogue(sid)
        existing=tiers_visibles(sid).filter(utilisateur_id=agent.id,type='agent',actif=True).first()
        if existing:return existing
        payload={'code':'AG-'+agent.id.hex[:24].upper(),'nom':agent_nom(agent)}
        verifier_doublon(tiers_visibles(sid),payload,'nom')
        return Tiers.objects.create(societe_id=sid,type='agent',utilisateur_id=agent.id,**payload)
    try:t=tiers_visibles(sid).filter(id=reference).first()
    except (ValueError,TypeError,DjangoValidationError):t=None
    if not tiers_disponible(t,sid):raise ValidationError('Choisissez un bénéficiaire actif de cette société ou une fiche partagée.')
    return t


@api_view(['GET','POST'])
@transaction.atomic
def beneficiaires(request):
    from .views import _societe_param
    from .commercial_views import _tiers_dict
    sid=_societe_param(request)
    roles=assert_acces_societe(request.user,sid)
    assert_role(roles,ROLES)
    if request.method=='GET':return Response(repertoire(sid))
    p=request.data or {}
    kind=p.get('type')
    if kind not in ('agent','fournisseur','client') or not str(p.get('code') or '').strip() or len(str(p.get('nom') or '').strip())<2:
        raise ValidationError('Type, code et nom du bénéficiaire requis.')
    verrouiller_catalogue(sid)
    if kind=='agent':
        for agent in agents_societe(sid):
            if normaliser(agent_nom(agent))==normaliser(p['nom']):
                raise DoublonCatalogue({'detail':'Un agent existant porte ce nom. Sélectionnez cet agent dans le répertoire.', 'existing_id':'agent:'+str(agent.id),'can_confirm_similar':False})
    verifier_doublon(tiers_visibles(sid),p,'nom')
    t=Tiers.objects.create(societe_id=sid,type=kind,code=p['code'].strip().upper(),nom=p['nom'].strip(),intra_groupe=bool(p.get('intra_groupe',False)))
    services.enregistrer_audit(request.user.id,'INSERT','tiers',t.id,None,{'nom':t.nom,'type':kind,'origine':'beneficiaire'})
    return Response(_tiers_dict(t),status=201)
