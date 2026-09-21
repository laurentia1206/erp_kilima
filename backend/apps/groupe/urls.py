from django.urls import path, include
from apps.groupe import views as intersociete_views

urlpatterns = [
    path("intersociete/commandes/<uuid:commande_id>/receptionner", intersociete_views.CommandeViewSet.as_view({'post': 'receptionner'}, http_method_names=['post', 'options'], detail=True, basename='commande')),
    path("intersociete/receptions", intersociete_views.ReceptionViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='reception')),
    path("intersociete/receptions/<uuid:reception_id>", intersociete_views.ReceptionViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}, http_method_names=['get', 'delete', 'options'], detail=True, basename='reception')),
    path("intersociete/receptions/<uuid:reception_id>/confirmer", intersociete_views.ReceptionViewSet.as_view({'post': 'confirmer'}, http_method_names=['post', 'options'], detail=True, basename='reception')),
    path("intersociete/tracer", intersociete_views.GroupeViewSet.as_view({'get': 'tracer'}, http_method_names=['get', 'options'], detail=False, basename='groupe')),
    path("intersociete/badges", intersociete_views.GroupeViewSet.as_view({'get': 'badges'}, http_method_names=['get', 'options'], detail=False, basename='groupe')),
    path("intersociete/liaisons", intersociete_views.GroupeViewSet.as_view({'get': 'liaisons'}, http_method_names=['get', 'options'], detail=False, basename='groupe')),
    path("intersociete/lier", intersociete_views.GroupeViewSet.as_view({'post': 'lier'}, http_method_names=['post', 'options'], detail=False, basename='groupe')),
    path("intersociete/positions", intersociete_views.GroupeViewSet.as_view({'get': 'positions'}, http_method_names=['get', 'options'], detail=False, basename='groupe')),
    path("intersociete/factures", intersociete_views.FactureViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='facture')),
    path("intersociete/factures/<uuid:facture_id>/regler", intersociete_views.FactureViewSet.as_view({'post': 'regler'}, http_method_names=['post', 'options'], detail=True, basename='facture')),
]
