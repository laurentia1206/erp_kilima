"""G02 — Ordre de dépense : création (palier), validation sortie de fonds, exécution."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import comptabilite, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user
from ..domain import avances as dom_avances
from ..domain.money import from_usd, to_usd
from ..domain.workflow import est_pleinement_approuve, resolve_palier
from ..schemas import DecisionIn, ExecutionIn, OrdreDepenseIn, OrdreDepenseOut

router = APIRouter(prefix="/api/ordres-depense", tags=["ordres de dépense"])


@router.post("", response_model=OrdreDepenseOut, status_code=status.HTTP_201_CREATED)
def creer_ordre(payload: OrdreDepenseIn, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    req = db.get(models.Requisition, payload.requisition_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réquisition introuvable.")
    roles = assert_acces_societe(db, user, req.societe_id)
    assert_role(roles, {"DFI"})   # seul le DFI initie l'ordre de dépense
    if req.statut != "demande_validee":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "La demande doit être validée avant d'émettre un ordre de dépense.")

    societe = db.get(models.Societe, req.societe_id)
    palier = services.palier_pour_montant(db, "ordre_depense", "sortie_fonds",
                                          req.societe_id, req.montant_total_usd)
    if not palier:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "Aucun palier de sortie de fonds configuré.")

    numero = services.next_numero(db, "ordre_depense", date.today().year, societe.code, societe.id)
    odp = models.OrdreDepense(
        numero=numero, requisition_id=req.id, societe_id=req.societe_id,
        beneficiaire_tiers_id=payload.beneficiaire_tiers_id, motif=payload.motif,
        mode_paiement=payload.mode_paiement, mode_decaissement=req.mode_decaissement,
        devise=req.devise, taux_jour=req.taux_jour,
        montant_autorise=req.montant_total, montant_autorise_usd=req.montant_total_usd,
        palier_applique=palier.libelle, statut="a_valider", created_by=user.id,
    )
    db.add(odp)
    db.flush()

    # L'ÉMISSION par le DFI VAUT sa validation Niveau 2 (sortie de fonds) — on évite ainsi
    # le cycle « émettre → re-valider ». On enregistre sa décision pour les rôles requis qu'il
    # détient ; l'ordre est validé d'office s'il suffit, sinon il attend les autres co-signataires.
    req.statut = "transformee"
    now = datetime.now(timezone.utc)
    roles_requis = {a.role_code for a in palier.approbateurs}
    for rc in (roles & roles_requis):
        db.add(models.Validation(
            document_type="ordre_depense", document_id=odp.id, etape="sortie_fonds",
            role_attendu_id=services.role_id_by_code(db, rc), utilisateur_id=user.id,
            decision="valide", canal="in_app", decided_at=now))
    db.flush()
    if est_pleinement_approuve(palier, services.decisions_par_role(db, "ordre_depense", odp.id, "sortie_fonds")):
        odp.statut = "valide"

    services.enregistrer_audit(db, user.id, "INSERT", "ordre_depense", odp.id, None,
                               {"numero": numero, "palier": palier.libelle, "statut": odp.statut})
    db.commit()
    db.refresh(odp)
    return odp


@router.post("/{ordre_id}/valider", response_model=OrdreDepenseOut)
def valider_sortie(ordre_id: uuid.UUID, decision: DecisionIn, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    odp = db.get(models.OrdreDepense, ordre_id)
    if not odp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ordre de dépense introuvable.")
    roles = assert_acces_societe(db, user, odp.societe_id)
    if odp.statut != "a_valider":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Statut non validable ({odp.statut}).")

    palier = services.palier_pour_montant(db, "ordre_depense", "sortie_fonds",
                                          odp.societe_id, odp.montant_autorise_usd)
    if not palier:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Aucun palier configuré.")
    roles_requis = {a.role_code for a in palier.approbateurs}
    role_agissant = roles & roles_requis
    if not role_agissant:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Votre rôle ne fait pas partie des validateurs requis {sorted(roles_requis)}.")

    for rc in role_agissant:
        rid = services.role_id_by_code(db, rc)
        existante = db.execute(
            select(models.Validation).where(
                models.Validation.document_type == "ordre_depense",
                models.Validation.document_id == odp.id,
                models.Validation.etape == "sortie_fonds",
                models.Validation.role_attendu_id == rid)
        ).scalar_one_or_none()
        if existante is None:
            existante = models.Validation(
                document_type="ordre_depense", document_id=odp.id, etape="sortie_fonds",
                role_attendu_id=rid)
            db.add(existante)
        existante.utilisateur_id = user.id
        existante.decision = decision.decision
        existante.commentaire = decision.commentaire
        existante.canal = decision.canal
    db.flush()

    decisions = services.decisions_par_role(db, "ordre_depense", odp.id, "sortie_fonds")
    if any(d == "rejete" for d in decisions.values()):
        odp.statut = "rejete"
    elif est_pleinement_approuve(palier, decisions):
        odp.statut = "valide"
    services.enregistrer_audit(db, user.id, "VALIDATE", "ordre_depense", odp.id, None,
                               {"decision": decision.decision, "statut": odp.statut})
    db.commit()
    db.refresh(odp)
    return odp


@router.post("/{ordre_id}/executer")
def executer(ordre_id: uuid.UUID, payload: ExecutionIn = ExecutionIn(),
             db: Session = Depends(get_db), user: models.Utilisateur = Depends(get_current_user)):
    """Exécute le décaissement. Caisse → le caissier (bon de sortie + pièce en attente).
    Banque → le comptable (OP/chèque + références) → écriture en attente au journal banque.
    Le bénéficiaire peut être remplacé au moment du paiement (payload.beneficiaire_tiers_id)."""
    odp = db.get(models.OrdreDepense, ordre_id)
    if not odp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ordre de dépense introuvable.")
    roles = assert_acces_societe(db, user, odp.societe_id)
    if odp.statut != "valide":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Décaissement refusé : l'ordre n'est pas validé selon le palier requis.")

    caisse_id = payload.caisse_id
    compte_bancaire_id = payload.compte_bancaire_id
    type_avance = payload.type_avance
    reference_paiement = payload.reference_paiement

    # Le caissier/comptable peut changer le bénéficiaire au moment du paiement (cf. #4)
    if payload.beneficiaire_tiers_id and payload.beneficiaire_tiers_id != odp.beneficiaire_tiers_id:
        nb = db.get(models.Tiers, payload.beneficiaire_tiers_id)
        if not nb:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bénéficiaire (remplacement) introuvable.")
        odp.beneficiaire_tiers_id = payload.beneficiaire_tiers_id

    # Décaissement partiel : on paie une partie (jamais plus que le reste validé) ; l'ordre
    # reste ouvert jusqu'à ce que le total autorisé soit atteint.
    reste_usd = float(odp.montant_autorise_usd) - float(odp.montant_paye_usd or 0)
    if reste_usd <= 0.01:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ordre déjà entièrement décaissé.")
    if odp.mode_decaissement == "paiement_direct" or payload.montant is None:
        montant_pay_usd = reste_usd
        montant_pay_dev = float(from_usd(odp.devise, reste_usd, odp.taux_jour))
    else:
        montant_pay_dev = float(payload.montant)
        montant_pay_usd = float(to_usd(odp.devise, montant_pay_dev, odp.taux_jour))
        if montant_pay_usd <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Montant à décaisser invalide.")
        if montant_pay_usd > reste_usd + 0.01:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Montant supérieur au reste à décaisser ({round(reste_usd, 2)} USD).")

    # Règle de blocage automatique
    blocage_actif = db.execute(
        select(models.BlocageBeneficiaire).where(
            models.BlocageBeneficiaire.tiers_id == odp.beneficiaire_tiers_id,
            models.BlocageBeneficiaire.actif.is_(True))
    ).first() is not None
    avances_benef = db.execute(
        select(models.Avance.statut, models.Avance.echeance_justif).where(
            models.Avance.beneficiaire_tiers_id == odp.beneficiaire_tiers_id)
    ).all()
    from datetime import datetime, timezone
    en_cours = [dom_avances.AvanceEnCours(statut=s, echeance_justif=e) for s, e in avances_benef]
    if dom_avances.beneficiaire_bloque(blocage_actif, en_cours, datetime.now(timezone.utc)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Bénéficiaire bloqué : avance non justifiée. Levée par le DFI requise.")

    # Résolution du moyen de paiement (caisse ou banque) selon le mode de l'ordre
    societe = db.get(models.Societe, odp.societe_id)
    caisse = banque = None
    if odp.mode_paiement == "banque":
        # Le décaissement par banque est exécuté par le COMPTABLE (établit l'OP / le chèque)
        assert_role(roles, {"COMPTABLE", "DFI"})
        if not compte_bancaire_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "compte_bancaire_id requis (paiement par banque).")
        banque = db.get(models.CompteBancaire, compte_bancaire_id)
        if not banque or banque.societe_id != odp.societe_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte bancaire introuvable.")
        compte_credit = banque.compte_comptable or "521"
        journal = ("BQ", "Banque", "banque")
    else:
        # Le décaissement par caisse est exécuté par le CAISSIER
        assert_role(roles, {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR"})
        if not caisse_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "caisse_id requis (paiement par caisse).")
        caisse = db.get(models.Caisse, caisse_id)
        if not caisse or caisse.societe_id != odp.societe_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Caisse introuvable.")
        # La caisse doit être ouverte et disposer du solde suffisant (pas de caisse négative)
        sess_c = db.execute(select(models.SessionCaisse).where(
            models.SessionCaisse.caisse_id == caisse_id,
            models.SessionCaisse.statut == "ouverte")).scalars().first()
        if not sess_c:
            raise HTTPException(status.HTTP_409_CONFLICT, "La caisse doit être ouverte pour décaisser.")
        solde_c = float(sess_c.fond_initial_usd if odp.devise == "USD" else sess_c.fond_initial_cdf)
        for s_, tot_ in db.execute(
            select(models.MouvementCaisse.sens, func.coalesce(func.sum(models.MouvementCaisse.montant), 0))
            .where(models.MouvementCaisse.session_id == sess_c.id,
                   models.MouvementCaisse.devise == odp.devise)
            .group_by(models.MouvementCaisse.sens)).all():
            solde_c += float(tot_) if s_ == "entree" else -float(tot_)
        if solde_c < montant_pay_dev - 0.01:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Solde caisse insuffisant : {round(solde_c, 2)} {odp.devise} disponible, "
                                f"{montant_pay_dev} requis. Alimentez la caisse ou décaissez une partie.")
        compte_credit = caisse.compte_comptable or "571"
        journal = ("CA", "Caisse", "caisse")

    annee = date.today().year
    brf = models.BonReception(
        numero=services.next_numero(db, "bon_reception", annee, societe.code, societe.id),
        ordre_depense_id=odp.id, caisse_id=caisse_id, compte_bancaire_id=compte_bancaire_id,
        receveur_tiers_id=odp.beneficiaire_tiers_id, caissier_id=user.id,
        mode=odp.mode_paiement, reference_paiement=reference_paiement,
        devise=odp.devise, taux_jour=odp.taux_jour,
        montant=montant_pay_dev, montant_usd=montant_pay_usd, statut="emis",
    )
    db.add(brf)
    db.flush()

    # ── Paiement direct sur justificatif : pas d'avance à justifier ──
    if odp.mode_decaissement == "paiement_direct":
        req = db.get(models.Requisition, odp.requisition_id)
        ecr = comptabilite.comptabiliser_paiement_direct(
            db, odp, req.lignes, compte_credit, user.id, *journal)
        odp.montant_paye_usd = odp.montant_autorise_usd
        odp.statut = "paye"
        db.flush()
        services.enregistrer_audit(db, user.id, "PAIEMENT_DIRECT", "ordre_depense", odp.id, None,
                                   {"bon_reception": brf.numero, "ecriture": ecr.numero})
        db.commit()
        return {"message": "Paiement direct enregistré (sur justificatif)",
                "bon_reception": brf.numero, "ecriture": ecr.numero, "mode": "paiement_direct"}

    # Délai de justification selon le type d'avance
    delai = services.get_parametre(db, f"delai_justif.{type_avance}", odp.societe_id) if type_avance else None
    delai = int(delai) if delai else int(services.get_parametre(db, "delai_justif_defaut_h", odp.societe_id, "24"))
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    avance = models.Avance(
        numero=services.next_numero(db, "avance", annee, None, None),
        ordre_depense_id=odp.id, bon_reception_id=brf.id,
        beneficiaire_tiers_id=odp.beneficiaire_tiers_id, societe_id=odp.societe_id,
        type_avance=type_avance, devise=odp.devise, montant_avance=montant_pay_dev,
        montant_avance_usd=montant_pay_usd, date_octroi=now,
        delai_justif_heures=delai, echeance_justif=dom_avances.compute_echeance(now, delai),
        statut="a_justifier",
    )
    db.add(avance)

    # Mouvement de caisse uniquement si paiement par caisse (rattaché à la session ouverte)
    mouvement_caisse_id = None
    if caisse is not None:
        tiers_b = db.get(models.Tiers, odp.beneficiaire_tiers_id)
        req_o = db.get(models.Requisition, odp.requisition_id)
        mvt_c = models.MouvementCaisse(
            caisse_id=caisse_id, session_id=sess_c.id,
            numero=services.next_numero(db, "bon_caisse", annee, societe.code, societe.id),
            reference=req_o.numero if req_o else None,
            sens="sortie", nature="Décaissement (ordre)", devise=odp.devise,
            taux_jour=odp.taux_jour, montant=montant_pay_dev, montant_usd=montant_pay_usd,
            reference_type="bon_reception", reference_id=brf.id,
            tiers_id=odp.beneficiaire_tiers_id, tiers_nom=tiers_b.nom if tiers_b else None,
            billetage=payload.billetage or None,
            libelle=f"Avance {avance.numero} — {odp.numero}", created_by=user.id,
        )
        db.add(mvt_c)
        db.flush()
        mouvement_caisse_id = str(mvt_c.id)
    odp.montant_paye_usd = float(odp.montant_paye_usd or 0) + montant_pay_usd
    # Entièrement décaissé → clôturé ; sinon l'ordre reste 'valide' pour le solde restant
    odp.statut = "execute" if odp.montant_paye_usd >= float(odp.montant_autorise_usd) - 0.01 else "valide"
    db.flush()

    # Comptabilisation automatique OHADA : D 409 (avance) / C 571 (caisse) ou 521 (banque)
    tiers = db.get(models.Tiers, odp.beneficiaire_tiers_id)
    ecr = comptabilite.comptabiliser_versement_avance(
        db, avance, odp, tiers, compte_credit, user.id, *journal)

    services.enregistrer_audit(db, user.id, "EXECUTE", "ordre_depense", odp.id, None,
                               {"avance": avance.numero, "bon_reception": brf.numero,
                                "ecriture": ecr.numero})
    db.commit()
    reste = round(float(odp.montant_autorise_usd) - float(odp.montant_paye_usd), 2)
    return {"message": "Décaissement exécuté", "avance_numero": avance.numero,
            "bon_reception": brf.numero, "echeance_justification": avance.echeance_justif.isoformat(),
            "montant_paye_usd": round(float(odp.montant_paye_usd), 2), "reste_usd": reste,
            "partiel": odp.statut == "valide", "mouvement_id": mouvement_caisse_id}
