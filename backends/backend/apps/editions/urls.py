from django.urls import path, include
from apps.editions import views as editions

urlpatterns = [
    path('editions/societe', editions.EditionViewSet.as_view({'get': 'societe'}, http_method_names=['get', 'options'], detail=False, basename='edition')),
    path('editions/telecharger', editions.EditionViewSet.as_view({'post': 'telecharger'}, http_method_names=['post', 'options'], detail=False, basename='edition')),
]
