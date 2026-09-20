"""Endpoints de lecture pour alimenter les écrans du frontend."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import assert_acces_societe, get_current_user

router = APIRouter(prefix="/api", tags=["lecture"])


@router.get("/societes")
def mes_societes(db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    rows = db.execute(
        select(models.Societe.id, models.Societe.code, models.Societe.nom, models.Role.code)
        .join(models.UtilisateurSociete, models.UtilisateurSociete.societe_id == models.Societe.id)
        .join(models.Role, models.Role.id == models.UtilisateurSociete.role_id)
        .where(models.UtilisateurSociete.utilisateur_id == user.id)
    ).all()
    out: dict = {}
    for sid, code, nom, role in rows:
        e = out.setdefault(str(sid), {"id": str(sid), "code": code, "nom": nom, "roles": []})
        e["roles"].append(role)
    return list(out.values())


@router.get("/tiers")
def lister_tiers(societe_id: uuid.UUID, type: str | None = None,
                 db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    q = select(models.Tiers).where(
        (models.Tiers.societe_id == societe_id) | (models.Tiers.societe_id.is_(None)),
        models.Tiers.actif.is_(True))
    if type:
        q = q.where(models.Tiers.type == type)
    return [{"id": str(t.id), "code": t.code, "nom": t.nom, "type": t.type}
            for t in db.execute(q).scalars().all()]


@router.get("/caisses")
def lister_caisses(societe_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    """Caisses de la société avec l'état de session et les soldes en temps réel
    (vue d'ensemble type « tableau de bord des caisses »)."""
    from .caisse import _session_ouverte, _soldes   # évite l'import circulaire au chargement
    assert_acces_societe(db, user, societe_id)
    q = select(models.Caisse).where(models.Caisse.societe_id == societe_id,
                                    models.Caisse.actif.is_(True))
    out = []
    for c in db.execute(q).scalars().all():
        sess = _session_ouverte(db, c.id)
        out.append({"id": str(c.id), "libelle": c.libelle, "compte": c.compte_comptable,
                    "est_principale": bool(c.est_principale),
                    "session_ouverte": sess is not None,
                    "ouverte_depuis": sess.date_ouverture.isoformat() if sess and sess.date_ouverture else None,
                    "soldes": _soldes(db, sess) if sess else None})
    return out


@router.get("/comptes-bancaires")
def lister_banques(societe_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    q = select(models.CompteBancaire).where(models.CompteBancaire.societe_id == societe_id,
                                            models.CompteBancaire.actif.is_(True))
    return [{"id": str(b.id), "libelle": f"{b.banque} — {b.numero_compte or ''}".strip(" —"),
             "devise": b.devise} for b in db.execute(q).scalars().all()]


@router.get("/ordres-depense")
def lister_ordres(societe_id: uuid.UUID, statut: str | None = None,
                  db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    q = select(models.OrdreDepense).where(models.OrdreDepense.societe_id == societe_id)
    if statut:
        q = q.where(models.OrdreDepense.statut == statut)
    out = []
    for o in db.execute(q.order_by(models.OrdreDepense.created_at.desc())).scalars().all():
        benef = db.get(models.Tiers, o.beneficiaire_tiers_id)
        req = db.get(models.Requisition, o.requisition_id)
        paye = float(o.montant_paye_usd or 0)
        out.append({"id": str(o.id), "numero": o.numero, "devise": o.devise,
                    "requisition_numero": req.numero if req else None,
                    "requisition_objet": req.objet if req else None,
                    "montant_autorise_usd": float(o.montant_autorise_usd),
                    "montant_paye_usd": round(paye, 2),
                    "reste_usd": round(float(o.montant_autorise_usd) - paye, 2),
                    "palier_applique": o.palier_applique, "statut": o.statut,
                    "mode_paiement": o.mode_paiement, "mode_decaissement": o.mode_decaissement,
                    "motif": o.motif, "beneficiaire": benef.nom if benef else None,
                    "beneficiaire_tiers_id": str(o.beneficiaire_tiers_id)})
    return out


@router.get("/ordres-depense/{ordre_id}/bon-sortie")
def bon_sortie(ordre_id: uuid.UUID, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    """Données du bon de sortie de caisse (ou de l'OP/chèque banque) pour impression."""
    odp = db.get(models.OrdreDepense, ordre_id)
    if not odp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ordre introuvable.")
    assert_acces_societe(db, user, odp.societe_id)
    brf = db.execute(select(models.BonReception)
                     .where(models.BonReception.ordre_depense_id == odp.id)).scalars().first()
    if not brf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucun décaissement exécuté pour cet ordre.")
    societe = db.get(models.Societe, odp.societe_id)
    benef = db.get(models.Tiers, odp.beneficiaire_tiers_id)
    executant = db.get(models.Utilisateur, brf.caissier_id)
    moyen = None
    if brf.caisse_id:
        c = db.get(models.Caisse, brf.caisse_id)
        moyen = c.libelle if c else None
    elif brf.compte_bancaire_id:
        b = db.get(models.CompteBancaire, brf.compte_bancaire_id)
        moyen = f"{b.banque} {b.numero_compte or ''}".strip() if b else None
    req = db.get(models.Requisition, odp.requisition_id)
    return {
        "societe": societe.nom, "bon_numero": brf.numero,
        "date": brf.date_reception.isoformat() if brf.date_reception else None,
        "ordre_numero": odp.numero, "mode": brf.mode, "moyen": moyen,
        "requisition_numero": req.numero if req else None,
        "requisition_objet": req.objet if req else None,
        "reference_paiement": brf.reference_paiement,
        "beneficiaire": benef.nom if benef else None, "motif": odp.motif,
        "devise": odp.devise, "montant": float(odp.montant_autorise),
        "montant_usd": float(odp.montant_autorise_usd),
        "executant": executant.nom if executant else None,
    }


@router.get("/avances")
def lister_avances(societe_id: uuid.UUID, statut: str | None = None,
                   db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    q = select(models.Avance).where(models.Avance.societe_id == societe_id)
    if statut:
        q = q.where(models.Avance.statut == statut)
    out = []
    for a in db.execute(q.order_by(models.Avance.date_octroi.desc())).scalars().all():
        benef = db.get(models.Tiers, a.beneficiaire_tiers_id)
        ordre = db.get(models.OrdreDepense, a.ordre_depense_id)
        req = db.get(models.Requisition, ordre.requisition_id) if ordre and ordre.requisition_id else None
        out.append({"id": str(a.id), "numero": a.numero, "devise": a.devise,
                    "montant_avance_usd": float(a.montant_avance_usd), "statut": a.statut,
                    "type_avance": a.type_avance, "beneficiaire": benef.nom if benef else None,
                    "nature": req.nature if req else "charge", "objet": req.objet if req else None,
                    "echeance_justif": a.echeance_justif.isoformat() if a.echeance_justif else None})
    return out


@router.get("/caisse/journal")
def caisse_journal(societe_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)
    caisses = db.execute(select(models.Caisse).where(models.Caisse.societe_id == societe_id)).scalars().all()
    out_caisses = []
    for c in caisses:
        # Solde = entrées - sorties (USD)
        entrees = db.execute(select(func.coalesce(func.sum(models.MouvementCaisse.montant_usd), 0))
                             .where(models.MouvementCaisse.caisse_id == c.id,
                                    models.MouvementCaisse.sens == "entree")).scalar_one()
        sorties = db.execute(select(func.coalesce(func.sum(models.MouvementCaisse.montant_usd), 0))
                             .where(models.MouvementCaisse.caisse_id == c.id,
                                    models.MouvementCaisse.sens == "sortie")).scalar_one()
        out_caisses.append({"id": str(c.id), "libelle": c.libelle,
                            "solde_usd": round(float(entrees) - float(sorties), 2)})
    mvts = db.execute(
        select(models.MouvementCaisse, models.Caisse.libelle)
        .join(models.Caisse, models.Caisse.id == models.MouvementCaisse.caisse_id)
        .where(models.Caisse.societe_id == societe_id)
        .order_by(models.MouvementCaisse.heure.desc()).limit(100)
    ).all()
    mouvements = [{
        "caisse": lib, "date": m.date_mouvement.isoformat() if m.date_mouvement else None,
        "sens": m.sens, "nature": m.nature, "devise": m.devise,
        "montant": float(m.montant), "montant_usd": float(m.montant_usd),
        "libelle": m.libelle} for m, lib in mvts]
    return {"caisses": out_caisses, "mouvements": mouvements}


@router.get("/dashboard")
def dashboard(societe_id: uuid.UUID, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    assert_acces_societe(db, user, societe_id)

    def _count(model, *conds):
        return db.execute(select(func.count()).select_from(model)
                          .where(model.societe_id == societe_id, *conds)).scalar_one()

    req_soumises = _count(models.Requisition, models.Requisition.statut == "soumise")
    odp_a_valider = _count(models.OrdreDepense, models.OrdreDepense.statut == "a_valider")
    av_en_cours = _count(models.Avance, models.Avance.statut.in_(["a_justifier", "en_retard"]))
    av_retard = _count(models.Avance, models.Avance.statut == "en_retard")
    montant_avances = db.execute(
        select(func.coalesce(func.sum(models.Avance.montant_avance_usd), 0))
        .where(models.Avance.societe_id == societe_id,
               models.Avance.statut.in_(["a_justifier", "en_retard"]))
    ).scalar_one()
    blocages = db.execute(
        select(func.count()).select_from(models.BlocageBeneficiaire)
        .join(models.Tiers, models.Tiers.id == models.BlocageBeneficiaire.tiers_id)
        .where(models.Tiers.societe_id == societe_id, models.BlocageBeneficiaire.actif.is_(True))
    ).scalar_one()
    return {
        "requisitions_soumises": req_soumises,
        "ordres_a_valider": odp_a_valider,
        "avances_en_cours": av_en_cours,
        "avances_en_retard": av_retard,
        "avances_montant_usd": float(montant_avances),
        "beneficiaires_bloques": blocages,
    }
