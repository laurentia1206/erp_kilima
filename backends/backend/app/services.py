"""Services applicatifs : numérotation, paramètres, taux, chargement des paliers.

Font le pont entre la base de données et la logique métier pure (app.domain).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .domain.workflow import Approbateur, Palier, resolve_palier

# Préfixes de numérotation par type de pièce
PREFIXES = {
    "requisition": "REQ", "ordre_depense": "ODP", "bon_reception": "BRF",
    "avance": "AVJ", "justification": "JUST", "cession": "CES", "transfert": "TRF",
    "bon_caisse": "BC", "facture_achat": "FA", "facture_vente": "FV",
    "commande": "CMD", "reception": "REC", "avoir_vente": "AVV",
    "devis": "DEV", "livraison": "BL",
    "course": "FC", "contrat_transport": "CTR", "intervention": "INT",
    "reception_inter": "RI",
}


def next_numero(db: Session, type_piece: str, annee: int, societe_code: str | None,
                societe_id: uuid.UUID | None) -> str:
    """Génère un numéro séquentiel (ex. REQ-PLA-2026-000125). Verrou par UPDATE."""
    compteur = db.execute(
        select(models.SequenceCompteur).where(
            models.SequenceCompteur.societe_id == societe_id,
            models.SequenceCompteur.type_piece == type_piece,
            models.SequenceCompteur.annee == annee,
        ).with_for_update()
    ).scalar_one_or_none()
    if compteur is None:
        compteur = models.SequenceCompteur(
            societe_id=societe_id, type_piece=type_piece, annee=annee, dernier_numero=0)
        db.add(compteur)
        db.flush()
    compteur.dernier_numero += 1
    prefix = PREFIXES.get(type_piece, type_piece[:3].upper())
    code = societe_code or "GRP"
    return f"{prefix}-{code}-{annee}-{compteur.dernier_numero:06d}"


def get_parametre(db: Session, cle: str, societe_id: uuid.UUID | None = None,
                  defaut: str | None = None) -> str | None:
    """Lit un paramètre : valeur spécifique société sinon valeur groupe."""
    if societe_id is not None:
        v = db.execute(
            select(models.Parametre.valeur).where(
                models.Parametre.societe_id == societe_id, models.Parametre.cle == cle)
        ).scalar_one_or_none()
        if v is not None:
            return v
    v = db.execute(
        select(models.Parametre.valeur).where(
            models.Parametre.societe_id.is_(None), models.Parametre.cle == cle)
    ).scalar_one_or_none()
    return v if v is not None else defaut


def get_taux_jour(db: Session, jour: date, devise: str = "CDF") -> Decimal | None:
    """Taux du jour fixé par le DFI (1 USD = taux CDF)."""
    if devise == "USD":
        return Decimal("1")
    v = db.execute(
        select(models.TauxChange.taux_usd).where(
            models.TauxChange.date_taux == jour, models.TauxChange.devise == devise)
    ).scalar_one_or_none()
    return Decimal(str(v)) if v is not None else None


def load_paliers(db: Session, type_document: str, etape: str,
                 societe_id: uuid.UUID | None) -> list[Palier]:
    """Charge la grille de paliers en objets domaine.

    Priorité : règles spécifiques à la société si elles existent, sinon règles
    groupe (societe_id IS NULL).
    """
    def _fetch(sid):
        rows = db.execute(
            select(models.PalierValidation).where(
                models.PalierValidation.type_document == type_document,
                models.PalierValidation.etape == etape,
                (models.PalierValidation.societe_id == sid) if sid is not None
                else models.PalierValidation.societe_id.is_(None),
            )
        ).scalars().all()
        return rows

    rows = _fetch(societe_id) if societe_id is not None else []
    if not rows:
        rows = _fetch(None)

    paliers: list[Palier] = []
    for pv in rows:
        appros = tuple(
            Approbateur(role_code=a.role.code, mode=a.mode)
            for a in sorted(pv.approbateurs, key=lambda a: a.ordre)
        )
        paliers.append(Palier(
            montant_min_usd=Decimal(str(pv.montant_min_usd)),
            montant_max_usd=Decimal(str(pv.montant_max_usd)) if pv.montant_max_usd is not None else None,
            approbateurs=appros,
            libelle=pv.libelle or "",
        ))
    return paliers


def role_id_by_code(db: Session, code: str) -> uuid.UUID:
    return db.execute(select(models.Role.id).where(models.Role.code == code)).scalar_one()


def decisions_par_role(db: Session, doc_type: str, doc_id: uuid.UUID, etape: str) -> dict[str, str]:
    """{role_code: decision} des validations enregistrées pour un document/étape."""
    rows = db.execute(
        select(models.Role.code, models.Validation.decision)
        .join(models.Role, models.Role.id == models.Validation.role_attendu_id)
        .where(models.Validation.document_type == doc_type,
               models.Validation.document_id == doc_id,
               models.Validation.etape == etape)
    ).all()
    return {code: decision for code, decision in rows}


def palier_pour_montant(db: Session, type_document: str, etape: str,
                        societe_id, montant_usd):
    """Palier applicable à un montant (USD), pour un niveau donné. None si aucun.

    Vaut pour les DEUX niveaux (demande ET sortie de fonds) : chaque niveau peut
    avoir un ou plusieurs paliers selon les montants.
    """
    paliers = load_paliers(db, type_document, etape, societe_id)
    if not paliers:
        return None
    try:
        return resolve_palier(montant_usd, paliers)
    except ValueError:
        # Aucun palier ne couvre exactement ce montant : on retient le plus proche par le bas.
        candidats = [p for p in paliers if float(p.montant_min_usd) <= float(montant_usd)]
        return max(candidats, key=lambda p: p.montant_min_usd) if candidats else paliers[0]


def enregistrer_audit(db: Session, utilisateur_id, action: str, table_cible: str,
                      enregistrement_id, ancienne=None, nouvelle=None, ip=None):
    """Trace une action dans le journal immuable."""
    db.add(models.AuditLog(
        utilisateur_id=utilisateur_id, action=action, table_cible=table_cible,
        enregistrement_id=str(enregistrement_id) if enregistrement_id else None,
        ancienne_valeur=ancienne, nouvelle_valeur=nouvelle, adresse_ip=ip,
    ))
