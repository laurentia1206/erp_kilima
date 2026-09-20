from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, NotFound
from apps.rh.models import RHSimulation, RHDecompte, RHContrat
from apps.rh.views import contexte, texte, sauver, simple, ident, agent_requis
from apps.rh.calculs import simulation, decompte_brut


@api_view(['POST'])
def simuler(request):
    contexte(request)
    p,r=simulation(request.data)
    return Response({'parametres':p,'resultat':r})


@api_view(['GET','POST'])
@transaction.atomic
def simulations(request):
    sid,roles=contexte(request)
    if request.method=='POST':
        p,r=simulation(request.data)
        obj=RHSimulation(societe_id=sid,nom=texte(request.data,'nom',180,True),parametres=p,resultat=r)
        sauver(obj,request,True)
        return Response(simple(obj,['nom','parametres','resultat','created_at']),status=201)
    return Response([simple(o,['nom','parametres','resultat','created_at']) for o in RHSimulation.objects.filter(societe_id=sid).order_by('-created_at')])


@api_view(['GET','POST'])
@transaction.atomic
def decomptes(request):
    sid,roles=contexte(request)
    if request.method=='POST':
        p=request.data;a=agent_requis(sid,p.get('agent_id'))
        c=RHContrat.objects.filter(id=ident(p.get('contrat_id')),agent=a,societe_id=sid).first()
        if not c: raise ValidationError('Contrat de cet agent requis.')
        param,r=decompte_brut(p,a,c)
        obj=RHDecompte(societe_id=sid,agent=a,contrat=c,date_depart=param['date_depart'],motif=param['motif'],parametres=param,resultat=r)
        sauver(obj,request,True)
        return Response(simple(obj,['agent_id','date_depart','motif','parametres','resultat','statut','created_at']),status=201)
    return Response([simple(o,['agent_id','date_depart','motif','parametres','resultat','statut','created_at']) for o in RHDecompte.objects.filter(societe_id=sid).order_by('-created_at')])
