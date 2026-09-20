from django.urls import path, include
from apps.pilotage import views as pilotage

urlpatterns = [
    path('pilotage/taches', pilotage.taches),
    path('pilotage/delais', pilotage.parametres),
]
