"""Réponses d'erreur compatibles FastAPI.

Chez FastAPI, lever une HTTPException au milieu d'un traitement ANNULE la
transaction (rien n'est committé). Côté Django, un `return Response(...)` au
milieu d'un bloc `transaction.atomic()` committerait les écritures déjà faites
(numéros de séquence consommés, lignes partielles…). `refus()` marque donc la
transaction courante pour rollback avant de retourner la réponse d'erreur.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.response import Response


def refus(data, status):
    """Réponse d'erreur qui annule la transaction en cours (le cas échéant)."""
    if transaction.get_connection().in_atomic_block:
        transaction.set_rollback(True)
    return Response(data, status=status)


class Parametre422(Exception):
    """Erreur de validation de paramètre au format 422 FastAPI/Pydantic."""

    def __init__(self, corps):
        self.corps = corps
        super().__init__(str(corps))
