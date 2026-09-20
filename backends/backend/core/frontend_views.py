"""Frontend & système — Django sert désormais l'application (bascule phase 10).

Même contrat que le main.py FastAPI : `/` → static/index.html, `/static/*` →
assets, `/api/health`, le tout SANS cache (sinon l'utilisateur voit une
ancienne version de app.js après une mise à jour).
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings as dj_settings
from django.http import FileResponse, JsonResponse
from rest_framework.views import APIView

STATIC = dj_settings.BASE_DIR.parent / "frontend" / "legacy"

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate",
             "Pragma": "no-cache", "Expires": "0"}


def _fichier(chemin: Path, content_type: str | None = None):
    reponse = FileResponse(open(chemin, "rb"),
                           content_type=content_type
                           or mimetypes.guess_type(str(chemin))[0]
                           or "application/octet-stream")
    for k, v in _NO_CACHE.items():
        reponse[k] = v
    return reponse


def index(request):
    return _fichier(STATIC / "index.html", "text/html")


def statique(request, chemin: str):
    cible = (STATIC / chemin).resolve()
    if not cible.is_relative_to(STATIC.resolve()) or not cible.is_file():
        return JsonResponse({"detail": "Not Found"}, status=404)
    return _fichier(cible)


class HealthView(APIView):
    http_method_names = ['get', 'options']
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return JsonResponse({"status": "ok", "app": dj_settings.APP_NAME,
                             "env": dj_settings.ENVIRONMENT})

# Compatibilité des imports ; les routes utilisent HealthView.as_view().
health = HealthView.as_view()
