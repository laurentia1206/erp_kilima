"""G01 — Réquisitions : création, soumission, validation de la demande."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, services
from ..database import get_db
from ..deps import assert_acces_societe, get_current_user
from ..domain import money
from ..domain.workflow import est_pleinement_approuve, resolve_palier
from ..schemas import DecisionIn, RequisitionIn, RequisitionOut

router = APIRouter(prefix="/api/requisitions", tags=["réquisitions"])


@router.post("", response_model=RequisitionOut, status_code=status.HTTP_201_CREATED)
def creer_requisition(payload: RequisitionIn, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, payload.societe_id)
    societe = db.get(models.Societe, payload.societe_id)
    if not societe:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Société introuvable.")

    jour = date.today()
    taux = services.get_taux_jour(db, jour, payload.devise)
    if payload.devise != "USD" and taux is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Aucun taux {payload.devise}/USD défini pour le {jour}. Le DFI doit le saisir.")

    numero = services.next_numero(db, "requisition", jour.year, societe.code, societe.id)
    req = models.Requisition(
        numero=numero, societe_id=societe.id, site_id=payload.site_id,
        initiateur_id=user.id, objet=payload.objet, justification=payload.justification,
        mode_decaissement=payload.mode_decaissement, nature=payload.nature,
        priorite=payload.priorite, devise=payload.devise, taux_jour=taux, statut="soumise",
    )
    total = money._d(0)
    total_usd = money._d(0)
    for i, l in enumerate(payload.lignes):
        montant = money.quantize(money._d(l.quantite) * money._d(l.prix_unitaire))
        montant_usd = money.to_usd(payload.devise, montant, taux)
        total += montant
        total_usd += montant_usd
        req.lignes.append(models.RequisitionLigne(
            ordre=i, compte_impute=l.compte_impute, code_article=l.code_article,
            description=l.description, unite=l.unite, quantite=l.quantite,
            prix_unitaire=l.prix_unitaire, montant=montant, devise=payload.devise,
            montant_usd=montant_usd,
        ))
    req.montant_total = money.quantize(total)
    req.montant_total_usd = money.quantize(total_usd)
    db.add(req)
    db.flush()
    services.enregistrer_audit(db, user.id, "INSERT", "requisition", req.id, None,
                               {"numero": numero, "montant_usd": float(req.montant_total_usd)})
    db.commit()
    db.refresh(req)
    return req


def _progression(db: Session, req: models.Requisition) -> dict:
    """Détail de l'avancement de la validation de la demande (niveau par niveau)."""
    palier = services.palier_pour_montant(db, "requisition", "demande", req.societe_id, req.montant_total_usd)
    roles = [a.role_code for a in palier.approbateurs] if palier else []
    decisions = services.decisions_par_role(db, "requisition", req.id, "demande")
    etapes = [{"role": rc, "decision": decisions.get(rc, "en_attente")} for rc in roles]
    valides = sum(1 for e in etapes if e["decision"] == "valide")
    if req.statut == "rejetee":
        label = "Rejetée"
    elif req.statut == "en_attente_info":
        label = "Précisions demandées à l'initiateur"
    elif req.statut == "demande_validee":
        label = "Demande validée — prête pour ordre de dépense"
    elif req.statut in ("transformee", "cloturee"):
        label = req.statut.capitalize()
    elif roles:
        label = f"Validation demande : {valides}/{len(roles)} — " + \
                " · ".join(f"{e['role']} {'OK' if e['decision']=='valide' else ('NON' if e['decision']=='rejete' else 'en attente')}" for e in etapes)
    else:
        label = req.statut
    return {"label": label, "niveau_valides": valides, "niveau_total": len(roles), "etapes": etapes}


@router.get("")
def lister(societe_id: uuid.UUID, statut: str | None = None,
           db: Session = Depends(get_db), user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    q = select(models.Requisition).where(models.Requisition.societe_id == societe_id)
    if statut:
        q = q.where(models.Requisition.statut == statut)
    out = []
    for r in db.execute(q.order_by(models.Requisition.created_at.desc())).scalars().all():
        nb_comm = db.execute(
            select(func.count()).select_from(models.RequisitionCommentaire)
            .where(models.RequisitionCommentaire.requisition_id == r.id)).scalar_one()
        out.append({
            "id": str(r.id), "numero": r.numero, "objet": r.objet, "priorite": r.priorite,
            "devise": r.devise, "montant_total_usd": float(r.montant_total_usd),
            "statut": r.statut, "initiateur_id": str(r.initiateur_id),
            "mode_decaissement": r.mode_decaissement,
            "est_initiateur": r.initiateur_id == user.id,
            "progression": _progression(db, r), "nb_commentaires": nb_comm,
        })
    return out


@router.get("/{requisition_id}/detail")
def detail(requisition_id: uuid.UUID, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    r = db.get(models.Requisition, requisition_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    assert_acces_societe(db, user, r.societe_id)
    initiateur = db.get(models.Utilisateur, r.initiateur_id)
    lignes = db.execute(
        select(models.RequisitionLigne).where(models.RequisitionLigne.requisition_id == r.id)
        .order_by(models.RequisitionLigne.ordre)
    ).scalars().all()
    nb_pj = db.execute(
        select(func.count()).select_from(models.PieceJointe)
        .where(models.PieceJointe.document_type == "requisition",
               models.PieceJointe.document_id == r.id)).scalar_one()
    return {
        "id": str(r.id), "numero": r.numero, "objet": r.objet, "justification": r.justification,
        "priorite": r.priorite, "devise": r.devise, "mode_decaissement": r.mode_decaissement,
        "montant_total": float(r.montant_total), "montant_total_usd": float(r.montant_total_usd),
        "statut": r.statut, "initiateur": initiateur.nom if initiateur else None,
        "date": r.date_requisition.isoformat() if r.date_requisition else None,
        "progression": _progression(db, r), "nb_pieces_jointes": nb_pj,
        "lignes": [{"description": l.description, "code_article": l.code_article,
                    "unite": l.unite, "quantite": float(l.quantite),
                    "prix_unitaire": float(l.prix_unitaire), "montant": float(l.montant),
                    "compte_impute": l.compte_impute} for l in lignes],
    }


@router.get("/{requisition_id}/commentaires")
def commentaires(requisition_id: uuid.UUID, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    req = db.get(models.Requisition, requisition_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    assert_acces_societe(db, user, req.societe_id)
    rows = db.execute(
        select(models.RequisitionCommentaire, models.Utilisateur.nom)
        .join(models.Utilisateur, models.Utilisateur.id == models.RequisitionCommentaire.auteur_id)
        .where(models.RequisitionCommentaire.requisition_id == requisition_id)
        .order_by(models.RequisitionCommentaire.created_at)
    ).all()
    return [{"auteur": nom, "type": c.type, "message": c.message,
             "created_at": c.created_at.isoformat() if c.created_at else None} for c, nom in rows]


@router.post("/{requisition_id}/demander-precisions", response_model=RequisitionOut)
def demander_precisions(requisition_id: uuid.UUID, decision: DecisionIn,
                        db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    """Un validateur renvoie la réquisition à l'initiateur pour précisions (sans la rejeter)."""
    req = db.get(models.Requisition, requisition_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    roles = assert_acces_societe(db, user, req.societe_id)
    if req.statut not in ("soumise", "en_attente_info"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Réquisition non éligible.")
    palier = services.palier_pour_montant(db, "requisition", "demande", req.societe_id, req.montant_total_usd)
    roles_requis = {a.role_code for a in palier.approbateurs} if palier else set()
    if not (roles & roles_requis):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Vous n'êtes pas validateur de cette demande.")
    if not decision.commentaire:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Précisez ce qui est demandé (commentaire requis).")
    req.statut = "en_attente_info"
    db.add(models.RequisitionCommentaire(requisition_id=req.id, auteur_id=user.id,
                                         type="precision_demandee", message=decision.commentaire))
    services.enregistrer_audit(db, user.id, "DEMANDE_PRECISIONS", "requisition", req.id, None,
                               {"commentaire": decision.commentaire})
    db.commit()
    db.refresh(req)
    return req


@router.post("/{requisition_id}/repondre", response_model=RequisitionOut)
def repondre(requisition_id: uuid.UUID, decision: DecisionIn,
             db: Session = Depends(get_db), user: models.Utilisateur = Depends(get_current_user)):
    """L'initiateur répond aux précisions et resoumet la réquisition."""
    req = db.get(models.Requisition, requisition_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    assert_acces_societe(db, user, req.societe_id)
    if req.initiateur_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seul l'initiateur peut répondre.")
    if req.statut != "en_attente_info":
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucune demande de précisions en cours.")
    if not decision.commentaire:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Réponse requise.")
    db.add(models.RequisitionCommentaire(requisition_id=req.id, auteur_id=user.id,
                                         type="reponse", message=decision.commentaire))
    req.statut = "soumise"   # re-soumise aux validateurs
    services.enregistrer_audit(db, user.id, "REPONSE_PRECISIONS", "requisition", req.id, None,
                               {"commentaire": decision.commentaire})
    db.commit()
    db.refresh(req)
    return req


@router.post("/{requisition_id}/valider-demande", response_model=RequisitionOut)
def valider_demande(requisition_id: uuid.UUID, decision: DecisionIn,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    req = db.get(models.Requisition, requisition_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    roles = assert_acces_societe(db, user, req.societe_id)
    if req.statut not in ("soumise", "en_attente_info"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"La demande n'est pas en attente de validation (statut={req.statut}).")
    if user.id == req.initiateur_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Interdiction de valider sa propre demande (séparation des tâches).")

    palier = services.palier_pour_montant(db, "requisition", "demande", req.societe_id, req.montant_total_usd)
    if not palier:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Aucune règle de validation configurée.")
    roles_requis = {a.role_code for a in palier.approbateurs}

    role_agissant = roles & roles_requis
    if not role_agissant:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Votre rôle ne fait pas partie des validateurs requis {sorted(roles_requis)}.")

    # Enregistre/maj la décision pour CE rôle
    for rc in role_agissant:
        existante = db.execute(
            select(models.Validation).where(
                models.Validation.document_type == "requisition",
                models.Validation.document_id == req.id,
                models.Validation.etape == "demande",
                models.Validation.role_attendu_id == _role_id(db, rc),
            )
        ).scalar_one_or_none()
        if existante is None:
            existante = models.Validation(
                document_type="requisition", document_id=req.id, etape="demande",
                role_attendu_id=_role_id(db, rc))
            db.add(existante)
        existante.utilisateur_id = user.id
        existante.decision = decision.decision
        existante.commentaire = decision.commentaire
        existante.canal = decision.canal

    db.flush()

    # Recalcule l'état d'approbation
    decisions = _decisions_par_role(db, "requisition", req.id, "demande")
    if any(d == "rejete" for d in decisions.values()):
        req.statut = "rejetee"
    elif est_pleinement_approuve(palier, decisions):
        req.statut = "demande_validee"

    services.enregistrer_audit(db, user.id, "VALIDATE", "requisition", req.id, None,
                               {"decision": decision.decision, "statut": req.statut})
    db.commit()
    db.refresh(req)
    return req


def _role_id(db: Session, code: str) -> uuid.UUID:
    return db.execute(select(models.Role.id).where(models.Role.code == code)).scalar_one()


def _decisions_par_role(db: Session, doc_type: str, doc_id: uuid.UUID, etape: str) -> dict[str, str]:
    rows = db.execute(
        select(models.Role.code, models.Validation.decision)
        .join(models.Role, models.Role.id == models.Validation.role_attendu_id)
        .where(models.Validation.document_type == doc_type,
               models.Validation.document_id == doc_id,
               models.Validation.etape == etape)
    ).all()
    return {code: decision for code, decision in rows}
