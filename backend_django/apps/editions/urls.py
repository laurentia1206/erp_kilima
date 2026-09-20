from django.urls import path, include
from apps.editions import views as editions

urlpatterns = [
    path('editions/societe', editions.societe),
    path('editions/telecharger', editions.telecharger),
]
