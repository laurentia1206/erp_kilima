"""Cycle de vente classique — devis → commande client → livraison → facture → règlement.

Comme dans Odoo, le devis et la commande client sont le même document à des
statuts différents (brouillon / envoyé / confirmé). Les livraisons sortent le
stock au CUMP (partielles possibles) ; la facturation porte sur les quantités
livrées ; les règlements clients apurent le compte 411 (lettrable).
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
from .commercial import _reglement_facture, _statut_piece

router = APIRouter(prefix="/api/ventes", tags=["ventes"])
ROLES = {"COMPTABLE", "DFI"}


# ── Schémas ──────────────────────────────────────────────────────────
class LigneDevisIn(BaseModel):
    article_id: uuid.UUID | None = None
    designation: str | None = None
    qte: float = Field(gt=0)
    prix_unitaire: float | None = None          # défaut : prix de vente de l'article
    remise_pct: float = Field(default=0, ge=0, le=100)
    taux_tva: float | None = None               # défaut : TVA de l'article / de la société


class DevisIn(BaseModel):
    tiers_id: uuid.UUID
    date_devis: date | None = None
    validite: date | None = None
    remise_globale_pct: float = Field(default=0, ge=0, le=100)
    conditions: str | None = None
    note: str | None = None
    lignes: list[LigneDevisIn]


class LivraisonLigneIn(BaseModel):
    ligne_id: uuid.UUID
    qte: float = Field(gt=0)


class LivraisonIn(BaseModel):
    lignes: list[LivraisonLigneIn]
    note: str | None = None


class FacturerIn(BaseModel):
    echeance: date | None = None


class ReglementIn(BaseModel):
    mode: str = Field(pattern="^(espece|banque|mobile_money)$")
    devise: str = Field(default="USD", pattern="^(USD|CDF)$")
    montant: float = Field(gt=0)                # dans la devise choisie
    caisse_id: uuid.UUID | None = None          # requis si espèces
    reference: str | None = None                # n° transaction / bordereau


# ── Helpers ──────────────────────────────────────────────────────────
def _devis_ou_404(db: Session, devis_id: uuid.UUID, user) -> tuple[models.Devis, set]:
    d = db.get(models.Devis, devis_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Devis introuvable.")
    roles = assert_acces_societe(db, user, d.societe_id)
    assert_role(roles, ROLES)
    return d, roles


def _facturable(l: models.LigneDevis, art: models.Article | None, po: bool = False) -> float:
    """Quantité facturable : le livré non facturé (articles en stock),
    ou tout le restant pour les lignes libres / articles sans stock.
    Pour une commande du GROUPE (PO), TOUTES les lignes suivent le chargement
    déclaré (qte_livree) — même sans article — car la réception de l'acheteur
    se réconcilie contre ce chargement."""
    base = float(l.qte_livree) if (po or (art and art.gere_stock)) else float(l.qte)
    return round(max(base - float(l.qte_facturee), 0.0), 3)


def _devis_dict(db: Session, d: models.Devis, detail: bool = True) -> dict:
    tiers = db.get(models.Tiers, d.tiers_id)
    po = bool(d.commande_origine_id)
    # codes des articles chez l'ACHETEUR (aide à l'association côté vendeur)
    codes_acheteur = {}
    if po:
        cmd_po = db.get(models.Commande, d.commande_origine_id)
        if cmd_po:
            for i, lc in enumerate(cmd_po.lignes):
                if lc.article_id:
                    a2 = db.get(models.Article, lc.article_id)
                    if a2:
                        codes_acheteur[i] = {"code": a2.code, "unite": a2.unite}
    lignes, tot_cmd = [], {"livree": 0.0, "facturee": 0.0, "qte": 0.0, "livrable": 0.0, "facturable": 0.0}
    for l in d.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        gere = bool(art and art.gere_stock)
        livrable = round(float(l.qte) - float(l.qte_livree), 3) if (gere or po) else 0.0
        facturable = _facturable(l, art, po)
        tot_cmd["qte"] += float(l.qte)
        tot_cmd["livree"] += float(l.qte_livree)
        tot_cmd["facturee"] += float(l.qte_facturee)
        tot_cmd["livrable"] += livrable
        tot_cmd["facturable"] += facturable
        lignes.append({"id": str(l.id), "article_id": str(l.article_id) if l.article_id else None,
                       "article": art.code if art else None, "designation": l.designation,
                       "qte": float(l.qte), "prix_unitaire": float(l.prix_unitaire),
                       "remise_pct": float(l.remise_pct or 0), "taux_tva": float(l.taux_tva),
                       "montant_ht": float(l.montant_ht), "montant_tva": float(l.montant_tva),
                       "gere_stock": gere, "suivi_livraison": gere or po,
                       "code_acheteur": (codes_acheteur.get(int(l.ordre or 0)) or {}).get("code"),
                       "unite_acheteur": (codes_acheteur.get(int(l.ordre or 0)) or {}).get("unite"),
                       "a_associer": po and not art,
                       "stock_dispo": float(art.stock_qte) if gere else None,
                       "qte_livree": float(l.qte_livree), "qte_facturee": float(l.qte_facturee),
                       "livrable": livrable, "facturable": facturable})
    # progression livraison : lignes stockables, ou TOUTES les lignes pour un PO
    stockables = [x for x in lignes if x["suivi_livraison"]]
    if not stockables:
        liv = "sans_objet"
    elif all(x["livrable"] <= 0 for x in stockables):
        liv = "livree"
    elif any(x["qte_livree"] > 0 for x in stockables):
        liv = "partielle"
    else:
        liv = "a_livrer"
    expire = bool(d.validite and d.statut in ("brouillon", "envoye") and d.validite < date.today())
    cmd_origine = db.get(models.Commande, d.commande_origine_id) if d.commande_origine_id else None
    transport = None
    if cmd_origine and cmd_origine.transporteur_societe_id:
        course = db.execute(select(models.Course).where(
            models.Course.commande_origine_id == cmd_origine.id)).scalars().first()
        transporteur = db.get(models.Societe, cmd_origine.transporteur_societe_id)
        if course:
            transport = {"transporteur": transporteur.nom if transporteur else "?",
                         "course": course.numero, "statut": course.statut}
    out = {
        "commande_origine": cmd_origine.numero if cmd_origine else None,
        "reference_producteur": d.reference_producteur,
        "transport": transport,
        "id": str(d.id), "numero": d.numero, "statut": d.statut,
        "client": tiers.nom if tiers else None, "tiers_id": str(d.tiers_id),
        "date": d.date_devis.isoformat(),
        "validite": d.validite.isoformat() if d.validite else None, "expire": expire,
        "remise_globale_pct": float(d.remise_globale_pct or 0),
        "total_ht": float(d.total_ht), "total_tva": float(d.total_tva),
        "total_ttc": float(d.total_ttc), "remise_totale": float(d.remise_totale or 0),
        "conditions": d.conditions, "note": d.note,
        "statut_livraison": liv,
        "facturable": round(tot_cmd["facturable"], 3) > 0,
        "pct_livre": round(tot_cmd["livree"] / tot_cmd["qte"] * 100) if tot_cmd["qte"] else 0,
        "pct_facture": round(tot_cmd["facturee"] / tot_cmd["qte"] * 100) if tot_cmd["qte"] else 0,
    }
    if detail:
        out["lignes"] = lignes
        out["livraisons"] = [{"id": str(bl.id), "numero": bl.numero, "date": bl.date_livraison.isoformat(),
                              "note": bl.note,
                              "lignes": [{"designation": x.designation, "qte": float(x.qte)}
                                         for x in bl.lignes]}
                             for bl in db.execute(select(models.Livraison).where(
                                 models.Livraison.devis_id == d.id)
                                 .order_by(models.Livraison.created_at)).scalars()]
        facs = db.execute(select(models.Facture).where(models.Facture.devis_id == d.id)
                          .order_by(models.Facture.created_at)).scalars().all()
        out["factures"] = [{"id": str(f.id), "numero": f.numero,
                            "date": f.date_facture.isoformat(),
                            "total_ttc": float(f.total_ttc), **_reglement_facture(db, f)}
                           for f in facs]
    return out


def _calculer_lignes(db: Session, d: models.Devis, societe_id, lignes_in: list[LigneDevisIn]) -> None:
    """(Re)construit les lignes du devis et ses totaux (remises ligne + globale)."""
    tva_defaut = float(services.get_parametre(db, "tva.taux_defaut", societe_id, "16"))
    gr = float(d.remise_globale_pct or 0)
    d.lignes.clear()
    total_ht = total_tva = remise_totale = 0.0
    for i, l in enumerate(lignes_in):
        art = db.get(models.Article, l.article_id) if l.article_id else None
        if l.article_id and (not art or art.societe_id != societe_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Article invalide.")
        designation = (l.designation or "").strip() or (art.designation if art else None)
        if not designation:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Désignation requise sur chaque ligne.")
        prix = l.prix_unitaire if l.prix_unitaire is not None else (float(art.prix_vente) if art else 0.0)
        if l.taux_tva is not None:
            taux = l.taux_tva
        elif art:
            taux = float(art.taux_tva) if art.assujetti_tva else 0.0
        else:
            taux = tva_defaut
        remise = round((1 - (1 - float(l.remise_pct) / 100) * (1 - gr / 100)) * 100, 4)
        brut = round(float(l.qte) * prix, 2)
        ht = round(brut * (1 - remise / 100), 2)
        tva = round(ht * taux / 100, 2)
        total_ht += ht
        total_tva += tva
        remise_totale += brut - ht
        d.lignes.append(models.LigneDevis(
            ordre=i, article_id=art.id if art else None, designation=designation,
            qte=l.qte, prix_unitaire=prix, remise_pct=round(remise, 2), taux_tva=taux,
            montant_ht=ht, montant_tva=tva))
    d.total_ht = round(total_ht, 2)
    d.total_tva = round(total_tva, 2)
    d.total_ttc = round(total_ht + total_tva, 2)
    d.remise_totale = round(remise_totale, 2)


# ── Devis : CRUD & workflow ──────────────────────────────────────────
@router.get("/devis")
def lister_devis(societe_id: uuid.UUID, statut: str | None = None, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    q = select(models.Devis).where(models.Devis.societe_id == societe_id)
    if statut:
        q = q.where(models.Devis.statut == statut)
    ds = db.execute(q.order_by(models.Devis.created_at.desc())).scalars().all()
    return [_devis_dict(db, d, detail=False) for d in ds]


@router.get("/devis/{devis_id}")
def detail_devis(devis_id: uuid.UUID, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    d, _ = _devis_ou_404(db, devis_id, user)
    return _devis_dict(db, d)


@router.post("/devis", status_code=status.HTTP_201_CREATED)
def creer_devis(societe_id: uuid.UUID, payload: DevisIn, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    societe = db.get(models.Societe, societe_id)
    tiers = db.get(models.Tiers, payload.tiers_id)
    if not tiers or tiers.type != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez un client.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins une ligne.")
    jour = payload.date_devis or date.today()
    d = models.Devis(societe_id=societe_id,
                     numero=services.next_numero(db, "devis", jour.year, societe.code, societe.id),
                     tiers_id=tiers.id, date_devis=jour, validite=payload.validite,
                     remise_globale_pct=payload.remise_globale_pct,
                     conditions=(payload.conditions or "").strip() or None,
                     note=(payload.note or "").strip() or None, created_by=user.id)
    db.add(d)
    db.flush()
    _calculer_lignes(db, d, societe_id, payload.lignes)
    services.enregistrer_audit(db, user.id, "INSERT", "devis", d.id, None,
                               {"numero": d.numero, "ttc": float(d.total_ttc)})
    db.commit()
    return _devis_dict(db, d)


@router.put("/devis/{devis_id}")
def modifier_devis(devis_id: uuid.UUID, payload: DevisIn, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    d, _ = _devis_ou_404(db, devis_id, user)
    if d.statut not in ("brouillon", "envoye"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Seul un devis brouillon ou envoyé peut être modifié — la commande est confirmée.")
    tiers = db.get(models.Tiers, payload.tiers_id)
    if not tiers or tiers.type != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sélectionnez un client.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins une ligne.")
    d.tiers_id = tiers.id
    d.date_devis = payload.date_devis or d.date_devis
    d.validite = payload.validite
    d.remise_globale_pct = payload.remise_globale_pct
    d.conditions = (payload.conditions or "").strip() or None
    d.note = (payload.note or "").strip() or None
    _calculer_lignes(db, d, d.societe_id, payload.lignes)
    services.enregistrer_audit(db, user.id, "UPDATE", "devis", d.id, None,
                               {"numero": d.numero, "ttc": float(d.total_ttc)})
    db.commit()
    return _devis_dict(db, d)


@router.post("/devis/{devis_id}/envoyer")
def envoyer_devis(devis_id: uuid.UUID, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    d, _ = _devis_ou_404(db, devis_id, user)
    if d.statut != "brouillon":
        raise HTTPException(status.HTTP_409_CONFLICT, "Seul un brouillon peut être marqué « envoyé ».")
    d.statut = "envoye"
    services.enregistrer_audit(db, user.id, "ENVOI", "devis", d.id, None, {"numero": d.numero})
    db.commit()
    return _devis_dict(db, d)


class AssociationIn(BaseModel):
    ligne_id: uuid.UUID
    article_id: uuid.UUID | None = None       # article existant du vendeur…
    nouvel_article: dict | None = None        # …ou création : {code, designation?, prix_achat?, prix_vente?, unite?}


def _associer_ligne(db: Session, d: models.Devis, a: AssociationIn, user_id) -> None:
    """Associe une ligne du PO à un article du VENDEUR (réponse à la question de
    Laurent : article inconnu chez DAKAM → on l'associe à son stock ou on le crée)."""
    ligne = next((l for l in d.lignes if str(l.id) == str(a.ligne_id)), None)
    if not ligne:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne étrangère à la commande.")
    if a.article_id:
        art = db.get(models.Article, a.article_id)
        if not art or art.societe_id != d.societe_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Article invalide pour cette société.")
    elif a.nouvel_article and (a.nouvel_article.get("code") or "").strip():
        na = a.nouvel_article
        code = str(na["code"]).strip().upper()
        art = db.execute(select(models.Article).where(
            models.Article.societe_id == d.societe_id,
            models.Article.code == code)).scalars().first()
        if not art:
            art = models.Article(societe_id=d.societe_id, code=code,
                                 designation=str(na.get("designation") or ligne.designation).strip(),
                                 unite=str(na.get("unite") or "unité"),
                                 prix_achat=float(na.get("prix_achat") or 0),
                                 prix_vente=float(na.get("prix_vente") or ligne.prix_unitaire))
            db.add(art)
            db.flush()
    else:
        return
    ligne.article_id = art.id
    services.enregistrer_audit(db, user_id, "ASSOCIATION", "ligne_devis", ligne.id, None,
                               {"article": art.code, "devis": d.numero})


class ConfirmerIn(BaseModel):
    reference_producteur: str | None = None   # n° de commande chez le producteur (réconciliations)
    associations: list[AssociationIn] = []    # lignes ↔ articles du vendeur


@router.post("/devis/{devis_id}/confirmer")
def confirmer_devis(devis_id: uuid.UUID, payload: ConfirmerIn | None = None,
                    db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Prise en charge : le devis devient la commande client. Pour une commande
    du groupe, le préposé renseigne le N° PRODUCTEUR (commande chez le
    fournisseur du vendeur, ex. GCK) — il suivra tous les documents."""
    d, _ = _devis_ou_404(db, devis_id, user)
    if d.statut not in ("brouillon", "envoye"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Devis déjà confirmé ou annulé.")
    d.statut = "confirme"
    d.date_confirmation = func.now()
    if payload:
        for a in payload.associations:
            _associer_ligne(db, d, a, user.id)
    if payload and payload.reference_producteur is not None:
        ref = payload.reference_producteur.strip() or None
        d.reference_producteur = ref
        # propage jusqu'au PO de l'acheteur (visible sur ses documents aussi)
        if ref and d.commande_origine_id:
            cmd = db.get(models.Commande, d.commande_origine_id)
            if cmd:
                cmd.reference_fournisseur = ref
    services.enregistrer_audit(db, user.id, "CONFIRMATION", "devis", d.id, None,
                               {"numero": d.numero, "ref_producteur": d.reference_producteur})
    db.commit()
    return _devis_dict(db, d)


@router.post("/devis/{devis_id}/associer")
def associer_articles(devis_id: uuid.UUID, payload: AssociationIn,
                      db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Associer (ou créer) l'article du vendeur pour une ligne — possible aussi
    après la prise en charge, tant que la ligne n'est pas chargée."""
    d, _ = _devis_ou_404(db, devis_id, user)
    _associer_ligne(db, d, payload, user.id)
    db.commit()
    return _devis_dict(db, d)


class RefProducteurIn(BaseModel):
    reference_producteur: str


@router.post("/devis/{devis_id}/reference-producteur")
def maj_reference_producteur(devis_id: uuid.UUID, payload: RefProducteurIn,
                             db: Session = Depends(get_db),
                             user: models.Utilisateur = Depends(get_current_user)):
    """Renseigner / corriger le n° producteur après coup (avant facturation)."""
    d, _ = _devis_ou_404(db, devis_id, user)
    ref = payload.reference_producteur.strip() or None
    d.reference_producteur = ref
    if ref and d.commande_origine_id:
        cmd = db.get(models.Commande, d.commande_origine_id)
        if cmd:
            cmd.reference_fournisseur = ref
    db.commit()
    return _devis_dict(db, d)


@router.post("/devis/{devis_id}/annuler")
def annuler_devis(devis_id: uuid.UUID, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    d, _ = _devis_ou_404(db, devis_id, user)
    if any(float(l.qte_livree) > 0 or float(l.qte_facturee) > 0 for l in d.lignes):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Impossible d'annuler : des livraisons ou factures existent déjà.")
    if d.statut == "annule":
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà annulé.")
    d.statut = "annule"
    services.enregistrer_audit(db, user.id, "ANNULATION", "devis", d.id, None, {"numero": d.numero})
    db.commit()
    return _devis_dict(db, d)


# ── Livraison (BL) — sortie de stock au CUMP ─────────────────────────
@router.post("/devis/{devis_id}/livrer", status_code=status.HTTP_201_CREATED)
def livrer(devis_id: uuid.UUID, payload: LivraisonIn, db: Session = Depends(get_db),
           user: models.Utilisateur = Depends(get_current_user)):
    d, _ = _devis_ou_404(db, devis_id, user)
    if d.statut != "confirme":
        raise HTTPException(status.HTTP_409_CONFLICT, "Confirmez la commande avant de livrer.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucune quantité à livrer.")
    societe = db.get(models.Societe, d.societe_id)
    jour = date.today()
    numero = services.next_numero(db, "livraison", jour.year, societe.code, societe.id)
    bl = models.Livraison(societe_id=d.societe_id, devis_id=d.id, numero=numero,
                          date_livraison=jour, note=(payload.note or "").strip() or None,
                          created_by=user.id)
    db.add(bl)
    db.flush()

    lignes_par_id = {str(l.id): l for l in d.lignes}
    po = bool(d.commande_origine_id)
    stock_par_compte: dict[str, float] = {}
    for rl in payload.lignes:
        orig = lignes_par_id.get(str(rl.ligne_id))
        if not orig:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne étrangère à la commande.")
        art = db.get(models.Article, orig.article_id) if orig.article_id else None
        gere = bool(art and art.gere_stock)
        # PO du groupe : chaque ligne doit être ASSOCIÉE à un article du vendeur
        # (prise en charge) — plus de chargement sans stock (règle de Laurent)
        if po and not art:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"« {orig.designation} » : associez d'abord cette ligne à un article "
                                "de votre stock (bouton « Associer les articles » de la commande).")
        if not gere and not po:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"« {orig.designation} » n'est pas un article en stock — rien à livrer.")
        qte = float(rl.qte)
        restant = round(float(orig.qte) - float(orig.qte_livree), 3)
        if qte > restant + 1e-6:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{qte} demandé mais {restant} restant à livrer sur « {orig.designation} ».")
        cump = val = 0.0
        if gere:
            if float(art.stock_qte) < qte - 1e-6:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Stock insuffisant pour {art.code} : {float(art.stock_qte)} disponible, {qte} à livrer.")
            cump = float(art.stock_valeur) / float(art.stock_qte) if art.stock_qte else 0.0
            val = round(qte * cump, 2)
            art.stock_qte = round(float(art.stock_qte) - qte, 3)
            art.stock_valeur = round(float(art.stock_valeur) - val, 2)
            stock_par_compte[art.compte_stock] = round(stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            db.add(models.MouvementStock(societe_id=d.societe_id, article_id=art.id, date_mvt=jour,
                                         sens="sortie", qte=qte, cout_unitaire=round(cump, 4),
                                         valeur=val, type_operation="livraison", reference=numero))
        orig.qte_livree = round(float(orig.qte_livree) + qte, 3)
        db.add(models.LigneLivraison(livraison_id=bl.id, ligne_devis_id=orig.id,
                                     article_id=art.id if art else None, designation=orig.designation,
                                     qte=qte, cout_unitaire=round(cump, 4), valeur=val))

    if stock_par_compte:
        # PO du groupe : la sortie de stock reste EN ATTENTE — le comptable la
        # valide (avec pièces jointes) dans « Pièces en attente » (règle NB3)
        comptabilite.comptabiliser_stock_sortie(db, societe, stock_par_compte, numero, jour,
                                                "livraison", bl.id, user.id,
                                                statut="en_attente" if po else "valide")
    services.enregistrer_audit(db, user.id, "INSERT", "livraison", bl.id, None,
                               {"numero": numero, "devis": d.numero})
    db.commit()
    return _devis_dict(db, d)


# ── Facturation des quantités livrées ────────────────────────────────
@router.post("/devis/{devis_id}/facturer", status_code=status.HTTP_201_CREATED)
def facturer(devis_id: uuid.UUID, payload: FacturerIn | None = None,
             db: Session = Depends(get_db),
             user: models.Utilisateur = Depends(get_current_user)):
    """Facture les quantités livrées non encore facturées (et les lignes libres
    non stockées). Pas de mouvement de stock ici — il est sorti à la livraison."""
    d, _ = _devis_ou_404(db, devis_id, user)
    if d.statut != "confirme":
        raise HTTPException(status.HTTP_409_CONFLICT, "Confirmez la commande avant de facturer.")
    # PO intersociété : facturation conditionnée à la réception physique de
    # l'acheteur (bon/mauvais/manquant) sur tout ce qui a été chargé
    if d.commande_origine_id:
        from .intersociete import reception_po_resume
        cmd_po = db.get(models.Commande, d.commande_origine_id)
        if cmd_po:
            r = reception_po_resume(db, cmd_po)
            if r["totaux"]["livre"] > 0 and not r["complete"]:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Facturation bloquée : l'acheteur n'a pas encore réceptionné "
                                    "toute la marchandise chargée (règle du groupe — la facture suit "
                                    "la réception).")
    societe = db.get(models.Societe, d.societe_id)
    jour = date.today()
    po = bool(d.commande_origine_id)
    a_facturer = []
    for l in d.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        qf = _facturable(l, art, po)
        if qf > 0:
            a_facturer.append((l, art, qf))
    if not a_facturer:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Rien à facturer — livrez d'abord (ou tout est déjà facturé).")

    numero = services.next_numero(db, "facture_vente", jour.year, societe.code, societe.id)
    # PO du groupe : la facture arrive TOUJOURS en attente de validation comptable
    statut_piece = "en_attente" if po else _statut_piece(db, d.societe_id, "vente")
    fac = models.Facture(societe_id=d.societe_id, type="vente", numero=numero,
                         tiers_id=d.tiers_id, date_facture=jour,
                         echeance=payload.echeance if payload else None,
                         reference=d.reference_producteur,   # n° producteur sur la facture
                         statut="validee" if statut_piece == "valide" else "en_attente",
                         devis_id=d.id, created_by=user.id)
    db.add(fac)
    db.flush()

    total_ht = total_tva = cout_total = 0.0
    lm_list = []
    for l, art, qf in a_facturer:
        ht = round(float(l.montant_ht) * qf / float(l.qte), 2)
        tva = round(float(l.montant_tva) * qf / float(l.qte), 2)
        total_ht += ht
        total_tva += tva
        # coût : CUMP moyen des livraisons de la ligne (0 pour les lignes libres)
        cump_rows = db.execute(
            select(func.coalesce(func.sum(models.LigneLivraison.valeur), 0),
                   func.coalesce(func.sum(models.LigneLivraison.qte), 0))
            .where(models.LigneLivraison.ligne_devis_id == l.id)).one()
        cump_moy = float(cump_rows[0]) / float(cump_rows[1]) if float(cump_rows[1]) else 0.0
        cout = round(qf * cump_moy, 2)
        cout_total += cout
        lm = models.LigneFacture(facture_id=fac.id, article_id=l.article_id,
                                 designation=l.designation, qte=qf,
                                 prix_unitaire=float(l.prix_unitaire),
                                 remise_pct=float(l.remise_pct or 0),
                                 taux_tva=float(l.taux_tva), montant_ht=ht, montant_tva=tva)
        db.add(lm)
        lm_list.append(lm)
        l.qte_facturee = round(float(l.qte_facturee) + qf, 3)

    fac.total_ht = round(total_ht, 2)
    fac.total_tva = round(total_tva, 2)
    fac.total_ttc = round(total_ht + total_tva, 2)
    fac.cout_ventes = round(cout_total, 2)
    fac.marge = round(fac.total_ht - cout_total, 2)
    ecr = comptabilite.comptabiliser_facture(db, fac, lm_list, user.id, statut=statut_piece)
    fac.ecriture_id = ecr.id
    # Intersociété : commande client d'une société du groupe → facture d'achat miroir
    from .intersociete import creer_facture_miroir
    creer_facture_miroir(db, fac, user.id)
    # PO d'origine chez l'acheteur : tout est facturé → la commande est soldée
    if d.commande_origine_id and all(_facturable(l, db.get(models.Article, l.article_id)
                                                 if l.article_id else None, po=True) <= 0
                                     for l in d.lignes):
        cmd_origine = db.get(models.Commande, d.commande_origine_id)
        if cmd_origine:
            cmd_origine.statut = "soldee"
    services.enregistrer_audit(db, user.id, "INSERT", "facture", fac.id, None,
                               {"numero": numero, "devis": d.numero, "ttc": float(fac.total_ttc)})
    db.commit()
    return {"facture": {"id": str(fac.id), "numero": numero, "total_ttc": float(fac.total_ttc)},
            "devis": _devis_dict(db, d)}


# ── Règlement client (encaissement sur facture) ──────────────────────
@router.post("/factures/{facture_id}/regler", status_code=status.HTTP_201_CREATED)
def regler_facture(facture_id: uuid.UUID, payload: ReglementIn, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    """Encaisse un règlement client : D trésorerie / C 411 (tiers, lettrable).
    Espèces → entrée dans la caisse choisie (session ouverte requise)."""
    fac = db.get(models.Facture, facture_id)
    if not fac or fac.type != "vente":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture de vente introuvable.")
    roles = assert_acces_societe(db, user, fac.societe_id)
    assert_role(roles, ROLES | {"CAISSIER_CENTRAL"})
    societe = db.get(models.Societe, fac.societe_id)
    tiers = db.get(models.Tiers, fac.tiers_id)
    sit = _reglement_facture(db, fac)
    solde = sit["solde_du_usd"]
    if solde <= 0.009:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cette facture est déjà réglée.")

    jour = date.today()
    taux = None
    if payload.devise == "CDF":
        t = services.get_taux_jour(db, jour, "CDF")
        if not t:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Aucun taux USD/CDF défini aujourd'hui — définissez le taux du jour.")
        taux = float(t)
        montant_usd = round(payload.montant / taux, 2)
    else:
        montant_usd = round(payload.montant, 2)
    if montant_usd > solde + 0.01:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Règlement de {montant_usd:.2f} USD supérieur au solde dû ({solde:.2f} USD).")

    caisse = sess = None
    if payload.mode == "espece":
        if not payload.caisse_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choisissez la caisse qui encaisse.")
        caisse = db.get(models.Caisse, payload.caisse_id)
        if not caisse or caisse.societe_id != fac.societe_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Caisse invalide.")
        from .caisse import _session_ouverte
        sess = _session_ouverte(db, caisse.id)
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Ouvrez la caisse « {caisse.libelle} » avant d'encaisser.")
        compte_tres = caisse.compte_comptable
    elif payload.mode == "banque":
        compte_tres = comptabilite._compte(db, "compte_banque", fac.societe_id)
    else:
        compte_tres = comptabilite._compte(db, "compte_mobile_money", fac.societe_id)

    lignes = [{"sens": "D", "compte": compte_tres, "montant_usd": montant_usd,
               "devise_origine": payload.devise, "montant_origine": round(payload.montant, 2),
               "taux_jour": taux, "libelle": f"Règlement {fac.numero} — {tiers.nom}"},
              {"sens": "C", "compte": comptabilite._compte(db, "compte_client", fac.societe_id),
               "montant_usd": montant_usd, "tiers_id": tiers.id,
               "libelle": f"Règlement client {tiers.nom} — {fac.numero}"}]
    ecr = comptabilite.post_ecriture(db, societe, "VE", "Ventes", "vente", jour,
                                     f"Règlement {fac.numero} — {tiers.nom}", lignes,
                                     "reglement_client", "facture", fac.id, fac.numero,
                                     user.id, statut="valide")
    db.add(models.PaiementFacture(facture_id=fac.id, mode=payload.mode, devise=payload.devise,
                                  montant=round(payload.montant, 2), taux_jour=taux,
                                  montant_usd=montant_usd,
                                  reference=(payload.reference or "").strip() or None,
                                  compte=compte_tres))
    if caisse:
        db.add(models.MouvementCaisse(
            caisse_id=caisse.id, session_id=sess.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
            reference=fac.numero, sens="entree", nature="Encaissement client",
            devise=payload.devise, taux_jour=taux, montant=round(payload.montant, 2),
            montant_usd=montant_usd, tiers_id=tiers.id, tiers_nom=tiers.nom,
            reference_type="facture", reference_id=fac.id,
            libelle=f"Règlement {fac.numero} — {tiers.nom}", created_by=user.id))
    services.enregistrer_audit(db, user.id, "REGLEMENT", "facture", fac.id, None,
                               {"numero": fac.numero, "montant_usd": montant_usd, "mode": payload.mode})
    db.commit()
    sit = _reglement_facture(db, fac)
    return {"ecriture": ecr.numero, **sit}


# ── Encours clients (balance âgée simplifiée) ────────────────────────
@router.get("/encours")
def encours_clients(societe_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Créances clients : solde 41x par client + factures non soldées (retards)."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    rows = db.execute(
        select(models.LigneEcriture.tiers_id, models.LigneEcriture.sens,
               func.coalesce(func.sum(models.LigneEcriture.montant_usd), 0))
        .where(models.LigneEcriture.societe_id == societe_id,
               models.LigneEcriture.tiers_id.is_not(None),
               models.LigneEcriture.compte_numero.like("41%"))
        .group_by(models.LigneEcriture.tiers_id, models.LigneEcriture.sens)).all()
    soldes: dict = {}
    for tiers_id, sens, montant in rows:
        soldes[tiers_id] = round(soldes.get(tiers_id, 0.0)
                                 + (float(montant) if sens == "D" else -float(montant)), 2)
    out = []
    for tiers_id, solde in soldes.items():
        if abs(solde) < 0.01:
            continue
        t = db.get(models.Tiers, tiers_id)
        facs = db.execute(select(models.Facture).where(
            models.Facture.societe_id == societe_id, models.Facture.tiers_id == tiers_id,
            models.Facture.type == "vente")).scalars().all()
        dues = []
        for f in facs:
            sit = _reglement_facture(db, f)
            if sit["solde_du_usd"] > 0.009:
                dues.append({"numero": f.numero, "date": f.date_facture.isoformat(),
                             "echeance": f.echeance.isoformat() if f.echeance else None,
                             "solde_du_usd": sit["solde_du_usd"], "en_retard": sit["en_retard"]})
        out.append({"tiers_id": str(tiers_id), "client": t.nom if t else "?",
                    "solde_usd": solde,
                    "limite_credit_usd": float(t.limite_credit_usd) if t and t.limite_credit_usd is not None else None,
                    "factures_dues": sorted(dues, key=lambda x: x["date"]),
                    "en_retard": any(x["en_retard"] for x in dues)})
    return sorted(out, key=lambda x: -x["solde_usd"])
