"""G04 — Justification d'avance, détection des retards, blocage/levée."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from decimal import Decimal

from .. import comptabilite, models, services
from ..database import get_db
from ..deps import assert_acces_societe, assert_role, get_current_user
from ..domain import money
from ..domain.avances import controle_equilibre, est_en_retard, AvanceEnCours
from ..schemas import JustificationIn, JustificationLigneIn, JustificationOut

router = APIRouter(prefix="/api/avances", tags=["avances à justifier"])


def _resolve_article(db: Session, societe: models.Societe, m) -> models.Article:
    """Retrouve un article, ou le crée à la volée (circuit 1 : nouvelles marchandises)."""
    if m.article_id:
        a = db.get(models.Article, m.article_id)
        if not a:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Article introuvable.")
        return a
    code = (m.code or "").strip().upper()
    if code:
        a = db.execute(select(models.Article).where(
            models.Article.societe_id == societe.id, models.Article.code == code)).scalars().first()
        if a:
            return a
    if not code:
        n = db.execute(select(models.Article).where(models.Article.societe_id == societe.id)).scalars().all()
        code = f"ART{len(n) + 1:04d}"
    a = models.Article(societe_id=societe.id, code=code, designation=(m.designation or "Article").strip(),
                       unite=(m.unite or "unité"), prix_achat=m.prix_unitaire,
                       taux_tva=m.taux_tva if m.taux_tva is not None else Decimal("16"))
    db.add(a)
    db.flush()
    return a


@router.post("/justifier", response_model=JustificationOut, status_code=status.HTTP_201_CREATED)
def justifier(payload: JustificationIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    avance = db.get(models.Avance, payload.avance_id)
    if not avance:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avance introuvable.")
    assert_acces_societe(db, user, avance.societe_id)
    if avance.statut not in ("a_justifier", "en_retard"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Avance non justifiable (statut={avance.statut}).")

    jour = date.today()
    # Conversion des lignes en USD
    lignes_usd = []
    lignes_models = []
    for l in payload.lignes:
        taux = services.get_taux_jour(db, jour, l.devise)
        if l.devise != "USD" and taux is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Taux {l.devise}/USD manquant pour le {jour}.")
        m_usd = money.to_usd(l.devise, l.montant, taux)
        lignes_usd.append(m_usd)
        lignes_models.append((l, m_usd))

    societe = db.get(models.Societe, avance.societe_id)

    # ── Circuit 1 : marchandises achetées avec l'avance → entrée en stock ──
    # (au coût d'acquisition = prix + frais annexes répartis ; TVA déductible)
    stock_entries = []   # (article, qte, cout_entree)
    if payload.marchandises:
        items = []
        for m in payload.marchandises:
            art = _resolve_article(db, societe, m)
            ht = round(float(m.qte) * float(m.prix_unitaire), 2)
            taux = float(m.taux_tva) if m.taux_tva is not None else float(art.taux_tva)
            if not art.assujetti_tva:
                taux = 0.0                               # article non assujetti → pas de TVA
            items.append({"art": art, "qte": float(m.qte), "ht": ht,
                          "tva": round(ht * taux / 100, 2), "des": m.designation or art.designation})
        frais_ht = round(sum(float(f.montant_ht) for f in payload.frais), 2)
        frais_tva = round(sum(round(float(f.montant_ht) * (float(f.taux_tva) if f.taux_tva is not None else 16) / 100, 2)
                              for f in payload.frais), 2)
        if frais_ht > 0 and items:
            w = [it["qte"] if payload.repartition != "valeur" else it["ht"] for it in items]
            tw = sum(w) or 1.0
            cumul = 0.0
            for i, it in enumerate(items):
                part = round(frais_ht * w[i] / tw, 2) if i < len(items) - 1 else round(frais_ht - cumul, 2)
                cumul = round(cumul + part, 2)
                it["cout"] = round(it["ht"] + part, 2)
        else:
            for it in items:
                it["cout"] = it["ht"]
        tva_totale = round(sum(it["tva"] for it in items) + frais_tva, 2)
        # Op 1 (achat) : la marchandise s'impute en 601 au PRIX d'achat (HT), pas au stock.
        for it in items:
            li = JustificationLigneIn(nature=f"Achat : {it['des']}",
                                      compte_impute=it["art"].compte_achat, devise="USD",
                                      montant=Decimal(str(it["ht"])))
            lignes_usd.append(money._d(it["ht"]))
            lignes_models.append((li, money._d(it["ht"])))
            stock_entries.append((it["art"], it["qte"], it["cout"]))
        # Frais accessoires → comptes de charge (611…), incorporés au coût du stock (op 2)
        for f in payload.frais:
            fht = round(float(f.montant_ht), 2)
            if fht <= 0:
                continue
            li = JustificationLigneIn(nature=f"Frais : {f.libelle}", compte_impute=f.compte,
                                      devise="USD", montant=Decimal(str(fht)))
            lignes_usd.append(money._d(fht))
            lignes_models.append((li, money._d(fht)))
        if tva_totale > 0:
            li = JustificationLigneIn(nature="TVA déductible (marchandises)",
                                      compte_impute=services.get_parametre(db, "compte.tva_deductible", societe.id, "4452"),
                                      devise="USD", montant=Decimal(str(tva_totale)))
            lignes_usd.append(money._d(tva_totale))
            lignes_models.append((li, money._d(tva_totale)))

    if not lignes_models:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Justification vide : au moins une dépense ou une marchandise.")

    taux_solde = services.get_taux_jour(db, jour, payload.devise_solde)
    solde_usd = money.to_usd(payload.devise_solde, payload.solde_retourne, taux_solde) \
        if payload.solde_retourne else money._d(0)

    eq = controle_equilibre(avance.montant_avance_usd, lignes_usd, solde_usd)

    just = models.Justification(
        numero=services.next_numero(db, "justification", jour.year, societe.code, societe.id),
        avance_id=avance.id, montant_justifie_usd=eq.total_justifie_usd,
        solde_retourne=payload.solde_retourne, solde_retourne_usd=eq.solde_retourne_usd,
        ecart_usd=eq.ecart_usd, complement_demande=eq.complement_du, statut="soumise",
        created_by=user.id,
    )
    for l, m_usd in lignes_models:
        just.lignes.append(models.JustificationLigne(
            date_achat=l.date_achat, nature=l.nature, compte_impute=l.compte_impute,
            fournisseur=l.fournisseur, num_piece=l.num_piece, devise=l.devise,
            montant=l.montant, montant_usd=m_usd, a_piece_jointe=l.a_piece_jointe,
        ))
    db.add(just)
    avance.statut = "justifiee"
    db.flush()

    # Retour de monnaie → entrée en caisse SUR LA SESSION OUVERTE (le 571 du grand livre
    # doit toujours égaler la caisse réelle). Le compte utilisé = compte de la caisse.
    caisse_compte = None
    if eq.solde_retourne_usd and eq.solde_retourne_usd > 0:
        caisse = None
        if payload.caisse_id:
            caisse = db.get(models.Caisse, payload.caisse_id)
        elif avance.bon_reception_id:
            brf = db.get(models.BonReception, avance.bon_reception_id)
            if brf and brf.caisse_id:
                caisse = db.get(models.Caisse, brf.caisse_id)
        if caisse is None:
            caisse = db.execute(select(models.Caisse).where(
                models.Caisse.societe_id == societe.id).order_by(models.Caisse.id)).scalars().first()
        if caisse is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucune caisse pour enregistrer le rendu.")
        sess = db.execute(select(models.SessionCaisse).where(
            models.SessionCaisse.caisse_id == caisse.id,
            models.SessionCaisse.statut == "ouverte")).scalars().first()
        if sess is None:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Ouvrez la caisse « {caisse.libelle} » pour enregistrer le rendu de monnaie.")
        caisse_compte = caisse.compte_comptable
        db.add(models.MouvementCaisse(
            caisse_id=caisse.id, session_id=sess.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
            reference=avance.numero, tiers_id=avance.beneficiaire_tiers_id,
            sens="entree", nature="Retour d'avance", devise=payload.devise_solde,
            taux_jour=taux_solde, montant=payload.solde_retourne, montant_usd=eq.solde_retourne_usd,
            reference_type="justification", reference_id=just.id,
            libelle=f"Retour solde avance {avance.numero}", created_by=user.id))

    # Entrées de stock des marchandises (au coût d'acquisition)
    for art, qte, cout in stock_entries:
        art.stock_qte = round(float(art.stock_qte) + qte, 3)
        art.stock_valeur = round(float(art.stock_valeur) + cout, 2)
        db.add(models.MouvementStock(
            societe_id=societe.id, article_id=art.id, date_mvt=jour, sens="entree", qte=qte,
            cout_unitaire=round(cout / qte, 4) if qte else 0.0, valeur=cout,
            type_operation="achat", reference=just.numero))

    # Comptabilisation OHADA — Op 1 : D 601/611 (achat au prix) / D TVA [+ D caisse] / C 421
    # Le compte de caisse du rendu = celui de la caisse mouvementée (cohérence 571 ↔ caisse).
    ecr = comptabilite.comptabiliser_justification(db, just, avance, user.id, caisse_compte=caisse_compte)
    # Op 2 : entrée en stock au coût d'acquisition (D 31 / C 603)
    if stock_entries:
        stock_par_compte: dict[str, float] = {}
        for art, qte, cout in stock_entries:
            stock_par_compte[art.compte_stock] = round(stock_par_compte.get(art.compte_stock, 0.0) + cout, 2)
        comptabilite.comptabiliser_stock_entree(db, societe, stock_par_compte, just.numero, jour,
                                                "justification", just.id, user.id)

    services.enregistrer_audit(db, user.id, "INSERT", "justification", just.id, None,
                               {"avance": avance.numero, "ecart_usd": float(eq.ecart_usd),
                                "complement": eq.complement_du, "ecriture": ecr.numero})
    db.commit()
    db.refresh(just)
    return just


@router.post("/verifier-retards")
def verifier_retards(db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Passe les avances échues en retard et crée les blocages (à planifier).
    À exécuter périodiquement (ex. tâche planifiée à 17h30)."""
    now = datetime.now(timezone.utc)
    en_attente = db.execute(
        select(models.Avance).where(models.Avance.statut == "a_justifier")
    ).scalars().all()
    bloques = 0
    for av in en_attente:
        if est_en_retard(AvanceEnCours(statut=av.statut, echeance_justif=av.echeance_justif), now):
            av.statut = "en_retard"
            deja = db.execute(
                select(models.BlocageBeneficiaire).where(
                    models.BlocageBeneficiaire.avance_id == av.id,
                    models.BlocageBeneficiaire.actif.is_(True))
            ).first()
            if not deja:
                db.add(models.BlocageBeneficiaire(
                    tiers_id=av.beneficiaire_tiers_id, avance_id=av.id,
                    motif=f"Avance {av.numero} non justifiée dans le délai."))
                bloques += 1
    db.commit()
    return {"avances_en_retard": bloques, "verifie_a": now.isoformat()}


@router.post("/blocages/{blocage_id}/lever")
def lever_blocage(blocage_id: uuid.UUID, motif: str, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Seul le DFI peut lever un blocage."""
    blocage = db.get(models.BlocageBeneficiaire, blocage_id)
    if not blocage:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blocage introuvable.")
    roles = db.execute(
        select(models.Role.code)
        .join(models.UtilisateurSociete, models.UtilisateurSociete.role_id == models.Role.id)
        .where(models.UtilisateurSociete.utilisateur_id == user.id)
    ).scalars().all()
    if "DFI" not in set(roles) and "PRESIDENT" not in set(roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Seul le DFI peut lever un blocage.")
    if not blocage.actif:
        raise HTTPException(status.HTTP_409_CONFLICT, "Blocage déjà levé.")
    blocage.actif = False
    blocage.leve_par = user.id
    blocage.leve_motif = motif
    blocage.leve_at = datetime.now(timezone.utc)
    services.enregistrer_audit(db, user.id, "UPDATE", "blocage_beneficiaire", blocage.id,
                               {"actif": True}, {"actif": False, "motif": motif})
    db.commit()
    return {"message": "Blocage levé", "blocage_id": str(blocage.id)}
