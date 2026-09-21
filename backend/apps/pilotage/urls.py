from django.urls import path, include
from apps.pilotage import views as pilotage

urlpatterns = [
    path('pilotage/taches', pilotage.PilotageViewSet.as_view({'get': 'taches'}, http_method_names=['get', 'options'], detail=False, basename='pilotage')),
    path('pilotage/delais', pilotage.PilotageViewSet.as_view({'get': 'get_delais', 'put': 'put_delais'}, http_method_names=['get', 'put', 'options'], detail=False, basename='pilotage')),
]
