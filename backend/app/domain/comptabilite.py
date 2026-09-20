"""Règles comptables OHADA pures (sans DB).

Contrôle de la partie double : toute écriture doit être équilibrée (Σ débits =
Σ crédits). Montants en USD pivot.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

CENT = Decimal("0.01")


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


@dataclass(frozen=True)
class LigneCompta:
    sens: str          # 'D' | 'C'
    compte: str
    montant_usd: Decimal


def totaux(lignes: list[LigneCompta]) -> tuple[Decimal, Decimal]:
    debit = sum((_d(l.montant_usd) for l in lignes if l.sens == "D"), Decimal("0"))
    credit = sum((_d(l.montant_usd) for l in lignes if l.sens == "C"), Decimal("0"))
    return debit.quantize(CENT), credit.quantize(CENT)


def est_equilibree(lignes: list[LigneCompta]) -> bool:
    """Vrai si Σ débits = Σ crédits, avec au moins une ligne D et une ligne C."""
    if not lignes:
        return False
    if not any(l.sens == "D" for l in lignes) or not any(l.sens == "C" for l in lignes):
        return False
    debit, credit = totaux(lignes)
    return debit == credit


def assert_equilibree(lignes: list[LigneCompta]) -> None:
    if not est_equilibree(lignes):
        d, c = totaux(lignes)
        raise ValueError(f"Écriture déséquilibrée : débit={d} crédit={c}.")
