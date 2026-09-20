"""Moteur de validation par paliers (cf. docs/04 §4).

Règles du groupe (paramétrables en base via palier_validation/palier_approbateur) :
  Sortie de fonds (ordre de dépense), évaluée sur l'équivalent USD :
    - ≤ 1 000        → DFI seul
    - 1 001 – 10 000 → DFI + DG + Admin + Président (conjoints)
    - > 10 000       → Président seul
  Validation de la demande :
    - standard       → DG + Admin (conjoints)
    - HORIZON        → DG + DT (conjoints)

Ces fonctions sont pures : on leur passe les paliers chargés depuis la base.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


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
    """Retourne le palier applicable au montant (équivalent USD)."""
    m = Decimal(str(montant_usd))
    for p in sorted(paliers, key=lambda p: p.montant_min_usd):
        if p.couvre(m):
            return p
    raise ValueError(f"Aucun palier ne couvre le montant {m} USD.")


def roles_requis(palier: Palier) -> list[str]:
    """Codes de rôles dont l'approbation est requise pour ce palier."""
    return [a.role_code for a in palier.approbateurs]


def est_pleinement_approuve(palier: Palier, approbations: dict[str, str]) -> bool:
    """Vrai si les approbations satisfont le palier.

    `approbations` : {role_code: decision} où decision ∈ {'valide','rejete','en_attente'}.
    - Si un approbateur requis a 'rejete' → False.
    - mode 'seul' : une seule approbation 'valide' parmi les requis suffit.
    - mode 'conjoint' : tous les approbateurs 'conjoint' doivent être 'valide'.
    """
    requis = palier.approbateurs
    if not requis:
        return True
    # Un rejet d'un rôle requis bloque
    for a in requis:
        if approbations.get(a.role_code) == "rejete":
            return False

    conjoints = [a for a in requis if a.mode == "conjoint"]
    seuls = [a for a in requis if a.mode == "seul"]

    if seuls:
        # Au moins un "seul" validé suffit
        if any(approbations.get(a.role_code) == "valide" for a in seuls):
            return True
        if not conjoints:
            return False
    # Tous les conjoints doivent être validés
    if conjoints:
        return all(approbations.get(a.role_code) == "valide" for a in conjoints)
    return False
