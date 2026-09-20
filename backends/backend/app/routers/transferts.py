"""Transferts de fonds entre points de trésorerie (caisse ou banque), à double
validation. L'initiateur crée (sortie côté source) → la destination valide
(entrée effective) → pièce comptable en attente. Rejet = retour des fonds.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import comptabilite, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user
from ..domain import money

router = APIRouter(prefix="/api/transferts", tags=["transferts"])
ROLES = {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "COMPTABLE", "DFI"}


def _endpoint(db: Session, type_: str, id_: uuid.UUID):
    """Retourne (objet, libellé, compte_comptable) pour une caisse ou une banque."""
    if type_ == "caisse":
        c = db.get(models.Caisse, id_)
        return (c, c.libelle, c.compte_comptable or "571") if c else (None, None, None)
    b = db.get(models.CompteBancaire, id_)
    return (b, f"{b.banque} {b.numero_compte or ''}".strip(), b.compte_comptable or "521") if b else (None, None, None)


def _session(db: Session, caisse_id: uuid.UUID):
    return db.execute(select(models.SessionCaisse).where(
        models.SessionCaisse.caisse_id == caisse_id,
        models.SessionCaisse.statut == "ouverte")).scalars().first()


def _solde(db: Session, sess: models.SessionCaisse, devise: str) -> float:
    base = float(sess.fond_initial_usd if devise == "USD" else sess.fond_initial_cdf)
    rows = db.execute(
        select(models.MouvementCaisse.sens, func.coalesce(func.sum(models.MouvementCaisse.montant), 0))
        .where(models.MouvementCaisse.session_id == sess.id, models.MouvementCaisse.devise == devise)
        .group_by(models.MouvementCaisse.sens)).all()
    for sens, total in rows:
        base += float(total) if sens == "entree" else -float(total)
    return round(base, 2)


class TransfertIn(BaseModel):
    societe_id: uuid.UUID
    source_type: str = Field(pattern="^(caisse|banque)$")
    source_id: uuid.UUID
    dest_type: str = Field(pattern="^(caisse|banque)$")
    dest_id: uuid.UUID
    devise: str = "USD"
    montant: float = Field(gt=0)
    motif: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
def creer(payload: TransfertIn, db: Session = Depends(get_db),
          user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, payload.societe_id)
    assert_role(roles, ROLES)
    if payload.source_type == payload.dest_type and payload.source_id == payload.dest_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Source et destination identiques.")
    src, src_lbl, _ = _endpoint(db, payload.source_type, payload.source_id)
    dst, dst_lbl, _ = _endpoint(db, payload.dest_type, payload.dest_id)
    if not src or not dst:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source ou destination introuvable.")

    taux = services.get_taux_jour(db, date.today(), payload.devise)
    if payload.devise != "USD" and taux is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Taux {payload.devise}/USD manquant.")
    montant_usd = float(money.to_usd(payload.devise, payload.montant, taux))

    societe = db.get(models.Societe, payload.societe_id)
    t = models.Transfert(
        numero=services.next_numero(db, "transfert", date.today().year, societe.code, societe.id),
        societe_id=payload.societe_id, source_type=payload.source_type, source_id=payload.source_id,
        dest_type=payload.dest_type, dest_id=payload.dest_id, devise=payload.devise, taux_jour=taux,
        montant=payload.montant, montant_usd=montant_usd, motif=payload.motif, statut="a_valider",
        initie_par=user.id)
    db.add(t)
    db.flush()

    # Sortie côté source si c'est une caisse (les fonds quittent physiquement la source)
    if payload.source_type == "caisse":
        sess = _session(db, payload.source_id)
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT, "La caisse source doit avoir une session ouverte.")
        if _solde(db, sess, payload.devise) < float(payload.montant):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Solde source insuffisant en {payload.devise}.")
        mvt = models.MouvementCaisse(
            caisse_id=payload.source_id, session_id=sess.id, sens="sortie",
            numero=services.next_numero(db, "bon_caisse", date.today().year, societe.code, societe.id),
            reference=t.numero, nature="Transfert émis", devise=payload.devise, taux_jour=taux,
            montant=payload.montant, montant_usd=montant_usd, tiers_nom=dst_lbl,
            reference_type="transfert", reference_id=t.id,
            libelle=f"Transfert {t.numero} → {dst_lbl}", created_by=user.id)
        db.add(mvt)
        db.flush()
        t.source_mouvement_id = mvt.id
    services.enregistrer_audit(db, user.id, "TRANSFERT_CREE", "transfert", t.id, None,
                               {"de": src_lbl, "vers": dst_lbl, "montant": payload.montant})
    db.commit()
    return {"id": str(t.id), "numero": t.numero, "statut": t.statut,
            "mouvement_id": str(t.source_mouvement_id) if t.source_mouvement_id else None}


def _peut_valider(roles: set, dest_type: str) -> bool:
    if dest_type == "caisse":
        return bool(roles & {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "DFI"})
    return bool(roles & {"COMPTABLE", "DFI"})


@router.get("")
def lister(societe_id: uuid.UUID, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    rows = db.execute(select(models.Transfert).where(models.Transfert.societe_id == societe_id)
                      .order_by(models.Transfert.created_at.desc())).scalars().all()
    out = []
    for t in rows:
        _, src_lbl, _ = _endpoint(db, t.source_type, t.source_id)
        _, dst_lbl, _ = _endpoint(db, t.dest_type, t.dest_id)
        init = db.get(models.Utilisateur, t.initie_par)
        out.append({
            "id": str(t.id), "numero": t.numero, "source": src_lbl, "dest": dst_lbl,
            "source_type": t.source_type, "dest_type": t.dest_type,
            "devise": t.devise, "montant": float(t.montant), "montant_usd": float(t.montant_usd),
            "motif": t.motif, "statut": t.statut, "initiateur": init.nom if init else None,
            "peut_valider": t.statut == "a_valider" and _peut_valider(roles, t.dest_type),
        })
    return out


class ValiderIn(BaseModel):
    montant_recu: float | None = None    # montant réellement reçu (devise du transfert) — écart si ≠ émis


@router.post("/{transfert_id}/valider")
def valider(transfert_id: uuid.UUID, payload: ValiderIn | None = None, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    payload = payload or ValiderIn()
    t = db.get(models.Transfert, transfert_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfert introuvable.")
    roles = assert_acces_societe(db, user, t.societe_id)
    assert_role(roles, ROLES)
    if t.statut != "a_valider":
        raise HTTPException(status.HTTP_409_CONFLICT, "Transfert déjà traité.")
    if not _peut_valider(roles, t.dest_type):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Non autorisé à valider la destination.")

    _, src_lbl, compte_src = _endpoint(db, t.source_type, t.source_id)
    _, dst_lbl, compte_dst = _endpoint(db, t.dest_type, t.dest_id)

    # Montant réellement reçu (pour constater un éventuel écart à la cession)
    recu = float(payload.montant_recu) if payload.montant_recu is not None else float(t.montant)
    if recu < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Montant reçu invalide.")
    recu_usd = float(money.to_usd(t.devise, recu, t.taux_jour))

    # Entrée effective côté destination si c'est une caisse (au montant réellement reçu)
    if t.dest_type == "caisse":
        sess = _session(db, t.dest_id)
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ouvrez d'abord la caisse destination.")
        societe = db.get(models.Societe, t.societe_id)
        ecart_note = "" if abs(recu - float(t.montant)) < 1e-9 else f" (reçu {recu} / émis {t.montant})"
        mvt = models.MouvementCaisse(
            caisse_id=t.dest_id, session_id=sess.id, sens="entree", nature="Transfert reçu",
            numero=services.next_numero(db, "bon_caisse", date.today().year, societe.code, societe.id),
            reference=t.numero, devise=t.devise, taux_jour=t.taux_jour,
            montant=recu, montant_usd=recu_usd,
            tiers_nom=src_lbl, reference_type="transfert", reference_id=t.id,
            libelle=f"Transfert {t.numero} ← {src_lbl}{ecart_note}", created_by=user.id)
        db.add(mvt)
        db.flush()
        t.dest_mouvement_id = mvt.id

    # Pièce comptable en attente : D destination / C source (+ écart 658/758 si reçu ≠ émis)
    ecr = comptabilite.comptabiliser_transfert(db, t, compte_dst, compte_src, f"{src_lbl} → {dst_lbl}",
                                               user.id, montant_recu_usd=recu_usd)
    t.statut = "valide"
    t.valide_par = user.id
    t.valide_at = datetime.now(timezone.utc)
    services.enregistrer_audit(db, user.id, "TRANSFERT_VALIDE", "transfert", t.id, None,
                               {"ecriture": ecr.numero, "recu": recu, "emis": float(t.montant)})
    db.commit()
    return {"id": str(t.id), "statut": "valide", "ecriture": ecr.numero,
            "ecart_usd": round(float(t.montant_usd) - recu_usd, 2),
            "mouvement_id": str(t.dest_mouvement_id) if t.dest_mouvement_id else None}


class RejetIn(BaseModel):
    motif: str


@router.post("/{transfert_id}/rejeter")
def rejeter(transfert_id: uuid.UUID, payload: RejetIn, db: Session = Depends(get_db),
            user: models.Utilisateur = Depends(get_current_user)):
    t = db.get(models.Transfert, transfert_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfert introuvable.")
    roles = assert_acces_societe(db, user, t.societe_id)
    assert_role(roles, ROLES)
    if t.statut != "a_valider":
        raise HTTPException(status.HTTP_409_CONFLICT, "Transfert déjà traité.")
    if not _peut_valider(roles, t.dest_type):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Non autorisé.")

    # Retour des fonds côté source (si la sortie avait été enregistrée en caisse)
    if t.source_type == "caisse" and t.source_mouvement_id:
        sess = _session(db, t.source_id)
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT, "Caisse source fermée : réouvrez-la pour le retour des fonds.")
        societe = db.get(models.Societe, t.societe_id)
        db.add(models.MouvementCaisse(
            caisse_id=t.source_id, session_id=sess.id, sens="entree",
            numero=services.next_numero(db, "bon_caisse", date.today().year, societe.code, societe.id),
            reference=t.numero, nature="Transfert rejeté — retour", devise=t.devise, taux_jour=t.taux_jour,
            montant=t.montant, montant_usd=t.montant_usd, reference_type="transfert", reference_id=t.id,
            libelle=f"Retour transfert {t.numero} (rejeté)", created_by=user.id))
    t.statut = "rejete"
    t.motif_rejet = payload.motif
    t.valide_par = user.id
    t.valide_at = datetime.now(timezone.utc)
    services.enregistrer_audit(db, user.id, "TRANSFERT_REJETE", "transfert", t.id, None,
                               {"motif": payload.motif})
    db.commit()
    return {"id": str(t.id), "statut": "rejete"}
