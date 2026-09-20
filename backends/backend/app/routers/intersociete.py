"""Opérations intersociétés — le ciment entre les sociétés du groupe.

Principe : un tiers intra-groupe est LIÉ à la société qu'il représente
(le fournisseur « DAKAM » chez KAKO Sarl pointe vers la société DAKAM).
Dès lors :
- toute facture de vente vers un tiers lié génère automatiquement la facture
  d'achat MIROIR chez la société acheteuse (avec entrée en stock si l'article
  existe chez elle) — personne ne saisit deux fois ;
- le règlement est RÉEL (choix de Laurent) : une seule action solde les deux
  côtés — sortie de trésorerie chez l'acheteur, entrée chez le vendeur ;
- l'état des positions donne à tout moment qui doit quoi à qui.
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

router = APIRouter(prefix="/api/intersociete", tags=["intersociété"])
ROLES = {"COMPTABLE", "DFI", "PRESIDENT"}


# ── Tiers réciproque & facture miroir (utilisés par les autres modules) ──
def tiers_reciproque(db: Session, societe_cible_id: uuid.UUID,
                     societe_source: models.Societe, type_: str) -> models.Tiers:
    """Dans la société cible, retrouve (ou crée) le tiers représentant la
    société source — ex. le fournisseur « DAKAM » dans les livres de KAKO."""
    t = db.execute(select(models.Tiers).where(
        models.Tiers.societe_id == societe_cible_id,
        models.Tiers.societe_liee_id == societe_source.id,
        models.Tiers.type == type_)).scalars().first()
    if not t:
        t = models.Tiers(societe_id=societe_cible_id, type=type_,
                         code=societe_source.code, nom=societe_source.nom,
                         intra_groupe=True, societe_liee_id=societe_source.id)
        db.add(t)
        db.flush()
    return t


def creer_facture_miroir(db: Session, fac_vente: models.Facture, user_id) -> models.Facture | None:
    """Facture d'achat miroir chez la société acheteuse, si le client de la
    vente est un tiers lié à une société du groupe. Entrée en stock quand
    l'article (même code) existe chez l'acheteur ; sinon ligne libre."""
    from .commercial import _statut_piece   # import local — évite le cycle
    client = db.get(models.Tiers, fac_vente.tiers_id)
    if not client or not client.societe_liee_id or fac_vente.type != "vente":
        return None
    cible_id = client.societe_liee_id
    societe_cible = db.get(models.Societe, cible_id)
    societe_vendeuse = db.get(models.Societe, fac_vente.societe_id)
    if not societe_cible or cible_id == fac_vente.societe_id:
        return None
    fournisseur = tiers_reciproque(db, cible_id, societe_vendeuse, "fournisseur")

    jour = fac_vente.date_facture
    numero = services.next_numero(db, "facture_achat", jour.year, societe_cible.code, cible_id)
    statut_piece = _statut_piece(db, cible_id, "achat")
    fac_achat = models.Facture(
        societe_id=cible_id, type="achat", numero=numero, tiers_id=fournisseur.id,
        date_facture=jour, echeance=fac_vente.echeance, reference=fac_vente.numero,
        statut="validee" if statut_piece == "valide" else "en_attente",
        intra_groupe=True, facture_liee_id=fac_vente.id, created_by=user_id)
    db.add(fac_achat)
    db.flush()
    fac_vente.intra_groupe = True
    fac_vente.facture_liee_id = fac_achat.id
    # Vente issue d'un PO : le stock est entré à la RÉCEPTION physique de
    # l'acheteur (bon + mauvais état) — le miroir ne double pas l'entrée.
    stock_deja_recu = False
    if fac_vente.devis_id:
        dv_origine = db.get(models.Devis, fac_vente.devis_id)
        stock_deja_recu = bool(dv_origine and dv_origine.commande_origine_id)

    # articles vendeur → articles acheteur par code
    codes_vendeur = {}
    for lv in fac_vente.lignes:
        if lv.article_id and lv.article_id not in codes_vendeur:
            a = db.get(models.Article, lv.article_id)
            codes_vendeur[lv.article_id] = a.code if a else None

    total_ht = total_tva = 0.0
    stock_par_compte: dict[str, float] = {}
    lm_list = []
    for lv in fac_vente.lignes:
        ht, tva = float(lv.montant_ht), float(lv.montant_tva)
        qte = float(lv.qte)
        art_cible = None
        code = codes_vendeur.get(lv.article_id)
        if code:
            art_cible = db.execute(select(models.Article).where(
                models.Article.societe_id == cible_id,
                models.Article.code == code)).scalars().first()
        lm = models.LigneFacture(facture_id=fac_achat.id,
                                 article_id=art_cible.id if art_cible else None,
                                 designation=lv.designation, qte=qte,
                                 prix_unitaire=round(ht / qte, 4) if qte else 0,
                                 taux_tva=float(lv.taux_tva), montant_ht=ht, montant_tva=tva,
                                 cout_entree=ht)
        db.add(lm)
        lm_list.append(lm)
        total_ht += ht
        total_tva += tva
        if art_cible and art_cible.gere_stock and not stock_deja_recu:
            art_cible.stock_qte = round(float(art_cible.stock_qte) + qte, 3)
            art_cible.stock_valeur = round(float(art_cible.stock_valeur) + ht, 2)
            stock_par_compte[art_cible.compte_stock] = round(
                stock_par_compte.get(art_cible.compte_stock, 0.0) + ht, 2)
            db.add(models.MouvementStock(societe_id=cible_id, article_id=art_cible.id,
                                         date_mvt=jour, sens="entree", qte=qte,
                                         cout_unitaire=round(ht / qte, 4) if qte else 0,
                                         valeur=ht, type_operation="achat", reference=numero))
    fac_achat.total_ht = round(total_ht, 2)
    fac_achat.total_tva = round(total_tva, 2)
    fac_achat.total_ttc = round(total_ht + total_tva, 2)
    ecr = comptabilite.comptabiliser_facture(db, fac_achat, lm_list, user_id, statut=statut_piece)
    fac_achat.ecriture_id = ecr.id
    for compte_stock, val in stock_par_compte.items():
        if val > 0:
            comptabilite.comptabiliser_variation_stock(db, fac_achat, compte_stock, val,
                                                       entree=True, created_by=user_id)
    services.enregistrer_audit(db, user_id, "MIROIR", "facture", fac_achat.id, None,
                               {"numero": numero, "origine": fac_vente.numero,
                                "societe": societe_cible.code})
    return fac_achat


def creer_devis_miroir_commande(db: Session, cmd: models.Commande, user_id) -> models.Devis | None:
    """PO intersociété : la commande d'achat de l'acheteur (ex. KAKO) apparaît
    chez le vendeur (ex. DAKAM) comme commande client À PRENDRE EN CHARGE
    (devis au statut « envoyé » — le vendeur confirme, livre, facture)."""
    fournisseur = db.get(models.Tiers, cmd.tiers_id)
    if not fournisseur or not fournisseur.societe_liee_id:
        return None
    vendeur_id = fournisseur.societe_liee_id
    societe_vendeuse = db.get(models.Societe, vendeur_id)
    societe_acheteuse = db.get(models.Societe, cmd.societe_id)
    if not societe_vendeuse or vendeur_id == cmd.societe_id:
        return None
    client = tiers_reciproque(db, vendeur_id, societe_acheteuse, "client")
    d = models.Devis(
        societe_id=vendeur_id,
        numero=services.next_numero(db, "devis", cmd.date_commande.year,
                                    societe_vendeuse.code, vendeur_id),
        tiers_id=client.id, date_devis=cmd.date_commande,
        validite=cmd.date_livraison_prevue, statut="envoye",
        conditions=f"Commande {cmd.numero} de {societe_acheteuse.nom}"
                   + (f" — livraison : {cmd.destination}" if cmd.destination else ""),
        commande_origine_id=cmd.id, created_by=user_id)
    db.add(d)
    db.flush()
    total_ht = total_tva = 0.0
    for i, lc in enumerate(cmd.lignes):
        code = None
        if lc.article_id:
            a = db.get(models.Article, lc.article_id)
            code = a.code if a else None
        art_v = db.execute(select(models.Article).where(
            models.Article.societe_id == vendeur_id,
            models.Article.code == code)).scalars().first() if code else None
        ht = round(float(lc.qte) * float(lc.prix_unitaire), 2)
        tva = round(ht * float(lc.taux_tva) / 100, 2)
        total_ht += ht
        total_tva += tva
        d.lignes.append(models.LigneDevis(
            ordre=i, article_id=art_v.id if art_v else None, designation=lc.designation,
            qte=float(lc.qte), prix_unitaire=float(lc.prix_unitaire),
            taux_tva=float(lc.taux_tva), montant_ht=ht, montant_tva=tva))
    d.total_ht = round(total_ht, 2)
    d.total_tva = round(total_tva, 2)
    d.total_ttc = round(total_ht + total_tva, 2)
    cmd.devis_lie_id = d.id
    cmd.intra_groupe = True
    services.enregistrer_audit(db, user_id, "MIROIR", "devis", d.id, None,
                               {"numero": d.numero, "commande": cmd.numero})
    return d


def creer_demande_course(db: Session, cmd: models.Commande, user_id) -> models.Course | None:
    """Le PO désigne un transporteur du groupe : une DEMANDE de course apparaît
    chez lui — prenable en charge une fois la commande confirmée par le vendeur."""
    if not cmd.transporteur_societe_id:
        return None
    transporteur = db.get(models.Societe, cmd.transporteur_societe_id)
    societe_acheteuse = db.get(models.Societe, cmd.societe_id)
    fournisseur = db.get(models.Tiers, cmd.tiers_id)
    vendeur = db.get(models.Societe, fournisseur.societe_liee_id) if fournisseur and fournisseur.societe_liee_id else None
    if not transporteur or transporteur.id == cmd.societe_id:
        return None
    client = tiers_reciproque(db, transporteur.id, societe_acheteuse, "client")
    marchandise = ", ".join(l.designation for l in cmd.lignes)[:120] or "Marchandises"
    jour = cmd.date_livraison_prevue or cmd.date_commande
    # quantité et unité d'emballage reprises du PO (ex. 300 sacs, pas des tonnes)
    qte_totale = round(sum(float(l.qte) for l in cmd.lignes), 3)
    unite = "unités"
    for lc in cmd.lignes:
        if lc.article_id:
            a2 = db.get(models.Article, lc.article_id)
            if a2 and a2.unite:
                unite = a2.unite
                break
    c = models.Course(
        societe_id=transporteur.id,
        numero=services.next_numero(db, "course", jour.year, transporteur.code, transporteur.id),
        date_course=jour, client_tiers_id=client.id, camion_id=None,
        origine=(vendeur.ville if vendeur and vendeur.ville else (vendeur.nom if vendeur else "À préciser")),
        destination=cmd.destination or "À préciser",
        marchandise=marchandise,
        tonnage_prevu=qte_totale, unite=unite, tarif_mode="voyage", prix_unitaire=0,
        statut="demande", commande_origine_id=cmd.id, created_by=user_id)
    db.add(c)
    db.flush()
    services.enregistrer_audit(db, user_id, "DEMANDE", "course", c.id, None,
                               {"numero": c.numero, "commande": cmd.numero})
    return c


# ── Réception physique de l'acheteur (bon / mauvais état / manquant) ─
def _mapping_lignes_po(db: Session, cmd: models.Commande) -> dict:
    """ligne_commande.id → ligne_devis correspondante (créées dans le même ordre)."""
    dv = db.get(models.Devis, cmd.devis_lie_id) if cmd.devis_lie_id else None
    if not dv:
        return {}
    lignes_dv = sorted(dv.lignes, key=lambda x: int(x.ordre or 0))
    return {str(lc.id): lignes_dv[i] for i, lc in enumerate(cmd.lignes) if i < len(lignes_dv)}


def _recu_cumule_po(db: Session, cmd: models.Commande) -> dict:
    """ligne_commande.id → {bon, mauvais, manquant} cumulés (réceptions non annulées)."""
    out: dict = {}
    for r in db.execute(select(models.ReceptionInter).where(
            models.ReceptionInter.commande_id == cmd.id,
            models.ReceptionInter.statut != "annulee")).scalars():
        for l in r.lignes:
            e = out.setdefault(str(l.ligne_commande_id), {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
            e["bon"] = round(e["bon"] + float(l.qte_bon), 3)
            e["mauvais"] = round(e["mauvais"] + float(l.qte_mauvais), 3)
            e["manquant"] = round(e["manquant"] + float(l.qte_manquante), 3)
    return out


class LigneReceptionPOIn(BaseModel):
    ligne_commande_id: uuid.UUID
    qte_bon: float = Field(default=0, ge=0)
    qte_mauvais: float = Field(default=0, ge=0)
    qte_manquante: float = Field(default=0, ge=0)


class ReceptionPOIn(BaseModel):
    lignes: list[LigneReceptionPOIn]
    note: str | None = None


@router.post("/commandes/{commande_id}/receptionner", status_code=status.HTTP_201_CREATED)
def receptionner_po(commande_id: uuid.UUID, payload: ReceptionPOIn,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """L'acheteur constate ce qu'il reçoit réellement : bon état, mauvais état,
    manquants — dans la limite de ce que le vendeur a chargé (livraisons).
    Le stock entre pour le REÇU (bon + mauvais) ; les manquants sont mis à la
    charge du transporteur du groupe au PRIX D'ACHAT (écritures croisées)."""
    cmd = db.get(models.Commande, commande_id)
    if not cmd or not cmd.devis_lie_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande intersociété introuvable.")
    roles = assert_acces_societe(db, user, cmd.societe_id)
    assert_role(roles, ROLES)
    if not payload.lignes or all(l.qte_bon + l.qte_mauvais + l.qte_manquante <= 0 for l in payload.lignes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucune quantité constatée.")

    mapping = _mapping_lignes_po(db, cmd)
    deja = _recu_cumule_po(db, cmd)
    lignes_cmd = {str(l.id): l for l in cmd.lignes}
    societe = db.get(models.Societe, cmd.societe_id)
    jour = date.today()
    numero = services.next_numero(db, "reception_inter", jour.year, societe.code, societe.id)
    rec = models.ReceptionInter(societe_id=cmd.societe_id, commande_id=cmd.id, numero=numero,
                                date_reception=jour, note=(payload.note or "").strip() or None,
                                # transporteur du groupe → il doit CONFIRMER le constat
                                statut="a_confirmer" if cmd.transporteur_societe_id else "confirmee",
                                created_by=user.id)
    db.add(rec)
    db.flush()

    stock_par_compte: dict[str, float] = {}
    valeur_manquants = 0.0
    for pl in payload.lignes:
        lc = lignes_cmd.get(str(pl.ligne_commande_id))
        if not lc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne étrangère à la commande.")
        constate = round(pl.qte_bon + pl.qte_mauvais + pl.qte_manquante, 3)
        if constate <= 0:
            continue
        ld = mapping.get(str(lc.id))
        livre = float(ld.qte_livree) if ld else 0.0
        d = deja.get(str(lc.id), {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
        deja_constate = d["bon"] + d["mauvais"] + d["manquant"]
        if constate + deja_constate > livre + 1e-6:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"« {lc.designation} » : {constate} constaté + {deja_constate} déjà "
                                f"réceptionné > {livre} chargé par le vendeur.")
        db.add(models.LigneReceptionInter(reception_id=rec.id, ligne_commande_id=lc.id,
                                          qte_bon=pl.qte_bon, qte_mauvais=pl.qte_mauvais,
                                          qte_manquante=pl.qte_manquante))
        recu = round(pl.qte_bon + pl.qte_mauvais, 3)
        lc.qte_recue = round(float(lc.qte_recue) + recu, 3)
        pu = float(lc.prix_unitaire)
        valeur_manquants += round(pl.qte_manquante * pu, 2)
        # stock chez l'acheteur : uniquement ce qui est physiquement là
        if recu > 0 and lc.article_id:
            art = db.get(models.Article, lc.article_id)
            if art and art.gere_stock:
                val = round(recu * pu, 2)
                art.stock_qte = round(float(art.stock_qte) + recu, 3)
                art.stock_valeur = round(float(art.stock_valeur) + val, 2)
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
                db.add(models.MouvementStock(societe_id=cmd.societe_id, article_id=art.id,
                                             date_mvt=jour, sens="entree", qte=recu,
                                             cout_unitaire=round(pu, 4), valeur=val,
                                             type_operation="achat", reference=numero))
    if stock_par_compte:
        # entrée en stock EN ATTENTE — le comptable valide avec les pièces (NB3)
        comptabilite.comptabiliser_stock_entree(db, societe, stock_par_compte, numero, jour,
                                                "reception_inter", rec.id, user.id,
                                                statut="en_attente")
    # le statut de la course évolue : « réceptionnée » (en attente de confirmation)
    course_po = db.execute(select(models.Course).where(
        models.Course.commande_origine_id == cmd.id)).scalars().first()
    if course_po and course_po.statut in ("en_cours", "arrivee"):
        course_po.statut = "receptionnee"

    # ── Manquants : à la charge du transporteur du groupe, au prix d'achat ──
    manquants_factures = False
    if valeur_manquants > 0.004 and cmd.transporteur_societe_id:
        transporteur = db.get(models.Societe, cmd.transporteur_societe_id)
        soc_transp_chez_acheteur = tiers_reciproque(db, cmd.societe_id, transporteur, "fournisseur")
        acheteur_chez_transp = tiers_reciproque(db, transporteur.id, societe, "client")
        m = round(valeur_manquants, 2)
        # acheteur : D 401 transporteur (réduit sa dette transport) / C 758
        comptabilite.post_ecriture(
            db, societe, "OD", "Opérations diverses", "od", jour,
            f"Manquants {numero} à charge du transporteur {transporteur.nom}",
            [{"sens": "D", "compte": comptabilite._compte(db, "compte_fournisseur", cmd.societe_id),
              "montant_usd": m, "tiers_id": soc_transp_chez_acheteur.id,
              "libelle": f"Manquants {numero} — {transporteur.nom}"},
             {"sens": "C", "compte": comptabilite._compte(db, "manquants_produit", cmd.societe_id),
              "montant_usd": m, "libelle": f"Indemnité manquants {numero}"}],
            "manquants_transport", "reception_inter", rec.id, numero, user.id, statut="en_attente")
        # transporteur : D 658 (manquants supportés) / C 411 acheteur (réduit sa créance)
        comptabilite.post_ecriture(
            db, transporteur, "OD", "Opérations diverses", "od", jour,
            f"Manquants {numero} supportés — commande {cmd.numero}",
            [{"sens": "D", "compte": comptabilite._compte(db, "manquants_charge", transporteur.id),
              "montant_usd": m, "libelle": f"Manquants transport {cmd.numero}"},
             {"sens": "C", "compte": comptabilite._compte(db, "compte_client", transporteur.id),
              "montant_usd": m, "tiers_id": acheteur_chez_transp.id,
              "libelle": f"Manquants dus à {societe.nom} — {numero}"}],
            "manquants_transport", "reception_inter", rec.id, numero, user.id, statut="en_attente")
        manquants_factures = True

    services.enregistrer_audit(db, user.id, "RECEPTION", "reception_inter", rec.id, None,
                               {"numero": numero, "commande": cmd.numero,
                                "manquants_usd": round(valeur_manquants, 2)})
    db.commit()
    return {"numero": numero, "manquants_usd": round(valeur_manquants, 2),
            "manquants_imputes_transporteur": manquants_factures}


def reception_po_resume(db: Session, cmd: models.Commande) -> dict:
    """Synthèse réception d'un PO — partagée entre acheteur, vendeur, transporteur."""
    mapping = _mapping_lignes_po(db, cmd)
    deja = _recu_cumule_po(db, cmd)
    lignes, tot = [], {"livre": 0.0, "bon": 0.0, "mauvais": 0.0, "manquant": 0.0}
    for lc in cmd.lignes:
        ld = mapping.get(str(lc.id))
        livre = float(ld.qte_livree) if ld else 0.0
        d = deja.get(str(lc.id), {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
        a_recevoir = round(livre - d["bon"] - d["mauvais"] - d["manquant"], 3)
        lignes.append({"ligne_commande_id": str(lc.id), "designation": lc.designation,
                       "qte_commandee": float(lc.qte), "livre": livre,
                       "bon": d["bon"], "mauvais": d["mauvais"], "manquant": d["manquant"],
                       "a_recevoir": max(a_recevoir, 0.0), "prix_unitaire": float(lc.prix_unitaire)})
        tot["livre"] += livre
        tot["bon"] += d["bon"]
        tot["mauvais"] += d["mauvais"]
        tot["manquant"] += d["manquant"]
    tot = {k: round(v, 3) for k, v in tot.items()}
    complete = tot["livre"] > 0 and tot["livre"] <= tot["bon"] + tot["mauvais"] + tot["manquant"] + 1e-6
    recs = [r for r in db.execute(select(models.ReceptionInter).where(
        models.ReceptionInter.commande_id == cmd.id)
        .order_by(models.ReceptionInter.created_at)).scalars().all()
        if r.statut != "annulee"]
    return {"lignes": lignes, "totaux": tot, "complete": complete,
            "a_receptionner": round(tot["livre"] - tot["bon"] - tot["mauvais"] - tot["manquant"], 3) > 0,
            "valeur_manquants_usd": round(sum(l["manquant"] * l["prix_unitaire"] for l in lignes), 2),
            "receptions": [{"id": str(r.id), "numero": r.numero, "date": r.date_reception.isoformat(),
                            "statut": r.statut, "note": r.note} for r in recs],
            "toutes_confirmees": bool(recs) and all(r.statut == "confirmee" for r in recs)}


@router.delete("/receptions/{reception_id}")
def annuler_reception(reception_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """L'acheteur peut MODIFIER son constat tant que le transporteur n'a pas
    confirmé : cette annulation contre-passe tout (stock, manquants) — il
    ressaisit ensuite une réception corrigée. Après confirmation : figé."""
    rec = db.get(models.ReceptionInter, reception_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réception introuvable.")
    cmd = db.get(models.Commande, rec.commande_id)
    roles = assert_acces_societe(db, user, rec.societe_id)
    assert_role(roles, ROLES)
    if rec.statut == "confirmee":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Réception confirmée par le transporteur — elle ne se modifie plus.")
    if rec.statut == "annulee":
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà annulée.")
    societe = db.get(models.Societe, rec.societe_id)
    jour = date.today()
    lignes_cmd = {str(l.id): l for l in cmd.lignes}
    stock_par_compte: dict[str, float] = {}
    valeur_manquants = 0.0
    for lr in rec.lignes:
        lc = lignes_cmd.get(str(lr.ligne_commande_id))
        if not lc:
            continue
        recu = round(float(lr.qte_bon) + float(lr.qte_mauvais), 3)
        pu = float(lc.prix_unitaire)
        valeur_manquants += round(float(lr.qte_manquante) * pu, 2)
        lc.qte_recue = round(float(lc.qte_recue) - recu, 3)
        if recu > 0 and lc.article_id:
            art = db.get(models.Article, lc.article_id)
            if art and art.gere_stock:
                val = round(recu * pu, 2)
                art.stock_qte = round(float(art.stock_qte) - recu, 3)
                art.stock_valeur = round(float(art.stock_valeur) - val, 2)
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
                db.add(models.MouvementStock(societe_id=rec.societe_id, article_id=art.id,
                                             date_mvt=jour, sens="sortie", qte=recu,
                                             cout_unitaire=round(pu, 4), valeur=val,
                                             type_operation="annulation_reception",
                                             reference=f"ANN-{rec.numero}"))
    if stock_par_compte:
        comptabilite.comptabiliser_stock_sortie(db, societe, stock_par_compte,
                                                f"ANN-{rec.numero}", jour,
                                                "reception_inter", rec.id, user.id)
    if valeur_manquants > 0.004 and cmd.transporteur_societe_id:
        transporteur = db.get(models.Societe, cmd.transporteur_societe_id)
        soc_transp_chez_acheteur = tiers_reciproque(db, rec.societe_id, transporteur, "fournisseur")
        acheteur_chez_transp = tiers_reciproque(db, transporteur.id, societe, "client")
        m = round(valeur_manquants, 2)
        comptabilite.post_ecriture(
            db, societe, "OD", "Opérations diverses", "od", jour,
            f"Annulation manquants {rec.numero}",
            [{"sens": "D", "compte": comptabilite._compte(db, "manquants_produit", rec.societe_id),
              "montant_usd": m, "libelle": f"Annulation indemnité {rec.numero}"},
             {"sens": "C", "compte": comptabilite._compte(db, "compte_fournisseur", rec.societe_id),
              "montant_usd": m, "tiers_id": soc_transp_chez_acheteur.id,
              "libelle": f"Annulation manquants {rec.numero}"}],
            "manquants_transport", "reception_inter", rec.id, f"ANN-{rec.numero}",
            user.id, statut="en_attente")
        comptabilite.post_ecriture(
            db, transporteur, "OD", "Opérations diverses", "od", jour,
            f"Annulation manquants {rec.numero}",
            [{"sens": "D", "compte": comptabilite._compte(db, "compte_client", transporteur.id),
              "montant_usd": m, "tiers_id": acheteur_chez_transp.id,
              "libelle": f"Annulation manquants {rec.numero}"},
             {"sens": "C", "compte": comptabilite._compte(db, "manquants_charge", transporteur.id),
              "montant_usd": m, "libelle": f"Annulation manquants {rec.numero}"}],
            "manquants_transport", "reception_inter", rec.id, f"ANN-{rec.numero}",
            user.id, statut="en_attente")
    rec.statut = "annulee"
    services.enregistrer_audit(db, user.id, "ANNULATION", "reception_inter", rec.id, None,
                               {"numero": rec.numero})
    db.commit()
    return {"ok": True, "numero": rec.numero}


@router.get("/receptions")
def receptions_intersociete(societe_id: uuid.UUID, db: Session = Depends(get_db),
                            user: models.Utilisateur = Depends(get_current_user)):
    """Pour la vue Achats › Réceptions de l'acheteur : les PO intersociétés dont
    la marchandise est chargée et attend sa réception, + l'historique."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    cmds = db.execute(select(models.Commande).where(
        models.Commande.societe_id == societe_id,
        models.Commande.devis_lie_id.is_not(None))
        .order_by(models.Commande.created_at.desc())).scalars().all()
    a_recevoir, historique = [], []
    socs = {s.id: s.nom for s in db.execute(select(models.Societe)).scalars()}
    for cmd in cmds:
        fourn = db.get(models.Tiers, cmd.tiers_id)
        r = reception_po_resume(db, cmd)
        course = db.execute(select(models.Course).where(
            models.Course.commande_origine_id == cmd.id)).scalars().first()
        # visible dès que la marchandise est chargée OU que le camion roule —
        # même si le vendeur n'a pas encore saisi son bon de chargement
        en_route = bool(course and course.statut in ("en_cours", "arrivee", "livree"))
        if (r["a_receptionner"] or en_route) and cmd.statut not in ("soldee", "annulee") and not r["complete"]:
            a_recevoir.append({"commande_id": str(cmd.id), "numero": cmd.numero,
                               "fournisseur": fourn.nom if fourn else "?",
                               "destination": cmd.destination,
                               "reference_producteur": cmd.reference_fournisseur,
                               "receptionnable": r["a_receptionner"],
                               "en_attente": round(r["totaux"]["livre"] - r["totaux"]["bon"]
                                                   - r["totaux"]["mauvais"] - r["totaux"]["manquant"], 3),
                               "course": course.numero if course else None,
                               "course_statut": course.statut if course else None})
        for rec in r["receptions"]:
            historique.append({**rec, "commande": cmd.numero,
                               "fournisseur": fourn.nom if fourn else "?",
                               "transporteur": socs.get(cmd.transporteur_societe_id)})
    return {"a_recevoir": a_recevoir, "historique": historique}


@router.get("/receptions/{reception_id}")
def detail_reception(reception_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Détail complet pour le BON DE RÉCEPTION imprimable."""
    rec = db.get(models.ReceptionInter, reception_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réception introuvable.")
    assert_acces_societe(db, user, rec.societe_id)
    cmd = db.get(models.Commande, rec.commande_id)
    fourn = db.get(models.Tiers, cmd.tiers_id) if cmd else None
    transporteur = db.get(models.Societe, cmd.transporteur_societe_id) if cmd and cmd.transporteur_societe_id else None
    lignes_cmd = {str(l.id): l for l in (cmd.lignes if cmd else [])}
    lignes = []
    for lr in rec.lignes:
        lc = lignes_cmd.get(str(lr.ligne_commande_id))
        pu = float(lc.prix_unitaire) if lc else 0.0
        lignes.append({"designation": lc.designation if lc else "?",
                       "bon": float(lr.qte_bon), "mauvais": float(lr.qte_mauvais),
                       "manquant": float(lr.qte_manquante), "prix_unitaire": pu,
                       "valeur_manquants": round(float(lr.qte_manquante) * pu, 2)})
    return {"id": str(rec.id), "numero": rec.numero, "date": rec.date_reception.isoformat(),
            "statut": rec.statut, "note": rec.note,
            "commande": cmd.numero if cmd else None,
            "reference_producteur": cmd.reference_fournisseur if cmd else None,
            "destination": cmd.destination if cmd else None,
            "fournisseur": fourn.nom if fourn else None,
            "transporteur": transporteur.nom if transporteur else None,
            "lignes": lignes,
            "valeur_manquants_usd": round(sum(l["valeur_manquants"] for l in lignes), 2)}


@router.get("/tracer")
def tracer(societe_id: uuid.UUID, q: str, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    """Traçabilité de bout en bout par N° PRODUCTEUR (ou n° de commande) :
    le même dossier, quel que soit le côté d'où on regarde (NB2 de Laurent)."""
    assert_acces_societe(db, user, societe_id)
    ql = f"%{q.strip()}%"
    cmds = db.execute(select(models.Commande).where(
        (models.Commande.reference_fournisseur.ilike(ql)) | (models.Commande.numero.ilike(ql)))
        .order_by(models.Commande.created_at.desc()).limit(10)).scalars().all()
    socs = {s.id: s.nom for s in db.execute(select(models.Societe)).scalars()}
    dossiers = []
    for cmd in cmds:
        fourn = db.get(models.Tiers, cmd.tiers_id)
        dv = db.get(models.Devis, cmd.devis_lie_id) if cmd.devis_lie_id else None
        course = db.execute(select(models.Course).where(
            models.Course.commande_origine_id == cmd.id)).scalars().first()
        r = reception_po_resume(db, cmd) if cmd.devis_lie_id else None
        livraisons = []
        factures = []
        if dv:
            for bl in db.execute(select(models.Livraison).where(
                    models.Livraison.devis_id == dv.id)).scalars():
                livraisons.append({"numero": bl.numero, "date": bl.date_livraison.isoformat(),
                                   "qte": round(sum(float(x.qte) for x in bl.lignes), 3)})
            for f in db.execute(select(models.Facture).where(
                    models.Facture.devis_id == dv.id)).scalars():
                factures.append({"numero": f.numero, "date": f.date_facture.isoformat(),
                                 "ttc": float(f.total_ttc), "statut": f.statut})
        dossiers.append({
            "reference_producteur": cmd.reference_fournisseur,
            "commande": {"numero": cmd.numero, "date": cmd.date_commande.isoformat(),
                         "acheteur": socs.get(cmd.societe_id), "vendeur": fourn.nom if fourn else "?",
                         "destination": cmd.destination, "statut": cmd.statut,
                         "qte_commandee": round(sum(float(l.qte) for l in cmd.lignes), 3),
                         "total_ht": float(cmd.total_ht)},
            "prise_en_charge": {"numero": dv.numero, "statut": dv.statut,
                                "date": dv.date_confirmation.isoformat() if dv.date_confirmation else None} if dv else None,
            "chargements": livraisons,
            "transport": {"transporteur": socs.get(cmd.transporteur_societe_id),
                          "course": course.numero, "statut": course.statut,
                          "camion": (db.get(models.Camion, course.camion_id).immatriculation
                                     if course.camion_id else None),
                          "unite": course.unite,
                          "depart": course.heure_depart.isoformat() if course.heure_depart else None,
                          "retour": course.heure_retour.isoformat() if course.heure_retour else None} if course else None,
            "reception": {"totaux": r["totaux"], "complete": r["complete"],
                          "toutes_confirmees": r["toutes_confirmees"],
                          "receptions": r["receptions"],
                          "valeur_manquants_usd": r["valeur_manquants_usd"]} if r else None,
            "factures_vendeur": factures,
        })
    return dossiers


@router.post("/receptions/{reception_id}/confirmer")
def confirmer_reception(reception_id: uuid.UUID, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    """Le TRANSPORTEUR confirme le constat de l'acheteur (règle de Laurent :
    KAKO réceptionne, le transporteur confirme que c'est correct — il assume
    les manquants). Sa facturation est bloquée tant qu'il n'a pas confirmé."""
    rec = db.get(models.ReceptionInter, reception_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réception introuvable.")
    cmd = db.get(models.Commande, rec.commande_id)
    if not cmd or not cmd.transporteur_societe_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Réception sans transporteur du groupe.")
    roles = assert_acces_societe(db, user, cmd.transporteur_societe_id)   # côté transporteur
    assert_role(roles, {"COMPTABLE", "DFI", "DG", "ASSISTANT_TECH"})
    if rec.statut == "confirmee":
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà confirmée.")
    rec.statut = "confirmee"
    rec.confirme_par = user.id
    rec.date_confirmation = func.now()
    services.enregistrer_audit(db, user.id, "CONFIRMATION", "reception_inter", rec.id, None,
                               {"numero": rec.numero})
    db.commit()
    return {"numero": rec.numero, "statut": "confirmee"}


@router.get("/badges")
def badges(societe_id: uuid.UUID, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    """Compteurs des opérations en attente pour les bannières de menus :
    commandes du groupe à prendre en charge (vendeur), marchandises à
    réceptionner (acheteur), demandes de course + réceptions à confirmer
    (transporteur)."""
    assert_acces_societe(db, user, societe_id)
    devis_po = db.execute(select(func.count()).select_from(models.Devis).where(
        models.Devis.societe_id == societe_id, models.Devis.statut == "envoye",
        models.Devis.commande_origine_id.is_not(None))).scalar() or 0
    n_rec = 0
    for cmd in db.execute(select(models.Commande).where(
            models.Commande.societe_id == societe_id,
            models.Commande.devis_lie_id.is_not(None),
            models.Commande.statut.not_in(["soldee", "annulee"]))).scalars():
        if reception_po_resume(db, cmd)["a_receptionner"]:
            n_rec += 1
    n_dem = db.execute(select(func.count()).select_from(models.Course).where(
        models.Course.societe_id == societe_id,
        models.Course.statut == "demande")).scalar() or 0
    n_conf = db.execute(select(func.count()).select_from(models.ReceptionInter)
                        .join(models.Commande, models.Commande.id == models.ReceptionInter.commande_id)
                        .where(models.ReceptionInter.statut == "a_confirmer",
                               models.Commande.transporteur_societe_id == societe_id)).scalar() or 0
    return {"devis_po": devis_po, "receptions": n_rec, "courses": n_dem + n_conf}


# ── Liaison tiers ↔ société du groupe ────────────────────────────────
class LiaisonIn(BaseModel):
    tiers_id: uuid.UUID
    societe_liee_id: uuid.UUID | None = None   # None → délier


@router.get("/liaisons")
def liaisons(societe_id: uuid.UUID, db: Session = Depends(get_db),
             user: models.Utilisateur = Depends(get_current_user)):
    """Tiers de la société marqués intra-groupe + leur société liée."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    socs = {str(s.id): {"id": str(s.id), "code": s.code, "nom": s.nom}
            for s in db.execute(select(models.Societe)).scalars()}
    ts = db.execute(select(models.Tiers).where(
        models.Tiers.societe_id == societe_id,
        (models.Tiers.intra_groupe.is_(True)) | (models.Tiers.societe_liee_id.is_not(None)))
        .order_by(models.Tiers.nom)).scalars().all()
    return {"societes": list(socs.values()),
            "tiers": [{"id": str(t.id), "type": t.type, "code": t.code, "nom": t.nom,
                       "societe_liee": socs.get(str(t.societe_liee_id)) if t.societe_liee_id else None}
                      for t in ts]}


@router.post("/lier")
def lier_tiers(payload: LiaisonIn, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    t = db.get(models.Tiers, payload.tiers_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tiers introuvable.")
    roles = assert_acces_societe(db, user, t.societe_id)
    assert_role(roles, ROLES)
    if payload.societe_liee_id:
        s = db.get(models.Societe, payload.societe_liee_id)
        if not s:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Société introuvable.")
        if s.id == t.societe_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Un tiers ne peut pas être lié à sa propre société.")
        t.societe_liee_id = s.id
        t.intra_groupe = True
    else:
        t.societe_liee_id = None
        t.intra_groupe = False
    services.enregistrer_audit(db, user.id, "LIAISON", "tiers", t.id, None,
                               {"societe_liee": str(payload.societe_liee_id)})
    db.commit()
    return {"ok": True}


# ── Positions intersociétés ──────────────────────────────────────────
def _solde_tiers(db: Session, societe_id, tiers_id, prefixe: str) -> float:
    """Solde d'un tiers sur les comptes prefixe* (D − C)."""
    rows = db.execute(
        select(models.LigneEcriture.sens,
               func.coalesce(func.sum(models.LigneEcriture.montant_usd), 0))
        .where(models.LigneEcriture.societe_id == societe_id,
               models.LigneEcriture.tiers_id == tiers_id,
               models.LigneEcriture.compte_numero.like(f"{prefixe}%"))
        .group_by(models.LigneEcriture.sens)).all()
    total = 0.0
    for sens, montant in rows:
        total += float(montant) if sens == "D" else -float(montant)
    return round(total, 2)


@router.get("/positions")
def positions(db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    """Qui doit quoi à qui : pour chaque paire (créancier → débiteur), la
    créance chez le vendeur, la dette miroir chez l'acheteur, et l'écart de
    réconciliation (doit être nul si tout est bien mirroré)."""
    societes_ids = [a.societe_id for a in db.execute(
        select(models.UtilisateurSociete).where(
            models.UtilisateurSociete.utilisateur_id == user.id)).scalars()]
    socs = {s.id: s for s in db.execute(select(models.Societe)).scalars()}
    out = []
    for sid in set(societes_ids):
        ts = db.execute(select(models.Tiers).where(
            models.Tiers.societe_id == sid,
            models.Tiers.societe_liee_id.is_not(None))).scalars().all()
        for t in ts:
            creance = _solde_tiers(db, sid, t.id, "41") if t.type == "client" else 0.0
            dette = -_solde_tiers(db, sid, t.id, "40") if t.type == "fournisseur" else 0.0
            if abs(creance) < 0.01 and abs(dette) < 0.01:
                continue
            liee = socs.get(t.societe_liee_id)
            # contre-passe : le tiers réciproque chez la société liée
            recip = db.execute(select(models.Tiers).where(
                models.Tiers.societe_id == t.societe_liee_id,
                models.Tiers.societe_liee_id == sid,
                models.Tiers.type == ("fournisseur" if t.type == "client" else "client"))).scalars().first()
            miroir = 0.0
            if recip:
                miroir = (-_solde_tiers(db, t.societe_liee_id, recip.id, "40") if t.type == "client"
                          else _solde_tiers(db, t.societe_liee_id, recip.id, "41"))
            montant = creance if t.type == "client" else dette
            out.append({
                "creancier": socs[sid].nom if t.type == "client" else (liee.nom if liee else "?"),
                "debiteur": (liee.nom if liee else "?") if t.type == "client" else socs[sid].nom,
                "vu_par": socs[sid].nom, "sens": t.type,
                "montant_usd": round(montant, 2), "miroir_usd": round(miroir, 2),
                "ecart_usd": round(montant - miroir, 2),
            })
    # dédoublonne (chaque paire vue des deux côtés) : on garde la vue « client »
    vues_client = [o for o in out if o["sens"] == "client"]
    couverts = {(o["creancier"], o["debiteur"]) for o in vues_client}
    vues_fourn = [o for o in out if o["sens"] == "fournisseur"
                  and (o["creancier"], o["debiteur"]) not in couverts]
    return vues_client + vues_fourn


# ── Factures intra-groupe & règlement réel double-face ───────────────
@router.get("/factures")
def factures_intragroupe(db: Session = Depends(get_db),
                         user: models.Utilisateur = Depends(get_current_user)):
    from .commercial import _reglement_facture
    societes_ids = {a.societe_id for a in db.execute(
        select(models.UtilisateurSociete).where(
            models.UtilisateurSociete.utilisateur_id == user.id)).scalars()}
    socs = {s.id: s.nom for s in db.execute(select(models.Societe)).scalars()}
    facs = db.execute(select(models.Facture).where(
        models.Facture.type == "vente", models.Facture.intra_groupe.is_(True),
        models.Facture.societe_id.in_(societes_ids))
        .order_by(models.Facture.created_at.desc())).scalars().all()
    out = []
    for f in facs:
        t = db.get(models.Tiers, f.tiers_id)
        miroir = db.get(models.Facture, f.facture_liee_id) if f.facture_liee_id else None
        out.append({"id": str(f.id), "numero": f.numero, "date": f.date_facture.isoformat(),
                    "vendeur": socs.get(f.societe_id), "acheteur": t.nom if t else "?",
                    "vendeur_societe_id": str(f.societe_id),
                    "acheteur_societe_id": str(miroir.societe_id) if miroir else None,
                    "total_ttc": float(f.total_ttc), **_reglement_facture(db, f),
                    "miroir_numero": miroir.numero if miroir else None,
                    "miroir_statut": miroir.statut if miroir else None})
    return out


class ReglementInterIn(BaseModel):
    montant_usd: float | None = None            # défaut : tout le solde
    vendeur_mode: str = Field(default="banque", pattern="^(espece|banque)$")
    vendeur_caisse_id: uuid.UUID | None = None
    acheteur_mode: str = Field(default="banque", pattern="^(espece|banque)$")
    acheteur_caisse_id: uuid.UUID | None = None
    reference: str | None = None


@router.post("/factures/{facture_id}/regler", status_code=status.HTTP_201_CREATED)
def regler_intersociete(facture_id: uuid.UUID, payload: ReglementInterIn,
                        db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    """Règlement réel en une action : sortie de trésorerie chez l'acheteur
    (D 401 / C 57x-52x) ET entrée chez le vendeur (D 57x-52x / C 411)."""
    from .caisse import _session_ouverte
    from .commercial import _reglement_facture
    fac_v = db.get(models.Facture, facture_id)
    if not fac_v or fac_v.type != "vente" or not fac_v.intra_groupe or not fac_v.facture_liee_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture intersociété introuvable (miroir manquant).")
    fac_a = db.get(models.Facture, fac_v.facture_liee_id)
    roles_v = assert_acces_societe(db, user, fac_v.societe_id)
    assert_role(roles_v, ROLES)
    roles_a = assert_acces_societe(db, user, fac_a.societe_id)   # il faut les DEUX sociétés
    assert_role(roles_a, ROLES)

    sit = _reglement_facture(db, fac_v)
    solde = sit["solde_du_usd"]
    if solde <= 0.009:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette facture est déjà réglée.")
    montant = round(payload.montant_usd, 2) if payload.montant_usd else solde
    if montant > solde + 0.01:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Montant supérieur au solde dû ({solde:.2f} USD).")

    soc_v = db.get(models.Societe, fac_v.societe_id)
    soc_a = db.get(models.Societe, fac_a.societe_id)
    tiers_client = db.get(models.Tiers, fac_v.tiers_id)       # l'acheteur vu du vendeur
    tiers_fourn = db.get(models.Tiers, fac_a.tiers_id)        # le vendeur vu de l'acheteur
    jour = date.today()
    ref = (payload.reference or "").strip() or f"Règlement intersociété {fac_v.numero}"

    def _tresorerie(societe_id, mode, caisse_id, sens_mouvement):
        """Compte de trésorerie + mouvement de caisse éventuel. Renvoie (compte, caisse, session)."""
        if mode == "espece":
            if not caisse_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choisissez la caisse concernée.")
            c = db.get(models.Caisse, caisse_id)
            if not c or c.societe_id != societe_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Caisse invalide pour cette société.")
            s = _session_ouverte(db, c.id)
            if not s:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Ouvrez la caisse « {c.libelle} ».")
            return c.compte_comptable, c, s
        return comptabilite._compte(db, "compte_banque", societe_id), None, None

    cpt_a, caisse_a, sess_a = _tresorerie(fac_a.societe_id, payload.acheteur_mode, payload.acheteur_caisse_id, "sortie")
    cpt_v, caisse_v, sess_v = _tresorerie(fac_v.societe_id, payload.vendeur_mode, payload.vendeur_caisse_id, "entree")

    # Côté acheteur : D 401 (fournisseur lié) / C trésorerie
    ecr_a = comptabilite.post_ecriture(
        db, soc_a, "TR", "Trésorerie", "tresorerie", jour, ref,
        [{"sens": "D", "compte": comptabilite._compte(db, "compte_fournisseur", fac_a.societe_id),
          "montant_usd": montant, "tiers_id": tiers_fourn.id,
          "libelle": f"Règlement {fac_a.numero} — {tiers_fourn.nom}"},
         {"sens": "C", "compte": cpt_a, "montant_usd": montant, "libelle": ref}],
        "reglement_intersociete", "facture", fac_a.id, fac_a.numero, user.id, statut="en_attente")
    # Côté vendeur : D trésorerie / C 411 (client lié)
    ecr_v = comptabilite.post_ecriture(
        db, soc_v, "TR", "Trésorerie", "tresorerie", jour, ref,
        [{"sens": "D", "compte": cpt_v, "montant_usd": montant, "libelle": ref},
         {"sens": "C", "compte": comptabilite._compte(db, "compte_client", fac_v.societe_id),
          "montant_usd": montant, "tiers_id": tiers_client.id,
          "libelle": f"Règlement {fac_v.numero} — {tiers_client.nom}"}],
        "reglement_intersociete", "facture", fac_v.id, fac_v.numero, user.id, statut="en_attente")

    for fac, mode in ((fac_v, payload.vendeur_mode), (fac_a, payload.acheteur_mode)):
        db.add(models.PaiementFacture(facture_id=fac.id, mode=mode, devise="USD",
                                      montant=montant, montant_usd=montant,
                                      reference=ref, compte=cpt_v if fac is fac_v else cpt_a))
    if caisse_a:
        db.add(models.MouvementCaisse(
            caisse_id=caisse_a.id, session_id=sess_a.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, soc_a.code, soc_a.id),
            reference=fac_a.numero, sens="sortie", nature="Règlement intersociété", devise="USD",
            montant=montant, montant_usd=montant, tiers_id=tiers_fourn.id, tiers_nom=tiers_fourn.nom,
            reference_type="facture", reference_id=fac_a.id, libelle=ref, created_by=user.id))
    if caisse_v:
        db.add(models.MouvementCaisse(
            caisse_id=caisse_v.id, session_id=sess_v.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, soc_v.code, soc_v.id),
            reference=fac_v.numero, sens="entree", nature="Règlement intersociété", devise="USD",
            montant=montant, montant_usd=montant, tiers_id=tiers_client.id, tiers_nom=tiers_client.nom,
            reference_type="facture", reference_id=fac_v.id, libelle=ref, created_by=user.id))

    services.enregistrer_audit(db, user.id, "REGLEMENT_INTER", "facture", fac_v.id, None,
                               {"montant_usd": montant, "vendeur": soc_v.code, "acheteur": soc_a.code})
    db.commit()
    return {"ecriture_vendeur": ecr_v.numero, "ecriture_acheteur": ecr_a.numero,
            **_reglement_facture(db, fac_v)}
