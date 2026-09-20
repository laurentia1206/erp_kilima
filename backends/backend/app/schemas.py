"""Schémas Pydantic (entrées/sorties API)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    nom: str
    prenom: str | None = None

    class Config:
        from_attributes = True


# ── Taux de change ───────────────────────────────────────────────────
class TauxIn(BaseModel):
    date_taux: date
    devise: str = "CDF"
    taux_usd: Decimal = Field(gt=0, description="1 USD = taux_usd CDF")


# ── Réquisition (G01) ────────────────────────────────────────────────
class RequisitionLigneIn(BaseModel):
    compte_impute: str | None = None
    code_article: str | None = None
    description: str
    unite: str | None = None
    quantite: Decimal = Decimal("1")
    prix_unitaire: Decimal = Decimal("0")


class RequisitionIn(BaseModel):
    societe_id: uuid.UUID
    site_id: uuid.UUID | None = None
    objet: str
    justification: str | None = None
    mode_decaissement: str = Field("avance", pattern="^(avance|paiement_direct)$")
    nature: str = Field("charge", pattern="^(charge|marchandise)$")
    priorite: str = "normal"
    devise: str = "USD"
    lignes: list[RequisitionLigneIn]


class RequisitionOut(BaseModel):
    id: uuid.UUID
    numero: str
    societe_id: uuid.UUID
    objet: str
    priorite: str
    devise: str
    montant_total: Decimal
    montant_total_usd: Decimal
    statut: str

    class Config:
        from_attributes = True


# ── Décision de validation ───────────────────────────────────────────
class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(valide|rejete)$")
    commentaire: str | None = None
    canal: str = "in_app"


# ── Ordre de dépense (G02) ───────────────────────────────────────────
class OrdreDepenseIn(BaseModel):
    requisition_id: uuid.UUID
    beneficiaire_tiers_id: uuid.UUID
    mode_paiement: str = "caisse"
    motif: str | None = None


class ExecutionIn(BaseModel):
    caisse_id: uuid.UUID | None = None
    compte_bancaire_id: uuid.UUID | None = None
    type_avance: str | None = None
    reference_paiement: str | None = None
    beneficiaire_tiers_id: uuid.UUID | None = None   # override possible au moment du paiement
    montant: float | None = None                      # décaissement partiel (devise de l'ordre) ; défaut = reste
    billetage: dict | None = None


class OrdreDepenseOut(BaseModel):
    id: uuid.UUID
    numero: str
    montant_autorise_usd: Decimal
    palier_applique: str | None
    statut: str

    class Config:
        from_attributes = True


# ── Justification d'avance (G04) ─────────────────────────────────────
class JustificationLigneIn(BaseModel):
    date_achat: date | None = None
    nature: str
    compte_impute: str | None = None
    fournisseur: str | None = None
    num_piece: str | None = None
    devise: str = "USD"
    montant: Decimal
    a_piece_jointe: bool = False


class MarchandiseIn(BaseModel):
    """Ligne de marchandise achetée avec l'avance (circuit 1) → entrée en stock."""
    article_id: uuid.UUID | None = None
    code: str | None = None
    designation: str | None = None
    unite: str | None = None
    qte: Decimal
    prix_unitaire: Decimal
    taux_tva: Decimal | None = None


class FraisJustifIn(BaseModel):
    libelle: str
    compte: str = "611"
    montant_ht: Decimal
    taux_tva: Decimal | None = None


class JustificationIn(BaseModel):
    avance_id: uuid.UUID
    solde_retourne: Decimal = Decimal("0")
    devise_solde: str = "USD"
    caisse_id: uuid.UUID | None = None               # caisse où le solde est rendu (défaut : caisse du décaissement)
    lignes: list[JustificationLigneIn] = []          # dépenses de charge
    marchandises: list[MarchandiseIn] = []           # achats de marchandises → stock
    frais: list[FraisJustifIn] = []                  # frais accessoires (transport…)
    repartition: str = "quantite"


class JustificationOut(BaseModel):
    id: uuid.UUID
    numero: str
    montant_justifie_usd: Decimal
    solde_retourne_usd: Decimal
    ecart_usd: Decimal
    complement_demande: bool
    statut: str

    class Config:
        from_attributes = True
