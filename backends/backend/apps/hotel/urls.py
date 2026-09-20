from django.urls import path, include
from apps.hotel import cuisine_views as cuisine_views
from apps.hotel import views as hotel_views

urlpatterns = [
    path("hotel/clients", hotel_views.ClientViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='client')),
    path("cuisine/config", cuisine_views.CuisineViewSet.as_view({'get': 'get_config', 'post': 'post_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='cuisine')),
    path("cuisine/fiches", cuisine_views.FicheTechniqueViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='fiche_technique')),
    path("cuisine/fiches/<uuid:fiche_id>", cuisine_views.FicheTechniqueViewSet.as_view({'delete': 'destroy'}, http_method_names=['delete', 'options'], detail=True, basename='fiche_technique')),
    path("cuisine/consommations", cuisine_views.ConsommationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='consommation')),
    path("cuisine/rapport", cuisine_views.CuisineViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='cuisine')),
    path("hotel/chambres", hotel_views.ChambreViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='chambre')),
    path("hotel/chambres/<uuid:chambre_id>", hotel_views.ChambreViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='chambre')),
    path("hotel/sejours", hotel_views.SejourViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>", hotel_views.SejourViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/checkin", hotel_views.SejourViewSet.as_view({'post': 'checkin'}, http_method_names=['post', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/annuler", hotel_views.SejourViewSet.as_view({'post': 'annuler'}, http_method_names=['post', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/folio", hotel_views.SejourViewSet.as_view({'get': 'folio'}, http_method_names=['get', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/lignes", hotel_views.SejourViewSet.as_view({'post': 'lignes'}, http_method_names=['post', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/lignes/<uuid:ligne_id>", hotel_views.SejourViewSet.as_view({'delete': 'supprimer_ligne'}, http_method_names=['delete', 'options'], detail=True, basename='sejour')),
    path("hotel/sejours/<uuid:sejour_id>/checkout", hotel_views.SejourViewSet.as_view({'post': 'checkout'}, http_method_names=['post', 'options'], detail=True, basename='sejour')),
    path("hotel/planning", hotel_views.HotelViewSet.as_view({'get': 'planning'}, http_method_names=['get', 'options'], detail=False, basename='hotel')),
    path("hotel/rapport", hotel_views.HotelViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='hotel')),
]
