"""Comptabilité — pièces en attente : validation et reclassement par le comptable.

C'est la couture entre le décaissement/caisse et la comptabilité : chaque
décaissement génère une pièce « en attente » que le comptable valide ou reclasse
(corrige les comptes d'imputation) avant qu'elle ne devienne définitive.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import comptabilite, etats_financiers, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user

router = APIRouter(prefix="/api/comptabilite", tags=["comptabilité"])
ROLES_COMPTA = {"COMPTABLE", "DFI"}


# Provenance = catégorie d'origine de la pièce (pour regrouper les pièces en attente)
_PROV_JOURNAL = {"caisse": "Caisse", "banque": "Banque", "achat": "Achat",
                 "vente": "Vente", "ouverture": "À-nouveaux"}


def _provenance(db: Session, e: models.Ecriture, journal) -> tuple[str, str | None]:
    """Retourne (catégorie, détail) : d'où vient la pièce, avec un libellé de source."""
    to = e.type_operation or ""
    cat = "Divers"
    if to == "transfert":
        cat = "Transfert"
    elif to == "operation_caisse":
        cat = "Caisse"
    elif journal and journal.type in _PROV_JOURNAL:
        cat = _PROV_JOURNAL[journal.type]
    elif journal:
        cat = journal.code

    detail = None
    if e.source_type == "mouvement_caisse" and e.source_id:
        m = db.get(models.MouvementCaisse, e.source_id)
        if m:
            c = db.get(models.Caisse, m.caisse_id)
            if c:
                detail = c.libelle
                if "POS" in (c.libelle or "").upper():
                    cat = "POS"
    elif e.source_type == "transfert" and e.source_id:
        t = db.get(models.Transfert, e.source_id)
        detail = t.numero if t else None
    elif e.source_type in ("avance", "ordre_depense") and e.source_id:
        detail = e.numero_piece
    return cat, detail


def _ecriture_dict(db: Session, e: models.Ecriture, intitules: dict | None = None) -> dict:
    journal = db.get(models.Journal, e.journal_id) if e.journal_id else None
    lignes = db.execute(
        select(models.LigneEcriture).where(models.LigneEcriture.ecriture_id == e.id)
        .order_by(models.LigneEcriture.ordre)
    ).scalars().all()
    if intitules is None:
        intitules = dict(db.execute(
            select(models.Compte.numero, models.Compte.intitule)
            .where(models.Compte.societe_id == e.societe_id)).all())
    tiers_noms = dict(db.execute(select(models.Tiers.id, models.Tiers.nom)).all())
    cat, detail = _provenance(db, e, journal)
    total = round(sum(float(l.montant_usd) for l in lignes if l.sens == "D"), 2)
    nb_pj = db.execute(select(func.count()).select_from(models.PieceJointe).where(
        models.PieceJointe.document_type == "ecriture",
        models.PieceJointe.document_id == e.id)).scalar() or 0
    return {
        "id": str(e.id), "numero": e.numero, "date": e.date_ecriture.isoformat(),
        "libelle": e.libelle, "journal": journal.code if journal else None,
        "provenance": cat, "source": detail, "montant": total,
        "piece": e.numero_piece, "nb_pj": nb_pj,
        "type_operation": e.type_operation, "statut": e.statut,
        "lignes": [{"id": str(l.id), "sens": l.sens, "compte": l.compte_numero,
                    "intitule": intitules.get(l.compte_numero, ""),
                    "tiers": tiers_noms.get(l.tiers_id) if l.tiers_id else None,
                    "montant_usd": float(l.montant_usd), "libelle": l.libelle_ligne} for l in lignes],
    }


@router.get("/ecritures")
def lister_ecritures(societe_id: uuid.UUID, statut: str = "en_attente",
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    q = select(models.Ecriture).where(models.Ecriture.societe_id == societe_id)
    if statut:
        q = q.where(models.Ecriture.statut == statut)
    rows = db.execute(q.order_by(models.Ecriture.created_at.desc())).scalars().all()
    return [_ecriture_dict(db, e) for e in rows]


class Reclassement(BaseModel):
    ligne_id: uuid.UUID
    compte_numero: str


class Repartition(BaseModel):
    compte_numero: str
    montant: float = Field(gt=0)
    tiers_id: uuid.UUID | None = None
    libelle: str | None = None


class Split(BaseModel):
    """Éclatement d'une ligne sur plusieurs comptes (même sens, montants = total)."""
    ligne_id: uuid.UUID
    repartition: list[Repartition]


class ValidationEcriture(BaseModel):
    reclassements: list[Reclassement] = []
    splits: list[Split] = []


@router.post("/ecritures/{ecriture_id}/valider")
def valider_ecriture(ecriture_id: uuid.UUID, payload: ValidationEcriture,
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Le comptable valide la pièce, après reclassement et/ou éclatement des lignes.

    - reclassement : change le compte d'imputation d'une ligne.
    - split : éclate une ligne sur plusieurs comptes (mêmes sens, la somme des
      montants doit égaler le montant de la ligne d'origine) — l'équilibre D=C est
      préservé puisqu'on ne touche qu'un seul côté à la fois.
    """
    e = db.get(models.Ecriture, ecriture_id)
    if not e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Écriture introuvable.")
    roles = assert_acces_societe(db, user, e.societe_id)
    assert_role(roles, ROLES_COMPTA)
    if e.statut != "en_attente":
        raise HTTPException(status.HTTP_409_CONFLICT, "Pièce déjà validée.")

    comptes_valides = set(db.execute(
        select(models.Compte.numero).where(models.Compte.societe_id == e.societe_id)).scalars().all())
    ordre_max = max((l.ordre for l in e.lignes), default=0)
    splits_faits, split_ids = 0, set()

    for sp in payload.splits:
        ligne = db.get(models.LigneEcriture, sp.ligne_id)
        if not ligne or ligne.ecriture_id != e.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne à éclater invalide.")
        if not sp.repartition:
            continue
        total = round(sum(r.montant for r in sp.repartition), 2)
        if abs(total - float(ligne.montant_usd)) > 0.01:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"L'éclatement ({total}) doit égaler le montant de la ligne "
                                f"({float(ligne.montant_usd)}).")
        for r in sp.repartition:
            if r.compte_numero not in comptes_valides:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Compte {r.compte_numero} absent du plan comptable.")
        # 1ère répartition réutilise la ligne existante
        first = sp.repartition[0]
        ligne.compte_numero = first.compte_numero
        ligne.montant_usd = round(first.montant, 2)
        ligne.tiers_id = first.tiers_id
        if first.libelle:
            ligne.libelle_ligne = first.libelle
        # les suivantes = nouvelles lignes, même sens
        for r in sp.repartition[1:]:
            ordre_max += 1
            db.add(models.LigneEcriture(
                ecriture_id=e.id, societe_id=e.societe_id, ordre=ordre_max, sens=ligne.sens,
                compte_numero=r.compte_numero, tiers_id=r.tiers_id, montant_usd=round(r.montant, 2),
                libelle_ligne=r.libelle or ligne.libelle_ligne))
        split_ids.add(ligne.id)
        splits_faits += 1

    changements = []
    for r in payload.reclassements:
        ligne = db.get(models.LigneEcriture, r.ligne_id)
        if not ligne or ligne.ecriture_id != e.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne invalide.")
        if ligne.id in split_ids:
            continue
        if r.compte_numero not in comptes_valides:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Compte {r.compte_numero} absent du plan comptable.")
        if ligne.compte_numero != r.compte_numero:
            changements.append({"ligne": str(ligne.id), "de": ligne.compte_numero, "vers": r.compte_numero})
            ligne.compte_numero = r.compte_numero

    e.statut = "valide"
    services.enregistrer_audit(db, user.id, "VALIDATE", "ecriture", e.id,
                               {"reclassements": changements, "splits": splits_faits}
                               if (changements or splits_faits) else None,
                               {"statut": "valide"})
    db.commit()
    return {"id": str(e.id), "statut": "valide", "reclassements": len(changements),
            "splits": splits_faits}


@router.get("/balance")
def balance(societe_id: uuid.UUID, annee: int | None = None, statut: str | None = None,
            classe: str | None = None, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    """Balance générale N / N-1, par compte. `statut` : filtre les écritures
    (None = toutes ; 'valide' = définitives seulement)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    annee = annee or date.today().year

    q = (select(models.LigneEcriture.compte_numero, models.LigneEcriture.sens,
                models.LigneEcriture.montant_usd, models.Ecriture.date_ecriture)
         .join(models.Ecriture, models.Ecriture.id == models.LigneEcriture.ecriture_id)
         .where(models.LigneEcriture.societe_id == societe_id))
    if statut:
        q = q.where(models.Ecriture.statut == statut)
    rows = db.execute(q).all()

    intitules = dict(db.execute(
        select(models.Compte.numero, models.Compte.intitule)
        .where(models.Compte.societe_id == societe_id)).all())

    agg: dict[str, dict] = {}
    for compte, sens, montant, dte in rows:
        an = dte.year
        if an not in (annee, annee - 1):
            continue
        a = agg.setdefault(compte, {"compte": compte, "debit": 0.0, "credit": 0.0, "solde_n1": 0.0})
        m = float(montant)
        if an == annee:
            a["debit" if sens == "D" else "credit"] += m
        else:
            a["solde_n1"] += m if sens == "D" else -m

    lignes, td, tc = [], 0.0, 0.0
    for a in agg.values():
        if classe and not a["compte"].startswith(classe):
            continue
        solde = a["debit"] - a["credit"]
        lignes.append({
            "compte": a["compte"], "intitule": intitules.get(a["compte"], ""),
            "debit": round(a["debit"], 2), "credit": round(a["credit"], 2),
            "solde_debiteur": round(solde, 2) if solde > 0 else 0.0,
            "solde_crediteur": round(-solde, 2) if solde < 0 else 0.0,
            "solde_n1": round(a["solde_n1"], 2),
        })
        td += a["debit"]; tc += a["credit"]
    lignes.sort(key=lambda x: x["compte"])
    return {"annee": annee, "lignes": lignes, "total_debit": round(td, 2),
            "total_credit": round(tc, 2), "equilibre": round(td, 2) == round(tc, 2)}


@router.get("/grand-livre")
def grand_livre(societe_id: uuid.UUID, compte: str | None = None, statut: str | None = None,
                tiers_id: uuid.UUID | None = None,
                db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    """Détail des mouvements par compte, avec solde progressif, code journal et tiers.
    `tiers_id` restreint au grand livre auxiliaire d'un tiers."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    journaux = dict(db.execute(
        select(models.Journal.id, models.Journal.code)
        .where(models.Journal.societe_id == societe_id)).all())
    tiers_noms = dict(db.execute(
        select(models.Tiers.id, models.Tiers.nom)).all())

    q = (select(models.LigneEcriture, models.Ecriture)
         .join(models.Ecriture, models.Ecriture.id == models.LigneEcriture.ecriture_id)
         .where(models.LigneEcriture.societe_id == societe_id)
         .order_by(models.LigneEcriture.compte_numero, models.Ecriture.date_ecriture,
                   models.Ecriture.numero))
    if compte:
        q = q.where(models.LigneEcriture.compte_numero.like(f"{compte}%"))
    if statut:
        q = q.where(models.Ecriture.statut == statut)
    if tiers_id:
        q = q.where(models.LigneEcriture.tiers_id == tiers_id)
    rows = db.execute(q).all()
    intitules = dict(db.execute(
        select(models.Compte.numero, models.Compte.intitule)
        .where(models.Compte.societe_id == societe_id)).all())
    comptes: dict[str, dict] = {}
    for ligne, ecr in rows:
        c = comptes.setdefault(ligne.compte_numero, {
            "compte": ligne.compte_numero, "intitule": intitules.get(ligne.compte_numero, ""),
            "mouvements": [], "_solde": 0.0})
        d = float(ligne.montant_usd) if ligne.sens == "D" else 0.0
        cr = float(ligne.montant_usd) if ligne.sens == "C" else 0.0
        c["_solde"] += d - cr
        c["mouvements"].append({
            "date": ecr.date_ecriture.isoformat(), "piece": ecr.numero,
            "journal": journaux.get(ecr.journal_id, ""),
            "tiers": tiers_noms.get(ligne.tiers_id) if ligne.tiers_id else None,
            "lettrage": ligne.lettrage_code,
            "libelle": ligne.libelle_ligne or ecr.libelle,
            "debit": round(d, 2), "credit": round(cr, 2), "solde": round(c["_solde"], 2),
            "statut": ecr.statut})
    for c in comptes.values():
        c["solde"] = round(c.pop("_solde"), 2)
    return sorted(comptes.values(), key=lambda x: x["compte"])


# ── Plan comptable ───────────────────────────────────────────────────
class CompteIn(BaseModel):
    numero: str = Field(min_length=1, max_length=12)
    intitule: str = Field(min_length=1)
    auxiliaire: bool = False


class CompteMaj(BaseModel):
    intitule: str | None = None
    auxiliaire: bool | None = None
    actif: bool | None = None


def _compte_dict(c: models.Compte) -> dict:
    return {"id": str(c.id), "numero": c.numero, "intitule": c.intitule,
            "classe": c.classe, "auxiliaire": bool(c.auxiliaire), "actif": bool(c.actif)}


@router.get("/plan-comptable")
def plan_comptable(societe_id: uuid.UUID, q: str | None = None, classe: str | None = None,
                   actifs_only: bool = False, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    query = select(models.Compte).where(models.Compte.societe_id == societe_id)
    if classe:
        query = query.where(models.Compte.classe == classe)
    if actifs_only:
        query = query.where(models.Compte.actif.is_(True))
    comptes = db.execute(query).scalars().all()
    if q:
        ql = q.lower()
        comptes = [c for c in comptes if ql in c.numero.lower() or ql in c.intitule.lower()]
    comptes.sort(key=lambda c: c.numero)
    return [_compte_dict(c) for c in comptes]


@router.post("/plan-comptable", status_code=status.HTTP_201_CREATED)
def creer_compte(societe_id: uuid.UUID, payload: CompteIn, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    num = payload.numero.strip()
    exists = db.execute(select(models.Compte).where(
        models.Compte.societe_id == societe_id, models.Compte.numero == num)).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le compte {num} existe déjà.")
    c = models.Compte(societe_id=societe_id, numero=num, intitule=payload.intitule.strip(),
                      classe=num[0], auxiliaire=payload.auxiliaire, actif=True)
    db.add(c)
    db.flush()
    services.enregistrer_audit(db, user.id, "INSERT", "compte", c.id, None, {"numero": num})
    db.commit()
    return _compte_dict(c)


@router.patch("/plan-comptable/{compte_id}")
def maj_compte(compte_id: uuid.UUID, payload: CompteMaj, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    c = db.get(models.Compte, compte_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES_COMPTA)
    if payload.intitule is not None:
        c.intitule = payload.intitule.strip()
    if payload.auxiliaire is not None:
        c.auxiliaire = payload.auxiliaire
    if payload.actif is not None:
        c.actif = payload.actif
    db.commit()
    return _compte_dict(c)


@router.post("/plan-comptable/charger-syscohada")
def charger_syscohada(societe_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """(Ré)initialise le plan SYSCOHADA — n'écrase aucun compte existant."""
    from ..plan_comptable import charger_plan
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    crees = charger_plan(db, societe_id)
    db.commit()
    return {"comptes_crees": crees}


# ── Journaux ─────────────────────────────────────────────────────────
class JournalIn(BaseModel):
    code: str = Field(min_length=1, max_length=6)
    libelle: str = Field(min_length=1)
    type: str = "od"


@router.get("/journaux")
def lister_journaux(societe_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    js = db.execute(select(models.Journal).where(models.Journal.societe_id == societe_id)
                    .order_by(models.Journal.code)).scalars().all()
    return [{"id": str(j.id), "code": j.code, "libelle": j.libelle, "type": j.type,
             "actif": bool(j.actif)} for j in js]


@router.post("/journaux", status_code=status.HTTP_201_CREATED)
def creer_journal(societe_id: uuid.UUID, payload: JournalIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    code = payload.code.strip().upper()
    exists = db.execute(select(models.Journal).where(
        models.Journal.societe_id == societe_id, models.Journal.code == code)).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le journal {code} existe déjà.")
    j = models.Journal(societe_id=societe_id, code=code, libelle=payload.libelle.strip(),
                       type=payload.type)
    db.add(j)
    db.commit()
    return {"id": str(j.id), "code": j.code, "libelle": j.libelle, "type": j.type}


# ── Saisie manuelle d'écriture (OD) ──────────────────────────────────
class LigneOD(BaseModel):
    sens: str = Field(pattern="^[DC]$")
    compte: str = Field(min_length=1)
    montant: float = Field(gt=0)          # en USD (devise pivot)
    tiers_id: uuid.UUID | None = None
    libelle: str | None = None


class EcritureManuelleIn(BaseModel):
    journal_code: str = "OD"
    date_ecriture: date | None = None
    libelle: str = Field(min_length=1)
    numero_piece: str | None = None
    lignes: list[LigneOD]


@router.post("/ecritures/saisie", status_code=status.HTTP_201_CREATED)
def saisir_ecriture(societe_id: uuid.UUID, payload: EcritureManuelleIn,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Saisie manuelle d'une écriture équilibrée (opérations diverses), en USD.
    Réservée au comptable/DFI ; enregistrée directement en 'valide'."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    societe = db.get(models.Societe, societe_id)
    if len(payload.lignes) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins deux lignes (un débit et un crédit).")

    total_d = round(sum(l.montant for l in payload.lignes if l.sens == "D"), 2)
    total_c = round(sum(l.montant for l in payload.lignes if l.sens == "C"), 2)
    if total_d != total_c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Écriture déséquilibrée : débit {total_d} ≠ crédit {total_c}.")

    comptes_valides = set(db.execute(
        select(models.Compte.numero).where(models.Compte.societe_id == societe_id)).scalars().all())
    lignes = []
    for l in payload.lignes:
        if l.compte not in comptes_valides:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Compte {l.compte} absent du plan comptable.")
        lignes.append({"sens": l.sens, "compte": l.compte, "montant_usd": round(l.montant, 2),
                       "tiers_id": l.tiers_id, "libelle": l.libelle})

    j = db.execute(select(models.Journal).where(
        models.Journal.societe_id == societe_id,
        models.Journal.code == payload.journal_code.upper())).scalars().first()
    jcode = j.code if j else payload.journal_code.upper()
    ecr = comptabilite.post_ecriture(
        db, societe, jcode, j.libelle if j else "Opérations diverses", j.type if j else "od",
        payload.date_ecriture or date.today(), payload.libelle, lignes,
        "od_manuelle", "saisie_manuelle", None, payload.numero_piece, user.id, statut="valide")
    db.commit()
    return _ecriture_dict(db, ecr)


# ── Lettrage des comptes de tiers ────────────────────────────────────
def _num_to_alpha(n: int) -> str:
    """1→A, 26→Z, 27→AA … pour numéroter les lettrages."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@router.get("/lettrage")
def lettrage_compte(societe_id: uuid.UUID, compte: str, tiers_id: uuid.UUID | None = None,
                    non_lettres: bool = False, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Lignes d'un compte (auxiliaire si tiers_id) avec leur état de lettrage.
    Sert à rapprocher débits et crédits (ex. avance ↔ justification d'un bénéficiaire)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    journaux = dict(db.execute(
        select(models.Journal.id, models.Journal.code)
        .where(models.Journal.societe_id == societe_id)).all())
    tiers_noms = dict(db.execute(select(models.Tiers.id, models.Tiers.nom)).all())
    compte_obj = db.execute(select(models.Compte).where(
        models.Compte.societe_id == societe_id, models.Compte.numero == compte)).scalars().first()

    q = (select(models.LigneEcriture, models.Ecriture)
         .join(models.Ecriture, models.Ecriture.id == models.LigneEcriture.ecriture_id)
         .where(models.LigneEcriture.societe_id == societe_id,
                models.LigneEcriture.compte_numero == compte)
         .order_by(models.Ecriture.date_ecriture, models.Ecriture.numero))
    if tiers_id:
        q = q.where(models.LigneEcriture.tiers_id == tiers_id)
    rows = db.execute(q).all()

    lignes, solde, non_lettre = [], 0.0, 0.0
    for l, e in rows:
        d = float(l.montant_usd) if l.sens == "D" else 0.0
        c = float(l.montant_usd) if l.sens == "C" else 0.0
        solde += d - c
        if not l.lettrage_code:
            non_lettre += d - c
        if non_lettres and l.lettrage_code:
            continue
        lignes.append({
            "id": str(l.id), "date": e.date_ecriture.isoformat(), "piece": e.numero,
            "journal": journaux.get(e.journal_id, ""), "libelle": l.libelle_ligne or e.libelle,
            "tiers": tiers_noms.get(l.tiers_id) if l.tiers_id else None,
            "debit": round(d, 2), "credit": round(c, 2), "lettrage": l.lettrage_code,
            "statut": e.statut})
    return {"compte": compte, "intitule": compte_obj.intitule if compte_obj else "",
            "lignes": lignes, "solde": round(solde, 2), "solde_non_lettre": round(non_lettre, 2)}


class LettrageIn(BaseModel):
    societe_id: uuid.UUID
    ligne_ids: list[uuid.UUID]


@router.post("/lettrage")
def lettrer(payload: LettrageIn, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    """Lettre un groupe de lignes équilibré (Σdébit = Σcrédit) d'un même compte."""
    roles = assert_acces_societe(db, user, payload.societe_id)
    assert_role(roles, ROLES_COMPTA)
    if len(payload.ligne_ids) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez au moins deux lignes.")
    lignes = [db.get(models.LigneEcriture, lid) for lid in payload.ligne_ids]
    if any(l is None or l.societe_id != payload.societe_id for l in lignes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne invalide.")
    comptes = {l.compte_numero for l in lignes}
    if len(comptes) != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Toutes les lignes doivent être du même compte.")
    if any(l.lettrage_code for l in lignes):
        raise HTTPException(status.HTTP_409_CONFLICT, "Une ligne sélectionnée est déjà lettrée.")
    total_d = round(sum(float(l.montant_usd) for l in lignes if l.sens == "D"), 2)
    total_c = round(sum(float(l.montant_usd) for l in lignes if l.sens == "C"), 2)
    if total_d != total_c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Lettrage déséquilibré : débit {total_d} ≠ crédit {total_c}.")

    compte = comptes.pop()
    seq = comptabilite._next_compteur(db, payload.societe_id, f"LET_{compte}", 0)
    code = _num_to_alpha(seq)
    for l in lignes:
        l.lettrage_code = code
    services.enregistrer_audit(db, user.id, "LETTRAGE", "compte", None, None,
                               {"compte": compte, "code": code, "lignes": len(lignes)})
    db.commit()
    return {"code": code, "compte": compte, "lignes": len(lignes)}


class DelettrageIn(BaseModel):
    societe_id: uuid.UUID
    compte: str
    code: str


@router.post("/delettrage")
def delettrer(payload: DelettrageIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    """Annule un lettrage (retire le code des lignes concernées)."""
    roles = assert_acces_societe(db, user, payload.societe_id)
    assert_role(roles, ROLES_COMPTA)
    lignes = db.execute(select(models.LigneEcriture).where(
        models.LigneEcriture.societe_id == payload.societe_id,
        models.LigneEcriture.compte_numero == payload.compte,
        models.LigneEcriture.lettrage_code == payload.code)).scalars().all()
    if not lignes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lettrage introuvable.")
    for l in lignes:
        l.lettrage_code = None
    services.enregistrer_audit(db, user.id, "DELETTRAGE", "compte", None, None,
                               {"compte": payload.compte, "code": payload.code})
    db.commit()
    return {"delettre": len(lignes)}


# ── Rapprochement bancaire ───────────────────────────────────────────
def _solde_compte(db: Session, societe_id: uuid.UUID, compte: str, rapproche: bool | None = None) -> float:
    """Solde (Σ débit − Σ crédit) d'un compte. rapproche=True → seulement les
    lignes déjà pointées ; None → toutes."""
    q = select(models.LigneEcriture.sens, models.LigneEcriture.montant_usd).where(
        models.LigneEcriture.societe_id == societe_id, models.LigneEcriture.compte_numero == compte)
    if rapproche is True:
        q = q.where(models.LigneEcriture.rapprochement_id.isnot(None))
    elif rapproche is False:
        q = q.where(models.LigneEcriture.rapprochement_id.is_(None))
    s = 0.0
    for sens, m in db.execute(q).all():
        s += float(m) if sens == "D" else -float(m)
    return round(s, 2)


@router.get("/rapprochement/a-pointer")
def rappro_a_pointer(societe_id: uuid.UUID, compte: str = "521",
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Lignes du compte de banque non encore rapprochées (à pointer contre le relevé)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    journaux = dict(db.execute(
        select(models.Journal.id, models.Journal.code)
        .where(models.Journal.societe_id == societe_id)).all())
    compte_obj = db.execute(select(models.Compte).where(
        models.Compte.societe_id == societe_id, models.Compte.numero == compte)).scalars().first()
    rows = db.execute(
        (select(models.LigneEcriture, models.Ecriture)
         .join(models.Ecriture, models.Ecriture.id == models.LigneEcriture.ecriture_id)
         .where(models.LigneEcriture.societe_id == societe_id,
                models.LigneEcriture.compte_numero == compte,
                models.LigneEcriture.rapprochement_id.is_(None))
         .order_by(models.Ecriture.date_ecriture, models.Ecriture.numero))).all()
    lignes = [{
        "id": str(l.id), "date": e.date_ecriture.isoformat(), "piece": e.numero,
        "journal": journaux.get(e.journal_id, ""), "libelle": l.libelle_ligne or e.libelle,
        "debit": round(float(l.montant_usd), 2) if l.sens == "D" else 0.0,
        "credit": round(float(l.montant_usd), 2) if l.sens == "C" else 0.0,
        "statut": e.statut} for l, e in rows]
    return {"compte": compte, "intitule": compte_obj.intitule if compte_obj else "",
            "lignes": lignes,
            "solde_comptable": _solde_compte(db, societe_id, compte),
            "solde_rapproche": _solde_compte(db, societe_id, compte, rapproche=True)}


class RapprochementIn(BaseModel):
    societe_id: uuid.UUID
    compte: str = "521"
    date_releve: date
    solde_releve: float
    ligne_ids: list[uuid.UUID] = []


def _rappro_dict(db: Session, r: models.RapprochementBancaire) -> dict:
    return {"id": str(r.id), "compte": r.compte, "date_releve": r.date_releve.isoformat(),
            "solde_releve": float(r.solde_releve_usd), "solde_comptable": float(r.solde_comptable_usd),
            "solde_rapproche": float(r.solde_rapproche_usd), "ecart": float(r.ecart_usd),
            "statut": r.statut, "date": r.created_at.isoformat() if r.created_at else None}


@router.post("/rapprochement", status_code=status.HTTP_201_CREATED)
def creer_rapprochement(payload: RapprochementIn, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    """Enregistre un rapprochement : pointe les lignes présentes sur le relevé,
    calcule l'écart entre le solde du relevé et le solde comptable pointé (cumulé)."""
    roles = assert_acces_societe(db, user, payload.societe_id)
    assert_role(roles, ROLES_COMPTA)
    lignes = [db.get(models.LigneEcriture, lid) for lid in payload.ligne_ids]
    for l in lignes:
        if l is None or l.societe_id != payload.societe_id or l.compte_numero != payload.compte:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne invalide pour ce compte.")
        if l.rapprochement_id is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Une ligne est déjà rapprochée.")

    solde_comptable = _solde_compte(db, payload.societe_id, payload.compte)
    deja = _solde_compte(db, payload.societe_id, payload.compte, rapproche=True)
    lot = round(sum(float(l.montant_usd) if l.sens == "D" else -float(l.montant_usd) for l in lignes), 2)
    solde_rapproche = round(deja + lot, 2)
    ecart = round(payload.solde_releve - solde_rapproche, 2)

    r = models.RapprochementBancaire(
        societe_id=payload.societe_id, compte=payload.compte, date_releve=payload.date_releve,
        solde_releve_usd=round(payload.solde_releve, 2), solde_comptable_usd=solde_comptable,
        solde_rapproche_usd=solde_rapproche, ecart_usd=ecart, statut="cloture", created_by=user.id)
    db.add(r)
    db.flush()
    for l in lignes:
        l.rapprochement_id = r.id
    services.enregistrer_audit(db, user.id, "RAPPROCHEMENT", "rapprochement_bancaire", r.id, None,
                               {"compte": payload.compte, "lignes": len(lignes), "ecart": ecart})
    db.commit()
    return _rappro_dict(db, r)


@router.get("/rapprochement")
def lister_rapprochements(societe_id: uuid.UUID, compte: str | None = None,
                          db: Session = Depends(get_db),
                          user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    q = select(models.RapprochementBancaire).where(
        models.RapprochementBancaire.societe_id == societe_id)
    if compte:
        q = q.where(models.RapprochementBancaire.compte == compte)
    rows = db.execute(q.order_by(models.RapprochementBancaire.date_releve.desc())).scalars().all()
    return [_rappro_dict(db, r) for r in rows]


@router.post("/rapprochement/{rappro_id}/annuler")
def annuler_rapprochement(rappro_id: uuid.UUID, db: Session = Depends(get_db),
                          user: models.Utilisateur = Depends(get_current_user)):
    """Annule un rapprochement : dépointe ses lignes."""
    r = db.get(models.RapprochementBancaire, rappro_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rapprochement introuvable.")
    roles = assert_acces_societe(db, user, r.societe_id)
    assert_role(roles, ROLES_COMPTA)
    lignes = db.execute(select(models.LigneEcriture).where(
        models.LigneEcriture.rapprochement_id == rappro_id)).scalars().all()
    for l in lignes:
        l.rapprochement_id = None
    db.delete(r)
    services.enregistrer_audit(db, user.id, "ANNUL_RAPPROCHEMENT", "rapprochement_bancaire", rappro_id,
                               None, {"lignes": len(lignes)})
    db.commit()
    return {"annule": True, "lignes_depointees": len(lignes)}


# ── États financiers OHADA + cockpit DAF ─────────────────────────────
@router.get("/compte-resultat")
def compte_resultat(societe_id: uuid.UUID, statut: str | None = None,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    return etats_financiers.compte_resultat(db, societe_id, statut)


@router.get("/bilan")
def bilan(societe_id: uuid.UUID, statut: str | None = None,
          db: Session = Depends(get_db),
          user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    return etats_financiers.bilan(db, societe_id, statut)


@router.get("/tft")
def tft(societe_id: uuid.UUID, statut: str | None = None,
        db: Session = Depends(get_db),
        user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    return etats_financiers.tft(db, societe_id, statut)


@router.get("/cockpit")
def cockpit(societe_id: uuid.UUID, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    return etats_financiers.cockpit(db, societe_id)


# ── Comptes de configuration (imputations des écritures automatiques) ─
# (clé de paramètre `compte.<cle>`, libellé, compte par défaut)
COMPTES_CONFIG = [
    ("compte_client", "Clients", "411"),
    ("compte_fournisseur", "Fournisseurs", "401"),
    ("fournisseur_fnp", "Fournisseurs, factures non parvenues", "408"),
    ("compte_avance_personnel", "Avances au personnel", "421"),
    ("compte_avance_fournisseur", "Avances aux fournisseurs", "409"),
    ("compte_avance", "Avances — compte par défaut", "409"),
    ("compte_caisse", "Caisse", "571"),
    ("compte_charge", "Charge par défaut", "605"),
    ("compte_attente", "Compte d'attente (à reclasser)", "471"),
    ("variation_stock", "Variation des stocks", "603"),
    ("tva_deductible", "TVA déductible (sur achats)", "4452"),
    ("tva_collectee", "TVA collectée (sur ventes)", "4431"),
    ("ecart_manquant", "Manquant de caisse (cession)", "658"),
    ("ecart_excedent", "Excédent de caisse (cession)", "758"),
    ("compte_banque", "Banque (encaissements POS)", "521"),
    ("compte_mobile_money", "Mobile Money (M-Pesa, Airtel, Orange)", "522"),
    ("compte_vente_transport", "Produits de transport (courses)", "706"),
    ("compte_sous_traitance", "Sous-traitance transport (camions tiers)", "612"),
]


def _set_parametre(db: Session, cle: str, societe_id: uuid.UUID, valeur: str) -> None:
    p = db.execute(select(models.Parametre).where(
        models.Parametre.cle == cle, models.Parametre.societe_id == societe_id)).scalars().first()
    if p:
        p.valeur = valeur
    else:
        db.add(models.Parametre(cle=cle, societe_id=societe_id, valeur=valeur, type_valeur="string"))


@router.get("/comptes-config")
def get_comptes_config(societe_id: uuid.UUID, db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    intitules = dict(db.execute(
        select(models.Compte.numero, models.Compte.intitule)
        .where(models.Compte.societe_id == societe_id)).all())
    comptes = []
    for cle, libelle, defaut in COMPTES_CONFIG:
        val = services.get_parametre(db, f"compte.{cle}", societe_id, defaut)
        comptes.append({"cle": cle, "libelle": libelle, "valeur": val, "defaut": defaut,
                        "intitule": intitules.get(val, "")})
    tva = services.get_parametre(db, "tva.taux_defaut", societe_id, "16")
    return {"comptes": comptes, "tva_taux_defaut": float(tva)}


class ComptesConfigIn(BaseModel):
    config: dict[str, str] = {}
    tva_taux_defaut: float | None = None


@router.post("/comptes-config")
def maj_comptes_config(societe_id: uuid.UUID, payload: ComptesConfigIn,
                       db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    known = {c[0] for c in COMPTES_CONFIG}
    n = 0
    for cle, val in payload.config.items():
        if cle in known and val and val.strip():
            _set_parametre(db, f"compte.{cle}", societe_id, val.strip())
            n += 1
    if payload.tva_taux_defaut is not None:
        _set_parametre(db, "tva.taux_defaut", societe_id, str(payload.tva_taux_defaut))
    services.enregistrer_audit(db, user.id, "CONFIG", "comptes_config", None, None, {"maj": n})
    db.commit()
    return {"ok": True, "modifies": n}


# ── Revue comptable (validation des pièces avant définitif) ──────────
@router.get("/revue-config")
def get_revue_config(societe_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Quels flux passent par une validation du comptable (statut « en attente »)
    avant de devenir définitifs. Par défaut : achats oui, ventes non."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    return {
        "revue_achats": services.get_parametre(db, "compta.revue_achats", societe_id, "1") == "1",
        "revue_ventes": services.get_parametre(db, "compta.revue_ventes", societe_id, "0") == "1",
    }


class RevueConfigIn(BaseModel):
    revue_achats: bool | None = None
    revue_ventes: bool | None = None


@router.post("/revue-config")
def maj_revue_config(societe_id: uuid.UUID, payload: RevueConfigIn,
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_COMPTA)
    if payload.revue_achats is not None:
        _set_parametre(db, "compta.revue_achats", societe_id, "1" if payload.revue_achats else "0")
    if payload.revue_ventes is not None:
        _set_parametre(db, "compta.revue_ventes", societe_id, "1" if payload.revue_ventes else "0")
    services.enregistrer_audit(db, user.id, "CONFIG", "revue_config", None, None,
                               {"achats": payload.revue_achats, "ventes": payload.revue_ventes})
    db.commit()
    return {"ok": True}
