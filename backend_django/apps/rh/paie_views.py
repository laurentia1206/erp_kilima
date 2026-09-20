
from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.rh.models import RHSimulation
from apps.rh.serializers import RHSimulationSerializer
from apps.rh.models import RHDecompte
from apps.rh.serializers import RHDecompteSerializer
from django.db import transaction
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, NotFound
from apps.rh.models import RHSimulation, RHDecompte, RHContrat
from apps.rh.views import contexte, texte, sauver, simple, ident, agent_requis
from apps.rh.calculs import simulation, decompte_brut


class CalculPaieViewSet(MetierViewSet):
    """Ressource CalculPaie ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['post'])
    def simuler(self, request):
        contexte(request)
        p,r=simulation(request.data)
        return Response({'parametres':p,'resultat':r})


class SimulationViewSet(MetierModelViewSet):
    """Ressource Simulation ; contrats HTTP et validations métier conservés."""
    queryset = RHSimulation.objects.none()
    serializer_class = RHSimulationSerializer

    def list(self, request):
        return self._traiter_simulations(request)


    def create(self, request):
        return self._traiter_simulations(request)


    @transaction.atomic
    def _traiter_simulations(self, request):
        sid,roles=contexte(request)
        if request.method=='POST':
            p,r=simulation(request.data)
            obj=RHSimulation(societe_id=sid,nom=texte(request.data,'nom',180,True),parametres=p,resultat=r)
            sauver(obj,request,True)
            return Response(simple(obj,['nom','parametres','resultat','created_at']),status=201)
        return Response([simple(o,['nom','parametres','resultat','created_at']) for o in RHSimulation.objects.filter(societe_id=sid).order_by('-created_at')])


class DecompteViewSet(MetierModelViewSet):
    """Ressource Decompte ; contrats HTTP et validations métier conservés."""
    queryset = RHDecompte.objects.none()
    serializer_class = RHDecompteSerializer

    def list(self, request):
        return self._traiter_decomptes(request)


    def create(self, request):
        return self._traiter_decomptes(request)


    @transaction.atomic
    def _traiter_decomptes(self, request):
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


# Anciens points d’entrée conservés pour les intégrations existantes.
simuler = CalculPaieViewSet.as_view({'post': 'simuler'}, http_method_names=['post', 'options'], detail=False, basename='calcul_paie')
simulations = SimulationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='simulation')
decomptes = DecompteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='decompte')
