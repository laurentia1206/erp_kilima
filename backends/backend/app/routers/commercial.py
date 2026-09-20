"""Cycle commercial — articles, factures d'achat / de vente, stock, TVA.

Chaque facture validée se déverse automatiquement en comptabilité (écriture
d'achat ou de vente avec TVA) et met à jour le stock valorisé au coût moyen
pondéré (CUMP). Les ventes calculent leur coût des ventes et leur marge.
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

router = APIRouter(prefix="/api/commercial", tags=["commercial"])
ROLES = {"COMPTABLE", "DFI"}
ROLES_POS = {"COMPTABLE", "DFI", "CAISSIER_CENTRAL", "CAISSIER_VENDEUR"}


# ── Articles ─────────────────────────────────────────────────────────
class ArticleIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    designation: str = Field(min_length=1)
    unite: str = "unité"
    prix_achat: float = 0
    prix_vente: float = 0
    assujetti_tva: bool = True
    taux_tva: float | None = None        # None → taux par défaut de la société (config)
    categorie: str | None = None
    code_barres: str | None = None
    taux_commission: float = 0
    points_fidelite: float = 0
    compte_achat: str = "601"
    compte_vente: str = "701"
    compte_stock: str = "31"
    gere_stock: bool = True


class ArticleMaj(BaseModel):
    designation: str | None = None
    prix_achat: float | None = None
    prix_vente: float | None = None
    assujetti_tva: bool | None = None
    taux_tva: float | None = None
    categorie: str | None = None
    code_barres: str | None = None
    taux_commission: float | None = None
    points_fidelite: float | None = None
    actif: bool | None = None


def _article_dict(a: models.Article) -> dict:
    qte = float(a.stock_qte or 0)
    val = float(a.stock_valeur or 0)
    return {"id": str(a.id), "code": a.code, "designation": a.designation, "unite": a.unite,
            "prix_achat": float(a.prix_achat), "prix_vente": float(a.prix_vente),
            "assujetti_tva": bool(a.assujetti_tva), "taux_tva": float(a.taux_tva),
            "categorie": a.categorie, "code_barres": a.code_barres,
            "taux_commission": float(a.taux_commission), "points_fidelite": float(a.points_fidelite),
            "compte_achat": a.compte_achat, "compte_vente": a.compte_vente, "compte_stock": a.compte_stock,
            "gere_stock": bool(a.gere_stock), "actif": bool(a.actif),
            "stock_qte": round(qte, 3), "stock_valeur": round(val, 2),
            "cump": round(val / qte, 2) if qte else 0.0}


@router.get("/articles")
def lister_articles(societe_id: uuid.UUID, q: str | None = None, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    arts = db.execute(select(models.Article).where(models.Article.societe_id == societe_id)
                      .order_by(models.Article.code)).scalars().all()
    if q:
        ql = q.lower()
        arts = [a for a in arts if ql in a.code.lower() or ql in a.designation.lower()]
    return [_article_dict(a) for a in arts]


@router.post("/articles", status_code=status.HTTP_201_CREATED)
def creer_article(societe_id: uuid.UUID, payload: ArticleIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    code = payload.code.strip().upper()
    if db.execute(select(models.Article).where(models.Article.societe_id == societe_id,
                                               models.Article.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"L'article {code} existe déjà.")
    taux = payload.taux_tva if payload.taux_tva is not None else float(
        services.get_parametre(db, "tva.taux_defaut", societe_id, "16"))
    a = models.Article(societe_id=societe_id, code=code, designation=payload.designation.strip(),
                       unite=payload.unite, prix_achat=payload.prix_achat, prix_vente=payload.prix_vente,
                       assujetti_tva=payload.assujetti_tva, taux_tva=taux if payload.assujetti_tva else 0,
                       categorie=(payload.categorie or None), code_barres=(payload.code_barres or None),
                       taux_commission=payload.taux_commission, points_fidelite=payload.points_fidelite,
                       compte_achat=payload.compte_achat, compte_vente=payload.compte_vente,
                       compte_stock=payload.compte_stock, gere_stock=payload.gere_stock)
    db.add(a)
    db.commit()
    return _article_dict(a)


@router.patch("/articles/{article_id}")
def maj_article(article_id: uuid.UUID, payload: ArticleMaj, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    a = db.get(models.Article, article_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article introuvable.")
    roles = assert_acces_societe(db, user, a.societe_id)
    assert_role(roles, ROLES)
    for f in ("designation", "prix_achat", "prix_vente", "assujetti_tva", "taux_tva",
              "categorie", "code_barres", "taux_commission", "points_fidelite", "actif"):
        v = getattr(payload, f)
        if v is not None:
            setattr(a, f, v.strip() if isinstance(v, str) else v)
    if payload.assujetti_tva is False:
        a.taux_tva = 0
    db.commit()
    return _article_dict(a)


# ── Tiers (clients / fournisseurs) ───────────────────────────────────
class TiersIn(BaseModel):
    type: str = Field(pattern="^(client|fournisseur)$")
    code: str = Field(min_length=1, max_length=30)
    nom: str = Field(min_length=1)
    intra_groupe: bool = False
    limite_credit_usd: float | None = None


def _tiers_dict(t: models.Tiers) -> dict:
    return {"id": str(t.id), "type": t.type, "code": t.code, "nom": t.nom,
            "intra_groupe": bool(t.intra_groupe),
            "limite_credit_usd": float(t.limite_credit_usd) if t.limite_credit_usd is not None else None,
            "points_fidelite": float(t.points_fidelite or 0)}


@router.get("/tiers")
def lister_tiers(societe_id: uuid.UUID, type: str | None = None, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)     # le caissier POS doit pouvoir chercher un client
    q = select(models.Tiers).where(
        (models.Tiers.societe_id == societe_id) | (models.Tiers.societe_id.is_(None)))
    if type:
        q = q.where(models.Tiers.type == type)
    ts = db.execute(q.order_by(models.Tiers.nom)).scalars().all()
    return [_tiers_dict(t) for t in ts]


@router.post("/tiers", status_code=status.HTTP_201_CREATED)
def creer_tiers(societe_id: uuid.UUID, payload: TiersIn, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)     # création rapide d'un client depuis le POS
    t = models.Tiers(societe_id=societe_id, type=payload.type, code=payload.code.strip().upper(),
                     nom=payload.nom.strip(), intra_groupe=payload.intra_groupe,
                     limite_credit_usd=payload.limite_credit_usd)
    db.add(t)
    db.commit()
    return _tiers_dict(t)


class TiersMaj(BaseModel):
    nom: str | None = None
    type: str | None = Field(default=None, pattern="^(client|fournisseur|personnel)$")
    limite_credit_usd: float | None = None
    compte_auxiliaire: str | None = None
    actif: bool | None = None


@router.patch("/tiers/{tiers_id}")
def maj_tiers(tiers_id: uuid.UUID, payload: TiersMaj, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    t = db.get(models.Tiers, tiers_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tiers introuvable.")
    roles = assert_acces_societe(db, user, t.societe_id)
    assert_role(roles, ROLES)
    for f in ("nom", "type", "limite_credit_usd", "compte_auxiliaire", "actif"):
        v = getattr(payload, f)
        if v is not None:
            setattr(t, f, v.strip() if isinstance(v, str) else v)
    services.enregistrer_audit(db, user.id, "UPDATE", "tiers", t.id, None, {"nom": t.nom})
    db.commit()
    return _tiers_dict(t)


# ── Factures ─────────────────────────────────────────────────────────
class LigneFactureIn(BaseModel):
    article_id: uuid.UUID | None = None
    designation: str | None = None
    qte: float = Field(gt=0)
    prix_unitaire: float = Field(ge=0)
    taux_tva: float | None = None


class FraisIn(BaseModel):
    libelle: str = Field(min_length=1)
    compte: str = "6085"                  # frais sur achats (SYSCOHADA)
    montant_ht: float = Field(gt=0)
    taux_tva: float | None = None
    mode: str = Field(default="credit", pattern="^(credit|banque|caisse)$")   # contrepartie du frais
    tiers_id: uuid.UUID | None = None     # si crédit : fournisseur du frais (défaut = fournisseur des marchandises)
    banque_id: uuid.UUID | None = None    # si banque
    caisse_id: uuid.UUID | None = None    # si caisse (session ouverte requise)


class FactureIn(BaseModel):
    type: str = Field(pattern="^(achat|vente)$")
    tiers_id: uuid.UUID
    date_facture: date | None = None
    echeance: date | None = None
    intra_groupe: bool = False
    lignes: list[LigneFactureIn]
    frais: list[FraisIn] = []                       # frais accessoires (achat)
    repartition: str = Field(default="quantite", pattern="^(quantite|valeur)$")


def _reglement_facture(db: Session, f: models.Facture) -> dict:
    """Situation de règlement d'une facture de vente : encaissé / solde / statut.
    (Les paiements « credit » ne sont pas des encaissements — c'est la créance.)"""
    if f.type != "vente":
        return {}
    regle = round(sum(float(p.montant_usd) for p in db.execute(
        select(models.PaiementFacture).where(
            models.PaiementFacture.facture_id == f.id,
            models.PaiementFacture.mode != "credit")).scalars()), 2)
    solde = round(float(f.total_ttc) - regle, 2)
    statut = "payee" if solde <= 0.009 else ("partielle" if regle > 0 else "due")
    retard = bool(f.echeance and solde > 0.009 and f.echeance < date.today())
    return {"regle_usd": regle, "solde_du_usd": max(solde, 0.0),
            "statut_reglement": statut, "en_retard": retard,
            "devis_id": str(f.devis_id) if f.devis_id else None}


def _statut_piece(db: Session, societe_id, sens: str) -> str:
    """Revue comptable hybride : les pièces d'achat/vente peuvent être mises « en
    attente » de validation par le comptable avant de devenir définitives. Par défaut
    achats = en attente, ventes = directes. Configurable par société (compta.revue_*)."""
    key = "compta.revue_achats" if sens == "achat" else "compta.revue_ventes"
    defaut = "1" if sens == "achat" else "0"
    return "en_attente" if services.get_parametre(db, key, societe_id, defaut) == "1" else "valide"


def _resoudre_contrepartie_frais(db, societe, f, jour, ref_numero, ref_type, ref_id, fht, ftva, user):
    """Résout la contrepartie réelle d'un frais accessoire (jamais flottant) :
    - crédit : dette envers le fournisseur du frais (401) — contrepartie par tiers ;
    - banque : sortie sur un compte bancaire ;
    - caisse : sortie de caisse RÉELLE (session ouverte exigée) → crée le mouvement.
    Retourne (compte_reglement, caisse_id)."""
    if f.mode == "banque":
        b = db.get(models.CompteBancaire, f.banque_id) if f.banque_id else None
        if not b or b.societe_id != societe.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Banque du frais invalide.")
        return b.compte_comptable, None
    if f.mode == "caisse":
        c = db.get(models.Caisse, f.caisse_id) if f.caisse_id else None
        if not c or c.societe_id != societe.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Caisse du frais invalide.")
        sess = db.execute(select(models.SessionCaisse).where(
            models.SessionCaisse.caisse_id == c.id, models.SessionCaisse.statut == "ouverte")).scalars().first()
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Ouvrez la caisse « {c.libelle} » pour régler ce frais.")
        db.add(models.MouvementCaisse(
            caisse_id=c.id, session_id=sess.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
            reference=ref_numero, sens="sortie", nature=f"Frais achat — {f.libelle}", devise="USD",
            montant=round(fht + ftva, 2), montant_usd=round(fht + ftva, 2),
            reference_type=ref_type, reference_id=ref_id,
            libelle=f"{f.libelle} ({ref_numero})", created_by=user.id))
        return c.compte_comptable, c.id
    return None, None   # crédit : contrepartie par tiers (résolue à la comptabilisation)


def _facture_dict(db: Session, f: models.Facture) -> dict:
    tiers = db.get(models.Tiers, f.tiers_id)
    lignes = db.execute(select(models.LigneFacture).where(
        models.LigneFacture.facture_id == f.id)).scalars().all()
    arts = {}
    for l in lignes:
        if l.article_id and l.article_id not in arts:
            a = db.get(models.Article, l.article_id)
            arts[l.article_id] = a.code if a else None
    frais = db.execute(select(models.FraisFacture).where(
        models.FraisFacture.facture_id == f.id)).scalars().all()
    return {
        "id": str(f.id), "numero": f.numero, "type": f.type,
        "tiers": tiers.nom if tiers else None, "tiers_id": str(f.tiers_id),
        "date": f.date_facture.isoformat(), "echeance": f.echeance.isoformat() if f.echeance else None,
        "reference": f.reference,
        "total_ht": float(f.total_ht), "total_frais": float(f.total_frais),
        "total_tva": float(f.total_tva), "total_ttc": float(f.total_ttc),
        "repartition": f.repartition,
        "cout_ventes": float(f.cout_ventes) if f.cout_ventes is not None else None,
        "marge": float(f.marge) if f.marge is not None else None,
        "intra_groupe": bool(f.intra_groupe), "statut": f.statut,
        **_reglement_facture(db, f),
        "lignes": [{"article": arts.get(l.article_id), "designation": l.designation,
                    "qte": float(l.qte), "prix_unitaire": float(l.prix_unitaire),
                    "remise_pct": float(l.remise_pct or 0),
                    "taux_tva": float(l.taux_tva), "montant_ht": float(l.montant_ht),
                    "montant_tva": float(l.montant_tva),
                    "frais_reparti": float(l.frais_reparti), "cout_entree": float(l.cout_entree)}
                   for l in lignes],
        "frais": [{"libelle": x.libelle, "compte": x.compte, "montant_ht": float(x.montant_ht),
                   "taux_tva": float(x.taux_tva), "montant_tva": float(x.montant_tva), "mode": x.mode,
                   "contrepartie": (db.get(models.Tiers, x.tiers_id).nom if x.tiers_id else None)
                   if x.mode == "credit" else (x.compte_reglement or "")} for x in frais],
    }


@router.post("/factures", status_code=status.HTTP_201_CREATED)
def creer_facture(societe_id: uuid.UUID, payload: FactureIn, db: Session = Depends(get_db),
                  user: models.Utilisateur = Depends(get_current_user)):
    """Crée une facture, met à jour le stock (CUMP) et génère l'écriture comptable."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    societe = db.get(models.Societe, societe_id)
    tiers = db.get(models.Tiers, payload.tiers_id)
    if not tiers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tiers introuvable.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins une ligne.")

    jour = payload.date_facture or date.today()
    numero = services.next_numero(db, f"facture_{payload.type}", jour.year, societe.code, societe.id)
    fac = models.Facture(societe_id=societe_id, type=payload.type, numero=numero,
                         tiers_id=tiers.id, date_facture=jour, echeance=payload.echeance,
                         intra_groupe=payload.intra_groupe or bool(tiers.intra_groupe),
                         statut="validee", created_by=user.id)
    db.add(fac)
    db.flush()

    total_ht = total_tva = 0.0
    lm_pairs = []
    defaut_tva = float(services.get_parametre(db, "tva.taux_defaut", societe_id, "16"))
    for l in payload.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        if l.article_id and not art:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Article introuvable.")
        taux = l.taux_tva if l.taux_tva is not None else (float(art.taux_tva) if art else defaut_tva)
        if art is not None and not art.assujetti_tva:
            taux = 0.0                                   # article non assujetti → pas de TVA
        ht = round(l.qte * l.prix_unitaire, 2)
        tva = round(ht * taux / 100, 2)
        total_ht += ht
        total_tva += tva
        lm = models.LigneFacture(facture_id=fac.id, article_id=l.article_id,
                                 designation=(l.designation or (art.designation if art else "")).strip(),
                                 qte=l.qte, prix_unitaire=l.prix_unitaire, taux_tva=taux,
                                 montant_ht=ht, montant_tva=tva, cout_entree=ht)
        db.add(lm)
        lm_pairs.append((lm, art))

    # ── Frais annexes (achat) : chacun avec SA contrepartie + répartition stock ──
    frais_objs = []
    total_frais = total_frais_tva = 0.0
    if payload.type == "achat":
        for f in payload.frais:
            ftaux = f.taux_tva if f.taux_tva is not None else 16.0
            fht = round(f.montant_ht, 2)
            ftva = round(fht * ftaux / 100, 2)
            total_frais += fht
            total_frais_tva += ftva
            compte_reg, caisse_id = _resoudre_contrepartie_frais(
                db, societe, f, jour, numero, "facture", fac.id, fht, ftva, user)
            ff = models.FraisFacture(facture_id=fac.id, libelle=f.libelle.strip(), compte=f.compte,
                                     montant_ht=fht, taux_tva=ftaux, montant_tva=ftva,
                                     mode=f.mode, tiers_id=f.tiers_id, compte_reglement=compte_reg, caisse_id=caisse_id)
            db.add(ff)
            frais_objs.append(ff)
        total_frais = round(total_frais, 2)
        total_frais_tva = round(total_frais_tva, 2)

        stock_lines = [(lm, art) for lm, art in lm_pairs if art and art.gere_stock]
        if total_frais > 0 and stock_lines:
            weights = [float(lm.montant_ht) if payload.repartition == "valeur" else float(lm.qte)
                       for lm, _ in stock_lines]
            tw = sum(weights) or 1.0
            cumul = 0.0
            for i, (lm, _) in enumerate(stock_lines):
                part = round(total_frais * weights[i] / tw, 2) if i < len(stock_lines) - 1 else round(total_frais - cumul, 2)
                cumul = round(cumul + part, 2)
                lm.frais_reparti = part
                lm.cout_entree = round(float(lm.montant_ht) + part, 2)

    fac.total_ht = round(total_ht, 2)
    fac.total_frais = total_frais
    fac.total_tva = round(total_tva + total_frais_tva, 2)
    fac.total_ttc = round(total_ht + total_frais + total_tva + total_frais_tva, 2)
    fac.repartition = payload.repartition

    # ── Mouvements de stock (CUMP au coût d'acquisition) ────────────
    cout_ventes = 0.0
    stock_par_compte: dict[str, float] = {}   # valeur entrée/sortie par compte de stock
    for lm, art in lm_pairs:
        if not art or not art.gere_stock:
            continue
        qte = float(lm.qte)
        if payload.type == "achat":
            valeur = round(float(lm.cout_entree), 2)   # coût d'acquisition (HT + frais répartis)
            cu = round(valeur / qte, 4) if qte else 0.0
            art.stock_qte = round(float(art.stock_qte) + qte, 3)
            art.stock_valeur = round(float(art.stock_valeur) + valeur, 2)
            db.add(models.MouvementStock(societe_id=societe_id, article_id=art.id, date_mvt=jour,
                                         sens="entree", qte=qte, cout_unitaire=cu,
                                         valeur=valeur, type_operation="achat", reference=numero))
        else:
            if float(art.stock_qte) < qte - 1e-6:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Stock insuffisant pour {art.code} : {float(art.stock_qte)} {art.unite} "
                                    f"disponible(s), {qte} demandé(s).")
            cump = float(art.stock_valeur) / float(art.stock_qte) if art.stock_qte else 0.0
            valeur = round(qte * cump, 2)
            art.stock_qte = round(float(art.stock_qte) - qte, 3)
            art.stock_valeur = round(float(art.stock_valeur) - valeur, 2)
            cout_ventes += valeur
            db.add(models.MouvementStock(societe_id=societe_id, article_id=art.id, date_mvt=jour,
                                         sens="sortie", qte=qte, cout_unitaire=round(cump, 4),
                                         valeur=valeur, type_operation="vente", reference=numero))
        stock_par_compte[art.compte_stock] = round(stock_par_compte.get(art.compte_stock, 0.0) + valeur, 2)

    if payload.type == "vente":
        fac.cout_ventes = round(cout_ventes, 2)
        fac.marge = round(fac.total_ht - cout_ventes, 2)

    statut_piece = _statut_piece(db, societe_id, "achat" if payload.type == "achat" else "vente")
    ecr = comptabilite.comptabiliser_facture(db, fac, [lm for lm, _ in lm_pairs], user.id,
                                             frais_objs=frais_objs, statut=statut_piece)
    fac.ecriture_id = ecr.id
    # Écriture de variation de stock (inventaire permanent) → résultat correct
    for compte_stock, valeur in stock_par_compte.items():
        if valeur > 0:
            comptabilite.comptabiliser_variation_stock(
                db, fac, compte_stock, valeur, entree=(payload.type == "achat"), created_by=user.id)
    # Intersociété : le client est une société du groupe → facture d'achat miroir chez elle
    if payload.type == "vente":
        from .intersociete import creer_facture_miroir
        creer_facture_miroir(db, fac, user.id)
    services.enregistrer_audit(db, user.id, "INSERT", "facture", fac.id, None,
                               {"numero": numero, "type": payload.type, "ttc": fac.total_ttc})
    db.commit()
    return _facture_dict(db, fac)


@router.get("/factures")
def lister_factures(societe_id: uuid.UUID, type: str | None = None, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    q = select(models.Facture).where(models.Facture.societe_id == societe_id)
    if type:
        q = q.where(models.Facture.type == type)
    facs = db.execute(q.order_by(models.Facture.created_at.desc())).scalars().all()
    return [_facture_dict(db, f) for f in facs]


@router.get("/factures/{facture_id}")
def detail_facture(facture_id: uuid.UUID, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    f = db.get(models.Facture, facture_id)
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable.")
    roles = assert_acces_societe(db, user, f.societe_id)
    assert_role(roles, ROLES)
    return _facture_dict(db, f)


# ── Stock ────────────────────────────────────────────────────────────
@router.get("/stock")
def etat_stock(societe_id: uuid.UUID, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    arts = db.execute(select(models.Article).where(
        models.Article.societe_id == societe_id, models.Article.gere_stock.is_(True))
        .order_by(models.Article.code)).scalars().all()
    lignes = [_article_dict(a) for a in arts]
    return {"lignes": lignes, "valeur_totale": round(sum(l["stock_valeur"] for l in lignes), 2)}


@router.get("/stock/mouvements")
def mouvements_stock(societe_id: uuid.UUID, article_id: uuid.UUID | None = None,
                     db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    noms = dict(db.execute(select(models.Article.id, models.Article.code)
                           .where(models.Article.societe_id == societe_id)).all())
    q = select(models.MouvementStock).where(models.MouvementStock.societe_id == societe_id)
    if article_id:
        q = q.where(models.MouvementStock.article_id == article_id)
    mvts = db.execute(q.order_by(models.MouvementStock.created_at.desc())).scalars().all()
    return [{"date": m.date_mvt.isoformat(), "article": noms.get(m.article_id, ""),
             "sens": m.sens, "type": m.type_operation, "reference": m.reference,
             "qte": float(m.qte), "cout_unitaire": float(m.cout_unitaire),
             "valeur": float(m.valeur)} for m in mvts]


# ── Rapports commerciaux ─────────────────────────────────────────────
@router.get("/achats-historique")
def achats_historique(societe_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Historique unifié de tous les achats entrés en stock, quelle que soit
    leur origine : facture directe, réception (commande) ou avance à justifier."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    codes = dict(db.execute(select(models.Article.id, models.Article.code)
                            .where(models.Article.societe_id == societe_id)).all())
    fac_tiers, rec_tiers, just_tiers = {}, {}, {}
    for f in db.execute(select(models.Facture).where(
            models.Facture.societe_id == societe_id, models.Facture.type == "achat")).scalars():
        t = db.get(models.Tiers, f.tiers_id)
        fac_tiers[f.numero] = t.nom if t else None
    for r in db.execute(select(models.Reception).where(
            models.Reception.societe_id == societe_id)).scalars():
        cmd = db.get(models.Commande, r.commande_id)
        t = db.get(models.Tiers, cmd.tiers_id) if cmd else None
        rec_tiers[r.numero] = t.nom if t else None
    for j in db.execute(select(models.Justification)).scalars():
        av = db.get(models.Avance, j.avance_id)
        if av and av.societe_id == societe_id:
            t = db.get(models.Tiers, av.beneficiaire_tiers_id)
            just_tiers[j.numero] = t.nom if t else None

    mvts = db.execute(select(models.MouvementStock).where(
        models.MouvementStock.societe_id == societe_id, models.MouvementStock.sens == "entree")
        .order_by(models.MouvementStock.created_at.desc())).scalars().all()
    groups: dict[str, dict] = {}
    for m in mvts:
        ref = m.reference or "—"
        g = groups.get(ref)
        if g is None:
            rs = ref
            if m.type_operation == "reception":
                origine, tiers = "Réception (commande)", rec_tiers.get(ref)
            elif rs.startswith("FA"):
                origine, tiers = "Facture d'achat", fac_tiers.get(ref)
            elif rs.startswith("JUST"):
                origine, tiers = "Avance à justifier", just_tiers.get(ref)
            else:
                origine, tiers = "Achat", None
            g = groups[ref] = {"reference": ref, "date": m.date_mvt.isoformat(), "origine": origine,
                               "tiers": tiers, "articles": [], "total_valeur": 0.0, "total_qte": 0.0}
        g["articles"].append({"code": codes.get(m.article_id, ""), "qte": float(m.qte), "cout": float(m.valeur)})
        g["total_valeur"] = round(g["total_valeur"] + float(m.valeur), 2)
        g["total_qte"] = round(g["total_qte"] + float(m.qte), 3)
    return sorted(groups.values(), key=lambda x: x["date"], reverse=True)


@router.get("/ventes-synthese")
def ventes_synthese(societe_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    """Synthèse des ventes : CA, marge, TVA collectée, et palmarès des articles."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    facs = db.execute(select(models.Facture).where(
        models.Facture.societe_id == societe_id, models.Facture.type == "vente")).scalars().all()
    avoirs = db.execute(select(models.Facture).where(
        models.Facture.societe_id == societe_id, models.Facture.type == "avoir_vente")).scalars().all()
    ca = round(sum(float(f.total_ht) for f in facs) - sum(float(a.total_ht) for a in avoirs), 2)
    marge = round(sum(float(f.marge or 0) for f in facs) - sum(float(a.marge or 0) for a in avoirs), 2)
    tva = round(sum(float(f.total_tva) for f in facs) - sum(float(a.total_tva) for a in avoirs), 2)
    codes = dict(db.execute(select(models.Article.id, models.Article.code)
                            .where(models.Article.societe_id == societe_id)).all())
    ventes = db.execute(select(models.MouvementStock).where(
        models.MouvementStock.societe_id == societe_id, models.MouvementStock.sens == "sortie",
        models.MouvementStock.type_operation == "vente")).scalars().all()
    par_article: dict = {}
    for m in ventes:
        a = par_article.setdefault(m.article_id, {"code": codes.get(m.article_id, ""), "qte": 0.0, "cout": 0.0})
        a["qte"] = round(a["qte"] + float(m.qte), 3)
        a["cout"] = round(a["cout"] + float(m.valeur), 2)
    top = sorted(par_article.values(), key=lambda x: x["qte"], reverse=True)[:8]
    return {"chiffre_affaires": ca, "marge": marge, "tva_collectee": tva,
            "nb_factures": len(facs), "taux_marge": round(marge / ca * 100, 1) if ca else 0.0,
            "palmares": top}


# ── Circuit 2 : commandes ────────────────────────────────────────────
class LigneCommandeIn(BaseModel):
    article_id: uuid.UUID | None = None
    designation: str | None = None
    qte: float = Field(gt=0)
    prix_unitaire: float = Field(ge=0)
    taux_tva: float | None = None


class CommandeIn(BaseModel):
    tiers_id: uuid.UUID
    date_commande: date | None = None
    date_livraison_prevue: date | None = None
    reference_fournisseur: str | None = None
    intra_groupe: bool = False
    destination: str | None = None                    # lieu de livraison (PO intersociété)
    transporteur_societe_id: uuid.UUID | None = None  # transporteur du groupe (ex. KAKO Logistique)
    lignes: list[LigneCommandeIn]


def _commande_dict(db: Session, c: models.Commande) -> dict:
    tiers = db.get(models.Tiers, c.tiers_id)
    lignes = db.execute(select(models.LigneCommande).where(
        models.LigneCommande.commande_id == c.id)).scalars().all()
    codes = {}
    for l in lignes:
        if l.article_id and l.article_id not in codes:
            a = db.get(models.Article, l.article_id)
            codes[l.article_id] = a.code if a else None
    modifiable = c.statut == "envoyee" and all(float(l.qte_recue) <= 1e-9 for l in lignes)
    # PO intersociété : état de la prise en charge chez le vendeur + course liée
    inter = None
    if c.devis_lie_id:
        dv = db.get(models.Devis, c.devis_lie_id)
        transporteur = db.get(models.Societe, c.transporteur_societe_id) if c.transporteur_societe_id else None
        course = db.execute(select(models.Course).where(
            models.Course.commande_origine_id == c.id)).scalars().first()
        etat = "facturee" if c.statut == "soldee" else (
            "prise_en_charge" if dv and dv.statut == "confirme" else
            ("annulee" if dv and dv.statut == "annule" else "en_attente"))
        from .intersociete import reception_po_resume
        inter = {"etat": etat, "devis_numero": dv.numero if dv else None,
                 "devis_statut": dv.statut if dv else None,
                 "transporteur": transporteur.nom if transporteur else None,
                 "course_numero": course.numero if course else None,
                 "course_statut": course.statut if course else None,
                 "reception": reception_po_resume(db, c)}
    return {"id": str(c.id), "numero": c.numero, "tiers": tiers.nom if tiers else None,
            "tiers_id": str(c.tiers_id), "date": c.date_commande.isoformat(), "statut": c.statut,
            "date_livraison_prevue": c.date_livraison_prevue.isoformat() if c.date_livraison_prevue else None,
            "reference_fournisseur": c.reference_fournisseur, "modifiable": modifiable,
            "destination": c.destination, "intersociete": inter,
            "total_ht": float(c.total_ht), "intra_groupe": bool(c.intra_groupe),
            "lignes": [{"id": str(l.id), "article": codes.get(l.article_id), "article_id": str(l.article_id) if l.article_id else None,
                        "designation": l.designation, "qte": float(l.qte), "qte_recue": float(l.qte_recue),
                        "reste": round(float(l.qte) - float(l.qte_recue), 3),
                        "prix_unitaire": float(l.prix_unitaire), "taux_tva": float(l.taux_tva)} for l in lignes]}


@router.post("/commandes", status_code=status.HTTP_201_CREATED)
def creer_commande(societe_id: uuid.UUID, payload: CommandeIn, db: Session = Depends(get_db),
                   user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    societe = db.get(models.Societe, societe_id)
    tiers = db.get(models.Tiers, payload.tiers_id)
    if not tiers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fournisseur introuvable.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins une ligne.")
    jour = payload.date_commande or date.today()
    cmd = models.Commande(societe_id=societe_id, numero=services.next_numero(db, "commande", jour.year, societe.code, societe.id),
                          tiers_id=tiers.id, date_commande=jour, statut="envoyee",
                          date_livraison_prevue=payload.date_livraison_prevue,
                          reference_fournisseur=(payload.reference_fournisseur or None),
                          destination=(payload.destination or "").strip() or None,
                          transporteur_societe_id=payload.transporteur_societe_id,
                          intra_groupe=payload.intra_groupe or bool(tiers.intra_groupe), created_by=user.id)
    db.add(cmd)
    db.flush()
    total = 0.0
    defaut_tva = float(services.get_parametre(db, "tva.taux_defaut", cmd.societe_id, "16"))
    for l in payload.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        taux = l.taux_tva if l.taux_tva is not None else (float(art.taux_tva) if art else defaut_tva)
        if art is not None and not art.assujetti_tva:
            taux = 0.0
        total += round(l.qte * l.prix_unitaire, 2)
        db.add(models.LigneCommande(commande_id=cmd.id, article_id=l.article_id,
                                    designation=(l.designation or (art.designation if art else "")).strip(),
                                    qte=l.qte, prix_unitaire=l.prix_unitaire, taux_tva=taux))
    cmd.total_ht = round(total, 2)
    # PO intersociété : commande client miroir chez le vendeur + demande de course
    # chez le transporteur du groupe (prenable en charge après confirmation du vendeur)
    if tiers.societe_liee_id:
        from .intersociete import creer_demande_course, creer_devis_miroir_commande
        creer_devis_miroir_commande(db, cmd, user.id)
        creer_demande_course(db, cmd, user.id)
    services.enregistrer_audit(db, user.id, "INSERT", "commande", cmd.id, None, {"numero": cmd.numero})
    db.commit()
    return _commande_dict(db, cmd)


@router.get("/commandes")
def lister_commandes(societe_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    cs = db.execute(select(models.Commande).where(models.Commande.societe_id == societe_id)
                    .order_by(models.Commande.created_at.desc())).scalars().all()
    return [_commande_dict(db, c) for c in cs]


@router.get("/commandes/{commande_id}")
def detail_commande(commande_id: uuid.UUID, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    c = db.get(models.Commande, commande_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    d = _commande_dict(db, c)
    # Rapprochement 3 voies : commandé / reçu / facturé
    recs = db.execute(select(models.Reception).where(models.Reception.commande_id == c.id)
                      .order_by(models.Reception.created_at)).scalars().all()
    recu_ht = facture_ht = 0.0
    recs_out = []
    for r in recs:
        rl = db.execute(select(models.LigneReception).where(models.LigneReception.reception_id == r.id)).scalars().all()
        r_ht = round(sum(float(x.montant_ht) for x in rl), 2)
        recu_ht += r_ht
        fac = db.execute(select(models.Facture).where(models.Facture.reception_id == r.id)).scalars().first()
        if fac:
            facture_ht += float(fac.total_ht)
        recs_out.append({"id": str(r.id), "numero": r.numero, "date": r.date_reception.isoformat(),
                         "statut": r.statut, "montant_ht": r_ht, "facture": fac.numero if fac else None})
    cmd_ht = float(c.total_ht)
    d["receptions"] = recs_out
    d["controle"] = {"commande_ht": round(cmd_ht, 2), "recu_ht": round(recu_ht, 2),
                     "facture_ht": round(facture_ht, 2),
                     "ecart_recu": round(recu_ht - cmd_ht, 2), "ecart_facture": round(facture_ht - recu_ht, 2)}
    return d


def _commande_modifiable(db: Session, c: models.Commande) -> bool:
    """Une commande reste modifiable/annulable tant qu'aucune réception ne l'a entamée."""
    if c.statut not in ("envoyee",):
        return False
    lignes = db.execute(select(models.LigneCommande).where(models.LigneCommande.commande_id == c.id)).scalars().all()
    return all(float(l.qte_recue) <= 1e-9 for l in lignes)


@router.put("/commandes/{commande_id}")
def modifier_commande(commande_id: uuid.UUID, payload: CommandeIn, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    """Modifie une commande tant qu'elle n'est pas entamée (aucune réception)."""
    c = db.get(models.Commande, commande_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    if not _commande_modifiable(db, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "Commande déjà réceptionnée ou clôturée : non modifiable.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Au moins une ligne.")
    tiers = db.get(models.Tiers, payload.tiers_id)
    if not tiers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fournisseur introuvable.")
    # Remplace les lignes
    for l in db.execute(select(models.LigneCommande).where(models.LigneCommande.commande_id == c.id)).scalars().all():
        db.delete(l)
    db.flush()
    c.tiers_id = tiers.id
    if payload.date_commande:
        c.date_commande = payload.date_commande
    c.date_livraison_prevue = payload.date_livraison_prevue
    c.reference_fournisseur = payload.reference_fournisseur or None
    c.intra_groupe = payload.intra_groupe or bool(tiers.intra_groupe)
    total = 0.0
    defaut_tva = float(services.get_parametre(db, "tva.taux_defaut", c.societe_id, "16"))
    for l in payload.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        taux = l.taux_tva if l.taux_tva is not None else (float(art.taux_tva) if art else defaut_tva)
        if art is not None and not art.assujetti_tva:
            taux = 0.0
        total += round(l.qte * l.prix_unitaire, 2)
        db.add(models.LigneCommande(commande_id=c.id, article_id=l.article_id,
                                    designation=(l.designation or (art.designation if art else "")).strip(),
                                    qte=l.qte, prix_unitaire=l.prix_unitaire, taux_tva=taux))
    c.total_ht = round(total, 2)
    services.enregistrer_audit(db, user.id, "UPDATE", "commande", c.id, None, {"numero": c.numero})
    db.commit()
    return _commande_dict(db, c)


@router.post("/commandes/{commande_id}/annuler")
def annuler_commande(commande_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    """Annule une commande non entamée (aucune réception)."""
    c = db.get(models.Commande, commande_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande introuvable.")
    roles = assert_acces_societe(db, user, c.societe_id)
    assert_role(roles, ROLES)
    if not _commande_modifiable(db, c):
        raise HTTPException(status.HTTP_409_CONFLICT, "Commande déjà réceptionnée ou clôturée : non annulable.")
    c.statut = "annulee"
    services.enregistrer_audit(db, user.id, "UPDATE", "commande", c.id, None, {"numero": c.numero, "action": "annulee"})
    db.commit()
    return _commande_dict(db, c)


# ── Circuit 2 : réceptions ───────────────────────────────────────────
class LigneReceptionIn(BaseModel):
    ligne_commande_id: uuid.UUID
    qte_recue: float = Field(gt=0)


class ReceptionIn(BaseModel):
    date_reception: date | None = None
    repartition: str = Field(default="quantite", pattern="^(quantite|valeur)$")
    lignes: list[LigneReceptionIn]
    frais: list[FraisIn] = []


def _reception_dict(db: Session, r: models.Reception) -> dict:
    cmd = db.get(models.Commande, r.commande_id)
    fournisseur = db.get(models.Tiers, cmd.tiers_id) if cmd else None
    lignes = db.execute(select(models.LigneReception).where(models.LigneReception.reception_id == r.id)).scalars().all()
    frais = db.execute(select(models.FraisReception).where(models.FraisReception.reception_id == r.id)).scalars().all()
    return {"id": str(r.id), "numero": r.numero, "commande": cmd.numero if cmd else None,
            "fournisseur": fournisseur.nom if fournisseur else None,
            "reference_fournisseur": cmd.reference_fournisseur if cmd else None,
            "commande_id": str(r.commande_id), "date": r.date_reception.isoformat(), "statut": r.statut,
            "total_valeur": float(r.total_valeur), "total_frais": float(r.total_frais), "repartition": r.repartition,
            "lignes": [{"designation": l.designation, "qte": float(l.qte), "prix_unitaire": float(l.prix_unitaire),
                        "taux_tva": float(l.taux_tva), "montant_ht": float(l.montant_ht),
                        "frais_reparti": float(l.frais_reparti), "cout": float(l.cout)} for l in lignes],
            "frais": [{"libelle": f.libelle, "compte": f.compte, "montant_ht": float(f.montant_ht),
                       "taux_tva": float(f.taux_tva), "mode": f.mode,
                       "contrepartie": (db.get(models.Tiers, f.tiers_id).nom if f.tiers_id else None)
                       if f.mode == "credit" else (f.compte_reglement or "")} for f in frais]}


@router.post("/commandes/{commande_id}/receptionner", status_code=status.HTTP_201_CREATED)
def receptionner(commande_id: uuid.UUID, payload: ReceptionIn, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    """Réception (totale ou partielle) : entrée en stock au coût d'acquisition, D 31 / C 408."""
    cmd = db.get(models.Commande, commande_id)
    if not cmd:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande introuvable.")
    roles = assert_acces_societe(db, user, cmd.societe_id)
    assert_role(roles, ROLES)
    if cmd.statut in ("soldee", "annulee"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Commande clôturée.")
    if cmd.devis_lie_id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Commande intersociété : le stock entrera automatiquement via la facture "
                            "miroir quand le vendeur livrera et facturera — pas de réception manuelle.")
    jour = payload.date_reception or date.today()
    rec = models.Reception(societe_id=cmd.societe_id, numero=services.next_numero(db, "reception", jour.year, db.get(models.Societe, cmd.societe_id).code, cmd.societe_id),
                           commande_id=cmd.id, date_reception=jour, repartition=payload.repartition,
                           statut="recue", created_by=user.id)
    db.add(rec)
    db.flush()

    lignes_rec = []
    for lr in payload.lignes:
        lc = db.get(models.LigneCommande, lr.ligne_commande_id)
        if not lc or lc.commande_id != cmd.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne de commande invalide.")
        reste = float(lc.qte) - float(lc.qte_recue)
        if lr.qte_recue > reste + 1e-6:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{lc.designation} : {lr.qte_recue} reçu > {round(reste, 3)} restant.")
        ht = round(lr.qte_recue * float(lc.prix_unitaire), 2)
        art = db.get(models.Article, lc.article_id) if lc.article_id else None
        lm = models.LigneReception(reception_id=rec.id, ligne_commande_id=lc.id, article_id=lc.article_id,
                                   designation=lc.designation, qte=lr.qte_recue, prix_unitaire=lc.prix_unitaire,
                                   taux_tva=lc.taux_tva, montant_ht=ht, cout=ht,
                                   compte_stock=art.compte_stock if art else "31")
        db.add(lm)
        lignes_rec.append((lm, lc, art))
        lc.qte_recue = round(float(lc.qte_recue) + lr.qte_recue, 3)

    # Frais annexes → chacun avec SA contrepartie réelle (dette fournisseur / banque / caisse),
    # répartis sur les lignes pour le coût d'acquisition du stock.
    societe = db.get(models.Societe, cmd.societe_id)
    frais_ht = 0.0
    frais_objs = []
    for f in payload.frais:
        ftaux = f.taux_tva if f.taux_tva is not None else 16.0
        fht = round(f.montant_ht, 2)
        ftva = round(fht * ftaux / 100, 2)
        frais_ht += fht
        compte_reg, caisse_id = _resoudre_contrepartie_frais(
            db, societe, f, jour, rec.numero, "reception", rec.id, fht, ftva, user)
        fr = models.FraisReception(reception_id=rec.id, libelle=f.libelle.strip(), compte=f.compte,
                                   montant_ht=fht, taux_tva=ftaux, montant_tva=ftva,
                                   mode=f.mode, tiers_id=f.tiers_id, compte_reglement=compte_reg, caisse_id=caisse_id)
        db.add(fr)
        frais_objs.append(fr)
    frais_ht = round(frais_ht, 2)
    if frais_ht > 0 and lignes_rec:
        w = [float(lm.qte) if payload.repartition != "valeur" else float(lm.montant_ht) for lm, _, _ in lignes_rec]
        tw = sum(w) or 1.0
        cumul = 0.0
        for i, (lm, _, _) in enumerate(lignes_rec):
            part = round(frais_ht * w[i] / tw, 2) if i < len(lignes_rec) - 1 else round(frais_ht - cumul, 2)
            cumul = round(cumul + part, 2)
            lm.frais_reparti = part
            lm.cout = round(float(lm.montant_ht) + part, 2)

    # Entrées de stock (au coût d'acquisition) + agrégats par compte de stock :
    # les MARCHANDISES vont sur le pont 408 (fournisseur X), les FRAIS ont leur propre
    # contrepartie et sont incorporés au stock via 603.
    goods_par_compte, frais_par_compte = {}, {}
    for lm, lc, art in lignes_rec:
        if art and art.gere_stock:
            qte = float(lm.qte)
            art.stock_qte = round(float(art.stock_qte) + qte, 3)
            art.stock_valeur = round(float(art.stock_valeur) + float(lm.cout), 2)
            db.add(models.MouvementStock(societe_id=cmd.societe_id, article_id=art.id, date_mvt=jour,
                                         sens="entree", qte=qte, cout_unitaire=round(float(lm.cout) / qte, 4) if qte else 0.0,
                                         valeur=float(lm.cout), type_operation="reception", reference=rec.numero))
        goods_par_compte[lm.compte_stock] = round(goods_par_compte.get(lm.compte_stock, 0.0) + float(lm.montant_ht), 2)
        if float(lm.frais_reparti or 0):
            frais_par_compte[lm.compte_stock] = round(frais_par_compte.get(lm.compte_stock, 0.0) + float(lm.frais_reparti or 0), 2)

    rec.total_valeur = round(sum(float(lm.cout) for lm, _, _ in lignes_rec), 2)
    rec.total_frais = frais_ht
    ecr = comptabilite.comptabiliser_reception(db, rec, goods_par_compte, frais_par_compte, frais_objs, user.id,
                                               statut=_statut_piece(db, cmd.societe_id, "achat"))
    rec.ecriture_id = ecr.id

    # Statut de la commande
    all_recu = all(float(lc.qte_recue) >= float(lc.qte) - 1e-6 for lc in cmd.lignes)
    cmd.statut = "soldee" if all_recu else "receptionnee"
    services.enregistrer_audit(db, user.id, "INSERT", "reception", rec.id, None, {"numero": rec.numero})
    db.commit()
    return _reception_dict(db, rec)


@router.get("/receptions")
def lister_receptions(societe_id: uuid.UUID, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    rs = db.execute(select(models.Reception).where(models.Reception.societe_id == societe_id)
                    .order_by(models.Reception.created_at.desc())).scalars().all()
    return [_reception_dict(db, r) for r in rs]


@router.get("/receptions/{reception_id}")
def detail_reception(reception_id: uuid.UUID, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    r = db.get(models.Reception, reception_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réception introuvable.")
    roles = assert_acces_societe(db, user, r.societe_id)
    assert_role(roles, ROLES)
    return _reception_dict(db, r)


class FacturerIn(BaseModel):
    reference: str | None = None                # n° de la facture fournisseur
    date_facture: date | None = None
    echeance: date | None = None


@router.post("/receptions/{reception_id}/facturer", status_code=status.HTTP_201_CREATED)
def facturer_reception(reception_id: uuid.UUID, payload: FacturerIn | None = None,
                       db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    """Enregistre la facture fournisseur d'une réception : D 408 + TVA / C 401.

    Reçoit (optionnellement) le n° de facture fournisseur, la date et l'échéance
    saisis dans l'aperçu avant validation."""
    payload = payload or FacturerIn()
    rec = db.get(models.Reception, reception_id)
    if not rec:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réception introuvable.")
    roles = assert_acces_societe(db, user, rec.societe_id)
    assert_role(roles, ROLES)
    if rec.statut == "facturee":
        raise HTTPException(status.HTTP_409_CONFLICT, "Réception déjà facturée.")
    societe = db.get(models.Societe, rec.societe_id)
    cmd = db.get(models.Commande, rec.commande_id)
    rec_lignes = db.execute(select(models.LigneReception).where(models.LigneReception.reception_id == rec.id)).scalars().all()

    # La facture ne porte que les MARCHANDISES (les frais ont leur propre contrepartie à la réception)
    total_ht = round(sum(float(l.montant_ht) for l in rec_lignes), 2)
    tva = round(sum(round(float(l.montant_ht) * float(l.taux_tva) / 100, 2) for l in rec_lignes), 2)
    total_ttc = round(total_ht + tva, 2)

    date_fac = payload.date_facture or rec.date_reception
    numero = services.next_numero(db, "facture_achat", date_fac.year, societe.code, societe.id)
    fac = models.Facture(societe_id=rec.societe_id, type="achat", numero=numero, tiers_id=cmd.tiers_id,
                         date_facture=date_fac, echeance=payload.echeance, reference=payload.reference,
                         total_ht=total_ht, total_frais=0,
                         total_tva=tva, total_ttc=total_ttc, statut="validee",
                         intra_groupe=cmd.intra_groupe, reception_id=rec.id, created_by=user.id)
    db.add(fac)
    db.flush()
    for l in rec_lignes:
        db.add(models.LigneFacture(facture_id=fac.id, article_id=l.article_id, designation=l.designation,
                                   qte=l.qte, prix_unitaire=l.prix_unitaire, taux_tva=l.taux_tva,
                                   montant_ht=l.montant_ht, montant_tva=round(float(l.montant_ht) * float(l.taux_tva) / 100, 2),
                                   frais_reparti=l.frais_reparti, cout_entree=l.cout))
    ecr = comptabilite.comptabiliser_facture_reception(db, fac, rec, user.id,
                                                       statut=_statut_piece(db, rec.societe_id, "achat"))
    fac.ecriture_id = ecr.id
    rec.statut = "facturee"
    services.enregistrer_audit(db, user.id, "INSERT", "facture", fac.id, None, {"numero": numero, "reception": rec.numero})
    db.commit()
    return _facture_dict(db, fac)


# ── Listes de prix & tarifs (préparation POS) ────────────────────────
class ListePrixIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=1)


@router.get("/listes-prix")
def lister_listes_prix(societe_id: uuid.UUID, db: Session = Depends(get_db),
                       user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    ls = db.execute(select(models.ListePrix).where(models.ListePrix.societe_id == societe_id)
                    .order_by(models.ListePrix.code)).scalars().all()
    out = []
    for l in ls:
        n = db.execute(select(func.count()).select_from(models.TarifArticle)
                       .where(models.TarifArticle.liste_prix_id == l.id)).scalar()
        out.append({"id": str(l.id), "code": l.code, "libelle": l.libelle, "actif": bool(l.actif), "nb_tarifs": int(n)})
    return out


@router.post("/listes-prix", status_code=status.HTTP_201_CREATED)
def creer_liste_prix(societe_id: uuid.UUID, payload: ListePrixIn, db: Session = Depends(get_db),
                     user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    code = payload.code.strip().upper()
    if db.execute(select(models.ListePrix).where(models.ListePrix.societe_id == societe_id,
                                                 models.ListePrix.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"La liste {code} existe déjà.")
    lp = models.ListePrix(societe_id=societe_id, code=code, libelle=payload.libelle.strip())
    db.add(lp)
    db.commit()
    return {"id": str(lp.id), "code": lp.code, "libelle": lp.libelle}


@router.get("/listes-prix/{liste_id}/tarifs")
def tarifs_liste(liste_id: uuid.UUID, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    """Tous les articles avec leur prix dans cette liste (sinon le prix de vente par défaut)."""
    liste = db.get(models.ListePrix, liste_id)
    if not liste:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Liste introuvable.")
    roles = assert_acces_societe(db, user, liste.societe_id)
    assert_role(roles, ROLES)
    tarifs = {t.article_id: float(t.prix) for t in db.execute(select(models.TarifArticle)
              .where(models.TarifArticle.liste_prix_id == liste_id)).scalars()}
    arts = db.execute(select(models.Article).where(models.Article.societe_id == liste.societe_id,
                      models.Article.actif.is_(True)).order_by(models.Article.code)).scalars().all()
    return {"liste": {"id": str(liste.id), "code": liste.code, "libelle": liste.libelle},
            "articles": [{"article_id": str(a.id), "code": a.code, "designation": a.designation,
                          "prix_defaut": float(a.prix_vente),
                          "prix": tarifs.get(a.id), "defini": a.id in tarifs} for a in arts]}


class TarifIn(BaseModel):
    article_id: uuid.UUID
    prix: float | None = None      # None -> supprime le tarif (revient au prix par défaut)


@router.post("/listes-prix/{liste_id}/tarifs")
def set_tarif(liste_id: uuid.UUID, payload: TarifIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    liste = db.get(models.ListePrix, liste_id)
    if not liste:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Liste introuvable.")
    roles = assert_acces_societe(db, user, liste.societe_id)
    assert_role(roles, ROLES)
    t = db.execute(select(models.TarifArticle).where(
        models.TarifArticle.liste_prix_id == liste_id,
        models.TarifArticle.article_id == payload.article_id)).scalars().first()
    if payload.prix is None:
        if t:
            db.delete(t)
    elif t:
        t.prix = round(payload.prix, 2)
    else:
        db.add(models.TarifArticle(societe_id=liste.societe_id, liste_prix_id=liste_id,
                                   article_id=payload.article_id, prix=round(payload.prix, 2)))
    db.commit()
    return {"ok": True}


# ── Points de vente ──────────────────────────────────────────────────
class PointVenteIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=1)
    liste_prix_id: uuid.UUID | None = None
    caisse_id: uuid.UUID | None = None


class PointVenteMaj(BaseModel):
    libelle: str | None = None
    liste_prix_id: uuid.UUID | None = None
    caisse_id: uuid.UUID | None = None
    actif: bool | None = None


def _pv_dict(db: Session, p: models.PointVente) -> dict:
    lp = db.get(models.ListePrix, p.liste_prix_id) if p.liste_prix_id else None
    c = db.get(models.Caisse, p.caisse_id) if p.caisse_id else None
    return {"id": str(p.id), "code": p.code, "libelle": p.libelle, "actif": bool(p.actif),
            "liste_prix_id": str(p.liste_prix_id) if p.liste_prix_id else None,
            "liste_prix": lp.libelle if lp else None,
            "caisse_id": str(p.caisse_id) if p.caisse_id else None, "caisse": c.libelle if c else None}


@router.get("/points-vente")
def lister_points_vente(societe_id: uuid.UUID, db: Session = Depends(get_db),
                        user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    ps = db.execute(select(models.PointVente).where(models.PointVente.societe_id == societe_id)
                    .order_by(models.PointVente.code)).scalars().all()
    return [_pv_dict(db, p) for p in ps]


@router.post("/points-vente", status_code=status.HTTP_201_CREATED)
def creer_point_vente(societe_id: uuid.UUID, payload: PointVenteIn, db: Session = Depends(get_db),
                      user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES)
    code = payload.code.strip().upper()
    if db.execute(select(models.PointVente).where(models.PointVente.societe_id == societe_id,
                                                  models.PointVente.code == code)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Le point de vente {code} existe déjà.")
    p = models.PointVente(societe_id=societe_id, code=code, libelle=payload.libelle.strip(),
                          liste_prix_id=payload.liste_prix_id, caisse_id=payload.caisse_id)
    db.add(p)
    db.commit()
    return _pv_dict(db, p)


@router.patch("/points-vente/{pv_id}")
def maj_point_vente(pv_id: uuid.UUID, payload: PointVenteMaj, db: Session = Depends(get_db),
                    user: models.Utilisateur = Depends(get_current_user)):
    p = db.get(models.PointVente, pv_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Point de vente introuvable.")
    roles = assert_acces_societe(db, user, p.societe_id)
    assert_role(roles, ROLES)
    for f in ("libelle", "liste_prix_id", "caisse_id", "actif"):
        v = getattr(payload, f)
        if v is not None:
            setattr(p, f, v)
    db.commit()
    return _pv_dict(db, p)


@router.get("/articles/{article_id}/prix")
def prix_article(article_id: uuid.UUID, point_vente_id: uuid.UUID | None = None,
                 liste_prix_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    """Prix de vente résolu : tarif de la liste (via le point de vente ou directement),
    sinon prix de vente par défaut de l'article."""
    a = db.get(models.Article, article_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article introuvable.")
    roles = assert_acces_societe(db, user, a.societe_id)
    assert_role(roles, ROLES)
    if point_vente_id and not liste_prix_id:
        pv = db.get(models.PointVente, point_vente_id)
        liste_prix_id = pv.liste_prix_id if pv else None
    prix, source = float(a.prix_vente), "défaut"
    if liste_prix_id:
        t = db.execute(select(models.TarifArticle).where(
            models.TarifArticle.liste_prix_id == liste_prix_id,
            models.TarifArticle.article_id == article_id)).scalars().first()
        if t:
            prix, source = float(t.prix), "liste"
    return {"article_id": str(a.id), "code": a.code, "prix": prix, "source": source}


# ── Point de vente : encaissement (POS) ──────────────────────────────
def _client_comptant(db: Session, societe_id: uuid.UUID) -> models.Tiers:
    t = db.execute(select(models.Tiers).where(
        models.Tiers.societe_id == societe_id, models.Tiers.code == "COMPTANT")).scalars().first()
    if not t:
        t = models.Tiers(societe_id=societe_id, type="client", code="COMPTANT", nom="Client comptant")
        db.add(t)
        db.flush()
    return t


def _taux_cdf(db: Session, jour: date) -> float | None:
    t = services.get_taux_jour(db, jour, "CDF")
    return float(t) if t else None


def _session_ouverte(db: Session, caisse_id: uuid.UUID) -> models.SessionCaisse | None:
    return db.execute(select(models.SessionCaisse).where(
        models.SessionCaisse.caisse_id == caisse_id,
        models.SessionCaisse.statut == "ouverte")).scalars().first()


def _encours_credit_usd(db: Session, tiers_id: uuid.UUID) -> float:
    """Encours client = solde comptable de ses comptes 41x (ventes à crédit
    − avoirs − règlements encaissés). Source de vérité : les écritures."""
    total = 0.0
    rows = db.execute(
        select(models.LigneEcriture.sens,
               func.coalesce(func.sum(models.LigneEcriture.montant_usd), 0))
        .where(models.LigneEcriture.tiers_id == tiers_id,
               models.LigneEcriture.compte_numero.like("41%"))
        .group_by(models.LigneEcriture.sens)).all()
    for sens, montant in rows:
        total += float(montant) if sens == "D" else -float(montant)
    return round(total, 2)


MODES_PAIEMENT = {"espece", "mobile_money", "banque", "credit"}


class PosLigneIn(BaseModel):
    article_id: uuid.UUID
    qte: float = Field(gt=0)
    prix: float | None = None      # override manuel du prix unitaire (brut)
    remise_pct: float = Field(default=0, ge=0, le=100)


class PosPaiementIn(BaseModel):
    mode: str = Field(pattern="^(espece|mobile_money|banque|credit)$")
    devise: str = Field(default="USD", pattern="^(USD|CDF)$")
    montant: float = Field(gt=0)
    reference: str | None = None   # n° de transaction mobile money / banque


class PosVenteIn(BaseModel):
    point_vente_id: uuid.UUID
    client_id: uuid.UUID | None = None
    montant_recu: float | None = None            # hérité : encaissement 100 % espèces USD
    remise_globale_pct: float = Field(default=0, ge=0, le=100)
    note: str | None = None
    paiements: list[PosPaiementIn] = []
    lignes: list[PosLigneIn]


@router.get("/pos/contexte")
def pos_contexte(societe_id: uuid.UUID, point_vente_id: uuid.UUID | None = None,
                 db: Session = Depends(get_db),
                 user: models.Utilisateur = Depends(get_current_user)):
    """Tout ce qu'il faut pour ouvrir l'écran POS en un seul appel :
    taux du jour, catégories d'articles, état de la caisse du point de vente."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)
    cats = [c for (c,) in db.execute(
        select(models.Article.categorie).where(
            models.Article.societe_id == societe_id, models.Article.actif.is_(True),
            models.Article.categorie.is_not(None)).distinct()).all() if c]
    from .caisse import _soldes
    out = {"taux_cdf": _taux_cdf(db, date.today()), "categories": sorted(cats),
           "date": date.today().isoformat()}
    principale = db.execute(select(models.Caisse).where(
        models.Caisse.societe_id == societe_id, models.Caisse.est_principale.is_(True),
        models.Caisse.actif.is_(True))).scalars().first()
    if principale:
        out["caisse_principale"] = {"id": str(principale.id), "libelle": principale.libelle}
    if point_vente_id:
        pv = db.get(models.PointVente, point_vente_id)
        if pv and pv.societe_id == societe_id and pv.caisse_id:
            caisse = db.get(models.Caisse, pv.caisse_id)
            sess = _session_ouverte(db, caisse.id)
            out["caisse"] = {"id": str(caisse.id), "libelle": caisse.libelle,
                            "session_ouverte": sess is not None,
                            "est_principale": bool(caisse.est_principale),
                            "ouverte_depuis": sess.date_ouverture.isoformat() if sess and sess.date_ouverture else None,
                            "fond_usd": float(sess.fond_initial_usd) if sess else None,
                            "fond_cdf": float(sess.fond_initial_cdf) if sess else None,
                            "soldes": _soldes(db, sess) if sess else None}
    return out


def _ticket_dict(db: Session, fac: models.Facture) -> dict:
    """Représentation « ticket » complète d'une vente ou d'un avoir POS
    (réimpression, liste des tickets, réponse de la vente)."""
    pv = db.get(models.PointVente, fac.point_vente_id) if fac.point_vente_id else None
    caisse = db.get(models.Caisse, pv.caisse_id) if pv and pv.caisse_id else None
    tiers = db.get(models.Tiers, fac.tiers_id)
    vendeur = db.get(models.Utilisateur, fac.created_by) if fac.created_by else None
    origine = db.get(models.Facture, fac.origine_id) if fac.origine_id else None
    lignes, points, commission = [], 0.0, 0.0
    for l in fac.lignes:
        art = db.get(models.Article, l.article_id) if l.article_id else None
        brut = round(float(l.qte) * float(l.prix_unitaire), 2)
        lignes.append({"id": str(l.id), "code": art.code if art else "", "designation": l.designation,
                       "qte": float(l.qte), "prix": float(l.prix_unitaire),
                       "remise_pct": float(l.remise_pct or 0), "brut": brut,
                       "ht": float(l.montant_ht), "tva": float(l.montant_tva)})
        if art:
            points += float(l.qte) * float(art.points_fidelite)
            commission += float(l.montant_ht) * float(art.taux_commission) / 100
    paiements = [{"mode": p.mode, "devise": p.devise, "montant": float(p.montant),
                  "montant_usd": float(p.montant_usd), "taux": float(p.taux_jour) if p.taux_jour else None,
                  "reference": p.reference}
                 for p in db.execute(select(models.PaiementFacture).where(
                     models.PaiementFacture.facture_id == fac.id)).scalars()]
    taux = _taux_cdf(db, fac.date_facture if isinstance(fac.date_facture, date) else date.today())
    ttc = float(fac.total_ttc)
    est_avoir = fac.type == "avoir_vente"
    return {
        "id": str(fac.id), "numero": fac.numero, "type": fac.type, "est_avoir": est_avoir,
        "point_vente": pv.libelle if pv else None, "caisse": caisse.libelle if caisse else None,
        "date": fac.date_facture.isoformat(), "heure": fac.created_at.isoformat() if fac.created_at else None,
        "client": {"id": str(tiers.id), "code": tiers.code, "nom": tiers.nom,
                   "points_fidelite": float(tiers.points_fidelite or 0)} if tiers else None,
        "vendeur": f"{vendeur.prenom or ''} {vendeur.nom}".strip() if vendeur else None,
        "origine_numero": origine.numero if origine else None,
        "note": fac.note, "lignes": lignes,
        "total_ht": float(fac.total_ht), "total_tva": float(fac.total_tva), "total_ttc": ttc,
        "remise_totale": float(fac.remise_totale or 0), "marge": float(fac.marge or 0),
        "montant_recu": float(fac.pos_recu_usd) if fac.pos_recu_usd is not None else None,
        "monnaie": float(fac.pos_monnaie_usd) if fac.pos_monnaie_usd is not None else None,
        "paiements": paiements,
        "points_fidelite": round(points, 2), "commission": round(commission, 2),
        "taux_cdf": taux, "total_ttc_cdf": round(ttc * taux, 0) if taux else None,
    }


@router.post("/pos/vente", status_code=status.HTTP_201_CREATED)
def pos_vente(societe_id: uuid.UUID, payload: PosVenteIn, db: Session = Depends(get_db),
              user: models.Utilisateur = Depends(get_current_user)):
    """Vente en point de vente : prix depuis la liste du PV, remises ligne/globale,
    sortie de stock (CUMP), règlement fractionné (espèces USD/CDF, mobile money,
    banque, crédit client), fidélité, écriture comptable et entrées en caisse."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)
    societe = db.get(models.Societe, societe_id)
    pv = db.get(models.PointVente, payload.point_vente_id)
    if not pv or pv.societe_id != societe_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Point de vente invalide.")
    if not pv.caisse_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Le point de vente n'a pas de caisse associée.")
    caisse = db.get(models.Caisse, pv.caisse_id)
    sess = _session_ouverte(db, caisse.id)
    if not sess:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ouvrez la caisse « {caisse.libelle} » avant de vendre.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Panier vide.")

    tiers = db.get(models.Tiers, payload.client_id) if payload.client_id else _client_comptant(db, societe_id)
    if not tiers or (tiers.societe_id and tiers.societe_id != societe_id) or tiers.type != "client":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Client invalide.")
    client_reel = tiers.code != "COMPTANT"
    jour = date.today()
    numero = services.next_numero(db, "facture_vente", jour.year, societe.code, societe.id)
    fac = models.Facture(societe_id=societe_id, type="vente", numero=numero, tiers_id=tiers.id,
                         date_facture=jour, statut="validee", point_vente_id=pv.id,
                         note=(payload.note or "").strip() or None, created_by=user.id)
    db.add(fac)
    db.flush()

    gr = float(payload.remise_globale_pct)
    total_ht = total_tva = cout_ventes = remise_totale = 0.0
    points = commission = 0.0
    stock_par_compte: dict[str, float] = {}
    lm_list = []
    for l in payload.lignes:
        art = db.get(models.Article, l.article_id)
        if not art or art.societe_id != societe_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Article invalide.")
        # prix BRUT : override → tarif de la liste → prix de vente par défaut
        prix = l.prix
        if prix is None and pv.liste_prix_id:
            t = db.execute(select(models.TarifArticle).where(
                models.TarifArticle.liste_prix_id == pv.liste_prix_id,
                models.TarifArticle.article_id == art.id)).scalars().first()
            prix = float(t.prix) if t else None
        if prix is None:
            prix = float(art.prix_vente)
        # remise combinée = remise ligne puis remise globale
        remise = round((1 - (1 - float(l.remise_pct) / 100) * (1 - gr / 100)) * 100, 4)
        taux = float(art.taux_tva) if art.assujetti_tva else 0.0
        qte = float(l.qte)
        brut = round(qte * prix, 2)
        ht = round(brut * (1 - remise / 100), 2)
        tva = round(ht * taux / 100, 2)
        total_ht += ht
        total_tva += tva
        remise_totale += brut - ht
        points += qte * float(art.points_fidelite)
        commission += ht * float(art.taux_commission) / 100
        lm = models.LigneFacture(facture_id=fac.id, article_id=art.id, designation=art.designation,
                                 qte=qte, prix_unitaire=prix, remise_pct=round(remise, 2),
                                 taux_tva=taux, montant_ht=ht, montant_tva=tva)
        db.add(lm)
        lm_list.append(lm)
        if art.gere_stock:
            if float(art.stock_qte) < qte - 1e-6:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Stock insuffisant pour {art.code} : {float(art.stock_qte)} en stock, {qte} demandé.")
            cump = float(art.stock_valeur) / float(art.stock_qte) if art.stock_qte else 0.0
            val = round(qte * cump, 2)
            art.stock_qte = round(float(art.stock_qte) - qte, 3)
            art.stock_valeur = round(float(art.stock_valeur) - val, 2)
            cout_ventes += val
            stock_par_compte[art.compte_stock] = round(stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            db.add(models.MouvementStock(societe_id=societe_id, article_id=art.id, date_mvt=jour,
                                         sens="sortie", qte=qte, cout_unitaire=round(cump, 4),
                                         valeur=val, type_operation="vente", reference=numero))

    t_ht = round(total_ht, 2)
    t_tva = round(total_tva, 2)
    t_ttc = round(t_ht + t_tva, 2)
    fac.total_ht, fac.total_tva, fac.total_ttc = t_ht, t_tva, t_ttc
    fac.remise_totale = round(remise_totale, 2)
    fac.cout_ventes, fac.marge = round(cout_ventes, 2), round(t_ht - cout_ventes, 2)

    # ── Règlement : normalisation des paiements ──────────────────────
    taux_cdf = _taux_cdf(db, jour)
    paiements = payload.paiements
    if not paiements:      # mode hérité : tout en espèces USD
        paiements = [PosPaiementIn(mode="espece", devise="USD",
                                   montant=max(payload.montant_recu or t_ttc, t_ttc))]
    norm = []
    for p in paiements:
        if p.devise == "CDF":
            if not taux_cdf:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Aucun taux USD/CDF défini aujourd'hui — définissez le taux du jour avant d'encaisser en CDF.")
            usd = round(p.montant / taux_cdf, 2)
        else:
            usd = round(p.montant, 2)
        norm.append({"mode": p.mode, "devise": p.devise, "montant": round(p.montant, 2),
                     "taux": taux_cdf if p.devise == "CDF" else None,
                     "usd": usd, "reference": (p.reference or "").strip() or None})

    cash_usd = round(sum(p["usd"] for p in norm if p["mode"] == "espece"), 2)
    noncash_usd = round(sum(p["usd"] for p in norm if p["mode"] != "espece"), 2)
    credit_usd = round(sum(p["usd"] for p in norm if p["mode"] == "credit"), 2)
    if credit_usd > 0:
        if not client_reel:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Vente à crédit : sélectionnez un client enregistré (pas le client comptant).")
        if tiers.limite_credit_usd is not None:
            encours = _encours_credit_usd(db, tiers.id)
            if encours + credit_usd > float(tiers.limite_credit_usd) + 0.01:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Plafond de crédit dépassé pour {tiers.nom} : encours {encours:.2f} USD "
                                    f"+ {credit_usd:.2f} USD > limite {float(tiers.limite_credit_usd):.2f} USD.")
    if noncash_usd > t_ttc + 0.01:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "La monnaie ne peut être rendue que sur les espèces — réduisez le paiement "
                            "mobile money / banque / crédit au montant exact.")
    du_cash = round(t_ttc - noncash_usd, 2)
    if cash_usd + 0.01 < du_cash:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Paiement insuffisant : {round(cash_usd + noncash_usd, 2):.2f} USD reçus "
                            f"pour un total de {t_ttc:.2f} USD.")
    monnaie_usd = round(cash_usd - du_cash, 2)
    fac.pos_recu_usd, fac.pos_monnaie_usd = cash_usd, monnaie_usd

    # ── Écriture de vente (D trésorerie / 411 ; C ventes + TVA) ──────
    compte_par_mode = {
        "espece": caisse.compte_comptable,
        "mobile_money": comptabilite._compte(db, "compte_mobile_money", societe_id),
        "banque": comptabilite._compte(db, "compte_banque", societe_id),
        "credit": comptabilite._compte(db, "compte_client", societe_id),
    }
    encaissements = []
    if du_cash > 0:
        encaissements.append({"compte": compte_par_mode["espece"], "montant_usd": du_cash,
                              "libelle": f"Espèces POS {numero}"})
    mm_usd = round(sum(p["usd"] for p in norm if p["mode"] == "mobile_money"), 2)
    bq_usd = round(sum(p["usd"] for p in norm if p["mode"] == "banque"), 2)
    if mm_usd:
        encaissements.append({"compte": compte_par_mode["mobile_money"], "montant_usd": mm_usd,
                              "libelle": f"Mobile money POS {numero}"})
    if bq_usd:
        encaissements.append({"compte": compte_par_mode["banque"], "montant_usd": bq_usd,
                              "libelle": f"Banque POS {numero}"})
    if credit_usd:
        encaissements.append({"compte": compte_par_mode["credit"], "montant_usd": credit_usd,
                              "tiers_id": tiers.id,
                              "libelle": f"Vente à crédit POS {numero} — {tiers.nom}"})
    ecr = comptabilite.comptabiliser_vente_pos(db, fac, lm_list, encaissements, user.id)
    fac.ecriture_id = ecr.id
    for compte_stock, val in stock_par_compte.items():
        if val > 0:
            comptabilite.comptabiliser_variation_stock(db, fac, compte_stock, val, entree=False, created_by=user.id)

    # ── Espèces : entrées en caisse du PV + monnaie rendue ───────────
    for p in norm:
        db.add(models.PaiementFacture(facture_id=fac.id, mode=p["mode"], devise=p["devise"],
                                      montant=p["montant"], taux_jour=p["taux"], montant_usd=p["usd"],
                                      reference=p["reference"], compte=compte_par_mode[p["mode"]]))
        if p["mode"] == "espece":
            db.add(models.MouvementCaisse(
                caisse_id=caisse.id, session_id=sess.id,
                numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
                reference=numero, sens="entree", nature="Vente POS", devise=p["devise"],
                taux_jour=p["taux"], montant=p["montant"], montant_usd=p["usd"],
                tiers_id=tiers.id if client_reel else None, tiers_nom=tiers.nom if client_reel else None,
                reference_type="facture", reference_id=fac.id,
                libelle=f"Vente POS {numero} — {pv.libelle}", created_by=user.id))
    if monnaie_usd > 0:
        # monnaie rendue en USD s'il y a eu des espèces USD, sinon en CDF
        rendu_usd = any(p["mode"] == "espece" and p["devise"] == "USD" for p in norm)
        db.add(models.MouvementCaisse(
            caisse_id=caisse.id, session_id=sess.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
            reference=numero, sens="sortie", nature="Monnaie rendue POS",
            devise="USD" if rendu_usd else "CDF",
            taux_jour=None if rendu_usd else taux_cdf,
            montant=monnaie_usd if rendu_usd else round(monnaie_usd * taux_cdf, 0),
            montant_usd=monnaie_usd, reference_type="facture", reference_id=fac.id,
            libelle=f"Monnaie rendue — vente {numero}", created_by=user.id))

    # ── Fidélité ─────────────────────────────────────────────────────
    if client_reel and points:
        tiers.points_fidelite = round(float(tiers.points_fidelite or 0) + points, 2)

    services.enregistrer_audit(db, user.id, "INSERT", "facture", fac.id, None,
                               {"numero": numero, "pos": pv.code, "ttc": t_ttc,
                                "remise": fac.remise_totale, "credit": credit_usd})
    db.commit()
    return _ticket_dict(db, fac)


# ── Tickets du jour, réimpression, retours ───────────────────────────
@router.get("/pos/tickets")
def pos_tickets(societe_id: uuid.UUID, point_vente_id: uuid.UUID | None = None,
                jour: date | None = None, db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)
    jour = jour or date.today()
    q = select(models.Facture).where(
        models.Facture.societe_id == societe_id,
        models.Facture.point_vente_id.is_not(None),
        models.Facture.type.in_(["vente", "avoir_vente"]),
        models.Facture.date_facture == jour)
    if point_vente_id:
        q = q.where(models.Facture.point_vente_id == point_vente_id)
    facs = db.execute(q.order_by(models.Facture.created_at.desc())).scalars().all()
    avoirs_par_origine: dict = {}
    for f in facs:
        if f.type == "avoir_vente" and f.origine_id:
            avoirs_par_origine.setdefault(f.origine_id, []).append(f.numero)
    out = []
    for f in facs:
        t = db.get(models.Tiers, f.tiers_id)
        v = db.get(models.Utilisateur, f.created_by) if f.created_by else None
        modes = sorted({p.mode for p in db.execute(select(models.PaiementFacture).where(
            models.PaiementFacture.facture_id == f.id)).scalars()})
        out.append({"id": str(f.id), "numero": f.numero, "type": f.type,
                    "heure": f.created_at.isoformat() if f.created_at else None,
                    "client": t.nom if t else None, "vendeur": v.prenom or v.nom if v else None,
                    "total_ttc": float(f.total_ttc), "remise": float(f.remise_totale or 0),
                    "modes": modes, "avoirs": avoirs_par_origine.get(f.id, [])})
    return out


@router.get("/pos/ticket/{facture_id}")
def pos_ticket(facture_id: uuid.UUID, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    f = db.get(models.Facture, facture_id)
    if not f or f.type not in ("vente", "avoir_vente") or not f.point_vente_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket introuvable.")
    roles = assert_acces_societe(db, user, f.societe_id)
    assert_role(roles, ROLES_POS)
    tk = _ticket_dict(db, f)
    # quantités déjà retournées par ligne (pour l'écran de retour)
    if f.type == "vente":
        deja = {}
        for lr in db.execute(select(models.LigneFacture).join(
                models.Facture, models.Facture.id == models.LigneFacture.facture_id).where(
                models.Facture.origine_id == f.id,
                models.Facture.type == "avoir_vente")).scalars():
            if lr.origine_ligne_id:
                deja[str(lr.origine_ligne_id)] = deja.get(str(lr.origine_ligne_id), 0.0) + float(lr.qte)
        for l in tk["lignes"]:
            l["deja_retourne"] = round(deja.get(l["id"], 0.0), 3)
    return tk


class RetourLigneIn(BaseModel):
    ligne_id: uuid.UUID
    qte: float = Field(gt=0)


class PosRetourIn(BaseModel):
    facture_id: uuid.UUID
    mode: str = Field(default="espece", pattern="^(espece|credit)$")
    motif: str | None = None
    lignes: list[RetourLigneIn]


@router.post("/pos/retour", status_code=status.HTTP_201_CREATED)
def pos_retour(societe_id: uuid.UUID, payload: PosRetourIn, db: Session = Depends(get_db),
               user: models.Utilisateur = Depends(get_current_user)):
    """Retour client sur un ticket : ré-entrée en stock au coût d'origine, avoir
    (AVV), écriture inverse, remboursement en espèces (sortie de caisse) ou
    porté au crédit du compte client."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)
    societe = db.get(models.Societe, societe_id)
    fac = db.get(models.Facture, payload.facture_id)
    if not fac or fac.societe_id != societe_id or fac.type != "vente" or not fac.point_vente_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ticket d'origine invalide.")
    if not payload.lignes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucune ligne à retourner.")
    pv = db.get(models.PointVente, fac.point_vente_id)
    caisse = db.get(models.Caisse, pv.caisse_id)
    tiers = db.get(models.Tiers, fac.tiers_id)
    client_reel = tiers and tiers.code != "COMPTANT"
    sess = None
    if payload.mode == "espece":
        sess = _session_ouverte(db, caisse.id)
        if not sess:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Ouvrez la caisse « {caisse.libelle} » pour rembourser en espèces.")
    elif not client_reel:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Avoir sur compte client impossible : la vente était au comptant anonyme.")

    # quantités déjà retournées (tous avoirs confondus)
    deja: dict[str, float] = {}
    for lr in db.execute(select(models.LigneFacture).join(
            models.Facture, models.Facture.id == models.LigneFacture.facture_id).where(
            models.Facture.origine_id == fac.id,
            models.Facture.type == "avoir_vente")).scalars():
        if lr.origine_ligne_id:
            k = str(lr.origine_ligne_id)
            deja[k] = deja.get(k, 0.0) + float(lr.qte)

    jour = date.today()
    numero = services.next_numero(db, "avoir_vente", jour.year, societe.code, societe.id)
    avoir = models.Facture(societe_id=societe_id, type="avoir_vente", numero=numero,
                           tiers_id=fac.tiers_id, date_facture=jour, statut="validee",
                           point_vente_id=fac.point_vente_id, origine_id=fac.id,
                           note=(payload.motif or "").strip() or None, created_by=user.id)
    db.add(avoir)
    db.flush()

    lignes_par_id = {str(l.id): l for l in fac.lignes}
    total_ht = total_tva = valeur_stock = points_repris = 0.0
    stock_par_compte: dict[str, float] = {}
    la_list = []
    for rl in payload.lignes:
        orig = lignes_par_id.get(str(rl.ligne_id))
        if not orig:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ligne étrangère au ticket d'origine.")
        qte_r = float(rl.qte)
        restant = float(orig.qte) - deja.get(str(orig.id), 0.0)
        if qte_r > restant + 1e-6:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Retour impossible : {qte_r} demandé, {restant} restant sur « {orig.designation} ».")
        # montants au prorata de la ligne d'origine (net de remise)
        ht = round(float(orig.montant_ht) * qte_r / float(orig.qte), 2)
        tva = round(float(orig.montant_tva) * qte_r / float(orig.qte), 2)
        total_ht += ht
        total_tva += tva
        la = models.LigneFacture(facture_id=avoir.id, article_id=orig.article_id,
                                 designation=orig.designation, qte=qte_r,
                                 prix_unitaire=float(orig.prix_unitaire),
                                 remise_pct=float(orig.remise_pct or 0),
                                 taux_tva=float(orig.taux_tva), montant_ht=ht, montant_tva=tva,
                                 origine_ligne_id=orig.id)
        db.add(la)
        la_list.append(la)
        art = db.get(models.Article, orig.article_id) if orig.article_id else None
        if art and art.gere_stock:
            # ré-entrée au coût de sortie d'origine (CUMP du jour de la vente)
            mvt = db.execute(select(models.MouvementStock).where(
                models.MouvementStock.reference == fac.numero,
                models.MouvementStock.article_id == art.id,
                models.MouvementStock.sens == "sortie")).scalars().first()
            cout = float(mvt.cout_unitaire) if mvt else (float(art.stock_valeur) / float(art.stock_qte)
                                                         if art.stock_qte else 0.0)
            val = round(qte_r * cout, 2)
            art.stock_qte = round(float(art.stock_qte) + qte_r, 3)
            art.stock_valeur = round(float(art.stock_valeur) + val, 2)
            valeur_stock += val
            stock_par_compte[art.compte_stock] = round(stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            db.add(models.MouvementStock(societe_id=societe_id, article_id=art.id, date_mvt=jour,
                                         sens="entree", qte=qte_r, cout_unitaire=round(cout, 4),
                                         valeur=val, type_operation="retour_vente", reference=numero))
        if art and client_reel:
            points_repris += qte_r * float(art.points_fidelite)

    t_ht, t_tva = round(total_ht, 2), round(total_tva, 2)
    t_ttc = round(t_ht + t_tva, 2)
    avoir.total_ht, avoir.total_tva, avoir.total_ttc = t_ht, t_tva, t_ttc
    avoir.cout_ventes = round(valeur_stock, 2)
    avoir.marge = round(t_ht - valeur_stock, 2)

    # écriture inverse + ré-entrée en stock
    compte_remb = caisse.compte_comptable if payload.mode == "espece" \
        else comptabilite._compte(db, "compte_client", societe_id)
    remboursements = [{"compte": compte_remb, "montant_usd": t_ttc,
                       "tiers_id": tiers.id if payload.mode == "credit" else None,
                       "libelle": f"Remboursement {numero}" if payload.mode == "espece"
                                  else f"Avoir {numero} — {tiers.nom}"}]
    ecr = comptabilite.comptabiliser_retour_pos(db, avoir, la_list, remboursements, user.id)
    avoir.ecriture_id = ecr.id
    for compte_stock, val in stock_par_compte.items():
        if val > 0:
            comptabilite.comptabiliser_variation_stock(db, avoir, compte_stock, val, entree=True, created_by=user.id)

    db.add(models.PaiementFacture(facture_id=avoir.id, mode="espece" if payload.mode == "espece" else "credit",
                                  devise="USD", montant=t_ttc, montant_usd=t_ttc, compte=compte_remb))
    if payload.mode == "espece":
        db.add(models.MouvementCaisse(
            caisse_id=caisse.id, session_id=sess.id,
            numero=services.next_numero(db, "bon_caisse", jour.year, societe.code, societe.id),
            reference=numero, sens="sortie", nature="Retour POS", devise="USD",
            montant=t_ttc, montant_usd=t_ttc,
            tiers_id=tiers.id if client_reel else None, tiers_nom=tiers.nom if client_reel else None,
            reference_type="facture", reference_id=avoir.id,
            libelle=f"Remboursement retour {numero} (ticket {fac.numero})", created_by=user.id))

    if client_reel and points_repris:
        tiers.points_fidelite = round(float(tiers.points_fidelite or 0) - points_repris, 2)

    services.enregistrer_audit(db, user.id, "INSERT", "facture", avoir.id, None,
                               {"numero": numero, "origine": fac.numero, "ttc": t_ttc,
                                "mode": payload.mode})
    db.commit()
    return _ticket_dict(db, avoir)


# ── Rapport de caisse POS (rapport « X ») ────────────────────────────
@router.get("/pos/rapport")
def pos_rapport(societe_id: uuid.UUID, point_vente_id: uuid.UUID, jour: date | None = None,
                db: Session = Depends(get_db),
                user: models.Utilisateur = Depends(get_current_user)):
    """Synthèse de la journée d'un point de vente : CA, remises, retours,
    encaissements par mode, palmarès articles, ventes par vendeur et par catégorie."""
    roles = assert_acces_societe(db, user, societe_id)
    assert_role(roles, ROLES_POS)
    jour = jour or date.today()
    facs = db.execute(select(models.Facture).where(
        models.Facture.societe_id == societe_id,
        models.Facture.point_vente_id == point_vente_id,
        models.Facture.type.in_(["vente", "avoir_vente"]),
        models.Facture.date_facture == jour)).scalars().all()
    ventes = [f for f in facs if f.type == "vente"]
    avoirs = [f for f in facs if f.type == "avoir_vente"]

    ca_ht = round(sum(float(f.total_ht) for f in ventes), 2)
    tva = round(sum(float(f.total_tva) for f in ventes), 2)
    ttc = round(sum(float(f.total_ttc) for f in ventes), 2)
    remises = round(sum(float(f.remise_totale or 0) for f in ventes), 2)
    marge = round(sum(float(f.marge or 0) for f in ventes) - sum(float(a.marge or 0) for a in avoirs), 2)
    retours_ttc = round(sum(float(a.total_ttc) for a in avoirs), 2)
    monnaie = round(sum(float(f.pos_monnaie_usd or 0) for f in ventes), 2)

    par_mode: dict[str, dict] = {}
    for f in facs:
        signe = 1 if f.type == "vente" else -1
        for p in db.execute(select(models.PaiementFacture).where(
                models.PaiementFacture.facture_id == f.id)).scalars():
            m = par_mode.setdefault(p.mode, {"usd": 0.0, "cdf": 0.0, "nb": 0})
            m["nb"] += 1
            if p.devise == "CDF":
                m["cdf"] = round(m["cdf"] + signe * float(p.montant), 0)
            m["usd"] = round(m["usd"] + signe * float(p.montant_usd), 2)
    # la monnaie rendue sort des espèces
    if monnaie and "espece" in par_mode:
        par_mode["espece"]["usd"] = round(par_mode["espece"]["usd"] - monnaie, 2)

    par_article: dict = {}
    par_categorie: dict[str, float] = {}
    for f in facs:
        signe = 1 if f.type == "vente" else -1
        for l in f.lignes:
            art = db.get(models.Article, l.article_id) if l.article_id else None
            key = art.code if art else l.designation
            a = par_article.setdefault(key, {"code": key, "designation": l.designation,
                                             "qte": 0.0, "ht": 0.0})
            a["qte"] = round(a["qte"] + signe * float(l.qte), 3)
            a["ht"] = round(a["ht"] + signe * float(l.montant_ht), 2)
            cat = (art.categorie if art else None) or "Sans catégorie"
            par_categorie[cat] = round(par_categorie.get(cat, 0.0) + signe * float(l.montant_ht), 2)

    par_vendeur: dict = {}
    for f in ventes:
        v = db.get(models.Utilisateur, f.created_by) if f.created_by else None
        nom = f"{v.prenom or ''} {v.nom}".strip() if v else "—"
        s = par_vendeur.setdefault(nom, {"vendeur": nom, "nb": 0, "ttc": 0.0})
        s["nb"] += 1
        s["ttc"] = round(s["ttc"] + float(f.total_ttc), 2)

    taux = _taux_cdf(db, jour)
    net = round(ttc - retours_ttc, 2)
    return {
        "jour": jour.isoformat(), "taux_cdf": taux,
        "nb_tickets": len(ventes), "nb_retours": len(avoirs),
        "ca_ht": ca_ht, "tva": tva, "ttc": ttc, "remises": remises,
        "retours_ttc": retours_ttc, "net_ttc": net,
        "net_ttc_cdf": round(net * taux, 0) if taux else None,
        "marge": marge, "monnaie_rendue": monnaie,
        "panier_moyen": round(ttc / len(ventes), 2) if ventes else 0.0,
        "par_mode": par_mode,
        "par_categorie": [{"categorie": k, "ht": v} for k, v in
                          sorted(par_categorie.items(), key=lambda x: -x[1])],
        "palmares": sorted(par_article.values(), key=lambda x: -x["ht"])[:10],
        "par_vendeur": sorted(par_vendeur.values(), key=lambda x: -x["ttc"]),
    }
