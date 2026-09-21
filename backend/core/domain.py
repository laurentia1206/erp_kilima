"""Règles métier pures — portage exact de backend/app/domain/ (money, workflow, avances).

Fonctions sans accès base : conversions USD/CDF, paliers de validation,
équilibre de justification, blocage automatique des bénéficiaires.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ── money ────────────────────────────────────────────────────────────
USD = "USD"
CDF = "CDF"
CENT = Decimal("0.01")


def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize(montant) -> Decimal:
    return _d(montant).quantize(CENT, rounding=ROUND_HALF_UP)


def to_usd(devise: str, montant, taux_usd=None) -> Decimal:
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
    devise = (devise or USD).upper()
    montant_usd = _d(montant_usd)
    if devise == USD:
        return quantize(montant_usd)
    if devise == CDF:
        if taux_usd is None or _d(taux_usd) <= 0:
            raise ValueError("Taux du jour USD/CDF requis et > 0.")
        return quantize(montant_usd * _d(taux_usd))
    raise ValueError(f"Devise non supportée : {devise!r}")


# ── workflow (paliers de validation) ─────────────────────────────────
@dataclass(frozen=True)
class Approbateur:
    role_code: str
    mode: str = "conjoint"   # 'conjoint' | 'seul'


@dataclass(frozen=True)
class Palier:
    montant_min_usd: Decimal
    montant_max_usd: Decimal | None       # None = pas de plafond
    approbateurs: tuple[Approbateur, ...] = field(default_factory=tuple)
    libelle: str = ""

    def couvre(self, montant_usd: Decimal) -> bool:
        m = Decimal(str(montant_usd))
        if m < self.montant_min_usd:
            return False
        if self.montant_max_usd is not None and m > self.montant_max_usd:
            return False
        return True


def resolve_palier(montant_usd, paliers: list[Palier]) -> Palier:
    m = Decimal(str(montant_usd))
    for p in sorted(paliers, key=lambda p: p.montant_min_usd):
        if p.couvre(m):
            return p
    raise ValueError(f"Aucun palier ne couvre le montant {m} USD.")


def est_pleinement_approuve(palier: Palier, approbations: dict[str, str]) -> bool:
    """Vrai si les approbations satisfont le palier (rejet requis → False ;
    'seul' : une validation suffit ; 'conjoint' : toutes requises)."""
    requis = palier.approbateurs
    if not requis:
        return True
    for a in requis:
        if approbations.get(a.role_code) == "rejete":
            return False
    conjoints = [a for a in requis if a.mode == "conjoint"]
    seuls = [a for a in requis if a.mode == "seul"]
    if seuls:
        if any(approbations.get(a.role_code) == "valide" for a in seuls):
            return True
        if not conjoints:
            return False
    if conjoints:
        return all(approbations.get(a.role_code) == "valide" for a in conjoints)
    return False


# ── avances à justifier ──────────────────────────────────────────────
def compute_echeance(date_octroi: datetime, delai_heures: int) -> datetime:
    return date_octroi + timedelta(hours=int(delai_heures))


@dataclass(frozen=True)
class EquilibreJustification:
    montant_avance_usd: Decimal
    total_justifie_usd: Decimal
    solde_retourne_usd: Decimal
    ecart_usd: Decimal           # avance - (justifié + retourné) ; 0 = conforme
    trop_percu: bool
    complement_du: bool
    conforme: bool


def controle_equilibre(montant_avance_usd, lignes_justifiees_usd,
                       solde_retourne_usd=0) -> EquilibreJustification:
    avance = _d(montant_avance_usd).quantize(CENT)
    total = sum((_d(x) for x in lignes_justifiees_usd), Decimal("0")).quantize(CENT)
    retourne = _d(solde_retourne_usd).quantize(CENT)
    ecart = (avance - (total + retourne)).quantize(CENT)
    return EquilibreJustification(
        montant_avance_usd=avance, total_justifie_usd=total, solde_retourne_usd=retourne,
        ecart_usd=ecart, trop_percu=retourne > 0, complement_du=total > avance,
        conforme=ecart == Decimal("0.00"))


@dataclass(frozen=True)
class AvanceEnCours:
    statut: str
    echeance_justif: datetime | None


def est_en_retard(avance: AvanceEnCours, maintenant: datetime) -> bool:
    """Robuste au mélange naïf/aware (SQLite renvoie des datetimes naïfs UTC)."""
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


def beneficiaire_bloque(a_blocage_actif: bool, avances: list[AvanceEnCours],
                        maintenant: datetime) -> bool:
    if a_blocage_actif:
        return True
    for av in avances:
        if av.statut in ("en_retard", "bloquante"):
            return True
        if est_en_retard(av, maintenant):
            return True
    return False
