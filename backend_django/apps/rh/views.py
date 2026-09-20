"""Dossiers et temps RH. Les responsables d'équipe ne reçoivent aucune donnée de paie."""

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.rh.models import RHAgent
from apps.rh.serializers import RHAgentSerializer
from apps.rh.models import RHDocument
from apps.rh.serializers import RHDocumentSerializer
from apps.rh.models import RHPointage
from apps.rh.serializers import RHPointageSerializer
from apps.rh.models import RHDemande
from apps.rh.serializers import RHDemandeSerializer
import hashlib
import re
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from django.db import transaction
from django.db.models import Q, F
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from rest_framework.response import Response
from core.auth import assert_acces_societe, assert_role
from core.models import Societe, Utilisateur, UtilisateurSociete, Tiers
from apps.rh.models import RHEquipe, RHHoraire, RHAgent, RHContrat, RHEvenement, RHDocument, RHPointage, RHDemande, RHDette, RHSimulation
from core.services import enregistrer_audit
from core.views import _societe_param
from apps.comptabilite.tva_views import periode_mensuelle

DOSSIERS = {'RH', 'DRH', 'DFI'}
POINTAGES = DOSSIERS | {'RESP_EQUIPE'}


def ident(v):
    try: return UUID(str(v))
    except (ValueError, TypeError): raise ValidationError('Identifiant invalide.')


def contexte(request, autorises=DOSSIERS):
    sid = ident(_societe_param(request))
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, autorises)
    if request.method != 'GET':
        Societe.objects.filter(id=sid).update(nom=F('nom'))
    return sid, roles


def texte(p, cle, maxlen=180, obligatoire=False):
    v = p.get(cle, '')
    if not isinstance(v, str): raise ValidationError(f'{cle} doit être du texte.')
    v = v.strip()
    if len(v)>maxlen or (obligatoire and not v): raise ValidationError(f'Champ {cle} invalide (maximum {maxlen} caractères).')
    return v


def jour(v, facultatif=False):
    if not v and facultatif: return None
    try: return date.fromisoformat(str(v))
    except ValueError: raise ValidationError('Date invalide.')


def choix(v, valeurs):
    if v not in valeurs: raise ValidationError('Valeur non autorisée : '+str(v))
    return v


def argent(v):
    try:
        n = Decimal(str(v))
        if not n.is_finite() or n<0 or n>Decimal('9999999999999999.99') or n != n.quantize(Decimal('.01')): raise ValueError
        return n
    except (InvalidOperation, ValueError, TypeError): raise ValidationError('Montant positif attendu, avec deux décimales au maximum.')


def normalise(v):
    return ' '.join(re.sub(r'[^\w\s]', ' ', ''.join(c for c in unicodedata.normalize('NFKD', v.casefold()) if not unicodedata.combining(c))).split())


def sauver(obj, request, creation=False):
    if creation: obj.created_by=request.user.id
    else:
        if request.data.get('revision') != obj.revision: raise ValidationError('Cette fiche a changé. Rechargez-la avant de modifier.')
        obj.revision += 1
    obj.updated_by=request.user.id
    obj.save()
    # Le journal général ne doit pas recopier de données RH confidentielles.
    enregistrer_audit(request.user.id, 'CREATE' if creation else 'UPDATE', obj._meta.model_name, obj.id, None, {'revision':obj.revision})


def agents_visibles(sid, roles, user):
    q=RHAgent.objects.filter(societe_id=sid).select_related('equipe', 'horaire')
    return q if roles & DOSSIERS else q.filter(equipe__responsable_id=user.id)


def agent_requis(sid, valeur, roles=DOSSIERS, user=None):
    a=agents_visibles(sid,roles,user).filter(id=ident(valeur)).first()
    if not a: raise NotFound('Agent introuvable dans votre périmètre.')
    return a


def agent_dict(a, prive=False):
    return RHAgentSerializer(a, context={'prive': prive}).data


def simple(obj, champs):
    return {'id':str(obj.id),'revision':obj.revision, **{c:getattr(obj,c) for c in champs}}


class OrganisationViewSet(MetierViewSet):
    """Ressource Organisation ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def get_organisation(self, request):
        return self._traiter_organisation(request)


    @action(detail=False, methods=['post'])
    def post_organisation(self, request):
        return self._traiter_organisation(request)


    @transaction.atomic
    def _traiter_organisation(self, request):
        sid,roles=contexte(request, POINTAGES)
        if request.method=='POST':
            assert_role(roles,DOSSIERS)
            p=request.data; nature=choix(p.get('nature'),['equipe','horaire'])
            cls=RHEquipe if nature=='equipe' else RHHoraire
            nom=texte(p,'nom',120,True)
            if cls.objects.filter(societe_id=sid,nom__iexact=nom).exists(): raise ValidationError('Ce nom existe déjà dans cette société.')
            obj=cls(societe_id=sid,nom=nom)
            if nature=='equipe':
                if p.get('responsable_id'):
                    uid=ident(p['responsable_id'])
                    if not UtilisateurSociete.objects.filter(societe_id=sid,utilisateur_id=uid,utilisateur__actif=True).exists(): raise ValidationError('Responsable non affecté à cette société.')
                    obj.responsable_id=uid
            else:
                semaine=p.get('semaine')
                if not isinstance(semaine,list) or not 1<=len(semaine)<=7: raise ValidationError('Sélectionnez un à sept jours.')
                jours=[]; lignes=[]
                for s in semaine:
                    if not isinstance(s,dict) or type(s.get('jour')) is not int or s['jour'] not in range(7) or s['jour'] in jours: raise ValidationError('Jour invalide ou répété.')
                    jours.append(s['jour']); d=date(2026,1,5)+timedelta(days=s['jour'])
                    debut,fin,pd,pf,minutes,nuit=heures(d,s)
                    lignes.append({'jour':s['jour'],'debut':debut.strftime('%H:%M'),'fin':fin.strftime('%H:%M'),
                        'lendemain':fin.date()>d, 'pause_debut':s.get('pause_debut',''),'pause_fin':s.get('pause_fin',''),
                        'minutes':minutes,'minutes_nuit':nuit})
                obj.semaine=lignes;obj.note=texte(p,'note',3000)
            sauver(obj,request,True)
        equipes=RHEquipe.objects.filter(societe_id=sid)
        if not roles & DOSSIERS: equipes=equipes.filter(responsable_id=request.user.id)
        utilisateurs=[]
        if roles & DOSSIERS:
            utilisateurs=list(Utilisateur.objects.filter(utilisateursociete__societe_id=sid,actif=True).distinct().values('id','nom','prenom'))
        return Response({'dossiers':bool(roles & DOSSIERS), 'equipes':[
            simple(e,['nom','responsable_id']) for e in equipes.order_by('nom')],
            'horaires':[simple(h,['nom','semaine','note']) for h in RHHoraire.objects.filter(societe_id=sid).order_by('nom')] if roles & DOSSIERS else [],
            'utilisateurs':utilisateurs,
            'tiers_agents':list(Tiers.objects.filter(societe_id=sid,type='agent',actif=True).values('id','nom')) if roles&DOSSIERS else []},status=201 if request.method=='POST' else 200)


def heures(d,p):
    def lire(cle):
        v=p.get(cle,'')
        if not isinstance(v,str) or not re.fullmatch(r'\d{2}:\d{2}',v): raise ValidationError(f'Heure {cle} attendue (HH:MM).')
        try: return datetime.combine(d,time.fromisoformat(v))
        except ValueError: raise ValidationError('Heure invalide.')
    b=lire('debut');f=lire('fin')
    if type(p.get('lendemain',False)) is not bool: raise ValidationError('Indiquez si la fin est le lendemain.')
    if p.get('lendemain'): f+=timedelta(days=1)
    if not 0<(f-b).total_seconds()<86400: raise ValidationError('La fin doit suivre le début et le service durer moins de 24 heures.')
    pd=pf=None; intervalles=[(b,f)]
    if p.get('pause_debut') or p.get('pause_fin'):
        pd=lire('pause_debut');pf=lire('pause_fin')
        if pd<b: pd+=timedelta(days=1)
        if pf<=pd: pf+=timedelta(days=1)
        if not b<=pd<pf<=f: raise ValidationError('La pause doit être comprise dans le service.')
        intervalles=[(b,pd),(pf,f)]
    minutes=sum(int((y-x).total_seconds()/60) for x,y in intervalles)
    nuit=0
    # Art.124 + arrêté 68/14 : 19h–5h. L'art.125 (18h–6h) est un régime protecteur distinct.
    for offset in (-1,0,1):
        n=datetime.combine(d+timedelta(days=offset),time(19));nf=n+timedelta(hours=10)
        for x,y in intervalles: nuit+=max(0,int((min(y,nf)-max(x,n)).total_seconds()/60))
    return b,f,pd,pf,minutes,nuit


def pointage_dict(p):
    return {**simple(p,['agent_id','jour','nature','debut','fin','pause_debut','pause_fin','minutes','minutes_nuit','horaire_prevu','note','statut','valide_at']),
        'nom':p.agent.nom,'matricule':p.agent.matricule}


class PointageViewSet(MetierModelViewSet):
    """Ressource Pointage ; contrats HTTP et validations métier conservés."""
    queryset = RHPointage.objects.none()
    serializer_class = RHPointageSerializer
    lookup_url_kwarg = 'pointage_id'

    def list(self, request):
        return self._traiter_pointages(request)


    def create(self, request):
        return self._traiter_pointages(request)


    @transaction.atomic
    def _traiter_pointages(self, request):
        sid,roles=contexte(request,POINTAGES)
        if request.method=='POST':
            p=request.data;a=agent_requis(sid,p.get('agent_id'),roles,request.user);d=jour(p.get('jour'))
            if d>date.today() or d<a.date_engagement or (a.date_sortie and d>a.date_sortie): raise ValidationError('Le pointage doit concerner un jour travaillé passé ou présent, entre engagement et sortie.')
            obj=RHPointage.objects.filter(agent=a,jour=d).first();nouveau=obj is None
            obj=obj or RHPointage(societe_id=sid,agent=a,jour=d)
            if obj.statut=='valide': raise ValidationError('Pointage validé : les RH doivent le rouvrir avec un motif avant correction.')
            obj.nature=choix(p.get('nature'),['present','absence','repos','conge','mission'])
            obj.note=texte(p,'note',2000)
            obj.debut=obj.fin=obj.pause_debut=obj.pause_fin=None;obj.minutes=obj.minutes_nuit=0
            if obj.nature in ('present','mission'):
                obj.debut,obj.fin,obj.pause_debut,obj.pause_fin,obj.minutes,obj.minutes_nuit=heures(d,p)
                if RHPointage.objects.filter(agent=a,debut__lt=obj.fin,fin__gt=obj.debut).exclude(id=obj.id).exists(): raise ValidationError('Ce service chevauche un autre pointage de l’agent.')
            if nouveau:
                ligne=next((s for s in (a.horaire.semaine if a.horaire else []) if s['jour']==d.weekday()),None)
                obj.horaire_prevu={'nom':a.horaire.nom if a.horaire else '', 'ligne':ligne}
            sauver(obj,request,nouveau)
            return Response(pointage_dict(obj),status=201 if nouveau else 200)
        du,au=periode_mensuelle(request.query_params.get('mois',date.today().strftime('%Y-%m')))
        q=RHPointage.objects.filter(agent__in=agents_visibles(sid,roles,request.user),jour__range=(du,au)).select_related('agent').order_by('-jour','agent__nom')
        return Response([pointage_dict(p) for p in q])


    @action(detail=True, methods=['post'])
    @transaction.atomic
    def decision(self, request, pointage_id):
        sid,roles=contexte(request);p=RHPointage.objects.filter(id=pointage_id,societe_id=sid).select_related('agent').first()
        if not p: raise NotFound()
        action=choix(request.data.get('action'),['valider','rouvrir'])
        if action=='valider':
            if p.statut!='brouillon': raise ValidationError('Pointage déjà validé.')
            p.statut='valide';p.valide_par=request.user.id;p.valide_at=datetime.now()
        else:
            if p.statut!='valide': raise ValidationError('Ce pointage est déjà modifiable.')
            motif=texte(request.data,'motif',500,True)
            RHEvenement.objects.create(societe_id=sid,agent=p.agent,nature='administratif',date=date.today(),titre=f'Correction du pointage du {p.jour}',contenu=motif+'\nAvant correction : '+str(pointage_dict(p)),created_by=request.user.id,updated_by=request.user.id)
            p.statut='brouillon';p.valide_par=None;p.valide_at=None
        sauver(p,request)
        return Response(pointage_dict(p))


class AgentViewSet(MetierModelViewSet):
    """Ressource Agent ; contrats HTTP et validations métier conservés."""
    queryset = RHAgent.objects.none()
    serializer_class = RHAgentSerializer
    lookup_url_kwarg = 'agent_id'

    def list(self, request):
        return self._traiter_agents(request)


    def create(self, request):
        return self._traiter_agents(request)


    def update(self, request):
        return self._traiter_agents(request)


    @transaction.atomic
    def _traiter_agents(self, request):
        sid,roles=contexte(request,POINTAGES)
        if request.method=='GET': return Response([agent_dict(a,bool(roles&DOSSIERS)) for a in agents_visibles(sid,roles,request.user).order_by('nom')])
        assert_role(roles,DOSSIERS)
        p=request.data; nouveau=request.method=='POST'
        a=RHAgent(societe_id=sid) if nouveau else agent_requis(sid,p.get('id'))
        ancien_lien=(a.utilisateur_id,a.tiers_id)
        a.matricule=texte(p,'matricule',40,True).upper();a.nom=texte(p,'nom',180,True);a.nom_normalise=normalise(a.nom)
        q=RHAgent.objects.filter(societe_id=sid).exclude(id=a.id)
        if q.filter(matricule=a.matricule).exists(): raise ValidationError('Matricule déjà utilisé dans cette société.')
        similaires=q.filter(nom_normalise=a.nom_normalise)
        if similaires.exists() and not texte(p,'motif_homonyme',500): raise ValidationError('Ce nom existe déjà : '+', '.join(similaires.values_list('matricule',flat=True))+'. Sélectionnez la fiche existante ou expliquez l’homonymie.')
        a.date_engagement=jour(p.get('date_engagement'));a.date_sortie=jour(p.get('date_sortie'),True)
        if a.date_sortie and a.date_sortie<a.date_engagement: raise ValidationError('La sortie doit suivre l’engagement.')
        if not nouveau:
            if RHContrat.objects.filter(agent=a,debut__lt=a.date_engagement).exists() or RHPointage.objects.filter(agent=a,jour__lt=a.date_engagement).exists():
                raise ValidationError('Un contrat ou pointage précède cette date d’engagement.')
            if a.date_sortie and RHPointage.objects.filter(agent=a,jour__gt=a.date_sortie).exists():
                raise ValidationError('Des pointages existent après cette date de sortie.')
        for cle,lim in [('telephone',40),('email',254),('adresse',3000),('numero_cnss',80),('nif',80),('poste',150)]: setattr(a,cle,texte(p,cle,lim))
        for cle in ('numero_cnss','nif'):
            if getattr(a,cle) and q.filter(**{cle:getattr(a,cle)}).exists(): raise ValidationError(f'{cle} déjà utilisé dans cette société.')
        for cle,cls in [('equipe',RHEquipe),('horaire',RHHoraire)]:
            val=p.get(cle+'_id');obj=cls.objects.filter(id=ident(val),societe_id=sid).first() if val else None
            if val and not obj: raise ValidationError(f'{cle} d’une autre société ou inexistant.')
            setattr(a,cle,obj)
        a.utilisateur_id=ident(p['utilisateur_id']) if p.get('utilisateur_id') else None
        if a.utilisateur_id:
            if not UtilisateurSociete.objects.filter(societe_id=sid,utilisateur_id=a.utilisateur_id,utilisateur__actif=True).exists(): raise ValidationError('Compte non affecté à cette société.')
            if q.filter(utilisateur_id=a.utilisateur_id).exists(): raise ValidationError('Ce compte est déjà lié à une fiche agent.')
        a.tiers_id=ident(p['tiers_id']) if p.get('tiers_id') else None
        if a.tiers_id:
            if not Tiers.objects.filter(id=a.tiers_id,societe_id=sid,type='agent',actif=True).exists(): raise ValidationError('Choisissez un bénéficiaire agent actif de cette société.')
            tiers=Tiers.objects.get(id=a.tiers_id)
            if a.utilisateur_id and tiers.utilisateur_id and a.utilisateur_id!=tiers.utilisateur_id: raise ValidationError('Le bénéficiaire financier et le compte de connexion désignent deux personnes différentes.')
            if q.filter(tiers_id=a.tiers_id).exists(): raise ValidationError('Ce bénéficiaire est déjà lié à un autre dossier agent.')
        if not nouveau and ancien_lien!=(a.utilisateur_id,a.tiers_id) and RHDette.objects.filter(agent=a).exists():
            raise ValidationError('Un dossier financier utilise déjà cette identité. Le changement de compte nécessite un rapprochement préalable.')
        sauver(a,request,nouveau)
        if similaires.exists():
            RHEvenement.objects.create(societe_id=sid,agent=a,nature='administratif',date=date.today(),titre='Homonymie vérifiée',contenu=texte(p,'motif_homonyme',500),created_by=request.user.id,updated_by=request.user.id)
        return Response(agent_dict(a,True),status=201 if nouveau else 200)


    @action(detail=True, methods=['get'])
    def get_dossier(self, request, agent_id):
        return self._traiter_dossier(request, agent_id)


    @action(detail=True, methods=['post'])
    def post_dossier(self, request, agent_id):
        return self._traiter_dossier(request, agent_id)


    @transaction.atomic
    def _traiter_dossier(self, request, agent_id):
        sid,roles=contexte(request);a=agent_requis(sid,agent_id)
        if request.method=='POST':
            p=request.data;nature=choix(p.get('nature'),['contrat','engagement','disciplinaire','formation','evaluation','administratif'])
            if nature=='contrat':
                debut=jour(p.get('debut'));fin=jour(p.get('fin'),True)
                typec=choix(p.get('type_contrat'),['CDI','CDD','stage','apprentissage'])
                if debut<a.date_engagement or (fin and fin<debut) or (a.date_sortie and (not fin or fin>a.date_sortie)): raise ValidationError('Dates de contrat incompatibles avec l’engagement ou la sortie.')
                if typec in ('CDD','stage','apprentissage') and not fin: raise ValidationError('Renseignez la fin prévue.')
                if RHContrat.objects.filter(agent=a,debut__lte=fin or date.max).filter(Q(fin__isnull=True)|Q(fin__gte=debut)).exists(): raise ValidationError('Un contrat couvre déjà cette période. Un avenant nécessite une gestion explicite des dates.')
                ref=texte(p,'reference',80,True)
                if RHContrat.objects.filter(societe_id=sid,reference__iexact=ref).exists(): raise ValidationError('Référence déjà utilisée.')
                obj=RHContrat(societe_id=sid,agent=a,reference=ref,type_contrat=typec,debut=debut,fin=fin,
                    salaire=argent(p.get('salaire')),base_salaire=choix(p.get('base_salaire'),['brut','net']),
                    devise=choix(p.get('devise'),['USD','CDF']),categorie=texte(p,'categorie',120),convention=texte(p,'convention',5000))
                if p.get('simulation_id'):
                    sim=RHSimulation.objects.filter(id=ident(p['simulation_id']),societe_id=sid).first()
                    if not sim: raise ValidationError('Proposition de rémunération introuvable dans cette société.')
                    if debut.year!=jour(sim.parametres['date_reference']).year: raise ValidationError('La proposition et le début du contrat doivent relever de la même année réglementaire. Préparez une simulation pour cette année.')
                    if obj.devise!=sim.parametres['devise'] or obj.base_salaire!='net' or obj.salaire!=Decimal(sim.resultat['net']):
                        raise ValidationError('Le contrat doit reprendre le net et la devise de la proposition sélectionnée. Recalculez une proposition si les montants changent.')
                    obj.remuneration={'simulation_id':str(sim.id),'nom':sim.nom,'parametres':sim.parametres,'resultat':sim.resultat}
            else:
                obj=RHEvenement(societe_id=sid,agent=a,nature=nature,date=jour(p.get('date')),
                    titre=texte(p,'titre',180,True),contenu=texte(p,'contenu',10000,True))
            sauver(obj,request,True)
        return Response({'agent':agent_dict(a,True),
            'contrats':[simple(c,['reference','type_contrat','debut','fin','salaire','base_salaire','devise','categorie','convention','remuneration']) for c in RHContrat.objects.filter(agent=a).order_by('-debut')],
            'evenements':[simple(e,['nature','date','titre','contenu','created_at']) for e in RHEvenement.objects.filter(agent=a).order_by('-date','-created_at')],
            'documents':[simple(d,['nom','nature','created_at']) for d in RHDocument.objects.filter(agent=a).defer('contenu').order_by('-created_at')]},status=201 if request.method=='POST' else 200)


    @action(detail=True, methods=['post'])
    @transaction.atomic
    def documents(self, request, agent_id):
        sid,roles=contexte(request);a=agent_requis(sid,agent_id)
        f=request.FILES.get('fichier')
        if not f or f.size>5*1024*1024 or not f.size: raise ValidationError('Fichier requis (maximum 5 Mo).')
        contenu=f.read();mime=''
        if contenu.startswith(b'%PDF-'): mime='application/pdf'
        elif contenu.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
        elif contenu.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
        if not mime: raise ValidationError('Formats admis : PDF, PNG et JPEG.')
        empreinte=hashlib.sha256(contenu).hexdigest()
        if RHDocument.objects.filter(agent=a,empreinte=empreinte).exists(): raise ValidationError('Ce document est déjà dans ce dossier.')
        obj=RHDocument(societe_id=sid,agent=a,nom=f.name[:180],nature=texte(request.data,'nature',30,True),mime=mime,empreinte=empreinte,contenu=contenu)
        sauver(obj,request,True)
        return Response(simple(obj,['nom','nature']),status=201)


class DocumentViewSet(MetierModelViewSet):
    """Ressource Document ; contrats HTTP et validations métier conservés."""
    queryset = RHDocument.objects.none()
    serializer_class = RHDocumentSerializer
    lookup_url_kwarg = 'document_id'

    def retrieve(self, request, document_id):
        sid,roles=contexte(request)
        d=RHDocument.objects.filter(id=document_id,societe_id=sid).first()
        if not d: raise NotFound()
        r=HttpResponse(bytes(d.contenu),content_type=d.mime)
        r['Content-Disposition']=content_disposition_header(True,d.nom)
        r['Cache-Control']='private, no-store';r['X-Content-Type-Options']='nosniff'
        return r


class DemandeViewSet(MetierModelViewSet):
    """Ressource Demande ; contrats HTTP et validations métier conservés."""
    queryset = RHDemande.objects.none()
    serializer_class = RHDemandeSerializer

    def list(self, request):
        return self._traiter_demandes(request)


    def create(self, request):
        return self._traiter_demandes(request)


    @transaction.atomic
    def _traiter_demandes(self, request):
        sid,roles=contexte(request)
        if request.method=='POST':
            p=request.data;a=agent_requis(sid,p.get('agent_id'));nature=choix(p.get('nature'),['conge','avance_salaire'])
            obj=RHDemande(societe_id=sid,agent=a,nature=nature,motif=texte(p,'motif',3000,True))
            if nature=='conge':
                obj.debut=jour(p.get('debut'));obj.fin=jour(p.get('fin'))
                if obj.fin<obj.debut or obj.debut<a.date_engagement: raise ValidationError('Période de congé invalide.')
                obj.type_conge=choix(p.get('type_conge'),['annuel','maladie','maternite','circonstance','sans_solde'])
                if RHDemande.objects.filter(agent=a,nature='conge',statut__in=['soumis','approuve'],debut__lte=obj.fin,fin__gte=obj.debut).exists(): raise ValidationError('Une demande de congé couvre déjà cette période.')
            else:
                obj.montant=argent(p.get('montant'));obj.devise=choix(p.get('devise'),['USD','CDF'])
                if not obj.montant: raise ValidationError('Le montant doit être supérieur à zéro.')
            sauver(obj,request,True)
        return Response([{**simple(d,['agent_id','nature','motif','debut','fin','type_conge','montant','devise','statut','created_at']),
            'nom':d.agent.nom,'matricule':d.agent.matricule} for d in RHDemande.objects.filter(societe_id=sid).select_related('agent').order_by('-created_at')],status=201 if request.method=='POST' else 200)


# Anciens points d’entrée conservés pour les intégrations existantes.
organisation = OrganisationViewSet.as_view({'get': 'get_organisation', 'post': 'post_organisation'}, http_method_names=['get', 'post', 'options'], detail=False, basename='organisation')
agents = AgentViewSet.as_view({'get': 'list', 'post': 'create', 'put': 'update'}, http_method_names=['get', 'post', 'put', 'options'], detail=False, basename='agent')
dossier = AgentViewSet.as_view({'get': 'get_dossier', 'post': 'post_dossier'}, http_method_names=['get', 'post', 'options'], detail=True, basename='agent')
pointages = PointageViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='pointage')
pointage_decision = PointageViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='pointage')
documents = AgentViewSet.as_view({'post': 'documents'}, http_method_names=['post', 'options'], detail=True, basename='agent')
document = DocumentViewSet.as_view({'get': 'retrieve'}, http_method_names=['get', 'options'], detail=True, basename='document')
demandes = DemandeViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='demande')
