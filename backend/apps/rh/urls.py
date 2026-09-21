from django.urls import path, include
from apps.rh import finances as rh_finances
from apps.rh import paie_mensuelle_views as rh_mensuel_views
from apps.rh import paie_views as rh_paie_views
from apps.rh import views as rh_views

urlpatterns = [
    path('rh/paies', rh_mensuel_views.PaieViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='paie')),
    path('rh/paies/<uuid:periode_id>', rh_mensuel_views.PaieViewSet.as_view({'get': 'retrieve'}, http_method_names=['get', 'options'], detail=True, basename='paie')),
    path('rh/paies/<uuid:periode_id>/preparer', rh_mensuel_views.PaieViewSet.as_view({'post': 'preparer'}, http_method_names=['post', 'options'], detail=True, basename='paie')),
    path('rh/paies/<uuid:periode_id>/decision', rh_mensuel_views.PaieViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='paie')),
    path('rh/bulletins/<uuid:bulletin_id>/payer', rh_mensuel_views.BulletinViewSet.as_view({'post': 'payer'}, http_method_names=['post', 'options'], detail=True, basename='bulletin')),
    path('rh/contrats/<uuid:contrat_id>/composition', rh_mensuel_views.ContratViewSet.as_view({'post': 'composition'}, http_method_names=['post', 'options'], detail=True, basename='contrat')),
    path('rh/simuler', rh_paie_views.CalculPaieViewSet.as_view({'post': 'simuler'}, http_method_names=['post', 'options'], detail=False, basename='calcul_paie')),
    path('rh/simulations', rh_paie_views.SimulationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='simulation')),
    path('rh/decomptes', rh_paie_views.DecompteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='decompte')),
    path('rh/politique', rh_finances.PolitiqueViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='politique')),
    path('rh/avances-a-justifier', rh_finances.AvanceJustifierViewSet.as_view({'get': 'sources'}, http_method_names=['get', 'options'], detail=False, basename='avance_justifier')),
    path('rh/dettes', rh_finances.DetteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='dette')),
    path('rh/dettes/<uuid:dette_id>/decision', rh_finances.DetteViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='dette')),
    path('rh/dettes/<uuid:dette_id>/accord', rh_finances.DetteViewSet.as_view({'get': 'accord'}, http_method_names=['get', 'options'], detail=True, basename='dette')),
    path('rh/a-payer', rh_finances.DetteAPayerViewSet.as_view({'get': 'a_payer'}, http_method_names=['get', 'options'], detail=False, basename='dette_a_payer')),
    path('rh/dettes/<uuid:dette_id>/verser', rh_finances.DetteViewSet.as_view({'post': 'verser'}, http_method_names=['post', 'options'], detail=True, basename='dette')),
    path('rh/organisation', rh_views.OrganisationViewSet.as_view({'get': 'get_organisation', 'post': 'post_organisation'}, http_method_names=['get', 'post', 'options'], detail=False, basename='organisation')),
    path('rh/agents', rh_views.AgentViewSet.as_view({'get': 'list', 'post': 'create', 'put': 'update'}, http_method_names=['get', 'post', 'put', 'options'], detail=False, basename='agent')),
    path('rh/agents/<uuid:agent_id>/dossier', rh_views.AgentViewSet.as_view({'get': 'get_dossier', 'post': 'post_dossier'}, http_method_names=['get', 'post', 'options'], detail=True, basename='agent')),
    path('rh/agents/<uuid:agent_id>/documents', rh_views.AgentViewSet.as_view({'post': 'documents'}, http_method_names=['post', 'options'], detail=True, basename='agent')),
    path('rh/documents/<uuid:document_id>', rh_views.DocumentViewSet.as_view({'get': 'retrieve'}, http_method_names=['get', 'options'], detail=True, basename='document')),
    path('rh/pointages', rh_views.PointageViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='pointage')),
    path('rh/pointages/<uuid:pointage_id>/decision', rh_views.PointageViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='pointage')),
    path('rh/demandes', rh_views.DemandeViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='demande')),
]
