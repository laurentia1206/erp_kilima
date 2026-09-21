from django.urls import path, include
from apps.stocks import views as depots_views
from apps.stocks import inventaires_views as inventaires_views

urlpatterns = [
    path("stock/depots", depots_views.DepotViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='depot')),
    path("stock/depots/<uuid:depot_id>", depots_views.DepotViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='depot')),
    path("stock/depots-etat", depots_views.EtatDepotViewSet.as_view({'get': 'etat_depot'}, http_method_names=['get', 'options'], detail=False, basename='etat_depot')),
    path("stock/transferts", depots_views.TransfertDepotViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='transfert_depot')),
    path("stock/inventaires", inventaires_views.InventaireViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='inventaire')),
    path("stock/inventaires/<uuid:inventaire_id>/decision", inventaires_views.InventaireViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='inventaire')),
]
