"""Gestion de caisse — sessions et mouvements (avec billetage optionnel).

Étape 1 du MVP caisse : ouverture d'une session (fond initial), saisie des
mouvements entrée/sortie via une boîte de dialogue avec billetage facultatif,
soldes théoriques par devise en temps réel.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import comptabilite, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user
from ..domain import money

router = APIRouter(prefix="/api/caisse", tags=["caisse"])
ROLES_CAISSE = {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "DFI"}


def _caisse_ou_404(db: Session, caisse_id: uuid.UUID, user) -> tuple[models.Caisse, set]:
    caisse = db.get(models.Caisse, caisse_id)
    if not caisse:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Caisse introuvable.")
    roles = assert_acces_societe(db, user, caisse.societe_id)
    assert_role(roles, ROLES_CAISSE)
    return caisse, roles


def _session_ouverte(db: Session, caisse_id: uuid.UUID) -> models.SessionCaisse | None:
    return db.execute(
        select(models.SessionCaisse).where(
            models.SessionCaisse.caisse_id == caisse_id,
            models.SessionCaisse.statut == "ouverte")
    ).scalars().first()


def _soldes(db: Session, sess: models.SessionCaisse) -> dict:
    """Solde théorique par devise = fond initial + entrées − sorties (dans la session)."""
    soldes = {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)}
    rows = db.execute(
        select(models.MouvementCaisse.devise, models.MouvementCaisse.sens,
               func.coalesce(func.sum(models.MouvementCaisse.montant), 0))
        .where(models.MouvementCaisse.session_id == sess.id)
        .group_by(models.MouvementCaisse.devise, models.MouvementCaisse.sens)
    ).all()
    for devise, sens, total in rows:
        soldes.setdefault(devise, 0.0)
        soldes[devise] += float(total) if sens == "entree" else -float(total)
    return {k: round(v, 2) for k, v in soldes.items()}


# ── Ouverture de session ─────────────────────────────────────────────
class OuvertureIn(BaseModel):
    fond_initial_usd: float = 0
    fond_initial_cdf: float = 0


@router.post("/{caisse_id}/ouvrir", status_code=status.HTTP_201_CREATED)
def ouvrir(caisse_id: uuid.UUID, payload: OuvertureIn, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    if _session_ouverte(db, caisse_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Une session de caisse est déjà ouverte.")
    sess = models.SessionCaisse(
        caisse_id=caisse_id, ouvert_par=user.id,
        fond_initial_usd=payload.fond_initial_usd, fond_initial_cdf=payload.fond_initial_cdf,
        statut="ouverte")
    db.add(sess)
    db.flush()
    services.enregistrer_audit(db, user.id, "OUVERTURE_CAISSE", "session_caisse", sess.id, None,
                               {"fond_usd": payload.fond_initial_usd, "fond_cdf": payload.fond_initial_cdf})
    db.commit()
    return {"id": str(sess.id), "statut": "ouverte"}


@router.get("/{caisse_id}/session")
def session_courante(caisse_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    sess = _session_ouverte(db, caisse_id)
    if not sess:
        return {"ouverte": False, "caisse": caisse.libelle}
    return {
        "ouverte": True, "session_id": str(sess.id), "caisse": caisse.libelle,
        "date_ouverture": sess.date_ouverture.isoformat() if sess.date_ouverture else None,
        "fond_initial_usd": float(sess.fond_initial_usd),
        "fond_initial_cdf": float(sess.fond_initial_cdf),
        "soldes": _soldes(db, sess),
    }


# ── Mouvement (entrée / sortie) avec billetage optionnel ─────────────
class MouvementIn(BaseModel):
    sens: str = Field(pattern="^(entree|sortie)$")
    nature: str
    devise: str = "USD"
    montant: float = Field(gt=0)
    libelle: str | None = None
    beneficiaire: str | None = None   # bénéficiaire (sortie) / provenance (entrée)
    billetage: dict | None = None     # {"100":2,"50":1,...} — facultatif


@router.post("/{caisse_id}/mouvement", status_code=status.HTTP_201_CREATED)
def mouvement(caisse_id: uuid.UUID, payload: MouvementIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    sess = _session_ouverte(db, caisse_id)
    if not sess:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucune session ouverte. Ouvrez d'abord la caisse.")

    jour = date.today()
    taux = services.get_taux_jour(db, jour, payload.devise)
    if payload.devise != "USD" and taux is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Aucun taux {payload.devise}/USD défini pour le {jour}.")
    montant_usd = money.to_usd(payload.devise, payload.montant, taux)

    # Contrôle du billetage s'il est fourni : la somme doit égaler le montant
    if payload.billetage:
        total_bill = sum(float(coupure) * float(nb) for coupure, nb in payload.billetage.items() if nb)
        if abs(total_bill - float(payload.montant)) > 0.01:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Le billetage ({total_bill}) ne correspond pas au montant ({payload.montant}).")

    # Sortie : ne pas descendre sous zéro dans la devise
    soldes = _soldes(db, sess)
    if payload.sens == "sortie" and soldes.get(payload.devise, 0) < float(payload.montant):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Solde caisse insuffisant en {payload.devise} (disponible {soldes.get(payload.devise, 0)}).")

    mvt = models.MouvementCaisse(
        caisse_id=caisse_id, session_id=sess.id, sens=payload.sens, nature=payload.nature,
        devise=payload.devise, taux_jour=taux, montant=payload.montant, montant_usd=montant_usd,
        libelle=payload.libelle, tiers_nom=payload.beneficiaire or None,
        billetage=payload.billetage or None, created_by=user.id)
    db.add(mvt)
    db.flush()
    services.enregistrer_audit(db, user.id, "MOUVEMENT_CAISSE", "mouvement_caisse", mvt.id, None,
                               {"sens": payload.sens, "devise": payload.devise, "montant": payload.montant})
    db.commit()
    return {"id": str(mvt.id), "soldes": _soldes(db, sess)}


class LegIn(BaseModel):
    devise: str
    montant: float = Field(gt=0)
    billetage: dict | None = None


class OperationIn(BaseModel):
    sens: str = Field(pattern="^(entree|sortie)$")
    nature: str
    beneficiaire: str | None = None
    reference: str | None = None   # réf. réquisition (libre, même hors circuit)
    libelle: str | None = None
    legs: list[LegIn]   # 1 ou 2 volets (ex. une sortie partie USD + partie CDF)


@router.post("/{caisse_id}/operation", status_code=status.HTTP_201_CREATED)
def operation(caisse_id: uuid.UUID, payload: OperationIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    """Opération de caisse pouvant mélanger plusieurs devises (USD + CDF) — atomique."""
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    sess = _session_ouverte(db, caisse_id)
    if not sess:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucune session ouverte.")
    if not payload.legs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins un volet de devise requis.")

    jour = date.today()
    prepared = []
    besoin = {}   # sorties par devise, pour le contrôle de solde
    for leg in payload.legs:
        taux = services.get_taux_jour(db, jour, leg.devise)
        if leg.devise != "USD" and taux is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Aucun taux {leg.devise}/USD pour le {jour}.")
        if leg.billetage:
            total_bill = sum(float(c) * float(n) for c, n in leg.billetage.items() if n)
            if abs(total_bill - float(leg.montant)) > 0.01:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Billetage {leg.devise} ({total_bill}) ≠ montant ({leg.montant}).")
        prepared.append((leg, taux, money.to_usd(leg.devise, leg.montant, taux)))
        if payload.sens == "sortie":
            besoin[leg.devise] = besoin.get(leg.devise, 0) + float(leg.montant)

    soldes = _soldes(db, sess)
    for devise, montant in besoin.items():
        if soldes.get(devise, 0) < montant:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Solde caisse insuffisant en {devise} (disponible {soldes.get(devise, 0)}, requis {montant}).")

    societe = db.get(models.Societe, caisse.societe_id)
    numero = services.next_numero(db, "bon_caisse", date.today().year, societe.code, caisse.societe_id)
    premier_id = None
    total_usd = 0.0
    for leg, taux, montant_usd in prepared:
        mvt = models.MouvementCaisse(
            caisse_id=caisse_id, session_id=sess.id, sens=payload.sens, nature=payload.nature,
            numero=numero, reference=payload.reference or None,
            devise=leg.devise, taux_jour=taux, montant=leg.montant, montant_usd=montant_usd,
            libelle=payload.libelle, tiers_nom=payload.beneficiaire or None,
            billetage=leg.billetage or None, created_by=user.id)
        db.add(mvt)
        db.flush()
        premier_id = premier_id or mvt.id
        total_usd += float(montant_usd)

    # Pièce comptable en attente (le comptable reclassera la contrepartie 471)
    # Libellé explicite : « Caisse centrale · Encaissement vente · Client X · réf REQ-… »
    parts = [caisse.libelle, payload.nature or ("Encaissement" if payload.sens == "entree" else "Sortie de caisse")]
    if payload.beneficiaire:
        parts.append(payload.beneficiaire)
    if payload.libelle:
        parts.append(payload.libelle)
    if payload.reference:
        parts.append(f"réf {payload.reference}")
    lib = " · ".join(parts)
    ecr = comptabilite.comptabiliser_operation_caisse(
        db, societe, payload.sens, round(total_usd, 2), lib, premier_id, numero, user.id,
        nature=payload.nature)

    services.enregistrer_audit(db, user.id, "OPERATION_CAISSE", "session_caisse", sess.id, None,
                               {"sens": payload.sens, "volets": len(payload.legs), "numero": numero,
                                "ecriture": ecr.numero})
    db.commit()
    return {"soldes": _soldes(db, sess), "numero": numero, "mouvement_id": str(premier_id),
            "piece_comptable": ecr.numero}


@router.get("/{caisse_id}/journal")
def journal_session(caisse_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Journal de la session ouverte, avec solde courant PAR DEVISE après chaque opération."""
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    sess = _session_ouverte(db, caisse_id)
    if not sess:
        return {"ouverte": False, "caisse": caisse.libelle, "mouvements": [], "soldes": {"USD": 0, "CDF": 0}}
    mvts = db.execute(
        select(models.MouvementCaisse).where(models.MouvementCaisse.session_id == sess.id)
        .order_by(models.MouvementCaisse.heure)
    ).scalars().all()
    soldes = {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)}
    lignes = []
    for m in mvts:
        soldes.setdefault(m.devise, 0.0)
        soldes[m.devise] += float(m.montant) if m.sens == "entree" else -float(m.montant)
        lignes.append({
            "id": str(m.id), "heure": m.heure.isoformat() if m.heure else None,
            "sens": m.sens, "nature": m.nature, "libelle": m.libelle,
            "tiers": m.tiers_nom, "devise": m.devise, "montant": float(m.montant),
            "a_billetage": bool(m.billetage), "numero": m.numero, "reference": m.reference,
            "solde_apres": round(soldes[m.devise], 2),
        })
    return {"ouverte": True, "caisse": caisse.libelle,
            "fond_initial_usd": float(sess.fond_initial_usd),
            "fond_initial_cdf": float(sess.fond_initial_cdf),
            "soldes": {k: round(v, 2) for k, v in soldes.items()}, "mouvements": lignes}


# ── Clôture de caisse (comptage + écart théorique/physique + rapport Z) ──
class ClotureIn(BaseModel):
    physique_usd: float = 0
    physique_cdf: float = 0
    billetage_usd: dict | None = None
    billetage_cdf: dict | None = None
    commentaire: str | None = None


def _totaux_session(db: Session, sess: models.SessionCaisse) -> dict:
    """Totaux entrées/sorties par devise + nombre d'opérations (pour le rapport Z)."""
    rows = db.execute(
        select(models.MouvementCaisse.devise, models.MouvementCaisse.sens,
               func.coalesce(func.sum(models.MouvementCaisse.montant), 0),
               func.count(models.MouvementCaisse.id))
        .where(models.MouvementCaisse.session_id == sess.id)
        .group_by(models.MouvementCaisse.devise, models.MouvementCaisse.sens)
    ).all()
    t = {}
    for devise, sens, total, nb in rows:
        d = t.setdefault(devise, {"entrees": 0.0, "sorties": 0.0, "nb": 0})
        d["entrees" if sens == "entree" else "sorties"] += float(total)
        d["nb"] += int(nb)
    return {k: {"entrees": round(v["entrees"], 2), "sorties": round(v["sorties"], 2), "nb": v["nb"]}
            for k, v in t.items()}


def _rapport_z(db: Session, sess: models.SessionCaisse, caisse: models.Caisse) -> dict:
    societe = db.get(models.Societe, caisse.societe_id)
    ouvreur = db.get(models.Utilisateur, sess.ouvert_par)
    clotureur = db.get(models.Utilisateur, sess.cloture_par) if sess.cloture_par else None
    return {
        "societe": societe.nom, "caisse": caisse.libelle, "session_id": str(sess.id),
        "date_ouverture": sess.date_ouverture.isoformat() if sess.date_ouverture else None,
        "date_cloture": sess.date_cloture.isoformat() if sess.date_cloture else None,
        "ouvert_par": ouvreur.nom if ouvreur else None,
        "cloture_par": clotureur.nom if clotureur else None,
        "fond_initial": {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)},
        "totaux": _totaux_session(db, sess),
        "theorique": {"USD": float(sess.solde_theorique_usd or 0), "CDF": float(sess.solde_theorique_cdf or 0)},
        "physique": {"USD": float(sess.solde_physique_usd or 0), "CDF": float(sess.solde_physique_cdf or 0)},
        "ecart": {"USD": float(sess.ecart_usd or 0), "CDF": float(sess.ecart_cdf or 0)},
        "billetage": sess.billetage_cloture,
        "commentaire": sess.commentaire_cloture,
    }


@router.post("/{caisse_id}/cloturer")
def cloturer(caisse_id: uuid.UUID, payload: ClotureIn, db: Session = Depends(get_db),
             user: models.Utilisateur = Depends(get_current_user)):
    """Clôture de la session : comptage physique, calcul de l'écart, verrouillage, rapport Z."""
    caisse, _ = _caisse_ou_404(db, caisse_id, user)
    sess = _session_ouverte(db, caisse_id)
    if not sess:
        raise HTTPException(status.HTTP_409_CONFLICT, "Aucune session ouverte à clôturer.")

    theorique = _soldes(db, sess)
    th_usd, th_cdf = theorique.get("USD", 0.0), theorique.get("CDF", 0.0)

    # Contrôle du billetage physique s'il est fourni
    for devise, bill, phys in (("USD", payload.billetage_usd, payload.physique_usd),
                               ("CDF", payload.billetage_cdf, payload.physique_cdf)):
        if bill:
            total_bill = sum(float(c) * float(n) for c, n in bill.items() if n)
            if abs(total_bill - float(phys)) > 0.01:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Billetage {devise} ({total_bill}) ≠ physique déclaré ({phys}).")

    ecart_usd = round(float(payload.physique_usd) - th_usd, 2)
    ecart_cdf = round(float(payload.physique_cdf) - th_cdf, 2)

    # Un écart impose une justification écrite (traçabilité / responsabilité du caissier)
    if (abs(ecart_usd) > 0.01 or abs(ecart_cdf) > 0.01) and not (payload.commentaire or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Un écart de caisse a été constaté : une justification est obligatoire.")

    seuil = float(services.get_parametre(db, "caisse.ecart_max_usd", caisse.societe_id, "5") or 5)
    escalade = abs(ecart_usd) > seuil  # au-delà du seuil : à escalader au DFI

    sess.solde_theorique_usd, sess.solde_theorique_cdf = th_usd, th_cdf
    sess.solde_physique_usd, sess.solde_physique_cdf = payload.physique_usd, payload.physique_cdf
    sess.ecart_usd, sess.ecart_cdf = ecart_usd, ecart_cdf
    sess.billetage_cloture = {"USD": payload.billetage_usd, "CDF": payload.billetage_cdf}
    sess.commentaire_cloture = (payload.commentaire or "").strip() or None
    sess.statut = "cloturee"
    sess.date_cloture = func.now()
    sess.cloture_par = user.id
    db.flush()
    services.enregistrer_audit(db, user.id, "CLOTURE_CAISSE", "session_caisse", sess.id, None,
                               {"ecart_usd": ecart_usd, "ecart_cdf": ecart_cdf, "escalade": escalade})
    db.commit()
    db.refresh(sess)
    rapport = _rapport_z(db, sess, caisse)
    rapport["escalade_dfi"] = escalade
    rapport["seuil_ecart_usd"] = seuil
    return rapport


@router.get("/session/{session_id}/rapport-z")
def rapport_z(session_id: uuid.UUID, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    """Ré-impression du rapport Z d'une session clôturée."""
    sess = db.get(models.SessionCaisse, session_id)
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session introuvable.")
    caisse, _ = _caisse_ou_404(db, sess.caisse_id, user)
    rapport = _rapport_z(db, sess, caisse)
    rapport["statut"] = sess.statut
    return rapport


@router.get("/mouvement/{mvt_id}/bon")
def bon_mouvement(mvt_id: uuid.UUID, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Données du bon de caisse (imprimable) pour un mouvement, avec le lien vers la
    réquisition / l'ordre / le transfert d'origine s'il existe."""
    m = db.get(models.MouvementCaisse, mvt_id)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mouvement introuvable.")
    caisse, _ = _caisse_ou_404(db, m.caisse_id, user)
    societe = db.get(models.Societe, caisse.societe_id)
    legs = ([m] if not m.numero else db.execute(
        select(models.MouvementCaisse).where(
            models.MouvementCaisse.numero == m.numero,
            models.MouvementCaisse.caisse_id == m.caisse_id)).scalars().all())

    lien = None
    if m.reference_type == "bon_reception" and m.reference_id:
        brf = db.get(models.BonReception, m.reference_id)
        odp = db.get(models.OrdreDepense, brf.ordre_depense_id) if brf else None
        req = db.get(models.Requisition, odp.requisition_id) if odp else None
        lien = {"type": "decaissement", "ordre": odp.numero if odp else None,
                "requisition": req.numero if req else None, "objet": req.objet if req else None}
    elif m.reference_type == "transfert" and m.reference_id:
        t = db.get(models.Transfert, m.reference_id)
        lien = {"type": "transfert", "transfert": t.numero if t else None, "motif": t.motif if t else None}

    caissier = db.get(models.Utilisateur, m.created_by)
    return {
        "societe": societe.nom, "caisse": caisse.libelle, "numero": m.numero,
        "date": m.heure.isoformat() if m.heure else None, "sens": m.sens, "nature": m.nature,
        "tiers": m.tiers_nom, "reference": m.reference, "lien": lien,
        "caissier": caissier.nom if caissier else None,
        "legs": [{"devise": l.devise, "montant": float(l.montant), "billetage": l.billetage} for l in legs],
    }
