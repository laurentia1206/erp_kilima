"""Multi-devise USD/CDF — conversions au taux du jour (pivot = USD).

Convention (cf. docs/04) : tout montant est stocké dans sa devise de saisie ET
en équivalent USD. Le taux journalier `taux_usd` exprime : 1 USD = `taux_usd` CDF,
fixé chaque jour par le DFI (table `taux_change`).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

USD = "USD"
CDF = "CDF"
CENT = Decimal("0.01")


def _d(value) -> Decimal:
    """Convertit en Decimal de façon sûre (évite les flottants binaires)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(montant) -> Decimal:
    """Arrondit à 2 décimales (arrondi commercial)."""
    return _d(montant).quantize(CENT, rounding=ROUND_HALF_UP)


def to_usd(devise: str, montant, taux_usd=None) -> Decimal:
    """Équivalent USD d'un montant saisi.

    - USD : retourné tel quel.
    - CDF : montant / taux_usd  (1 USD = taux_usd CDF).
    """
    devise = (devise or USD).upper()
    montant = _d(montant)
    if devise == USD:
        return quantize(montant)
    if devise == CDF:
        if taux_usd is None or _d(taux_usd) <= 0:
            raise ValueError("Taux du jour USD/CDF requis et > 0 pour convertir des CDF.")
        return quantize(montant / _d(taux_usd))
    raise ValueError(f"Devise non supportée : {devise!r}")


def from_usd(devise: str, montant_usd, taux_usd=None) -> Decimal:
    """Montant exprimé dans `devise` à partir d'un équivalent USD."""
    devise = (devise or USD).upper()
    montant_usd = _d(montant_usd)
    if devise == USD:
        return quantize(montant_usd)
    if devise == CDF:
        if taux_usd is None or _d(taux_usd) <= 0:
            raise ValueError("Taux du jour USD/CDF requis et > 0.")
        return quantize(montant_usd * _d(taux_usd))
    raise ValueError(f"Devise non supportée : {devise!r}")
