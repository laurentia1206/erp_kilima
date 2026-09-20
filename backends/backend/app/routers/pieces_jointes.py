"""Pièces jointes : téléversement, liste et téléchargement des justificatifs."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, services
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/pieces-jointes", tags=["pièces jointes"])

UPLOADS = Path(__file__).resolve().parents[2] / "uploads"
UPLOADS.mkdir(exist_ok=True)
MAX_OCTETS = 10 * 1024 * 1024  # 10 Mo


def _safe(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", nom)[:120] or "fichier"


@router.post("", status_code=status.HTTP_201_CREATED)
async def televerser(document_type: str = Form(...), document_id: uuid.UUID = Form(...),
                     file: UploadFile = File(...), db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    data = await file.read()
    if len(data) > MAX_OCTETS:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fichier trop volumineux (max 10 Mo).")
    nom = _safe(file.filename or "fichier")
    stockage = f"{uuid.uuid4().hex}_{nom}"
    (UPLOADS / stockage).write_bytes(data)
    pj = models.PieceJointe(document_type=document_type, document_id=document_id,
                            nom_fichier=nom, chemin_stockage=stockage,
                            mime_type=file.content_type, taille_octets=len(data),
                            uploaded_by=user.id)
    db.add(pj)
    db.flush()
    services.enregistrer_audit(db, user.id, "UPLOAD", document_type, document_id, None,
                               {"piece": nom})
    db.commit()
    return {"id": str(pj.id), "nom_fichier": nom, "taille_octets": len(data)}


@router.get("")
def lister(document_type: str, document_id: uuid.UUID, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    rows = db.execute(
        select(models.PieceJointe).where(models.PieceJointe.document_type == document_type,
                                         models.PieceJointe.document_id == document_id)
        .order_by(models.PieceJointe.uploaded_at)
    ).scalars().all()
    return [{"id": str(p.id), "nom_fichier": p.nom_fichier, "mime_type": p.mime_type,
             "taille_octets": p.taille_octets} for p in rows]


@router.get("/{piece_id}/download")
def telecharger(piece_id: uuid.UUID, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    pj = db.get(models.PieceJointe, piece_id)
    if not pj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce introuvable.")
    chemin = UPLOADS / pj.chemin_stockage
    if not chemin.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier absent du stockage.")
    return FileResponse(str(chemin), filename=pj.nom_fichier,
                        media_type=pj.mime_type or "application/octet-stream")
