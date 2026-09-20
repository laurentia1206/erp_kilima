"""Comptabilité analytique — axes, sections et ventilation des charges/produits.

Modèle « à la ERP » : des AXES analytiques (Centre de coût, Activité…), chacun
avec ses SECTIONS (Administration, Transport, Ciment…). Une ligne d'écriture de
charge (classe 6) ou de produit (classe 7) est VENTILÉE sur une ou plusieurs
sections d'un axe. Le rapport analytique croise sections × charges/produits pour
sortir un résultat par section — indépendamment de la comptabilité générale.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user

router = APIRouter(prefix="/api/analytique", tags=["analytique"])
ROLES = {"COMPTABLE", "DFI"}


# ── Axes & sections ──────────────────────────────────────────────────
class AxeIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=1)


class SectionIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=1)


class MajIn(BaseModel):
    libelle: str | None = None
    actif: bool | None = None


@router.get("/axes")
def lister_axes(societe_id: uuid.UUID, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    axes = db.execute(select(models.AxeAnalytique).where(
        models.AxeAnalytique.societe_id == societe_id)
        .order_by(models.AxeAnalytique.code)).scalars().all()
    out = []
    for a in axes:
        sections = db.execute(select(models.SectionAnalytique).where(
            models.SectionAnalytique.axe_id == a.id)
            .order_by(models.SectionAnalytique.code)).scalars().all()
        out.append({"id": str(a.id), "code": a.code, "libelle": a.libelle, "actif": bool(a.actif),
                    "sections": [{"id": str(s.id), "code": s.code, "libelle": s.libelle,
                                  "actif": bool(s.actif)} for s in sections]})
    return out


@router.post("/axes", status_code=status.HTTP_201_CREATED)
def creer_axe(societe_id: uuid.UUID, payload: AxeIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    code = payload.code.strip().upper()
    if db.execute(select(models.AxeAnalytique).where(
            models.AxeAnalytique.societe_id == societe_id,
            models.AxeAnalytique.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"L'axe {code} existe déjà.")
    a = models.AxeAnalytique(societe_id=societe_id, code=code, libelle=payload.libelle.strip())
    db.add(a)
    db.commit()
    return {"id": str(a.id), "code": a.code, "libelle": a.libelle}


@router.post("/axes/{axe_id}/sections", status_code=status.HTTP_201_CREATED)
def creer_section(axe_id: uuid.UUID, payload: SectionIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    axe = db.get(models.AxeAnalytique, axe_id)
    if not axe:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Axe introuvable.")
    roles = assert_acces_societe(db, user, axe.societe_id)
    assert_role(roles, ROLES)
    s = models.SectionAnalytique(axe_id=axe.id, societe_id=axe.societe_id,
                                 code=payload.code.strip().upper(), libelle=payload.libelle.strip())
    db.add(s)
    db.commit()
    return {"id": str(s.id), "code": s.code, "libelle": s.libelle}


@router.patch("/sections/{section_id}")
def maj_section(section_id: uuid.UUID, payload: MajIn, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    s = db.get(models.SectionAnalytique, section_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section introuvable.")
    roles = assert_acces_societe(db, user, s.societe_id)
    assert_role(roles, ROLES)
    if payload.libelle is not None:
        s.libelle = payload.libelle.strip()
    if payload.actif is not None:
        s.actif = payload.actif
    db.commit()
    return {"id": str(s.id), "libelle": s.libelle, "actif": bool(s.actif)}


# ── Lignes à ventiler ────────────────────────────────────────────────
def _classe_ok(compte: str, classe: str | None) -> bool:
    if classe:
        return compte.startswith(classe)
    return compte[:1] in ("6", "7")


@router.get("/lignes")
def lignes_a_ventiler(societe_id: uuid.UUID, axe_id: uuid.UUID, classe: str | None = None,
                      non_ventilees: bool = False, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Lignes de charge (6x) / produit (7x) avec leur état de ventilation pour l'axe."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    journaux = dict(db.execute(
        select(models.Journal.id, models.Journal.code)
        .where(models.Journal.societe_id == societe_id)).all())
    sect_noms = dict(db.execute(
        select(models.SectionAnalytique.id, models.SectionAnalytique.libelle)
        .where(models.SectionAnalytique.axe_id == axe_id)).all())
    rows = db.execute(
        (select(models.LigneEcriture, models.Ecriture)
         .join(models.Ecriture, models.Ecriture.id == models.LigneEcriture.ecriture_id)
         .where(models.LigneEcriture.societe_id == societe_id)
         .order_by(models.Ecriture.date_ecriture, models.Ecriture.numero))).all()
    out = []
    for l, e in rows:
        if not _classe_ok(l.compte_numero, classe):
            continue
        vents = db.execute(select(models.VentilationAnalytique).where(
            models.VentilationAnalytique.ligne_ecriture_id == l.id,
            models.VentilationAnalytique.axe_id == axe_id)).scalars().all()
        montant = round(float(l.montant_usd), 2)
        ventile = round(sum(float(v.montant_usd) for v in vents), 2)
        if non_ventilees and ventile >= montant - 0.01:
            continue
        out.append({
            "id": str(l.id), "date": e.date_ecriture.isoformat(), "piece": e.numero,
            "journal": journaux.get(e.journal_id, ""), "compte": l.compte_numero,
            "libelle": l.libelle_ligne or e.libelle, "type": "charge" if l.compte_numero[:1] == "6" else "produit",
            "montant": montant, "ventile": ventile, "reste": round(montant - ventile, 2),
            "ventilation": [{"section_id": str(v.section_id), "section": sect_noms.get(v.section_id, ""),
                             "montant": round(float(v.montant_usd), 2)} for v in vents]})
    return out


class Part(BaseModel):
    section_id: uuid.UUID
    montant: float = Field(gt=0)


class VentilerIn(BaseModel):
    societe_id: uuid.UUID
    ligne_id: uuid.UUID
    axe_id: uuid.UUID
    repartition: list[Part] = []


@router.post("/ventiler")
def ventiler(payload: VentilerIn, db: Session = Depends(get_db),
             user: models.Utilisateur = Depends(get_current_user)):
    """Remplace la ventilation d'une ligne sur un axe (somme ≤ montant de la ligne)."""
    roles = assert_acces_societe(db, user, payload.societe_id)
    assert_role(roles, ROLES)
    ligne = db.get(models.LigneEcriture, payload.ligne_id)
    if not ligne or ligne.societe_id != payload.societe_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne invalide.")
    sections_axe = set(db.execute(select(models.SectionAnalytique.id).where(
        models.SectionAnalytique.axe_id == payload.axe_id)).scalars().all())
    total = round(sum(p.montant for p in payload.repartition), 2)
    if total > float(ligne.montant_usd) + 0.01:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"La ventilation ({total}) dépasse le montant de la ligne "
                            f"({float(ligne.montant_usd)}).")
    for p in payload.repartition:
        if p.section_id not in sections_axe:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Section hors de l'axe choisi.")

    # remplace les ventilations existantes de cette ligne pour cet axe
    for v in db.execute(select(models.VentilationAnalytique).where(
            models.VentilationAnalytique.ligne_ecriture_id == ligne.id,
            models.VentilationAnalytique.axe_id == payload.axe_id)).scalars().all():
        db.delete(v)
    for p in payload.repartition:
        db.add(models.VentilationAnalytique(
            societe_id=payload.societe_id, ligne_ecriture_id=ligne.id, axe_id=payload.axe_id,
            section_id=p.section_id, montant_usd=round(p.montant, 2)))
    services.enregistrer_audit(db, user.id, "VENTILATION", "ligne_ecriture", ligne.id, None,
                               {"axe": str(payload.axe_id), "parts": len(payload.repartition)})
    db.commit()
    return {"ligne_id": str(ligne.id), "ventile": total, "parts": len(payload.repartition)}


# ── Rapport analytique ───────────────────────────────────────────────
@router.get("/rapport")
def rapport(societe_id: uuid.UUID, axe_id: uuid.UUID, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    """Charges / produits / résultat par section d'un axe (+ non ventilé)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    axe = db.get(models.AxeAnalytique, axe_id)
    if not axe:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Axe introuvable.")
    sections = db.execute(select(models.SectionAnalytique).where(
        models.SectionAnalytique.axe_id == axe_id)
        .order_by(models.SectionAnalytique.code)).scalars().all()

    # montant + classe de chaque ligne ventilée
    vent_rows = db.execute(
        select(models.VentilationAnalytique.section_id, models.VentilationAnalytique.montant_usd,
               models.LigneEcriture.compte_numero)
        .join(models.LigneEcriture, models.LigneEcriture.id == models.VentilationAnalytique.ligne_ecriture_id)
        .where(models.VentilationAnalytique.axe_id == axe_id,
               models.VentilationAnalytique.societe_id == societe_id)).all()
    par_section: dict[str, dict] = {}
    tot_vent_ch = tot_vent_pr = 0.0
    for section_id, montant, compte in vent_rows:
        agg = par_section.setdefault(str(section_id), {"charges": 0.0, "produits": 0.0})
        m = float(montant)
        if compte[:1] == "6":
            agg["charges"] += m; tot_vent_ch += m
        elif compte[:1] == "7":
            agg["produits"] += m; tot_vent_pr += m

    # totaux généraux charges/produits (pour le non ventilé)
    tot_ch = tot_pr = 0.0
    for compte, montant in db.execute(
            select(models.LigneEcriture.compte_numero, models.LigneEcriture.montant_usd)
            .where(models.LigneEcriture.societe_id == societe_id)).all():
        if compte[:1] == "6":
            tot_ch += float(montant)
        elif compte[:1] == "7":
            tot_pr += float(montant)

    lignes = []
    for s in sections:
        a = par_section.get(str(s.id), {"charges": 0.0, "produits": 0.0})
        ch, pr = round(a["charges"], 2), round(a["produits"], 2)
        lignes.append({"section": s.libelle, "code": s.code, "charges": ch, "produits": pr,
                       "resultat": round(pr - ch, 2)})
    non_vent = {"charges": round(tot_ch - tot_vent_ch, 2), "produits": round(tot_pr - tot_vent_pr, 2)}
    return {"axe": axe.libelle, "lignes": lignes, "non_ventile": non_vent,
            "total_charges": round(tot_ch, 2), "total_produits": round(tot_pr, 2),
            "resultat": round(tot_pr - tot_ch, 2)}
