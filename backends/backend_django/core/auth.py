"""Authentification JWT + contrôle d'accès par société — portage de deps.py.

Jetons 100 % compatibles avec le backend FastAPI (même SECRET_KEY, même payload
{"sub": <uuid utilisateur>, "exp": ...}) : une session ouverte sur l'un
fonctionne sur l'autre pendant la transition.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from django.conf import settings
from jose import JWTError, jwt
from rest_framework import authentication, exceptions

from .models import Role, Utilisateur, UtilisateurSociete



def creer_token(user_id: str) -> str:
    payload = {"sub": str(user_id),
               "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


class JWTAuthentication(authentication.BaseAuthentication):
    """Bearer <jwt> → Utilisateur (table existante, hors django.contrib.auth)."""

    def authenticate_header(self, request):
        # DRF répond sinon 403 pour un jeton expiré : l'interface ne peut pas
        # distinguer une session expirée d'un véritable refus de permission.
        return 'Bearer realm="kilima"'

    def authenticate(self, request):
        entete = request.headers.get("Authorization", "")
        if not entete.startswith("Bearer "):
            return None
        try:
            payload = jwt.decode(entete[7:], settings.SECRET_KEY,
                                 algorithms=[settings.JWT_ALGORITHM])
            user = Utilisateur.objects.filter(id=uuid.UUID(payload["sub"])).first()
        except (JWTError, KeyError, ValueError, TypeError, AttributeError):
            raise exceptions.AuthenticationFailed("Identifiants invalides")
        if not user or not user.actif:
            raise exceptions.AuthenticationFailed("Identifiants invalides")
        return (user, None)


def roles_pour_societe(user: Utilisateur, societe_id) -> set[str]:
    """Codes de rôles sur une société, héritage suivi (portage de deps.py)."""
    rows = list(UtilisateurSociete.objects.filter(
        utilisateur_id=user.id, societe_id=societe_id)
        .values_list("role__code", "role__herite_de"))
    codes = {c for c, _ in rows}
    a_resoudre = {h for _, h in rows if h}
    vus: set[str] = set()
    while a_resoudre:
        h = a_resoudre.pop()
        if h in vus or h in codes:
            continue
        vus.add(h)
        codes.add(h)
        parent = Role.objects.filter(code=h).values_list("herite_de", flat=True).first()
        if parent:
            a_resoudre.add(parent)
    return codes


def assert_acces_societe(user: Utilisateur, societe_id) -> set[str]:
    roles = roles_pour_societe(user, societe_id)
    if not roles:
        raise exceptions.PermissionDenied(
            "Accès refusé : utilisateur non affecté à cette société.")
    return roles


def assert_role(roles: set[str], requis: set[str]) -> None:
    if not (roles & requis):
        raise exceptions.PermissionDenied(
            f"Rôle requis parmi {sorted(requis)} ; rôles de l'utilisateur : {sorted(roles)}.")


def gestion_exceptions(exc, context):
    """Erreurs au même format que FastAPI : {"detail": "message"}."""
    from rest_framework.response import Response
    from rest_framework.views import exception_handler as drf_exception_handler
    from .erreurs import Parametre422
    if isinstance(exc, Parametre422):
        return Response(exc.corps, status=422)
    reponse = drf_exception_handler(exc, context)
    if reponse is not None and isinstance(reponse.data, dict) and "detail" not in reponse.data:
        reponse.data = {"detail": str(exc)}
    return reponse
