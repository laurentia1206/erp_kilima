from django.urls import path, include
from apps.engins import views as engins_views

urlpatterns = [
    path("engins/config", engins_views.ExploitationEnginViewSet.as_view({'get': 'get_config', 'post': 'post_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='exploitation_engin')),
    path("engins/engins", engins_views.EnginViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='engin')),
    path("engins/engins/<uuid:engin_id>", engins_views.EnginViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='engin')),
    path("engins/prestations", engins_views.PrestationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='prestation')),
    path("engins/prestations/<uuid:prestation_id>", engins_views.PrestationViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='prestation')),
    path("engins/rpe", engins_views.ExploitationEnginViewSet.as_view({'get': 'rpe'}, http_method_names=['get', 'options'], detail=False, basename='exploitation_engin')),
    path("engins/facturer", engins_views.ExploitationEnginViewSet.as_view({'post': 'facturer'}, http_method_names=['post', 'options'], detail=False, basename='exploitation_engin')),
    path("engins/reconciliation", engins_views.ReconciliationEnginViewSet.as_view({'get': 'get_reconciliation', 'post': 'post_reconciliation'}, http_method_names=['get', 'post', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/reconciliation/valider", engins_views.ReconciliationEnginViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/reconciliation/rouvrir", engins_views.ReconciliationEnginViewSet.as_view({'post': 'rouvrir'}, http_method_names=['post', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/harmonisations", engins_views.ReconciliationEnginViewSet.as_view({'get': 'get_harmonisations', 'post': 'post_harmonisations'}, http_method_names=['get', 'post', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/harmonisations/<uuid:harmonisation_id>/decider", engins_views.ReconciliationEnginViewSet.as_view({'post': 'decider'}, http_method_names=['post', 'options'], detail=True, basename='reconciliation_engin')),
    path("engins/rapport-technique", engins_views.ReconciliationEnginViewSet.as_view({'get': 'rapport_technique'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/disponibilite", engins_views.ReconciliationEnginViewSet.as_view({'get': 'disponibilite'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')),
    path("engins/evolution", engins_views.ReconciliationEnginViewSet.as_view({'get': 'evolution'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')),
]
