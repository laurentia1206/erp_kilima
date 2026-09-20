"""Taux de change journalier — fixé par le DFI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import TauxChange, Utilisateur, UtilisateurSociete, Role
from ..schemas import TauxIn
from ..services import enregistrer_audit

router = APIRouter(prefix="/api/taux", tags=["taux de change"])


def _est_dfi(db: Session, user: Utilisateur) -> bool:
    code = db.execute(
        select(Role.code).join(UtilisateurSociete, UtilisateurSociete.role_id == Role.id)
        .where(UtilisateurSociete.utilisateur_id == user.id, Role.code.in_(["DFI", "PRESIDENT"]))
    ).first()
    return code is not None


@router.post("", status_code=status.HTTP_201_CREATED)
def definir_taux(payload: TauxIn, db: Session = Depends(get_db),
                 user: Utilisateur = Depends(get_current_user)):
    if not _est_dfi(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seul le DFI peut définir le taux du jour.")
    existant = db.execute(
        select(TauxChange).where(TauxChange.date_taux == payload.date_taux,
                                 TauxChange.devise == payload.devise)
    ).scalar_one_or_none()
    if existant:
        ancienne = float(existant.taux_usd)
        existant.taux_usd = payload.taux_usd
        existant.defini_par = user.id
        enregistrer_audit(db, user.id, "UPDATE", "taux_change", existant.id,
                          {"taux_usd": ancienne}, {"taux_usd": float(payload.taux_usd)})
        db.commit()
        return {"message": "Taux mis à jour", "id": str(existant.id)}
    t = TauxChange(date_taux=payload.date_taux, devise=payload.devise,
                   taux_usd=payload.taux_usd, defini_par=user.id)
    db.add(t)
    db.flush()
    enregistrer_audit(db, user.id, "INSERT", "taux_change", t.id, None,
                      {"taux_usd": float(payload.taux_usd)})
    db.commit()
    return {"message": "Taux défini", "id": str(t.id)}
