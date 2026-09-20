"""Dépendances FastAPI : authentification et contrôle d'accès par société.

C'est le grand manque du prototype : ici l'isolation des sociétés est imposée
CÔTÉ SERVEUR (jamais via un paramètre d'URL de confiance).
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Utilisateur, UtilisateurSociete, Role
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Utilisateur:
    cred_exc = HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides",
                             headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise cred_exc
    user = db.get(Utilisateur, uuid.UUID(payload["sub"]))
    if not user or not user.actif:
        raise cred_exc
    return user


def roles_pour_societe(db: Session, user: Utilisateur, societe_id: uuid.UUID) -> set[str]:
    """Codes de rôles de l'utilisateur sur une société donnée.

    Un rôle personnalisé (créé dans Administration) hérite des DROITS d'accès
    de son rôle de base : LOGISTICIEN(herite_de=COMPTABLE) donne aussi COMPTABLE
    dans les contrôles — les chaînes d'héritage sont suivies."""
    rows = db.execute(
        select(Role.code, Role.herite_de)
        .join(UtilisateurSociete, UtilisateurSociete.role_id == Role.id)
        .where(UtilisateurSociete.utilisateur_id == user.id,
               UtilisateurSociete.societe_id == societe_id)
    ).all()
    codes = {c for c, _ in rows}
    a_resoudre = {h for _, h in rows if h}
    vus = set()
    while a_resoudre:
        h = a_resoudre.pop()
        if h in vus or h in codes:
            continue
        vus.add(h)
        codes.add(h)
        parent = db.execute(select(Role.herite_de).where(Role.code == h)).scalar_one_or_none()
        if parent:
            a_resoudre.add(parent)
    return codes


def assert_acces_societe(db: Session, user: Utilisateur, societe_id: uuid.UUID) -> set[str]:
    """Vérifie que l'utilisateur est affecté à la société ; retourne ses rôles."""
    roles = roles_pour_societe(db, user, societe_id)
    if not roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Accès refusé : utilisateur non affecté à cette société.")
    return roles


def assert_role(roles: set[str], requis: set[str]):
    """Vérifie qu'au moins un des rôles requis est présent."""
    if not (roles & requis):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Rôle requis parmi {sorted(requis)} ; rôles de l'utilisateur : {sorted(roles)}.")
