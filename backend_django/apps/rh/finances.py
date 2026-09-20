"""Accords de prêt et de recouvrement : instruction, signatures, puis caisse."""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from core import services as services
from apps.comptabilite import services as comptabilite
from apps.rh.models import RHAgent, RHContrat, RHDette, RHPolitique, RHDemande, RHDocument
from core.models import Tiers, Societe
from apps.tresorerie.models import Avance, Justification, Caisse, MouvementCaisse, SessionCaisse
from apps.rh.views import contexte, DOSSIERS, ident, argent, texte, choix, simple, sauver, agent_requis, jour

DECIDEURS = {'DFI','DRH','DG','ADMIN'}
CAISSE = {'CAISSIER_CENTRAL','CAISSIER_VENDEUR'}
LECTURE = DOSSIERS | DECIDEURS


def politique(sid):
    p=RHPolitique.objects.filter(societe_id=sid).first()
    return {'revision':p.revision if p else 0,'plafond_avance_pct':str(p.plafond_avance_pct) if p else '30.00',
            'delai_recouvrement_jours':p.delai_recouvrement_jours if p else 30}


@api_view(['GET','POST'])
@transaction.atomic
def parametres(request):
    sid,roles=contexte(request,LECTURE)
    if request.method=='POST':
        if not roles & {'DFI','DRH'}: raise PermissionDenied('Paramétrage réservé au DFI / DRH.')
        p=RHPolitique.objects.filter(societe_id=sid).first();nouveau=p is None
        if nouveau and request.data.get('revision')!=0: raise ValidationError('Rechargez les paramètres.')
        p=p or RHPolitique(societe_id=sid)
        taux=argent(request.data.get('plafond_avance_pct'))
        if not 0<=taux<=100: raise ValidationError('Le plafond doit être compris entre 0 et 100 %.')
        p.plafond_avance_pct=taux
        # Le délai autorisé dans cette session est 30 jours ; pas de modification implicite.
        p.delai_recouvrement_jours=30
        sauver(p,request,nouveau)
    return Response(politique(sid))


def tiers_agent(a):
    if a.tiers_id: return [a.tiers_id]
    if a.utilisateur_id: return list(Tiers.objects.filter(societe_id=a.societe_id,type='agent',utilisateur_id=a.utilisateur_id).values_list('id',flat=True))
    return []


def source_valide(a, avance, verifier_delai=True):
    if avance.societe_id!=a.societe_id or avance.beneficiaire_tiers_id not in tiers_agent(a): raise ValidationError('Cette avance n’appartient pas au compte de cet agent dans cette société.')
    if avance.statut not in ('a_justifier','en_retard','partiellement_justifiee') or Justification.objects.filter(avance_id=avance.id).exists(): raise ValidationError('Cette avance a été traitée ou justifiée. Son solde doit être vérifié avant tout recouvrement.')
    if verifier_delai and (not avance.date_octroi or services.maintenant()-avance.date_octroi<timedelta(days=30)): raise ValidationError('Le délai de 30 jours depuis l’octroi n’est pas atteint.')


@api_view(['GET'])
def sources(request):
    sid,roles=contexte(request);a=agent_requis(sid,request.query_params.get('agent_id'))
    out=[]
    for av in Avance.objects.filter(societe_id=sid,beneficiaire_tiers_id__in=tiers_agent(a)).order_by('-date_octroi'):
        erreur=''
        try: source_valide(a,av)
        except ValidationError as e: erreur=str(e.detail[0])
        if RHDette.objects.filter(avance_source=av).exists(): erreur='Déjà liée à un dossier de recouvrement.'
        out.append({'id':str(av.id),'numero':av.numero,'montant':str(av.montant_avance),'devise':av.devise,
                    'date_octroi':av.date_octroi,'statut':av.statut,'eligible':not erreur,'motif':erreur})
    return Response(out)


def dette_dict(d):
    from apps.rh.models import RHRetenue
    retenues=list(RHRetenue.objects.filter(dette=d,bulletin__periode__statut__in=['valide','cloture']).select_related('bulletin__periode'))
    rembourse=sum((x.montant for x in retenues),Decimal(0))
    return {**simple(d,['agent_id','nature','montant','devise','salaire_reference','plafond_pct','echeancier','motif',
                        'statut','decisions','verse_at','mouvement_id','accord_id','avance_source_id','demande_id']),
            'nom':d.agent.nom,'matricule':d.agent.matricule,'accord_nom':d.accord.nom,
            'source_numero':d.avance_source.numero if d.avance_source_id else '',
            'rembourse':str(rembourse),'solde':str(d.montant-rembourse),
            'remboursements':[{'mois':x.bulletin.periode.mois,'montant':str(x.montant)} for x in retenues]}


@api_view(['GET','POST'])
@transaction.atomic
def dettes(request):
    sid,roles=contexte(request,LECTURE)
    if request.method=='POST':
        if not roles & DOSSIERS: raise PermissionDenied('Préparation réservée aux RH / DFI.')
        p=request.data;a=agent_requis(sid,p.get('agent_id'));accord=RHDocument.objects.filter(id=ident(p.get('accord_id')),agent=a,societe_id=sid).first()
        if not accord: raise ValidationError('Joignez d’abord l’accord écrit signé au dossier de cet agent.')
        c=RHContrat.objects.filter(agent=a,debut__lte=date.today()).filter(Q(fin__isnull=True)|Q(fin__gte=date.today())).first()
        if not c or c.base_salaire!='net' or c.salaire<=0: raise ValidationError('Un contrat en cours avec salaire net doit être enregistré.')
        if a.date_sortie and a.date_sortie<date.today(): raise ValidationError('Cet agent a quitté la société.')
        pol=politique(sid);obj=RHDette(societe_id=sid,agent=a,accord=accord,motif=texte(p,'motif',3000,True),salaire_reference=c.salaire,plafond_pct=pol['plafond_avance_pct'])
        if p.get('avance_source_id'):
            av=Avance.objects.filter(id=ident(p['avance_source_id'])).first()
            if not av: raise ValidationError('Avance introuvable.')
            source_valide(a,av)
            if RHDette.objects.filter(avance_source=av).exists(): raise ValidationError('Un dossier existe déjà pour cette avance.')
            obj.avance_source=av;obj.nature='recouvrement';obj.montant=av.montant_avance;obj.devise=av.devise
        else:
            demande=RHDemande.objects.filter(id=ident(p.get('demande_id')),agent=a,nature='avance_salaire',statut='soumis').first()
            if not demande or RHDette.objects.filter(demande=demande).exists(): raise ValidationError('Demande introuvable ou déjà instruite.')
            if demande.devise!=c.devise: raise ValidationError('La demande doit utiliser la devise du contrat pour comparer correctement le plafond.')
            obj.demande=demande;obj.montant=demande.montant;obj.devise=demande.devise
            # Cumuler les demandes en cours du mois pour éviter le fractionnement du plafond.
            debut=date.today().replace(day=1)
            encours=sum((d.montant for d in RHDette.objects.filter(agent=a,devise=c.devise,created_at__date__gte=debut).exclude(statut__in=['rejete','annule']).exclude(nature='recouvrement')),Decimal(0))
            obj.nature='avance_salaire' if encours+obj.montant<=c.salaire*Decimal(pol['plafond_avance_pct'])/100 else 'pret_personnel'
        echeancier=p.get('echeancier')
        if not isinstance(echeancier,list) or not 1<=len(echeancier)<=120: raise ValidationError('Prévoyez un échéancier de 1 à 120 mensualités.')
        lignes=[];mois_vus=set();total=Decimal(0)
        for l in echeancier:
            if not isinstance(l,dict): raise ValidationError('Mensualité invalide.')
            from apps.comptabilite.tva_views import periode_mensuelle
            mois=str(l.get('mois',''));periode_mensuelle(mois)
            if mois<date.today().strftime('%Y-%m') or mois in mois_vus: raise ValidationError('Mois passé ou répété dans l’échéancier.')
            montant=argent(l.get('montant'))
            if not montant: raise ValidationError('Chaque mensualité doit être positive.')
            mois_vus.add(mois);total+=montant;lignes.append({'mois':mois,'montant':str(montant)})
        if total!=obj.montant: raise ValidationError('Le total de l’échéancier doit être égal au montant à rembourser.')
        obj.echeancier=sorted(lignes,key=lambda l:l['mois']);sauver(obj,request,True)
        if obj.demande_id: RHDemande.objects.filter(id=obj.demande_id).update(statut='instruit')
        return Response(dette_dict(obj),status=201)
    return Response([dette_dict(d) for d in RHDette.objects.filter(societe_id=sid).select_related('agent','accord','avance_source').order_by('-created_at')])


@api_view(['POST'])
@transaction.atomic
def decision(request,dette_id):
    sid,roles=contexte(request,LECTURE);d=RHDette.objects.filter(id=dette_id,societe_id=sid).select_related('agent','accord','avance_source').first()
    if not d: raise NotFound()
    action=choix(request.data.get('action'),['valider','rejeter'])
    # Toute opération attend le DFI. Les prêts et recouvrements exigent ensuite DRH et direction.
    etapes={'attente_dfi':({'DFI'},'attente_drh' if d.nature!='avance_salaire' else 'approuve'),
            'attente_drh':({'DRH'},'attente_direction'),'attente_direction':({'DG','ADMIN'},'approuve')}
    etape=etapes.get(d.statut)
    if not etape: raise ValidationError('Ce dossier n’attend plus de validation.')
    requis,suivant=etape
    if not roles & requis: raise PermissionDenied('Validation attendue : '+' ou '.join(sorted(requis)))
    if str(d.agent.utilisateur_id)==str(request.user.id): raise PermissionDenied('Un agent ne peut pas valider sa propre dette.')
    if any(x['utilisateur_id']==str(request.user.id) for x in d.decisions): raise PermissionDenied('Chaque niveau doit être validé par une personne différente.')
    commentaire=texte(request.data,'commentaire',1000,True)
    if d.avance_source_id: source_valide(d.agent,d.avance_source)
    d.decisions=[*d.decisions,{'etape':d.statut,'action':action,'utilisateur_id':str(request.user.id),
        'nom':request.user.nom,'date':datetime.now().isoformat(),'commentaire':commentaire}]
    d.statut=suivant if action=='valider' else 'rejete'
    sauver(d,request)
    if action=='rejeter' and d.demande_id: RHDemande.objects.filter(id=d.demande_id).update(statut='rejete')
    return Response(dette_dict(d))


@api_view(['GET'])
def accord(request,dette_id):
    sid,roles=contexte(request,LECTURE)
    d=RHDette.objects.filter(id=dette_id,societe_id=sid).select_related('accord').first()
    if not d: raise NotFound()
    from django.http import HttpResponse
    from django.utils.http import content_disposition_header
    r=HttpResponse(bytes(d.accord.contenu),content_type=d.accord.mime)
    r['Content-Disposition']=content_disposition_header(True,d.accord.nom)
    r['Cache-Control']='private, no-store';r['X-Content-Type-Options']='nosniff'
    return r


@api_view(['GET'])
def a_payer(request):
    sid,roles=contexte(request,CAISSE|{'DFI'})
    return Response([{'id':str(d.id),'nom':d.agent.nom,'matricule':d.agent.matricule,
        'nature':d.nature,'montant':str(d.montant),'devise':d.devise,'revision':d.revision,
        'statut':d.statut,'verse_at':d.verse_at} for d in RHDette.objects.filter(
            societe_id=sid,statut__in=['approuve','verse']).exclude(nature='recouvrement').select_related('agent').order_by('-created_at')])


@api_view(['POST'])
@transaction.atomic
def verser(request,dette_id):
    sid,roles=contexte(request,CAISSE)
    d=RHDette.objects.filter(id=dette_id,societe_id=sid).select_related('agent').first()
    if not d: raise NotFound()
    if d.statut!='approuve' or d.nature=='recouvrement' or d.mouvement_id: raise ValidationError('Ce dossier ne peut pas faire l’objet d’un nouveau versement.')
    if str(d.agent.utilisateur_id)==str(request.user.id): raise PermissionDenied('Un caissier ne peut pas se payer lui-même.')
    if any(x['utilisateur_id']==str(request.user.id) for x in d.decisions): raise PermissionDenied('Le paiement doit être exécuté par une personne distincte des validateurs.')
    caisse=Caisse.objects.filter(id=ident(request.data.get('caisse_id')),societe_id=sid,actif=True).first()
    if not caisse: raise ValidationError('Caisse active de cette société requise.')
    from apps.tresorerie.views import _soldes
    session=SessionCaisse.objects.select_for_update().filter(caisse_id=caisse.id,statut='ouverte').first()
    if not session: raise ValidationError('Ouvrez la session de caisse avant le versement.')
    if Decimal(str(_soldes(session).get(d.devise,0)))<d.montant: raise ValidationError('Solde de caisse insuffisant dans cette devise.')
    taux=Decimal(1) if d.devise=='USD' else services.get_taux_jour(date.today(),d.devise)
    if taux is None or Decimal(str(taux))<=0: raise ValidationError('Taux de change du jour manquant.')
    montant_usd=(d.montant/Decimal(str(taux))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if d.devise!='USD' else d.montant
    if not montant_usd: raise ValidationError('Montant trop faible pour une écriture en USD.')
    candidats=Tiers.objects.filter(id__in=tiers_agent(d.agent),actif=True)
    if candidats.count()!=1: raise ValidationError('Les RH doivent relier la fiche agent à un bénéficiaire financier unique avant paiement.')
    tiers=candidats.first()
    reference=texte(request.data,'reference',64,True)
    soc=Societe.objects.get(id=sid)
    numero=services.next_numero('bon_caisse',date.today().year,soc.code,sid)
    m=MouvementCaisse.objects.create(caisse_id=caisse.id,session_id=session.id,numero=numero,
        sens='sortie',nature='Avance sur salaire' if d.nature=='avance_salaire' else 'Prêt au personnel',
        devise=d.devise,taux_jour=taux,montant=d.montant,montant_usd=montant_usd,
        reference_type='rh_dette',reference_id=d.id,reference=reference,tiers_id=tiers.id,tiers_nom=tiers.nom,
        libelle=f'{d.agent.matricule} — accord RH {str(d.id)[:8]}',created_by=request.user.id,
        date_mouvement=date.today(),heure=services.maintenant())
    compte='421' if d.nature=='avance_salaire' else '272'
    e=comptabilite.post_ecriture(sid,'CA','Caisse','caisse',date.today(),f'Versement RH {numero}',[
        {'sens':'D','compte':compte,'tiers_id':str(tiers.id),'montant_usd':montant_usd,'libelle':reference,'devise_origine':d.devise,'montant_origine':d.montant,'taux_jour':taux},
        {'sens':'C','compte':caisse.compte_comptable or '571','montant_usd':montant_usd,'libelle':reference,'devise_origine':d.devise,'montant_origine':d.montant,'taux_jour':taux}],
        'rh_versement','rh_dette',d.id,numero,request.user.id)
    d.statut='verse';d.verse_at=datetime.now();d.mouvement_id=m.id;d.ecriture_id=e.id
    sauver(d,request)
    if d.demande_id:
        RHDemande.objects.filter(id=d.demande_id).update(statut='verse')
    return Response({'numero':numero,'montant':str(d.montant),'devise':d.devise,'nom':d.agent.nom,'date':date.today(),'ecriture':e.numero})
