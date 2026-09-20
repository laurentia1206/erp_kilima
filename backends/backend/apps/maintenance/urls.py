from django.urls import path, include
from apps.maintenance import documents_views as documents_views
from apps.maintenance import views as maintenance_views

urlpatterns = [
    path("maintenance/parc", maintenance_views.ParcViewSet.as_view({'get': 'parc'}, http_method_names=['get', 'options'], detail=False, basename='parc')),
    path("maintenance/plans", maintenance_views.PlanEntretienViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='plan_entretien')),
    path("maintenance/plans/<uuid:plan_id>", maintenance_views.PlanEntretienViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='plan_entretien')),
    path("maintenance/plans/<uuid:plan_id>/planifier", maintenance_views.PlanEntretienViewSet.as_view({'post': 'planifier'}, http_method_names=['post', 'options'], detail=True, basename='plan_entretien')),
    path("flotte/documents", documents_views.DocumentFlotteViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='document_flotte')),
    path("flotte/documents/<uuid:document_id>", documents_views.DocumentFlotteViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='document_flotte')),
]
