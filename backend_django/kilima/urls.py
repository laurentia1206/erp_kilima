"""Routes — mêmes chemins que le backend FastAPI (le frontend fait foi).

Depuis la bascule (phase 10), Django sert aussi le frontend : page d'accueil,
assets statiques et /api/health.
"""
from django.urls import include, path

from core import frontend_views

urlpatterns = [
    path("", frontend_views.index),
    path("static/<path:chemin>", frontend_views.statique),
    path("api/health", frontend_views.health),
    path("api/", include("core.urls")),
]
