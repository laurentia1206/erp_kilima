"""Avances à justifier — règles de gestion (cf. docs/04 §3).

Couvre : calcul d'échéance de justification, contrôle d'équilibre de la
justification (trop-perçu / complément), et règle de blocage automatique.
Fonctions pures, montants en USD pivot (Decimal).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

CENT = Decimal("0.01")


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def compute_echeance(date_octroi: datetime, delai_heures: int) -> datetime:
    """Échéance de justification = date d'octroi + délai (heures)."""
    return date_octroi + timedelta(hours=int(delai_heures))


@dataclass(frozen=True)
class EquilibreJustification:
    montant_avance_usd: Decimal
    total_justifie_usd: Decimal
    solde_retourne_usd: Decimal
    ecart_usd: Decimal           # avance - (justifié + retourné) ; 0 = conforme
    trop_percu: bool             # avance > dépenses → solde à rendre
    complement_du: bool          # dépenses > avance → réquisition de complément
    conforme: bool               # ecart == 0


def controle_equilibre(montant_avance_usd, lignes_justifiees_usd, solde_retourne_usd=0) -> EquilibreJustification:
    """Vérifie : avance = total justifié + solde retourné.

    - total justifié > avance  → complément dû (complement_du)
    - solde retourné > 0        → trop-perçu rendu
    - ecart != 0 (et non couvert par un complément) → à expliquer
    """
    avance = _d(montant_avance_usd).quantize(CENT)
    total = sum((_d(x) for x in lignes_justifiees_usd), Decimal("0")).quantize(CENT)
    retourne = _d(solde_retourne_usd).quantize(CENT)

    ecart = (avance - (total + retourne)).quantize(CENT)
    complement_du = total > avance
    trop_percu = retourne > 0
    conforme = ecart == Decimal("0.00")
    return EquilibreJustification(
        montant_avance_usd=avance,
        total_justifie_usd=total,
        solde_retourne_usd=retourne,
        ecart_usd=ecart,
        trop_percu=trop_percu,
        complement_du=complement_du,
        conforme=conforme,
    )


@dataclass(frozen=True)
class AvanceEnCours:
    statut: str                  # 'a_justifier','en_retard','bloquante','justifiee',...
    echeance_justif: datetime | None


def est_en_retard(avance: AvanceEnCours, maintenant: datetime) -> bool:
    """Une avance non justifiée dont l'échéance est dépassée est en retard.

    Robuste au mélange datetime naïf/aware (SQLite renvoie des datetimes naïfs) :
    on aligne les deux avant comparaison en supposant l'UTC pour le naïf.
    """
    if avance.statut not in ("a_justifier",):
        return False
    ech = avance.echeance_justif
    if ech is None:
        return False
    if ech.tzinfo is None and maintenant.tzinfo is not None:
        ech = ech.replace(tzinfo=timezone.utc)
    elif ech.tzinfo is not None and maintenant.tzinfo is None:
        maintenant = maintenant.replace(tzinfo=timezone.utc)
    return maintenant > ech


def beneficiaire_bloque(a_blocage_actif: bool, avances: list[AvanceEnCours], maintenant: datetime) -> bool:
    """Règle de blocage automatique : un bénéficiaire est bloqué s'il a un
    blocage actif, OU une avance au statut bloquant/en retard, OU une avance
    'a_justifier' dont l'échéance est dépassée.
    """
    if a_blocage_actif:
        return True
    for av in avances:
        if av.statut in ("en_retard", "bloquante"):
            return True
        if est_en_retard(av, maintenant):
            return True
    return False
