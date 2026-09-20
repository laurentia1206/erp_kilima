"""Cycle mensuel : préparation RH, contrôle, validation DFI, règlement, clôture."""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal as D
from django.db import transaction
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from apps.rh.models import RHPaieMois, RHBulletin, RHRetenue, RHPaiement, RHContrat, RHDette, RHSimulation, RHPointage
from core.models import Tiers, Societe
from apps.tresorerie.models import Caisse, SessionCaisse, MouvementCaisse, CompteBancaire
from apps.comptabilite.models import LigneEcriture
from apps.rh.views import contexte, ident, texte, choix, argent, sauver, simple, DOSSIERS, jour
from apps.rh.finances import CAISSE, tiers_agent
from apps.rh.calculs import arrondi, entier
from apps.rh.paie_mensuelle_calculs import calculer
from apps.comptabilite.tva_views import periode_mensuelle
from core import services as services
from apps.comptabilite import services as comptabilite

PAYER=CAISSE|{'COMPTABLE'}
LECTURE=DOSSIERS|PAYER


def objet(sid, pid):
    o=RHPaieMois.objects.filter(id=pid,societe_id=sid).first()
    if not o: raise NotFound('Paie introuvable dans cette société.')
    return o


def revision(o,p):
    if p.get('revision')!=o.revision: raise ValidationError('La paie a changé. Rechargez avant de continuer.')


def eligibles(o):
    debut,fin=periode_mensuelle(o.mois)
    return RHContrat.objects.filter(societe_id=o.societe_id,debut__lte=fin,agent__date_engagement__lte=fin).filter(
        Q(fin__isnull=True)|Q(fin__gte=debut)).filter(Q(agent__date_sortie__isnull=True)|Q(agent__date_sortie__gte=debut)).select_related('agent')


def sources(b):
    debut,fin=periode_mensuelle(b.periode.mois)
    ps=list(RHPointage.objects.filter(agent=b.agent,jour__range=(debut,fin)).order_by('jour').values('id','revision','jour','nature','minutes','minutes_nuit','statut'))
    c=b.contrat;a=b.agent
    contenu={'pointages':ps,'agent_revision':a.revision,'tiers':str(a.tiers_id),'contrat_revision':c.revision,
             'contrat':str(c.id),'periode':b.periode.parametres}
    empreinte=hashlib.sha256(json.dumps(contenu,sort_keys=True,default=str).encode()).hexdigest()
    return empreinte,ps


def tiers_unique(a):
    q=Tiers.objects.filter(id__in=tiers_agent(a),actif=True,societe_id=a.societe_id)
    if q.count()!=1: raise ValidationError(f'{a.matricule} : reliez un bénéficiaire financier unique et actif à la fiche agent.')
    return q.first()


def retenues_verifiees(b, entrees):
    if not isinstance(entrees,list) or len(entrees)>100: raise ValidationError('Liste des retenues invalide.')
    total=D(0);lignes=[];vus=set()
    for p in entrees:
        if not isinstance(p,dict): raise ValidationError('Retenue invalide.')
        did=ident(p.get('dette_id'))
        if did in vus: raise ValidationError('Une dette ne doit figurer qu’une fois.')
        vus.add(did)
        d=RHDette.objects.filter(id=did,agent=b.agent,societe_id=b.societe_id).first()
        if not d: raise ValidationError('Dette introuvable pour cet agent.')
        if d.nature=='recouvrement':
            raise ValidationError('Recouvrement d’avance à justifier : le traitement du rapprochement DFI reste à confirmer avant retenue sur paie.')
        if d.statut!='verse' or not d.verse_at or d.verse_at.date()>periode_mensuelle(b.periode.mois)[1]:
            raise ValidationError('Seules les avances et prêts réellement versés peuvent être remboursés.')
        if d.devise!=b.contrat.devise: raise ValidationError('Dette et paie doivent utiliser la même devise ; aucun change implicite sur l’échéancier.')
        montant=argent(p.get('montant'))
        if not montant: raise ValidationError('Retenue positive requise.')
        anciennes=RHRetenue.objects.filter(dette=d,bulletin__periode__statut__in=['valide','cloture']).exclude(bulletin=b)
        rembourse=sum((r.montant for r in anciennes),D(0))
        echeance=sum((D(l['montant']) for l in d.echeancier if l['mois']==b.periode.mois),D(0))
        pris=sum((r.montant for r in anciennes.filter(mois_echeance=b.periode.mois)),D(0))
        if montant>min(d.montant-rembourse,echeance-pris): raise ValidationError('Retenue supérieure au solde ou à l’échéance convenue de ce mois.')
        # Apurement au cours historique du versement, sans recréer une créance de change.
        compte='421' if d.nature=='avance_salaire' else '272'
        debit=sum(LigneEcriture.objects.filter(ecriture_id=d.ecriture_id,sens='D',compte_numero=compte).values_list('montant_usd',flat=True),D(0))
        if not debit: raise ValidationError('Écriture de versement de la dette introuvable.')
        usd=debit-sum((r.montant_usd for r in anciennes),D(0)) if montant==d.montant-rembourse else arrondi(debit*montant/d.montant)
        lignes.append((d,montant,usd));total+=montant
    if total>D(b.resultat['plafond_retenues']): raise ValidationError('Les retenues dépassent la quotité autorisée. Revoyez l’échéancier par accord écrit.')
    if total>D(b.resultat['net']): raise ValidationError('Retenues supérieures au net disponible.')
    return total,lignes


def bulletin_dict(b,prive=True):
    paiement=RHPaiement.objects.filter(bulletin=b).first()
    r=b.resultat
    d={'id':str(b.id),'revision':b.revision,'agent_id':str(b.agent_id),'nom':r['nom'],'matricule':r['matricule'],
       'net_a_payer':r['net_a_payer'],'devise':r['devise'],'paye':bool(paiement) or D(r['net_a_payer'])==0,
       'paiement':simple(paiement,['date','mode','reference','montant','devise']) if paiement else None}
    if prive:
        d.update({'contrat_id':str(b.contrat_id),'saisie':b.saisie,'resultat':r,
                  'retenues':[{'dette_id':str(x.dette_id),'montant':str(x.montant),'nature':x.dette.nature} for x in RHRetenue.objects.filter(bulletin=b).select_related('dette')]})
    if prive:
        facteur=D(b.periode.parametres['taux_cdf']) if r['devise']=='USD' else D(1)
        d['declarations_cdf']={k:str(arrondi(D(r[k])*facteur)) for k in ['base_cnss','cnss_salarie','cnss_employeur','base_irpp','inpp','onem']}
        d['declarations_cdf']['irpp']=r['irpp_cdf']
    return d


def periode_dict(o,roles,detail=False):
    prive=bool(roles&DOSSIERS)
    d=simple(o,['mois','statut','decisions'])
    if prive: d['parametres']=o.parametres
    bs=list(RHBulletin.objects.filter(periode=o).select_related('agent','contrat','periode'))
    d['nombre']=len(bs);d['payes']=sum(RHPaiement.objects.filter(bulletin=b).exists() or D(b.resultat['net_a_payer'])==0 for b in bs)
    d['totaux']={dev:str(sum((D(b.resultat['net_a_payer']) for b in bs if b.resultat['devise']==dev),D(0))) for dev in ['USD','CDF']}
    if detail:
        d['bulletins']=[bulletin_dict(b,prive) for b in bs]
        if prive:
            d['contrats']=[{'id':str(c.id),'agent_id':str(c.agent_id),'nom':c.agent.nom,'matricule':c.agent.matricule,
                'reference':c.reference,'net':str(c.salaire),'devise':c.devise,'composition':c.remuneration.get('parametres',{}),
                'debut':c.debut,'fin':c.fin,'revision':c.revision} for c in eligibles(o)]
            d['dettes']=[{'id':str(x.id),'agent_id':str(x.agent_id),'nature':x.nature,'devise':x.devise,
                'echeance':str(sum((D(l['montant']) for l in x.echeancier if l['mois']==o.mois),D(0)))}
                for x in RHDette.objects.filter(societe_id=o.societe_id,statut='verse').exclude(nature='recouvrement')]
        d['caisses']=[{'id':str(c.id),'libelle':c.libelle} for c in Caisse.objects.filter(societe_id=o.societe_id,actif=True)]
        d['banques']=[{'id':str(c.id),'libelle':c.banque+' · '+(c.numero_compte or ''),'devise':c.devise} for c in CompteBancaire.objects.filter(societe_id=o.societe_id,actif=True)]
    return d


@api_view(['GET','POST'])
@transaction.atomic
def periodes(request):
    sid,roles=contexte(request,LECTURE)
    if request.method=='POST':
        if not roles&DOSSIERS: raise PermissionDenied('Préparation réservée aux RH / DFI.')
        p=request.data;mois=texte(p,'mois',7,True);debut,fin=periode_mensuelle(mois)
        if debut.year!=2026 or debut>date.today(): raise ValidationError('Paie 2026 uniquement, sans mois futur.')
        existant=objet(sid,ident(p['id'])) if p.get('id') else None
        if existant:
            revision(existant,p)
            if existant.statut!='brouillon' or existant.mois!=mois: raise ValidationError('Seuls les paramètres d’une paie en préparation peuvent être corrigés, sans changer le mois.')
        elif RHPaieMois.objects.filter(societe_id=sid,mois=mois).exists(): raise ValidationError('La paie de ce mois existe déjà.')
        taux=argent(p.get('taux_cdf'))
        if not 0<taux<=1000000: raise ValidationError('Taux CDF pour 1 USD requis.')
        effectif=entier(p,'effectif',1,1000000)
        heures=argent(p.get('heures_mensuelles_reference','195'))
        if not 1<=heures<=195: raise ValidationError('Horaire mensuel de référence : entre 1 et 195 heures pour le régime général.')
        secteur=choix(p.get('secteur'),['prive','public'])
        inpp='4' if secteur=='public' else ('3.5' if effectif<=50 else '3' if effectif<=300 else '2')
        o=existant or RHPaieMois(societe_id=sid,mois=mois)
        o.parametres={'taux_cdf':str(taux),'source_taux':texte(p,'source_taux',180,True),
            'effectif':effectif,'secteur':secteur,'taux_inpp':inpp,'heures_mensuelles_reference':str(heures),
            'reference_reglementaire':texte(p,'reference_reglementaire',2000,True)}
        sauver(o,request,existant is None)
        return Response(periode_dict(o,roles,True),status=200 if existant else 201)
    qs=RHPaieMois.objects.filter(societe_id=sid).order_by('-mois')
    if not roles&DOSSIERS: qs=qs.filter(statut__in=['valide','cloture'])
    return Response([periode_dict(o,roles) for o in qs])


@api_view(['GET'])
def detail(request,periode_id):
    sid,roles=contexte(request,LECTURE);o=objet(sid,periode_id)
    if not roles&DOSSIERS and o.statut not in ['valide','cloture']: raise PermissionDenied('Paie encore en préparation.')
    return Response(periode_dict(o,roles,True))


@api_view(['POST'])
@transaction.atomic
def composition(request,contrat_id):
    sid,roles=contexte(request);p=request.data
    c=RHContrat.objects.filter(id=contrat_id,societe_id=sid).first()
    if not c: raise NotFound()
    if c.remuneration or RHBulletin.objects.filter(contrat=c).exists():
        raise ValidationError('Ce contrat possède déjà une composition ou une paie. Un avenant doit être traité séparément.')
    s=RHSimulation.objects.filter(id=ident(p.get('simulation_id')),societe_id=sid).first()
    if not s or c.base_salaire!='net' or s.parametres['devise']!=c.devise or D(s.resultat['net'])!=c.salaire:
        raise ValidationError('La simulation doit correspondre exactement au net et à la devise du contrat.')
    c.remuneration={'simulation_id':str(s.id),'nom':s.nom,'parametres':s.parametres,'resultat':s.resultat}
    sauver(c,request)
    return Response({'detail':'Composition ajoutée au contrat existant, sans modifier le net convenu.'})


@api_view(['POST'])
@transaction.atomic
def preparer(request,periode_id):
    sid,roles=contexte(request);o=objet(sid,periode_id);p=request.data;revision(o,p)
    if o.statut!='brouillon': raise ValidationError('Rouvrez le contrôle avant toute modification. Une paie validée est figée.')
    c=eligibles(o).filter(id=ident(p.get('contrat_id'))).first()
    if not c: raise ValidationError('Contrat applicable à cette période requis.')
    if eligibles(o).filter(agent=c.agent).count()!=1:
        raise ValidationError('Plusieurs contrats couvrent ce mois. Une paie de transition doit être qualifiée avant traitement.')
    b=RHBulletin.objects.filter(periode=o,agent=c.agent).first()
    nouveau=b is None
    b=b or RHBulletin(periode=o,agent=c.agent,societe_id=sid,contrat=c)
    b.contrat=c;b.saisie,b.resultat=calculer(c,o,p)
    b.empreinte_sources,ps=sources(b)
    b.resultat['pointages']=[{**x,'id':str(x['id']),'jour':str(x['jour'])} for x in ps]
    if sum(x['minutes_nuit'] for x in ps)>0 and p.get('regime_nuit')=='aucun':
        raise ValidationError('Les pointages contiennent du travail de nuit. Qualifiez le régime avant calcul.')
    if D(p.get('heures_nuit','0'))*60<sum(x['minutes_nuit'] for x in ps) and p.get('regime_nuit')!='exclusion_documentee':
        raise ValidationError('Les heures de nuit saisies sont inférieures aux pointages. Rapprochez les temps avant calcul.')
    total,lignes=retenues_verifiees(b,p.get('retenues',[]))
    b.resultat.update({'retenues_total':str(total),'net_a_payer':str(D(b.resultat['net'])-total),
                       'tiers_id':str(tiers_unique(c.agent).id)})
    b.created_by=b.created_by or request.user.id;b.updated_by=request.user.id
    if not nouveau: b.revision+=1
    b.save();RHRetenue.objects.filter(bulletin=b).delete()
    for d,m,usd in lignes:
        RHRetenue.objects.create(societe_id=sid,bulletin=b,dette=d,montant=m,montant_usd=usd,mois_echeance=o.mois,created_by=request.user.id,updated_by=request.user.id)
    sauver(o,request)
    return Response(periode_dict(o,roles,True),status=201 if nouveau else 200)


def controles(o):
    bs=list(RHBulletin.objects.filter(periode=o).select_related('agent','contrat','periode'))
    if not bs: raise ValidationError('Préparez au moins un bulletin.')
    for b in bs:
        empreinte,ps=sources(b)
        if empreinte!=b.empreinte_sources: raise ValidationError(f'{b.agent.matricule} : dossier ou pointages modifiés. Recalculez le bulletin.')
        if any(p['statut']!='valide' for p in ps): raise ValidationError(f'{b.agent.matricule} : validez les pointages du mois avant contrôle de paie.')
        if str(tiers_unique(b.agent).id)!=b.resultat['tiers_id']: raise ValidationError('Bénéficiaire financier modifié. Recalculez.')
        entrees=[{'dette_id':str(x.dette_id),'montant':str(x.montant)} for x in RHRetenue.objects.filter(bulletin=b)]
        total,lignes=retenues_verifiees(b,entrees)
        if total!=D(b.resultat['retenues_total']): raise ValidationError('Retenues modifiées. Recalculez.')
        for d,m,usd in lignes:
            if RHRetenue.objects.get(bulletin=b,dette=d).montant_usd!=usd:
                raise ValidationError('Le solde comptable d’une dette a changé. Recalculez ce bulletin.')
    return bs


def comptabiliser(b,request):
    r=b.resultat;dev=r['devise'];fx=D(b.periode.parametres['taux_cdf']) if dev=='CDF' else D(1)
    tiers=r['tiers_id'];lignes=[]
    def ligne(sens,compte,montant,libelle,tid=None,usd=None):
        m=D(montant)
        if m:
            lignes.append({'sens':sens,'compte':compte,'montant_usd':arrondi(m/fx) if usd is None else usd,
                           'tiers_id':tid,'libelle':libelle,'devise_origine':dev,'montant_origine':m,'taux_jour':fx})
    ligne('D','661',r['brut_total'],'Rémunération brute')
    ligne('D','664',D(r['cnss_employeur'])+D(r['inpp'])+D(r['onem']),'Charges patronales')
    ligne('C','431',D(r['cnss_salarie'])+D(r['cnss_employeur']),'CNSS')
    ligne('C','447',r['irpp'],'IRPP salarié')
    ligne('C','433',r['inpp'],'INPP')
    ligne('C','437',r['onem'],'ONEM')
    b.net_comptable_usd=arrondi(D(r['net_a_payer'])/fx)
    ligne('C','422',r['net_a_payer'],'Net à payer',tiers)
    ecart_change=D(0)
    for x in RHRetenue.objects.filter(bulletin=b).select_related('dette'):
        ligne('C','421' if x.dette.nature=='avance_salaire' else '272',x.montant,'Remboursement accord '+str(x.dette_id)[:8],tiers,usd=x.montant_usd)
        ecart_change+=x.montant_usd-arrondi(x.montant/fx)
    if ecart_change: lignes.append({'sens':'D' if ecart_change>0 else 'C','compte':'676' if ecart_change>0 else '776','montant_usd':abs(ecart_change),'libelle':'Change sur remboursement'})
    ecart=sum((x['montant_usd']*(1 if x['sens']=='D' else -1) for x in lignes),D(0))
    if abs(ecart)>D('.10'): raise ValidationError('Écart comptable inattendu : contrôle requis.')
    if ecart: lignes.append({'sens':'C' if ecart>0 else 'D','compte':'758' if ecart>0 else '658','montant_usd':abs(ecart),'libelle':'Arrondi de conversion de paie'})
    e=comptabilite.post_ecriture(b.societe_id,'PAI','Paie','operations_diverses',min(date.today(),periode_mensuelle(b.periode.mois)[1]),
        f'Paie {b.periode.mois} · {r["matricule"]}',lignes,'rh_paie','rh_bulletin',b.id,'PAIE-'+b.periode.mois+'-'+str(b.id)[:8],request.user.id)
    b.ecriture_id=e.id;b.save(update_fields=['ecriture_id','net_comptable_usd'])


@api_view(['POST'])
@transaction.atomic
def decision(request,periode_id):
    sid,roles=contexte(request);o=objet(sid,periode_id);p=request.data;revision(o,p)
    action=choix(p.get('action'),['controler','rouvrir','valider','cloturer'])
    commentaire=texte(p,'commentaire',3000,True)
    if action=='controler':
        if not roles&{'RH','DRH'}: raise PermissionDenied('Le contrôle doit être réalisé par les RH / DRH.')
        if o.statut!='brouillon': raise ValidationError('Paie déjà contrôlée.')
        bs=controles(o)
        manquants=set(str(c.agent_id) for c in eligibles(o))-set(str(b.agent_id) for b in bs)
        exclusions=p.get('exclusions',[])
        if not isinstance(exclusions,list) or any(not isinstance(x,dict) for x in exclusions): raise ValidationError('Liste des exclusions invalide.')
        if {str(x.get('agent_id')) for x in exclusions}!=manquants: raise ValidationError('Expliquez individuellement chaque agent non préparé.')
        o.parametres['exclusions']=[{'agent_id':str(ident(x['agent_id'])),'motif':texte(x,'motif',1000,True)} for x in exclusions]
        # Les exclusions font partie du contrôle, pas des paramètres de calcul.
        for b in bs:
            b.periode=o;b.empreinte_sources=sources(b)[0];b.save(update_fields=['empreinte_sources'])
        o.statut='controle'
    elif action=='rouvrir':
        if o.statut!='controle': raise ValidationError('Seule une paie contrôlée non comptabilisée peut être rouverte.')
        o.statut='brouillon'
    elif action=='valider':
        if 'DFI' not in roles: raise PermissionDenied('Validation réservée au DFI.')
        if o.statut!='controle': raise ValidationError('Contrôle RH préalable requis.')
        controle=next((x for x in reversed(o.decisions) if x['action']=='controler'),None)
        if not controle or controle['utilisateur_id']==str(request.user.id): raise PermissionDenied('DFI et contrôleur RH doivent être deux personnes distinctes.')
        if p.get('reglementation_verifiee') is not True: raise ValidationError('Confirmez le rapprochement des bases et barèmes avec vos références réglementaires, notamment IRPP et INPP.')
        bs=controles(o)
        couverts={str(b.agent_id) for b in bs}|{x['agent_id'] for x in o.parametres.get('exclusions',[])}
        if set(str(c.agent_id) for c in eligibles(o))!=couverts: raise ValidationError('La liste des contrats du mois a changé. Rouvrez le contrôle.')
        for b in bs: comptabiliser(b,request)
        o.statut='valide'
    else:
        if 'DFI' not in roles: raise PermissionDenied('Clôture réservée au DFI.')
        if o.statut!='valide': raise ValidationError('La paie doit être validée avant clôture.')
        if any(D(b.resultat['net_a_payer']) and not RHPaiement.objects.filter(bulletin=b).exists() for b in RHBulletin.objects.filter(periode=o)):
            raise ValidationError('Des bulletins restent à payer.')
        o.statut='cloture'
    o.decisions=[*o.decisions,{'action':action,'utilisateur_id':str(request.user.id),'nom':request.user.nom,'date':datetime.now().isoformat(),'commentaire':commentaire}]
    sauver(o,request)
    return Response(periode_dict(o,roles,True))


@api_view(['POST'])
@transaction.atomic
def payer(request,bulletin_id):
    sid,roles=contexte(request,PAYER);p=request.data
    b=RHBulletin.objects.filter(id=bulletin_id,societe_id=sid).select_related('periode','agent').first()
    if not b: raise NotFound()
    revision(b,p)
    if b.periode.statut!='valide' or not b.ecriture_id or RHPaiement.objects.filter(bulletin=b).exists(): raise ValidationError('Ce bulletin n’est pas disponible pour un nouveau règlement.')
    if str(b.agent.utilisateur_id)==str(request.user.id): raise PermissionDenied('Un agent ne peut pas enregistrer son propre paiement.')
    if any(x['action'] in ['controler','valider'] and x['utilisateur_id']==str(request.user.id) for x in b.periode.decisions):
        raise PermissionDenied('Le paiement doit être enregistré par une personne distincte du contrôle RH et de la validation DFI.')
    mode=choix(p.get('mode'),['caisse','banque']);ref=texte(p,'reference',64,True)
    if mode=='caisse' and not roles&CAISSE: raise PermissionDenied('Paiement en espèces réservé à la caisse.')
    jour_paie=jour(p.get('date'))
    date_validation=date.fromisoformat(next(x['date'][:10] for x in reversed(b.periode.decisions) if x['action']=='valider'))
    if jour_paie<date_validation or jour_paie>date.today(): raise ValidationError('Date comprise entre la validation DFI et aujourd’hui requise.')
    dev=b.resultat['devise'];montant=D(b.resultat['net_a_payer'])
    if not montant: raise ValidationError('Bulletin sans net à verser.')
    taux=D(1) if dev=='USD' else services.get_taux_jour(jour_paie,dev)
    if taux is None or D(str(taux))<=0: raise ValidationError('Enregistrez le taux de change exact à la date de règlement.')
    taux=D(str(taux));usd=arrondi(montant/taux)
    if usd<=0: raise ValidationError('Montant trop faible pour le règlement comptable en USD.')
    tiers=Tiers.objects.filter(id=b.resultat['tiers_id'],societe_id=sid,actif=True).first()
    if not tiers: raise ValidationError('Le bénéficiaire validé est inactif. Rapprochement DFI requis.')
    m=None;banque=None
    if mode=='caisse':
        if jour_paie!=date.today(): raise ValidationError('Le paiement en caisse doit être enregistré le jour du versement.')
        caisse=Caisse.objects.filter(id=ident(p.get('caisse_id')),societe_id=sid,actif=True).first()
        if not caisse: raise ValidationError('Caisse active de cette société requise.')
        session=SessionCaisse.objects.select_for_update().filter(caisse_id=caisse.id,statut='ouverte').first()
        if not session: raise ValidationError('Ouvrez une session de caisse.')
        from apps.tresorerie.views import _soldes
        if D(str(_soldes(session).get(dev,0)))<montant: raise ValidationError('Solde insuffisant dans cette devise.')
        numero=services.next_numero('bon_caisse',jour_paie.year,Societe.objects.get(id=sid).code,sid)
        m=MouvementCaisse.objects.create(caisse_id=caisse.id,session_id=session.id,numero=numero,sens='sortie',nature='Salaire',
            devise=dev,taux_jour=taux,montant=montant,montant_usd=usd,reference_type='rh_bulletin',reference_id=b.id,
            reference=ref,tiers_id=tiers.id,tiers_nom=b.resultat['nom'],libelle='Paie '+b.periode.mois,
            created_by=request.user.id,date_mouvement=jour_paie,heure=services.maintenant())
        compte=caisse.compte_comptable or '571';journal='CA';typejournal='caisse'
    else:
        banque=CompteBancaire.objects.filter(id=ident(p.get('compte_bancaire_id')),societe_id=sid,actif=True,devise=dev).first()
        if not banque: raise ValidationError('Compte bancaire actif de cette société, dans la devise de paie, requis.')
        if p.get('virement_confirme') is not True: raise ValidationError('Confirmez le virement réellement exécuté et sa référence bancaire.')
        if RHPaiement.objects.filter(societe_id=sid,compte_bancaire=banque,reference=ref).exists(): raise ValidationError('Cette référence bancaire a déjà servi à un paiement salarial.')
        compte=banque.compte_comptable or '521';journal='BQ';typejournal='banque';numero=ref
    lignes=[{'sens':'D','compte':'422','tiers_id':str(tiers.id),'montant_usd':b.net_comptable_usd,'libelle':ref,
              'devise_origine':dev,'montant_origine':montant,'taux_jour':D(b.periode.parametres['taux_cdf']) if dev=='CDF' else D(1)},
             {'sens':'C','compte':compte,'montant_usd':usd,'libelle':ref,'devise_origine':dev,'montant_origine':montant,'taux_jour':taux}]
    ecart=usd-b.net_comptable_usd
    if ecart: lignes.append({'sens':'D' if ecart>0 else 'C','compte':'676' if ecart>0 else '776','montant_usd':abs(ecart),'libelle':'Change sur règlement salarial'})
    e=comptabilite.post_ecriture(sid,journal,'Caisse' if mode=='caisse' else 'Banque',typejournal,jour_paie,
        'Règlement paie '+b.periode.mois,lignes,'rh_reglement','rh_bulletin',b.id,numero,request.user.id)
    pay=RHPaiement(societe_id=sid,bulletin=b,mode=mode,date=jour_paie,reference=ref,montant=montant,devise=dev,
        ecriture_id=e.id,mouvement_id=m.id if m else None,compte_bancaire=banque)
    sauver(pay,request,True);sauver(b,request)
    return Response(bulletin_dict(b,False))
