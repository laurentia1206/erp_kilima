"""Cycle commercial & POS — portage exact de backend/app/routers/commercial.py.

Articles/stock (CUMP), tiers, factures achat/vente avec frais annexes, commandes
→ réceptions (3 voies) → facture fournisseur, listes de prix, points de vente,
POS complet (vente fractionnée, tickets, retours/avoirs, rapport X).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import comptabilite, intersociete_lib, services, stock_lib
from .erreurs import refus
from .auth import assert_acces_societe, assert_role
from .caisse_views import _session_ouverte, _soldes
from .models import (Article, Avance, Caisse, Commande, CompteBancaire, Course, Depot, Devis,
                     Facture, FraisFacture, FraisReception, Justification, LigneCommande,
                     LigneEcriture, LigneFacture, LigneReception, ListePrix,
                     MouvementCaisse, MouvementStock, PaiementFacture, PointVente,
                     Reception, SessionCaisse, Societe, TarifArticle, Tiers, Utilisateur)
from .views import _societe_param
from .catalogue import verifier_doublon, verrouiller_catalogue, tiers_visibles, tiers_disponible, normaliser

ROLES = {"COMPTABLE", "DFI"}
ROLES_POS = {"COMPTABLE", "DFI", "CAISSIER_CENTRAL", "CAISSIER_VENDEUR"}


def _acces(request, societe_id, roles_requis=ROLES):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, roles_requis)
    return roles


# ── Articles ─────────────────────────────────────────────────────────
def _article_dict(a: Article) -> dict:
    qte = float(a.stock_qte or 0)
    val = float(a.stock_valeur or 0)
    return {"id": str(a.id), "code": a.code, "designation": a.designation,
            "unite": a.unite, "prix_achat": float(a.prix_achat),
            "prix_vente": float(a.prix_vente), "assujetti_tva": bool(a.assujetti_tva),
            "taux_tva": float(a.taux_tva), "categorie": a.categorie,
            "nature": a.nature or "marchandise",
            "code_barres": a.code_barres, "taux_commission": float(a.taux_commission),
            "points_fidelite": float(a.points_fidelite), "compte_achat": a.compte_achat,
            "compte_vente": a.compte_vente, "compte_stock": a.compte_stock,
            "gere_stock": bool(a.gere_stock), "actif": bool(a.actif),
            "stock_qte": round(qte, 3), "stock_valeur": round(val, 2),
            "cump": round(val / qte, 2) if qte else 0.0}


@api_view(["GET", "POST"])
@transaction.atomic
def articles(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        code = (payload.get("code") or "").strip().upper()
        if not code or not (payload.get("designation") or "").strip():
            return refus({"detail": "code et designation requis."}, status=422)
        verrouiller_catalogue(sid)
        verifier_doublon(Article.objects.filter(societe_id=sid), payload, 'designation')
        assujetti = payload.get("assujetti_tva", True)
        taux = payload["taux_tva"] if payload.get("taux_tva") is not None else float(
            services.get_parametre("tva.taux_defaut", sid, "16"))
        nature = payload.get("nature", "marchandise")
        if nature not in ("marchandise", "matiere_premiere", "consommable"):
            return refus({"detail": "nature : marchandise, matiere_premiere ou "
                                    "consommable."}, status=422)
        a = Article.objects.create(
            societe_id=sid, code=code, designation=payload["designation"].strip(),
            nature=nature,
            unite=payload.get("unite", "unité"), prix_achat=payload.get("prix_achat", 0),
            prix_vente=payload.get("prix_vente", 0), assujetti_tva=assujetti,
            taux_tva=taux if assujetti else 0,
            categorie=payload.get("categorie") or None,
            code_barres=payload.get("code_barres") or None,
            taux_commission=payload.get("taux_commission", 0),
            points_fidelite=payload.get("points_fidelite", 0),
            compte_achat=payload.get("compte_achat", "601"),
            compte_vente=payload.get("compte_vente", "701"),
            compte_stock=payload.get("compte_stock", "31"),
            gere_stock=payload.get("gere_stock", True))
        return Response(_article_dict(a), status=201)

    arts = list(Article.objects.filter(societe_id=sid).order_by("code"))
    q = request.query_params.get("q")
    if q:
        ql = q.lower()
        arts = [a for a in arts if ql in a.code.lower() or ql in a.designation.lower()]
    return Response([_article_dict(a) for a in arts])


@api_view(["PATCH"])
@transaction.atomic
def maj_article(request, article_id):
    a = Article.objects.filter(id=article_id).first()
    if not a:
        return refus({"detail": "Article introuvable."}, status=404)
    _acces(request, a.societe_id)
    payload = request.data or {}
    controle = {'confirmer_homonyme':payload.get('confirmer_homonyme')}
    if 'designation' in payload and normaliser(payload['designation']) != normaliser(a.designation):
        controle['designation']=payload['designation']
    if 'code_barres' in payload:
        controle['code_barres']=payload['code_barres']
    verrouiller_catalogue(a.societe_id)
    verifier_doublon(Article.objects.filter(societe_id=a.societe_id),controle,'designation',a.id)
    if payload.get("nature") is not None:
        if payload["nature"] not in ("marchandise", "matiere_premiere",
                                     "consommable"):
            return refus({"detail": "nature : marchandise, matiere_premiere ou "
                                    "consommable."}, status=422)
        a.nature = payload["nature"]
    if payload.get("gere_stock") is not None \
            and bool(payload["gere_stock"]) != bool(a.gere_stock):
        if not payload["gere_stock"] and (float(a.stock_qte or 0) != 0
                                          or float(a.stock_valeur or 0) != 0):
            return refus({"detail": f"{a.code} a encore du stock "
                                    f"({float(a.stock_qte)} {a.unite}, "
                                    f"{float(a.stock_valeur):.2f} USD) — videz-le "
                                    f"(inventaire ou vente) avant de passer en "
                                    f"« sans stock »."}, status=409)
        a.gere_stock = bool(payload["gere_stock"])
    for f in ("designation", "prix_achat", "prix_vente", "assujetti_tva", "taux_tva",
              "categorie", "code_barres", "taux_commission", "points_fidelite", "actif"):
        v = payload.get(f)
        if v is not None:
            setattr(a, f, v.strip() if isinstance(v, str) else v)
    if payload.get("assujetti_tva") is False:
        a.taux_tva = 0
    a.save()
    return Response(_article_dict(a))


# ── Tiers (clients / fournisseurs) ───────────────────────────────────
def _tiers_dict(t: Tiers) -> dict:
    return {"id": str(t.id), "type": t.type, "code": t.code, "nom": t.nom,
            "societe_id": str(t.societe_id) if t.societe_id else None, "actif": bool(t.actif),
            "intra_groupe": bool(t.intra_groupe),
            "limite_credit_usd": float(t.limite_credit_usd)
            if t.limite_credit_usd is not None else None,
            "points_fidelite": float(t.points_fidelite or 0)}


@api_view(["GET", "POST"])
@transaction.atomic
def tiers_commercial(request):
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)   # le caissier POS doit pouvoir chercher un client
    if request.method == "POST":
        payload = request.data or {}
        if payload.get("type") not in ("client", "fournisseur") \
                or not (payload.get("code") or "").strip() \
                or not (payload.get("nom") or "").strip():
            return refus({"detail": "type (client|fournisseur), code et nom requis."},
                            status=422)
        verrouiller_catalogue(sid)
        verifier_doublon(tiers_visibles(sid), payload, 'nom')
        t = Tiers.objects.create(
            societe_id=sid, type=payload["type"], code=payload["code"].strip().upper(),
            nom=payload["nom"].strip(), intra_groupe=payload.get("intra_groupe", False),
            limite_credit_usd=payload.get("limite_credit_usd"))
        return Response(_tiers_dict(t), status=201)

    from django.db.models import Q
    q = Tiers.objects.filter(Q(societe_id=sid) | Q(societe_id__isnull=True))
    type_ = request.query_params.get("type")
    if type_:
        q = q.filter(type=type_)
    return Response([_tiers_dict(t) for t in q.order_by("nom")])


@api_view(["PATCH"])
@transaction.atomic
def maj_tiers(request, tiers_id):
    t = Tiers.objects.filter(id=tiers_id).first()
    if not t:
        return refus({"detail": "Tiers introuvable."}, status=404)
    _acces(request, t.societe_id)
    payload = request.data or {}
    if 'nom' in payload and normaliser(payload['nom']) != normaliser(t.nom):
        verrouiller_catalogue(t.societe_id)
        verifier_doublon(tiers_visibles(t.societe_id),payload,'nom',t.id)
    for f in ("nom", "type", "limite_credit_usd", "compte_auxiliaire", "actif"):
        v = payload.get(f)
        if v is not None:
            setattr(t, f, v.strip() if isinstance(v, str) else v)
    t.save()
    services.enregistrer_audit(request.user.id, "UPDATE", "tiers", t.id, None,
                               {"nom": t.nom})
    return Response(_tiers_dict(t))


# ── Factures ─────────────────────────────────────────────────────────
def _reglement_facture(f: Facture) -> dict:
    if f.type != "vente":
        return {}
    regle = round(sum(float(p.montant_usd) for p in PaiementFacture.objects.filter(
        facture_id=f.id).exclude(mode="credit")), 2)
    solde = round(float(f.total_ttc) - regle, 2)
    statut = "payee" if solde <= 0.009 else ("partielle" if regle > 0 else "due")
    retard = bool(f.echeance and solde > 0.009 and f.echeance < date.today())
    return {"regle_usd": regle, "solde_du_usd": max(solde, 0.0),
            "statut_reglement": statut, "en_retard": retard,
            "devis_id": str(f.devis_id) if f.devis_id else None}


def _resoudre_contrepartie_frais(societe: Societe, f: dict, jour, ref_numero, ref_type,
                                 ref_id, fht, ftva, user):
    """(compte_reglement, caisse_id) — ou Response d'erreur."""
    mode = f.get("mode", "credit")
    if mode == "banque":
        b = CompteBancaire.objects.filter(id=f.get("banque_id")).first() \
            if f.get("banque_id") else None
        if not b or str(b.societe_id) != str(societe.id):
            return refus({"detail": "Banque du frais invalide."}, status=400)
        return b.compte_comptable, None
    if mode == "caisse":
        c = Caisse.objects.filter(id=f.get("caisse_id")).first() \
            if f.get("caisse_id") else None
        if not c or str(c.societe_id) != str(societe.id):
            return refus({"detail": "Caisse du frais invalide."}, status=400)
        sess = SessionCaisse.objects.filter(caisse_id=c.id, statut="ouverte").first()
        if not sess:
            return refus({"detail": f"Ouvrez la caisse « {c.libelle} » pour régler ce "
                                       f"frais."}, status=409)
        MouvementCaisse.objects.create(
            caisse_id=c.id, session_id=sess.id,
            numero=services.next_numero("bon_caisse", jour.year, societe.code, societe.id),
            reference=ref_numero, sens="sortie", nature=f"Frais achat — {f.get('libelle')}",
            devise="USD", montant=round(fht + ftva, 2), montant_usd=round(fht + ftva, 2),
            reference_type=ref_type, reference_id=ref_id,
            libelle=f"{f.get('libelle')} ({ref_numero})", created_by=user.id,
            date_mouvement=services.maintenant().date(), heure=services.maintenant())
        return c.compte_comptable, c.id
    return None, None   # crédit : contrepartie par tiers (résolue à la comptabilisation)


def _facture_dict(f: Facture) -> dict:
    tiers = Tiers.objects.filter(id=f.tiers_id).first()
    lignes = list(LigneFacture.objects.filter(facture_id=f.id))
    arts = {}
    for l in lignes:
        if l.article_id and l.article_id not in arts:
            a = Article.objects.filter(id=l.article_id).first()
            arts[l.article_id] = a.code if a else None
    frais = list(FraisFacture.objects.filter(facture_id=f.id))

    def _contrepartie(x):
        if x.mode == "credit":
            t = Tiers.objects.filter(id=x.tiers_id).first() if x.tiers_id else None
            return t.nom if t else None
        return x.compte_reglement or ""

    return {
        "id": str(f.id), "numero": f.numero, "type": f.type,
        "tiers": tiers.nom if tiers else None, "tiers_id": str(f.tiers_id),
        "date": f.date_facture.isoformat(),
        "echeance": f.echeance.isoformat() if f.echeance else None,
        "reference": f.reference,
        "total_ht": float(f.total_ht), "total_frais": float(f.total_frais),
        "total_tva": float(f.total_tva), "total_ttc": float(f.total_ttc),
        "repartition": f.repartition,
        "cout_ventes": float(f.cout_ventes) if f.cout_ventes is not None else None,
        "marge": float(f.marge) if f.marge is not None else None,
        "intra_groupe": bool(f.intra_groupe), "statut": f.statut,
        **_reglement_facture(f),
        "lignes": [{"article": arts.get(l.article_id), "designation": l.designation,
                    "qte": float(l.qte), "prix_unitaire": float(l.prix_unitaire),
                    "remise_pct": float(l.remise_pct or 0),
                    "taux_tva": float(l.taux_tva), "montant_ht": float(l.montant_ht),
                    "montant_tva": float(l.montant_tva),
                    "frais_reparti": float(l.frais_reparti),
                    "cout_entree": float(l.cout_entree)} for l in lignes],
        "frais": [{"libelle": x.libelle, "compte": x.compte,
                   "montant_ht": float(x.montant_ht), "taux_tva": float(x.taux_tva),
                   "montant_tva": float(x.montant_tva), "mode": x.mode,
                   "contrepartie": _contrepartie(x)} for x in frais],
    }


@api_view(["GET", "POST"])
def factures(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        return _creer_facture(request, sid)
    q = Facture.objects.filter(societe_id=sid)
    type_ = request.query_params.get("type")
    if type_:
        q = q.filter(type=type_)
    return Response([_facture_dict(f) for f in q.order_by("-created_at")])


def _creer_facture(request, sid):
    """Crée une facture, met à jour le stock (CUMP) et génère l'écriture."""
    payload = request.data or {}
    if payload.get("type") not in ("achat", "vente"):
        return refus({"detail": "type (achat|vente) requis."}, status=422)
    societe = Societe.objects.filter(id=sid).first()
    tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
    if not tiers_disponible(tiers, sid):
        return refus({"detail": "Tiers introuvable."}, status=400)
    if not payload.get("lignes"):
        return refus({"detail": "Au moins une ligne."}, status=400)
    type_ = payload["type"]
    repartition = payload.get("repartition", "quantite")

    with transaction.atomic():
        jour = date.fromisoformat(payload["date_facture"]) \
            if payload.get("date_facture") else date.today()
        echeance = date.fromisoformat(payload["echeance"]) \
            if payload.get("echeance") else None
        numero = services.next_numero(f"facture_{type_}", jour.year, societe.code,
                                      societe.id)
        fac = Facture.objects.create(
            societe_id=sid, type=type_, numero=numero, tiers_id=tiers.id,
            date_facture=jour, echeance=echeance,
            intra_groupe=payload.get("intra_groupe", False) or bool(tiers.intra_groupe),
            statut="validee", created_by=request.user.id,
            created_at=services.maintenant())

        total_ht = total_tva = 0.0
        lm_pairs = []
        defaut_tva = float(services.get_parametre("tva.taux_defaut", sid, "16"))
        for l in payload["lignes"]:
            art = Article.objects.filter(id=l.get("article_id")).first() \
                if l.get("article_id") else None
            if l.get("article_id") and (not art or str(art.societe_id) != str(sid)):
                return refus({"detail": "Article introuvable."}, status=400)
            taux = l["taux_tva"] if l.get("taux_tva") is not None else \
                (float(art.taux_tva) if art else defaut_tva)
            if art is not None and not art.assujetti_tva:
                taux = 0.0
            qte = float(l.get("qte", 0))
            pu = float(l.get("prix_unitaire", 0))
            if qte <= 0 or pu < 0:
                return refus({"detail": "Ligne invalide (qte > 0, prix ≥ 0)."},
                                status=422)
            ht = round(qte * pu, 2)
            tva = round(ht * taux / 100, 2)
            total_ht += ht
            total_tva += tva
            lm = LigneFacture.objects.create(
                facture_id=fac.id, article_id=l.get("article_id"),
                designation=(l.get("designation")
                             or (art.designation if art else "")).strip(),
                qte=qte, prix_unitaire=pu, taux_tva=taux,
                montant_ht=ht, montant_tva=tva, cout_entree=ht)
            lm_pairs.append((lm, art))

        # ── Frais annexes (achat) ────────────────────────────────────
        frais_objs = []
        total_frais = total_frais_tva = 0.0
        if type_ == "achat":
            for f in payload.get("frais") or []:
                ftaux = f["taux_tva"] if f.get("taux_tva") is not None else 16.0
                fht = round(float(f.get("montant_ht", 0)), 2)
                ftva = round(fht * ftaux / 100, 2)
                total_frais += fht
                total_frais_tva += ftva
                res = _resoudre_contrepartie_frais(societe, f, jour, numero, "facture",
                                                   fac.id, fht, ftva, request.user)
                if isinstance(res, Response):
                    return res
                compte_reg, caisse_id = res
                ff = FraisFacture.objects.create(
                    facture_id=fac.id, libelle=(f.get("libelle") or "").strip(),
                    compte=f.get("compte", "6085"), montant_ht=fht, taux_tva=ftaux,
                    montant_tva=ftva, mode=f.get("mode", "credit"),
                    tiers_id=f.get("tiers_id"), compte_reglement=compte_reg,
                    caisse_id=caisse_id)
                frais_objs.append(ff)
            total_frais = round(total_frais, 2)
            total_frais_tva = round(total_frais_tva, 2)

            stock_lines = [(lm, art) for lm, art in lm_pairs if art and art.gere_stock]
            if total_frais > 0 and stock_lines:
                weights = [float(lm.montant_ht) if repartition == "valeur"
                           else float(lm.qte) for lm, _ in stock_lines]
                tw = sum(weights) or 1.0
                cumul = 0.0
                for i, (lm, _) in enumerate(stock_lines):
                    part = round(total_frais * weights[i] / tw, 2) \
                        if i < len(stock_lines) - 1 else round(total_frais - cumul, 2)
                    cumul = round(cumul + part, 2)
                    lm.frais_reparti = part
                    lm.cout_entree = round(float(lm.montant_ht) + part, 2)
                    lm.save(update_fields=["frais_reparti", "cout_entree"])

        fac.total_ht = round(total_ht, 2)
        fac.total_frais = total_frais
        fac.total_tva = round(total_tva + total_frais_tva, 2)
        fac.total_ttc = round(total_ht + total_frais + total_tva + total_frais_tva, 2)
        fac.repartition = repartition

        # ── Mouvements de stock (CUMP, dépôt central) ────────────────
        cout_ventes = 0.0
        stock_par_compte: dict[str, float] = {}
        central = stock_lib.depot_central(sid)
        for lm, art in lm_pairs:
            if not art or not art.gere_stock:
                continue
            qte = float(lm.qte)
            if type_ == "achat":
                valeur = round(float(lm.cout_entree), 2)
                stock_lib.entree(art, central, qte, valeur, "achat", numero,
                                 jour=jour)
            else:
                dispo = stock_lib.qte_disponible(central.id, art.id)
                if dispo < qte - 1e-6:
                    return refus({"detail": f"Stock insuffisant pour {art.code} "
                                            f"au dépôt central : {dispo} "
                                            f"{art.unite} disponible(s), {qte} "
                                            f"demandé(s)."}, status=409)
                valeur = stock_lib.sortie(art, central, qte, "vente", numero,
                                          jour=jour)
                cout_ventes += valeur
            stock_par_compte[art.compte_stock] = round(
                stock_par_compte.get(art.compte_stock, 0.0) + valeur, 2)

        if type_ == "vente":
            fac.cout_ventes = round(cout_ventes, 2)
            fac.marge = round(fac.total_ht - cout_ventes, 2)

        statut_piece = intersociete_lib._statut_piece(
            sid, "achat" if type_ == "achat" else "vente")
        ecr = comptabilite.comptabiliser_facture(fac, [lm for lm, _ in lm_pairs],
                                                 request.user.id, frais_objs=frais_objs,
                                                 statut=statut_piece)
        fac.ecriture_id = ecr.id
        fac.save()
        for compte_stock, valeur in stock_par_compte.items():
            if valeur > 0:
                comptabilite.comptabiliser_variation_stock(
                    fac, compte_stock, valeur, entree=(type_ == "achat"),
                    created_by=request.user.id, statut=statut_piece)
        # Intersociété : client du groupe → facture d'achat miroir chez lui
        if type_ == "vente":
            intersociete_lib.creer_facture_miroir(fac, request.user.id)
        services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id, None,
                                   {"numero": numero, "type": type_,
                                    "ttc": float(fac.total_ttc)})
    return Response(_facture_dict(fac), status=201)


@api_view(["GET"])
def detail_facture(request, facture_id):
    f = Facture.objects.filter(id=facture_id).first()
    if not f:
        return refus({"detail": "Facture introuvable."}, status=404)
    _acces(request, f.societe_id)
    return Response(_facture_dict(f))


# ── Stock ────────────────────────────────────────────────────────────
@api_view(["GET"])
def etat_stock(request):
    sid = _societe_param(request)
    _acces(request, sid)
    arts = Article.objects.filter(societe_id=sid, gere_stock=True).order_by("code")
    lignes = [_article_dict(a) for a in arts]
    return Response({"lignes": lignes,
                     "valeur_totale": round(sum(l["stock_valeur"] for l in lignes), 2)})


@api_view(["GET"])
def mouvements_stock(request):
    sid = _societe_param(request)
    _acces(request, sid)
    noms = dict(Article.objects.filter(societe_id=sid).values_list("id", "code"))
    q = MouvementStock.objects.filter(societe_id=sid)
    article_id = request.query_params.get("article_id")
    if article_id:
        q = q.filter(article_id=article_id)
    return Response([{"date": m.date_mvt.isoformat(), "article": noms.get(m.article_id, ""),
                      "sens": m.sens, "type": m.type_operation, "reference": m.reference,
                      "qte": float(m.qte), "cout_unitaire": float(m.cout_unitaire),
                      "valeur": float(m.valeur)} for m in q.order_by("-created_at")])


# ── Rapports commerciaux ─────────────────────────────────────────────
@api_view(["GET"])
def achats_historique(request):
    """Historique unifié des achats entrés en stock (facture, réception, avance)."""
    sid = _societe_param(request)
    _acces(request, sid)
    codes = dict(Article.objects.filter(societe_id=sid).values_list("id", "code"))
    tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
    fac_tiers, rec_tiers, just_tiers = {}, {}, {}
    for f in Facture.objects.filter(societe_id=sid, type="achat"):
        fac_tiers[f.numero] = tiers_noms.get(f.tiers_id)
    for r in Reception.objects.filter(societe_id=sid):
        cmd = Commande.objects.filter(id=r.commande_id).first()
        rec_tiers[r.numero] = tiers_noms.get(cmd.tiers_id) if cmd else None
    for j in Justification.objects.all():
        av = Avance.objects.filter(id=j.avance_id).first()
        if av and str(av.societe_id) == str(sid):
            just_tiers[j.numero] = tiers_noms.get(av.beneficiaire_tiers_id)

    mvts = (MouvementStock.objects.filter(societe_id=sid, sens="entree")
            .order_by("-created_at"))
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
            g = groups[ref] = {"reference": ref, "date": m.date_mvt.isoformat(),
                               "origine": origine, "tiers": tiers, "articles": [],
                               "total_valeur": 0.0, "total_qte": 0.0}
        g["articles"].append({"code": codes.get(m.article_id, ""), "qte": float(m.qte),
                              "cout": float(m.valeur)})
        g["total_valeur"] = round(g["total_valeur"] + float(m.valeur), 2)
        g["total_qte"] = round(g["total_qte"] + float(m.qte), 3)
    return Response(sorted(groups.values(), key=lambda x: x["date"], reverse=True))


@api_view(["GET"])
def ventes_synthese(request):
    """Synthèse des ventes : CA, marge, TVA collectée, palmarès des articles."""
    sid = _societe_param(request)
    _acces(request, sid)
    facs = list(Facture.objects.filter(societe_id=sid, type="vente"))
    avoirs = list(Facture.objects.filter(societe_id=sid, type="avoir_vente"))
    ca = round(sum(float(f.total_ht) for f in facs)
               - sum(float(a.total_ht) for a in avoirs), 2)
    marge = round(sum(float(f.marge or 0) for f in facs)
                  - sum(float(a.marge or 0) for a in avoirs), 2)
    tva = round(sum(float(f.total_tva) for f in facs)
                - sum(float(a.total_tva) for a in avoirs), 2)
    codes = dict(Article.objects.filter(societe_id=sid).values_list("id", "code"))
    ventes = MouvementStock.objects.filter(societe_id=sid, sens="sortie",
                                           type_operation="vente")
    par_article: dict = {}
    for m in ventes:
        a = par_article.setdefault(m.article_id, {"code": codes.get(m.article_id, ""),
                                                  "qte": 0.0, "cout": 0.0})
        a["qte"] = round(a["qte"] + float(m.qte), 3)
        a["cout"] = round(a["cout"] + float(m.valeur), 2)
    top = sorted(par_article.values(), key=lambda x: x["qte"], reverse=True)[:8]
    return Response({"chiffre_affaires": ca, "marge": marge, "tva_collectee": tva,
                     "nb_factures": len(facs),
                     "taux_marge": round(marge / ca * 100, 1) if ca else 0.0,
                     "palmares": top})


# ── Circuit 2 : commandes ────────────────────────────────────────────
def _commande_dict(c: Commande) -> dict:
    tiers = Tiers.objects.filter(id=c.tiers_id).first()
    lignes = list(LigneCommande.objects.filter(commande_id=c.id))
    codes = {}
    for l in lignes:
        if l.article_id and l.article_id not in codes:
            a = Article.objects.filter(id=l.article_id).first()
            codes[l.article_id] = a.code if a else None
    modifiable = c.statut == "envoyee" and all(float(l.qte_recue) <= 1e-9 for l in lignes)
    inter = None
    if c.devis_lie_id:
        dv = Devis.objects.filter(id=c.devis_lie_id).first()
        transporteur = Societe.objects.filter(id=c.transporteur_societe_id).first() \
            if c.transporteur_societe_id else None
        course = intersociete_lib.course_active(c.id)
        etat = "facturee" if c.statut == "soldee" else (
            "prise_en_charge" if dv and dv.statut == "confirme" else
            ("annulee" if dv and dv.statut == "annule" else "en_attente"))
        inter = {"etat": etat, "devis_numero": dv.numero if dv else None,
                 "devis_statut": dv.statut if dv else None,
                 "transporteur": transporteur.nom if transporteur else None,
                 "course_numero": course.numero if course else None,
                 "course_statut": course.statut if course else None,
                 "reception": intersociete_lib.reception_po_resume(c),
                 "etapes": intersociete_lib.etapes_po(c)}
    return {"id": str(c.id), "numero": c.numero, "tiers": tiers.nom if tiers else None,
            "tiers_id": str(c.tiers_id), "date": c.date_commande.isoformat(),
            "statut": c.statut,
            "date_livraison_prevue": c.date_livraison_prevue.isoformat()
            if c.date_livraison_prevue else None,
            "reference_fournisseur": c.reference_fournisseur, "modifiable": modifiable,
            "destination": c.destination, "intersociete": inter,
            "total_ht": float(c.total_ht), "intra_groupe": bool(c.intra_groupe),
            "lignes": [{"id": str(l.id), "article": codes.get(l.article_id),
                        "article_id": str(l.article_id) if l.article_id else None,
                        "designation": l.designation, "qte": float(l.qte),
                        "qte_recue": float(l.qte_recue),
                        "reste": round(float(l.qte) - float(l.qte_recue), 3),
                        "prix_unitaire": float(l.prix_unitaire),
                        "taux_tva": float(l.taux_tva)} for l in lignes]}


def _lignes_commande_depuis(payload, cmd_id, societe_id):
    """Crée les lignes et retourne le total HT (aides communes POST/PUT)."""
    total = 0.0
    defaut_tva = float(services.get_parametre("tva.taux_defaut", societe_id, "16"))
    for l in payload["lignes"]:
        art = Article.objects.filter(id=l.get("article_id")).first() \
            if l.get("article_id") else None
        if l.get('article_id') and (not art or str(art.societe_id) != str(societe_id)):
            from rest_framework.exceptions import ValidationError
            raise ValidationError('Choisissez un article de cette société.')
        taux = l["taux_tva"] if l.get("taux_tva") is not None else \
            (float(art.taux_tva) if art else defaut_tva)
        if art is not None and not art.assujetti_tva:
            taux = 0.0
        total += round(float(l.get("qte", 0)) * float(l.get("prix_unitaire", 0)), 2)
        LigneCommande.objects.create(
            commande_id=cmd_id, article_id=l.get("article_id"),
            designation=(l.get("designation") or (art.designation if art else "")).strip(),
            qte=l.get("qte", 1), prix_unitaire=l.get("prix_unitaire", 0), taux_tva=taux)
    return round(total, 2)


@api_view(["GET", "POST"])
def commandes(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        societe = Societe.objects.filter(id=sid).first()
        tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not tiers_disponible(tiers, sid):
            return refus({"detail": "Fournisseur introuvable."}, status=400)
        if not payload.get("lignes"):
            return refus({"detail": "Au moins une ligne."}, status=400)
        with transaction.atomic():
            jour = date.fromisoformat(payload["date_commande"]) \
                if payload.get("date_commande") else date.today()
            cmd = Commande.objects.create(
                societe_id=sid,
                numero=services.next_numero("commande", jour.year, societe.code,
                                            societe.id),
                tiers_id=tiers.id, date_commande=jour, statut="envoyee",
                date_livraison_prevue=date.fromisoformat(payload["date_livraison_prevue"])
                if payload.get("date_livraison_prevue") else None,
                reference_fournisseur=payload.get("reference_fournisseur") or None,
                destination=(payload.get("destination") or "").strip() or None,
                transporteur_societe_id=payload.get("transporteur_societe_id"),
                intra_groupe=payload.get("intra_groupe", False)
                or bool(tiers.intra_groupe),
                created_by=request.user.id, created_at=services.maintenant())
            cmd.total_ht = _lignes_commande_depuis(payload, cmd.id, sid)
            cmd.save(update_fields=["total_ht"])
            # PO intersociété : miroir vendeur + demande de course transporteur
            if tiers.societe_liee_id:
                intersociete_lib.creer_devis_miroir_commande(cmd, request.user.id)
                intersociete_lib.creer_demande_course(cmd, request.user.id)
            services.enregistrer_audit(request.user.id, "INSERT", "commande", cmd.id,
                                       None, {"numero": cmd.numero})
        return Response(_commande_dict(cmd), status=201)
    cs = Commande.objects.filter(societe_id=sid).order_by("-created_at")
    return Response([_commande_dict(c) for c in cs])


def _commande_modifiable(c: Commande) -> bool:
    if c.statut not in ("envoyee",):
        return False
    return all(float(l.qte_recue) <= 1e-9
               for l in LigneCommande.objects.filter(commande_id=c.id))


@api_view(["GET", "PUT"])
def commande_detail(request, commande_id):
    c = Commande.objects.filter(id=commande_id).first()
    if not c:
        return refus({"detail": "Commande introuvable."}, status=404)
    _acces(request, c.societe_id)
    if request.method == "PUT":
        payload = request.data or {}
        if c.devis_lie_id:
            return refus({"detail": "Commande intersociété : elle ne se modifie plus "
                                    "après émission (le vendeur a une copie miroir). "
                                    "Annulez-la tant qu'il n'a pas pris en charge, "
                                    "puis recréez-la."}, status=409)
        if not _commande_modifiable(c):
            return refus({"detail": "Commande déjà réceptionnée ou clôturée : non "
                                       "modifiable."}, status=409)
        if not payload.get("lignes"):
            return refus({"detail": "Au moins une ligne."}, status=400)
        tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not tiers_disponible(tiers, c.societe_id):
            return refus({"detail": "Fournisseur introuvable."}, status=400)
        with transaction.atomic():
            LigneCommande.objects.filter(commande_id=c.id).delete()
            c.tiers_id = tiers.id
            if payload.get("date_commande"):
                c.date_commande = date.fromisoformat(payload["date_commande"])
            c.date_livraison_prevue = date.fromisoformat(payload["date_livraison_prevue"]) \
                if payload.get("date_livraison_prevue") else None
            c.reference_fournisseur = payload.get("reference_fournisseur") or None
            c.intra_groupe = payload.get("intra_groupe", False) or bool(tiers.intra_groupe)
            c.total_ht = _lignes_commande_depuis(payload, c.id, c.societe_id)
            c.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "commande", c.id, None,
                                       {"numero": c.numero})
        return Response(_commande_dict(c))

    d = _commande_dict(c)
    # Rapprochement 3 voies : commandé / reçu / facturé
    recs = Reception.objects.filter(commande_id=c.id).order_by("created_at")
    recu_ht = facture_ht = 0.0
    recs_out = []
    for r in recs:
        rl = LigneReception.objects.filter(reception_id=r.id)
        r_ht = round(sum(float(x.montant_ht) for x in rl), 2)
        recu_ht += r_ht
        fac = Facture.objects.filter(reception_id=r.id).first()
        if fac:
            facture_ht += float(fac.total_ht)
        recs_out.append({"id": str(r.id), "numero": r.numero,
                         "date": r.date_reception.isoformat(), "statut": r.statut,
                         "montant_ht": r_ht, "facture": fac.numero if fac else None})
    cmd_ht = float(c.total_ht)
    d["receptions"] = recs_out
    d["controle"] = {"commande_ht": round(cmd_ht, 2), "recu_ht": round(recu_ht, 2),
                     "facture_ht": round(facture_ht, 2),
                     "ecart_recu": round(recu_ht - cmd_ht, 2),
                     "ecart_facture": round(facture_ht - recu_ht, 2)}
    return Response(d)


@api_view(["POST"])
def annuler_commande(request, commande_id):
    c = Commande.objects.filter(id=commande_id).first()
    if not c:
        return refus({"detail": "Commande introuvable."}, status=404)
    _acces(request, c.societe_id)
    if not _commande_modifiable(c):
        return refus({"detail": "Commande déjà réceptionnée ou clôturée : non "
                                   "annulable."}, status=409)
    # PO intersociété : annulable par l'acheteur SEULEMENT tant que le vendeur
    # n'a pas pris en charge — ensuite, c'est au vendeur d'annuler de son côté
    dv = Devis.objects.filter(id=c.devis_lie_id).first() if c.devis_lie_id else None
    if dv and dv.statut == "confirme":
        return refus({"detail": "Le vendeur a déjà pris la commande en charge — "
                                "l'annulation se décide avec lui (il annule sa "
                                "commande client de son côté)."}, status=409)
    with transaction.atomic():
        c.statut = "annulee"
        c.save(update_fields=["statut"])
        # cascade : le miroir chez le vendeur et les demandes de course s'annulent
        if dv and dv.statut in ("brouillon", "envoye"):
            dv.statut = "annule"
            dv.save(update_fields=["statut"])
        if c.devis_lie_id:
            Course.objects.filter(commande_origine_id=c.id,
                                  statut="demande").update(statut="annulee")
        services.enregistrer_audit(request.user.id, "UPDATE", "commande", c.id, None,
                                   {"numero": c.numero, "action": "annulee"})
    return Response(_commande_dict(c))


# ── Circuit 2 : réceptions ───────────────────────────────────────────
def _reception_dict(r: Reception) -> dict:
    cmd = Commande.objects.filter(id=r.commande_id).first()
    fournisseur = Tiers.objects.filter(id=cmd.tiers_id).first() if cmd else None
    lignes = list(LigneReception.objects.filter(reception_id=r.id))
    frais = list(FraisReception.objects.filter(reception_id=r.id))

    def _contrepartie(f):
        if f.mode == "credit":
            t = Tiers.objects.filter(id=f.tiers_id).first() if f.tiers_id else None
            return t.nom if t else None
        return f.compte_reglement or ""

    return {"id": str(r.id), "numero": r.numero, "commande": cmd.numero if cmd else None,
            "fournisseur": fournisseur.nom if fournisseur else None,
            "reference_fournisseur": cmd.reference_fournisseur if cmd else None,
            "commande_id": str(r.commande_id), "date": r.date_reception.isoformat(),
            "statut": r.statut, "total_valeur": float(r.total_valeur),
            "total_frais": float(r.total_frais), "repartition": r.repartition,
            "lignes": [{"designation": l.designation, "qte": float(l.qte),
                        "prix_unitaire": float(l.prix_unitaire),
                        "taux_tva": float(l.taux_tva), "montant_ht": float(l.montant_ht),
                        "frais_reparti": float(l.frais_reparti), "cout": float(l.cout)}
                       for l in lignes],
            "frais": [{"libelle": f.libelle, "compte": f.compte,
                       "montant_ht": float(f.montant_ht), "taux_tva": float(f.taux_tva),
                       "mode": f.mode, "contrepartie": _contrepartie(f)} for f in frais]}


@api_view(["POST"])
def receptionner(request, commande_id):
    """Réception (totale ou partielle) : stock au coût d'acquisition, D 31 / C 408."""
    cmd = Commande.objects.filter(id=commande_id).first()
    if not cmd:
        return refus({"detail": "Commande introuvable."}, status=404)
    _acces(request, cmd.societe_id)
    if cmd.statut in ("soldee", "annulee"):
        return refus({"detail": "Commande clôturée."}, status=409)
    if cmd.devis_lie_id:
        return refus({"detail": "Commande intersociété : le stock entrera "
                                   "automatiquement via la facture miroir quand le "
                                   "vendeur livrera et facturera — pas de réception "
                                   "manuelle."}, status=409)
    payload = request.data or {}
    if not payload.get("lignes"):
        return refus({"detail": "lignes requises."}, status=422)
    repartition = payload.get("repartition", "quantite")

    with transaction.atomic():
        jour = date.fromisoformat(payload["date_reception"]) \
            if payload.get("date_reception") else date.today()
        societe = Societe.objects.filter(id=cmd.societe_id).first()
        rec = Reception.objects.create(
            societe_id=cmd.societe_id,
            numero=services.next_numero("reception", jour.year, societe.code,
                                        cmd.societe_id),
            commande_id=cmd.id, date_reception=jour, repartition=repartition,
            statut="recue", created_by=request.user.id, created_at=services.maintenant())

        lignes_rec = []
        for lr in payload["lignes"]:
            lc = LigneCommande.objects.filter(id=lr.get("ligne_commande_id")).first()
            if not lc or lc.commande_id != cmd.id:
                return refus({"detail": "Ligne de commande invalide."}, status=400)
            qte_recue = float(lr.get("qte_recue", 0))
            reste = float(lc.qte) - float(lc.qte_recue)
            if qte_recue > reste + 1e-6:
                return refus({"detail": f"{lc.designation} : {qte_recue} reçu > "
                                           f"{round(reste, 3)} restant."}, status=400)
            ht = round(qte_recue * float(lc.prix_unitaire), 2)
            art = Article.objects.filter(id=lc.article_id).first() \
                if lc.article_id else None
            lm = LigneReception.objects.create(
                reception_id=rec.id, ligne_commande_id=lc.id, article_id=lc.article_id,
                designation=lc.designation, qte=qte_recue,
                prix_unitaire=lc.prix_unitaire, taux_tva=lc.taux_tva, montant_ht=ht,
                cout=ht, compte_stock=art.compte_stock if art else "31")
            lignes_rec.append((lm, lc, art))
            lc.qte_recue = round(float(lc.qte_recue) + qte_recue, 3)
            lc.save(update_fields=["qte_recue"])

        # Frais annexes : contrepartie réelle + répartition sur le coût du stock
        frais_ht = 0.0
        frais_objs = []
        for f in payload.get("frais") or []:
            ftaux = f["taux_tva"] if f.get("taux_tva") is not None else 16.0
            fht = round(float(f.get("montant_ht", 0)), 2)
            ftva = round(fht * ftaux / 100, 2)
            frais_ht += fht
            res = _resoudre_contrepartie_frais(societe, f, jour, rec.numero, "reception",
                                               rec.id, fht, ftva, request.user)
            if isinstance(res, Response):
                return res
            compte_reg, caisse_id = res
            fr = FraisReception.objects.create(
                reception_id=rec.id, libelle=(f.get("libelle") or "").strip(),
                compte=f.get("compte", "6085"), montant_ht=fht, taux_tva=ftaux,
                montant_tva=ftva, mode=f.get("mode", "credit"),
                tiers_id=f.get("tiers_id"), compte_reglement=compte_reg,
                caisse_id=caisse_id)
            frais_objs.append(fr)
        frais_ht = round(frais_ht, 2)
        if frais_ht > 0 and lignes_rec:
            w = [float(lm.qte) if repartition != "valeur" else float(lm.montant_ht)
                 for lm, _, _ in lignes_rec]
            tw = sum(w) or 1.0
            cumul = 0.0
            for i, (lm, _, _) in enumerate(lignes_rec):
                part = round(frais_ht * w[i] / tw, 2) if i < len(lignes_rec) - 1 \
                    else round(frais_ht - cumul, 2)
                cumul = round(cumul + part, 2)
                lm.frais_reparti = part
                lm.cout = round(float(lm.montant_ht) + part, 2)
                lm.save(update_fields=["frais_reparti", "cout"])

        # Entrées de stock (dépôt central) + agrégats par compte
        goods_par_compte, frais_par_compte = {}, {}
        central = stock_lib.depot_central(cmd.societe_id)
        for lm, lc, art in lignes_rec:
            if art and art.gere_stock:
                stock_lib.entree(art, central, float(lm.qte), float(lm.cout),
                                 "reception", rec.numero, jour=jour)
            goods_par_compte[lm.compte_stock] = round(
                goods_par_compte.get(lm.compte_stock, 0.0) + float(lm.montant_ht), 2)
            if float(lm.frais_reparti or 0):
                frais_par_compte[lm.compte_stock] = round(
                    frais_par_compte.get(lm.compte_stock, 0.0)
                    + float(lm.frais_reparti or 0), 2)

        rec.total_valeur = round(sum(float(lm.cout) for lm, _, _ in lignes_rec), 2)
        rec.total_frais = frais_ht
        ecr = comptabilite.comptabiliser_reception(
            rec, goods_par_compte, frais_par_compte, frais_objs, request.user.id,
            statut=intersociete_lib._statut_piece(cmd.societe_id, "achat"))
        rec.ecriture_id = ecr.id
        rec.save()

        all_recu = all(float(lc.qte_recue) >= float(lc.qte) - 1e-6
                       for lc in LigneCommande.objects.filter(commande_id=cmd.id))
        cmd.statut = "soldee" if all_recu else "receptionnee"
        cmd.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "INSERT", "reception", rec.id, None,
                                   {"numero": rec.numero})
    return Response(_reception_dict(rec), status=201)


@api_view(["GET"])
def lister_receptions(request):
    sid = _societe_param(request)
    _acces(request, sid)
    rs = Reception.objects.filter(societe_id=sid).order_by("-created_at")
    return Response([_reception_dict(r) for r in rs])


@api_view(["GET"])
def detail_reception(request, reception_id):
    r = Reception.objects.filter(id=reception_id).first()
    if not r:
        return refus({"detail": "Réception introuvable."}, status=404)
    _acces(request, r.societe_id)
    return Response(_reception_dict(r))


@api_view(["POST"])
def facturer_reception(request, reception_id):
    """Facture fournisseur d'une réception : D 408 + TVA / C 401."""
    rec = Reception.objects.filter(id=reception_id).first()
    if not rec:
        return refus({"detail": "Réception introuvable."}, status=404)
    _acces(request, rec.societe_id)
    if rec.statut == "facturee":
        return refus({"detail": "Réception déjà facturée."}, status=409)
    payload = request.data or {}
    societe = Societe.objects.filter(id=rec.societe_id).first()
    cmd = Commande.objects.filter(id=rec.commande_id).first()
    rec_lignes = list(LigneReception.objects.filter(reception_id=rec.id))

    total_ht = round(sum(float(l.montant_ht) for l in rec_lignes), 2)
    tva = round(sum(round(float(l.montant_ht) * float(l.taux_tva) / 100, 2)
                    for l in rec_lignes), 2)
    total_ttc = round(total_ht + tva, 2)

    with transaction.atomic():
        date_fac = date.fromisoformat(payload["date_facture"]) \
            if payload.get("date_facture") else rec.date_reception
        numero = services.next_numero("facture_achat", date_fac.year, societe.code,
                                      societe.id)
        fac = Facture.objects.create(
            societe_id=rec.societe_id, type="achat", numero=numero, tiers_id=cmd.tiers_id,
            date_facture=date_fac,
            echeance=date.fromisoformat(payload["echeance"])
            if payload.get("echeance") else None,
            reference=payload.get("reference"), total_ht=total_ht, total_frais=0,
            total_tva=tva, total_ttc=total_ttc, statut="validee",
            intra_groupe=cmd.intra_groupe, reception_id=rec.id,
            created_by=request.user.id, created_at=services.maintenant())
        for l in rec_lignes:
            LigneFacture.objects.create(
                facture_id=fac.id, article_id=l.article_id, designation=l.designation,
                qte=l.qte, prix_unitaire=l.prix_unitaire, taux_tva=l.taux_tva,
                montant_ht=l.montant_ht,
                montant_tva=round(float(l.montant_ht) * float(l.taux_tva) / 100, 2),
                frais_reparti=l.frais_reparti, cout_entree=l.cout)
        ecr = comptabilite.comptabiliser_facture_reception(
            fac, rec, request.user.id,
            statut=intersociete_lib._statut_piece(rec.societe_id, "achat"))
        fac.ecriture_id = ecr.id
        fac.save(update_fields=["ecriture_id"])
        rec.statut = "facturee"
        rec.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id, None,
                                   {"numero": numero, "reception": rec.numero})
    return Response(_facture_dict(fac), status=201)


# ── Listes de prix & points de vente ─────────────────────────────────
@api_view(["GET", "POST"])
def listes_prix(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        code = (payload.get("code") or "").strip().upper()
        if not code or not (payload.get("libelle") or "").strip():
            return refus({"detail": "code et libelle requis."}, status=422)
        if ListePrix.objects.filter(societe_id=sid, code=code).exists():
            return refus({"detail": f"La liste {code} existe déjà."}, status=409)
        lp = ListePrix.objects.create(societe_id=sid, code=code,
                                      libelle=payload["libelle"].strip())
        return Response({"id": str(lp.id), "code": lp.code, "libelle": lp.libelle},
                        status=201)
    out = []
    for l in ListePrix.objects.filter(societe_id=sid).order_by("code"):
        n = TarifArticle.objects.filter(liste_prix_id=l.id).count()
        out.append({"id": str(l.id), "code": l.code, "libelle": l.libelle,
                    "actif": bool(l.actif), "nb_tarifs": int(n)})
    return Response(out)


@api_view(["GET", "POST"])
def tarifs_liste(request, liste_id):
    liste = ListePrix.objects.filter(id=liste_id).first()
    if not liste:
        return refus({"detail": "Liste introuvable."}, status=404)
    _acces(request, liste.societe_id)
    if request.method == "POST":
        payload = request.data or {}
        t = TarifArticle.objects.filter(liste_prix_id=liste_id,
                                        article_id=payload.get("article_id")).first()
        if payload.get("prix") is None:
            if t:
                t.delete()
        elif t:
            t.prix = round(float(payload["prix"]), 2)
            t.save(update_fields=["prix"])
        else:
            TarifArticle.objects.create(societe_id=liste.societe_id,
                                        liste_prix_id=liste_id,
                                        article_id=payload["article_id"],
                                        prix=round(float(payload["prix"]), 2))
        return Response({"ok": True})
    tarifs = {t.article_id: float(t.prix)
              for t in TarifArticle.objects.filter(liste_prix_id=liste_id)}
    arts = Article.objects.filter(societe_id=liste.societe_id, actif=True).order_by("code")
    return Response({"liste": {"id": str(liste.id), "code": liste.code,
                               "libelle": liste.libelle},
                     "articles": [{"article_id": str(a.id), "code": a.code,
                                   "designation": a.designation,
                                   "prix_defaut": float(a.prix_vente),
                                   "prix": tarifs.get(a.id), "defini": a.id in tarifs}
                                  for a in arts]})


def _pv_dict(p: PointVente) -> dict:
    lp = ListePrix.objects.filter(id=p.liste_prix_id).first() if p.liste_prix_id else None
    c = Caisse.objects.filter(id=p.caisse_id).first() if p.caisse_id else None
    dep = Depot.objects.filter(id=p.depot_id).first() if p.depot_id else None
    return {"id": str(p.id), "code": p.code, "libelle": p.libelle, "actif": bool(p.actif),
            "liste_prix_id": str(p.liste_prix_id) if p.liste_prix_id else None,
            "liste_prix": lp.libelle if lp else None,
            "caisse_id": str(p.caisse_id) if p.caisse_id else None,
            "caisse": c.libelle if c else None,
            "depot_id": str(p.depot_id) if p.depot_id else None,
            "depot": dep.libelle if dep else None}


@api_view(["GET", "POST"])
def points_vente(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        code = (payload.get("code") or "").strip().upper()
        if not code or not (payload.get("libelle") or "").strip():
            return refus({"detail": "code et libelle requis."}, status=422)
        if PointVente.objects.filter(societe_id=sid, code=code).exists():
            return refus({"detail": f"Le point de vente {code} existe déjà."},
                            status=409)
        p = PointVente.objects.create(societe_id=sid, code=code,
                                      libelle=payload["libelle"].strip(),
                                      liste_prix_id=payload.get("liste_prix_id") or None,
                                      caisse_id=payload.get("caisse_id") or None,
                                      depot_id=payload.get("depot_id") or None)
        return Response(_pv_dict(p), status=201)
    ps = PointVente.objects.filter(societe_id=sid).order_by("code")
    return Response([_pv_dict(p) for p in ps])


@api_view(["PATCH"])
def maj_point_vente(request, pv_id):
    p = PointVente.objects.filter(id=pv_id).first()
    if not p:
        return refus({"detail": "Point de vente introuvable."}, status=404)
    _acces(request, p.societe_id)
    payload = request.data or {}
    if "libelle" in payload:
        libelle = (payload["libelle"] or "").strip()
        if len(libelle) < 2:
            return refus({"detail": "libelle requis."}, status=422)
        p.libelle = libelle
    if "liste_prix_id" in payload:
        v = payload["liste_prix_id"] or None      # "" = aucune liste (prix défaut)
        if v and not ListePrix.objects.filter(id=v,
                                              societe_id=p.societe_id).exists():
            return refus({"detail": "Liste de prix invalide."}, status=400)
        p.liste_prix_id = v
    if "caisse_id" in payload:
        v = payload["caisse_id"] or None
        if v and not Caisse.objects.filter(id=v,
                                           societe_id=p.societe_id).exists():
            return refus({"detail": "Caisse invalide."}, status=400)
        p.caisse_id = v
    if "depot_id" in payload:
        v = payload["depot_id"] or None    # "" = dépôt central par défaut
        if v and not Depot.objects.filter(id=v,
                                          societe_id=p.societe_id).exists():
            return refus({"detail": "Dépôt invalide."}, status=400)
        p.depot_id = v
    if "actif" in payload and payload["actif"] is not None:
        p.actif = bool(payload["actif"])
    p.save()
    return Response(_pv_dict(p))


@api_view(["GET"])
def prix_article(request, article_id):
    """Prix de vente résolu : tarif de liste (via PV ou direct), sinon défaut."""
    a = Article.objects.filter(id=article_id).first()
    if not a:
        return refus({"detail": "Article introuvable."}, status=404)
    _acces(request, a.societe_id)
    liste_prix_id = request.query_params.get("liste_prix_id")
    point_vente_id = request.query_params.get("point_vente_id")
    if point_vente_id and not liste_prix_id:
        pv = PointVente.objects.filter(id=point_vente_id).first()
        liste_prix_id = pv.liste_prix_id if pv else None
    prix, source = float(a.prix_vente), "défaut"
    if liste_prix_id:
        t = TarifArticle.objects.filter(liste_prix_id=liste_prix_id,
                                        article_id=article_id).first()
        if t:
            prix, source = float(t.prix), "liste"
    return Response({"article_id": str(a.id), "code": a.code, "prix": prix,
                     "source": source})


# ── POS : contexte, vente, tickets, retours, rapport ─────────────────
def _client_comptant(societe_id) -> Tiers:
    t = Tiers.objects.filter(societe_id=societe_id, code="COMPTANT").first()
    if not t:
        t = Tiers.objects.create(societe_id=societe_id, type="client", code="COMPTANT",
                                 nom="Client comptant")
    return t


def _taux_cdf(jour: date) -> float | None:
    t = services.get_taux_jour(jour, "CDF")
    return float(t) if t else None


def _encours_credit_usd(tiers_id) -> float:
    total = 0.0
    for sens, montant in (LigneEcriture.objects
                          .filter(tiers_id=tiers_id, compte_numero__startswith="41")
                          .values_list("sens", "montant_usd")):
        total += float(montant) if sens == "D" else -float(montant)
    return round(total, 2)


@api_view(["GET"])
def pos_contexte(request):
    """Tout pour ouvrir l'écran POS : taux, catégories, état de la caisse du PV."""
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)
    cats = [c for c in Article.objects.filter(societe_id=sid, actif=True,
                                              nature="marchandise",
                                              categorie__isnull=False)
            .values_list("categorie", flat=True).distinct() if c]
    out = {"taux_cdf": _taux_cdf(date.today()), "categories": sorted(cats),
           "date": date.today().isoformat()}
    principale = Caisse.objects.filter(societe_id=sid, est_principale=True,
                                       actif=True).first()
    if principale:
        out["caisse_principale"] = {"id": str(principale.id),
                                    "libelle": principale.libelle}
    point_vente_id = request.query_params.get("point_vente_id")
    if point_vente_id:
        pv = PointVente.objects.filter(id=point_vente_id).first()
        if pv and str(pv.societe_id) == str(sid) and pv.caisse_id:
            caisse = Caisse.objects.filter(id=pv.caisse_id).first()
            sess = _session_ouverte(caisse.id)
            out["caisse"] = {"id": str(caisse.id), "libelle": caisse.libelle,
                             "session_ouverte": sess is not None,
                             "est_principale": bool(caisse.est_principale),
                             "ouverte_depuis": sess.date_ouverture.isoformat()
                             if sess and sess.date_ouverture else None,
                             "fond_usd": float(sess.fond_initial_usd) if sess else None,
                             "fond_cdf": float(sess.fond_initial_cdf) if sess else None,
                             "soldes": _soldes(sess) if sess else None}
    return Response(out)


def _ticket_dict(fac: Facture) -> dict:
    pv = PointVente.objects.filter(id=fac.point_vente_id).first() \
        if fac.point_vente_id else None
    caisse = Caisse.objects.filter(id=pv.caisse_id).first() \
        if pv and pv.caisse_id else None
    tiers = Tiers.objects.filter(id=fac.tiers_id).first()
    vendeur = Utilisateur.objects.filter(id=fac.created_by).first() \
        if fac.created_by else None
    origine = Facture.objects.filter(id=fac.origine_id).first() if fac.origine_id else None
    lignes, points, commission = [], 0.0, 0.0
    for l in LigneFacture.objects.filter(facture_id=fac.id):
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        brut = round(float(l.qte) * float(l.prix_unitaire), 2)
        lignes.append({"id": str(l.id), "code": art.code if art else "",
                       "designation": l.designation, "qte": float(l.qte),
                       "prix": float(l.prix_unitaire),
                       "remise_pct": float(l.remise_pct or 0), "brut": brut,
                       "ht": float(l.montant_ht), "tva": float(l.montant_tva)})
        if art:
            points += float(l.qte) * float(art.points_fidelite)
            commission += float(l.montant_ht) * float(art.taux_commission) / 100
    paiements = [{"mode": p.mode, "devise": p.devise, "montant": float(p.montant),
                  "montant_usd": float(p.montant_usd),
                  "taux": float(p.taux_jour) if p.taux_jour else None,
                  "reference": p.reference}
                 for p in PaiementFacture.objects.filter(facture_id=fac.id)]
    taux = _taux_cdf(fac.date_facture if isinstance(fac.date_facture, date)
                     else date.today())
    ttc = float(fac.total_ttc)
    est_avoir = fac.type == "avoir_vente"
    return {
        "id": str(fac.id), "numero": fac.numero, "type": fac.type, "est_avoir": est_avoir,
        "point_vente": pv.libelle if pv else None,
        "caisse": caisse.libelle if caisse else None,
        "date": fac.date_facture.isoformat(),
        "heure": fac.created_at.isoformat() if fac.created_at else None,
        "client": {"id": str(tiers.id), "code": tiers.code, "nom": tiers.nom,
                   "points_fidelite": float(tiers.points_fidelite or 0)}
        if tiers else None,
        "vendeur": f"{vendeur.prenom or ''} {vendeur.nom}".strip() if vendeur else None,
        "origine_numero": origine.numero if origine else None,
        "note": fac.note, "lignes": lignes,
        "total_ht": float(fac.total_ht), "total_tva": float(fac.total_tva),
        "total_ttc": ttc, "remise_totale": float(fac.remise_totale or 0),
        "marge": float(fac.marge or 0),
        "montant_recu": float(fac.pos_recu_usd) if fac.pos_recu_usd is not None else None,
        "monnaie": float(fac.pos_monnaie_usd)
        if fac.pos_monnaie_usd is not None else None,
        "paiements": paiements,
        "points_fidelite": round(points, 2), "commission": round(commission, 2),
        "taux_cdf": taux, "total_ttc_cdf": round(ttc * taux, 0) if taux else None,
    }


@api_view(["POST"])
def pos_vente(request):
    """Vente POS : prix de liste, remises, sortie stock CUMP, règlement fractionné."""
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)
    payload = request.data or {}
    societe = Societe.objects.filter(id=sid).first()
    pv = PointVente.objects.filter(id=payload.get("point_vente_id")).first()
    if not pv or str(pv.societe_id) != str(sid):
        return refus({"detail": "Point de vente invalide."}, status=400)
    if not pv.caisse_id:
        return refus({"detail": "Le point de vente n'a pas de caisse associée."},
                        status=400)
    caisse = Caisse.objects.filter(id=pv.caisse_id).first()
    sess = _session_ouverte(caisse.id)
    if not sess:
        return refus({"detail": f"Ouvrez la caisse « {caisse.libelle} » avant de "
                                   f"vendre."}, status=409)
    if not payload.get("lignes"):
        return refus({"detail": "Panier vide."}, status=400)

    # ── « Sur la chambre » (module Hôtellerie) : le ticket va sur la note
    # du séjour — la créance est portée par le tiers du séjour, encaissée au
    # check-out. Un seul paiement mode "chambre", couvrant tout le ticket.
    sejour_chambre = None
    modes_chambre = [p for p in (payload.get("paiements") or [])
                     if p.get("mode") == "chambre"]
    if modes_chambre:
        from . import hotel_views
        from .models import Sejour
        if len(modes_chambre) != 1 or len(payload.get("paiements") or []) != 1:
            return refus({"detail": "« Sur la chambre » couvre tout le ticket — "
                                    "pas de paiement mixte."}, status=422)
        sejour_chambre = Sejour.objects.filter(
            id=modes_chambre[0].get("sejour_id")).first()
        if not sejour_chambre or str(sejour_chambre.societe_id) != str(sid):
            return refus({"detail": "Séjour invalide."}, status=400)
        if sejour_chambre.statut != "arrivee":
            return refus({"detail": f"Séjour {sejour_chambre.numero} : "
                                    f"{sejour_chambre.statut} — seul un client "
                                    f"présent peut charger sa chambre."},
                         status=409)
        hotel_views._tiers_du_sejour(sejour_chambre, sid, request.user.id)
        payload = dict(payload)
        payload["client_id"] = str(sejour_chambre.tiers_id)

    tiers = Tiers.objects.filter(id=payload.get("client_id")).first() \
        if payload.get("client_id") else _client_comptant(sid)
    if not tiers or (tiers.societe_id and str(tiers.societe_id) != str(sid)) \
            or tiers.type != "client":
        return refus({"detail": "Client invalide."}, status=400)
    client_reel = tiers.code != "COMPTANT"
    jour = date.today()

    with transaction.atomic():
        numero = services.next_numero("facture_vente", jour.year, societe.code,
                                      societe.id)
        fac = Facture.objects.create(
            societe_id=sid, type="vente", numero=numero, tiers_id=tiers.id,
            date_facture=jour, statut="validee", point_vente_id=pv.id,
            note=(payload.get("note") or "").strip() or None,
            created_by=request.user.id, created_at=services.maintenant())

        gr = float(payload.get("remise_globale_pct", 0))
        total_ht = total_tva = cout_ventes = remise_totale = 0.0
        points = commission = 0.0
        stock_par_compte: dict[str, float] = {}
        lm_list = []
        for l in payload["lignes"]:
            art = Article.objects.filter(id=l.get("article_id")).first()
            if not art or str(art.societe_id) != str(sid):
                return refus({"detail": "Article invalide."}, status=400)
            if (art.nature or "marchandise") != "marchandise":
                return refus({"detail": f"{art.code} est une "
                                        f"{'matière première' if art.nature == 'matiere_premiere' else 'fourniture consommable'}"
                                        f" — pas un article de vente."},
                             status=400)
            prix = l.get("prix")
            if prix is None and pv.liste_prix_id:
                t = TarifArticle.objects.filter(liste_prix_id=pv.liste_prix_id,
                                                article_id=art.id).first()
                prix = float(t.prix) if t else None
            if prix is None:
                prix = float(art.prix_vente)
            remise = round((1 - (1 - float(l.get("remise_pct", 0)) / 100)
                            * (1 - gr / 100)) * 100, 4)
            taux = float(art.taux_tva) if art.assujetti_tva else 0.0
            qte = float(l.get("qte", 0))
            if qte <= 0:
                return refus({"detail": "Quantité invalide."}, status=422)
            brut = round(qte * prix, 2)
            ht = round(brut * (1 - remise / 100), 2)
            tva = round(ht * taux / 100, 2)
            total_ht += ht
            total_tva += tva
            remise_totale += brut - ht
            points += qte * float(art.points_fidelite)
            commission += ht * float(art.taux_commission) / 100
            lm = LigneFacture.objects.create(
                facture_id=fac.id, article_id=art.id, designation=art.designation,
                qte=qte, prix_unitaire=prix, remise_pct=round(remise, 2),
                taux_tva=taux, montant_ht=ht, montant_tva=tva)
            lm_list.append(lm)
            if art.gere_stock:
                # le POS puise dans le dépôt de son point de vente
                depot_pv = stock_lib.depot_du_point_vente(pv, sid)
                dispo = stock_lib.qte_disponible(depot_pv.id, art.id)
                if dispo < qte - 1e-6:
                    return refus({"detail": f"Stock insuffisant pour {art.code} "
                                            f"au dépôt « {depot_pv.libelle} » : "
                                            f"{dispo} en stock, {qte} demandé. "
                                            f"Faites un transfert depuis le "
                                            f"dépôt central."}, status=409)
                val = stock_lib.sortie(art, depot_pv, qte, "vente", numero,
                                       jour=jour)
                cout_ventes += val
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + val, 2)

        t_ht = round(total_ht, 2)
        t_tva = round(total_tva, 2)
        t_ttc = round(t_ht + t_tva, 2)
        fac.total_ht, fac.total_tva, fac.total_ttc = t_ht, t_tva, t_ttc
        fac.remise_totale = round(remise_totale, 2)
        fac.cout_ventes, fac.marge = round(cout_ventes, 2), round(t_ht - cout_ventes, 2)

        # ── Règlement : normalisation des paiements ──────────────────
        taux_cdf = _taux_cdf(jour)
        paiements = payload.get("paiements") or []
        if not paiements:      # mode hérité : tout en espèces USD
            recu = payload.get("montant_recu")
            paiements = [{"mode": "espece", "devise": "USD",
                          "montant": max(recu if recu is not None else t_ttc, t_ttc)}]
        norm = []
        for p in paiements:
            mode = p.get("mode")
            devise = p.get("devise", "USD")
            montant = float(p.get("montant", 0))
            if mode not in ("espece", "mobile_money", "banque", "credit",
                            "chambre") \
                    or devise not in ("USD", "CDF") or montant <= 0:
                return refus({"detail": "Paiement invalide."}, status=422)
            if devise == "CDF":
                if not taux_cdf:
                    return refus({"detail": "Aucun taux USD/CDF défini aujourd'hui — "
                                               "définissez le taux du jour avant "
                                               "d'encaisser en CDF."}, status=409)
                usd = round(montant / taux_cdf, 2)
            else:
                usd = round(montant, 2)
            norm.append({"mode": mode, "devise": devise, "montant": round(montant, 2),
                         "taux": taux_cdf if devise == "CDF" else None,
                         "usd": usd, "reference": (p.get("reference") or "").strip()
                         or None})

        cash_usd = round(sum(p["usd"] for p in norm if p["mode"] == "espece"), 2)
        noncash_usd = round(sum(p["usd"] for p in norm if p["mode"] != "espece"), 2)
        credit_usd = round(sum(p["usd"] for p in norm if p["mode"] == "credit"), 2)
        if credit_usd > 0:
            if not client_reel:
                return refus({"detail": "Vente à crédit : sélectionnez un client "
                                           "enregistré (pas le client comptant)."},
                                status=400)
            if tiers.limite_credit_usd is not None:
                encours = _encours_credit_usd(tiers.id)
                if encours + credit_usd > float(tiers.limite_credit_usd) + 0.01:
                    return refus(
                        {"detail": f"Plafond de crédit dépassé pour {tiers.nom} : "
                                   f"encours {encours:.2f} USD + {credit_usd:.2f} USD "
                                   f"> limite {float(tiers.limite_credit_usd):.2f} USD."},
                        status=409)
        if noncash_usd > t_ttc + 0.01:
            return refus({"detail": "La monnaie ne peut être rendue que sur les "
                                       "espèces — réduisez le paiement mobile money / "
                                       "banque / crédit au montant exact."}, status=400)
        du_cash = round(t_ttc - noncash_usd, 2)
        if cash_usd + 0.01 < du_cash:
            return refus({"detail": f"Paiement insuffisant : "
                                       f"{round(cash_usd + noncash_usd, 2):.2f} USD "
                                       f"reçus pour un total de {t_ttc:.2f} USD."},
                            status=400)
        monnaie_usd = round(cash_usd - du_cash, 2)
        fac.pos_recu_usd, fac.pos_monnaie_usd = cash_usd, monnaie_usd
        fac.save()

        # ── Écriture de vente ────────────────────────────────────────
        compte_par_mode = {
            "espece": caisse.compte_comptable,
            "mobile_money": comptabilite._compte("compte_mobile_money", sid),
            "banque": comptabilite._compte("compte_banque", sid),
            "credit": comptabilite._compte("compte_client", sid),
            "chambre": comptabilite._compte("compte_client", sid),
        }
        encaissements = []
        if du_cash > 0:
            encaissements.append({"compte": compte_par_mode["espece"],
                                  "montant_usd": du_cash,
                                  "libelle": f"Espèces POS {numero}"})
        mm_usd = round(sum(p["usd"] for p in norm if p["mode"] == "mobile_money"), 2)
        bq_usd = round(sum(p["usd"] for p in norm if p["mode"] == "banque"), 2)
        if mm_usd:
            encaissements.append({"compte": compte_par_mode["mobile_money"],
                                  "montant_usd": mm_usd,
                                  "libelle": f"Mobile money POS {numero}"})
        if bq_usd:
            encaissements.append({"compte": compte_par_mode["banque"],
                                  "montant_usd": bq_usd,
                                  "libelle": f"Banque POS {numero}"})
        if credit_usd:
            encaissements.append({"compte": compte_par_mode["credit"],
                                  "montant_usd": credit_usd, "tiers_id": tiers.id,
                                  "libelle": f"Vente à crédit POS {numero} — "
                                             f"{tiers.nom}"})
        chambre_usd = round(sum(p["usd"] for p in norm
                                if p["mode"] == "chambre"), 2)
        if chambre_usd:
            encaissements.append({"compte": compte_par_mode["chambre"],
                                  "montant_usd": chambre_usd,
                                  "tiers_id": tiers.id,
                                  "libelle": f"Sur chambre POS {numero} — "
                                             f"{sejour_chambre.numero} "
                                             f"({tiers.nom})"})
            from .models import LigneSejour
            origine_pos = "bar" if "bar" in (pv.libelle or "").lower() \
                else "restaurant"
            LigneSejour.objects.create(
                sejour_id=sejour_chambre.id, date_ligne=jour,
                designation=f"Ticket {numero} — {pv.libelle}",
                qte=1, prix_unitaire=t_ttc, montant_usd=t_ttc,
                origine=origine_pos, facture_pos_id=fac.id,
                created_by=request.user.id, created_at=services.maintenant())
        statut_piece = intersociete_lib._statut_piece(sid, "vente")
        ecr = comptabilite.comptabiliser_vente_pos(fac, lm_list, encaissements,
                                                   request.user.id,
                                                   statut=statut_piece)
        fac.ecriture_id = ecr.id
        fac.save(update_fields=["ecriture_id"])
        for compte_stock, val in stock_par_compte.items():
            if val > 0:
                comptabilite.comptabiliser_variation_stock(fac, compte_stock, val,
                                                           entree=False,
                                                           created_by=request.user.id,
                                                           statut=statut_piece)

        # ── Espèces : entrées en caisse + monnaie rendue ─────────────
        for p in norm:
            # « chambre » = créance client encaissée au check-out : stockée en
            # mode credit (contrainte CHECK de la table), référence = séjour.
            PaiementFacture.objects.create(
                facture_id=fac.id,
                mode="credit" if p["mode"] == "chambre" else p["mode"],
                devise=p["devise"],
                montant=p["montant"], taux_jour=p["taux"], montant_usd=p["usd"],
                reference=p["reference"] or (sejour_chambre.numero
                                             if p["mode"] == "chambre" else None),
                compte=compte_par_mode[p["mode"]])
            if p["mode"] == "espece":
                MouvementCaisse.objects.create(
                    caisse_id=caisse.id, session_id=sess.id,
                    numero=services.next_numero("bon_caisse", jour.year, societe.code,
                                                societe.id),
                    reference=numero, sens="entree", nature="Vente POS",
                    devise=p["devise"], taux_jour=p["taux"], montant=p["montant"],
                    montant_usd=p["usd"],
                    tiers_id=tiers.id if client_reel else None,
                    tiers_nom=tiers.nom if client_reel else None,
                    reference_type="facture", reference_id=fac.id,
                    libelle=f"Vente POS {numero} — {pv.libelle}",
                    created_by=request.user.id,
                    date_mouvement=services.maintenant().date(),
                    heure=services.maintenant())
        if monnaie_usd > 0:
            rendu_usd = any(p["mode"] == "espece" and p["devise"] == "USD" for p in norm)
            MouvementCaisse.objects.create(
                caisse_id=caisse.id, session_id=sess.id,
                numero=services.next_numero("bon_caisse", jour.year, societe.code,
                                            societe.id),
                reference=numero, sens="sortie", nature="Monnaie rendue POS",
                devise="USD" if rendu_usd else "CDF",
                taux_jour=None if rendu_usd else taux_cdf,
                montant=monnaie_usd if rendu_usd else round(monnaie_usd * taux_cdf, 0),
                montant_usd=monnaie_usd, reference_type="facture", reference_id=fac.id,
                libelle=f"Monnaie rendue — vente {numero}", created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())

        # ── Fidélité ─────────────────────────────────────────────────
        if client_reel and points:
            tiers.points_fidelite = round(float(tiers.points_fidelite or 0) + points, 2)
            tiers.save(update_fields=["points_fidelite"])

        services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id, None,
                                   {"numero": numero, "pos": pv.code, "ttc": t_ttc,
                                    "remise": float(fac.remise_totale),
                                    "credit": credit_usd})
    return Response(_ticket_dict(fac), status=201)


@api_view(["GET"])
def pos_tickets(request):
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)
    jour = date.fromisoformat(request.query_params["jour"]) \
        if request.query_params.get("jour") else date.today()
    q = Facture.objects.filter(societe_id=sid, point_vente_id__isnull=False,
                               type__in=["vente", "avoir_vente"], date_facture=jour)
    point_vente_id = request.query_params.get("point_vente_id")
    if point_vente_id:
        q = q.filter(point_vente_id=point_vente_id)
    facs = list(q.order_by("-created_at"))
    avoirs_par_origine: dict = {}
    for f in facs:
        if f.type == "avoir_vente" and f.origine_id:
            avoirs_par_origine.setdefault(f.origine_id, []).append(f.numero)
    out = []
    for f in facs:
        t = Tiers.objects.filter(id=f.tiers_id).first()
        v = Utilisateur.objects.filter(id=f.created_by).first() if f.created_by else None
        modes = sorted({p.mode for p in PaiementFacture.objects.filter(facture_id=f.id)})
        out.append({"id": str(f.id), "numero": f.numero, "type": f.type,
                    "heure": f.created_at.isoformat() if f.created_at else None,
                    "client": t.nom if t else None,
                    "vendeur": (v.prenom or v.nom) if v else None,
                    "total_ttc": float(f.total_ttc),
                    "remise": float(f.remise_totale or 0),
                    "modes": modes, "avoirs": avoirs_par_origine.get(f.id, [])})
    return Response(out)


@api_view(["GET"])
def pos_ticket(request, facture_id):
    f = Facture.objects.filter(id=facture_id).first()
    if not f or f.type not in ("vente", "avoir_vente") or not f.point_vente_id:
        return refus({"detail": "Ticket introuvable."}, status=404)
    _acces(request, f.societe_id, ROLES_POS)
    tk = _ticket_dict(f)
    if f.type == "vente":
        deja = {}
        avoirs_ids = Facture.objects.filter(origine_id=f.id,
                                            type="avoir_vente").values("id")
        for lr in LigneFacture.objects.filter(facture_id__in=avoirs_ids):
            if lr.origine_ligne_id:
                deja[str(lr.origine_ligne_id)] = \
                    deja.get(str(lr.origine_ligne_id), 0.0) + float(lr.qte)
        for l in tk["lignes"]:
            l["deja_retourne"] = round(deja.get(l["id"], 0.0), 3)
    return Response(tk)


@api_view(["POST"])
def pos_retour(request):
    """Retour client : ré-entrée en stock au coût d'origine, avoir AVV, écriture
    inverse, remboursement espèces ou crédit client."""
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)
    payload = request.data or {}
    societe = Societe.objects.filter(id=sid).first()
    fac = Facture.objects.filter(id=payload.get("facture_id")).first()
    if not fac or str(fac.societe_id) != str(sid) or fac.type != "vente" \
            or not fac.point_vente_id:
        return refus({"detail": "Ticket d'origine invalide."}, status=400)
    if not payload.get("lignes"):
        return refus({"detail": "Aucune ligne à retourner."}, status=400)
    mode = payload.get("mode", "espece")
    if mode not in ("espece", "credit"):
        return refus({"detail": "mode invalide (espece|credit)."}, status=422)
    pv = PointVente.objects.filter(id=fac.point_vente_id).first()
    caisse = Caisse.objects.filter(id=pv.caisse_id).first()
    tiers = Tiers.objects.filter(id=fac.tiers_id).first()
    client_reel = tiers and tiers.code != "COMPTANT"
    sess = None
    if mode == "espece":
        sess = _session_ouverte(caisse.id)
        if not sess:
            return refus({"detail": f"Ouvrez la caisse « {caisse.libelle} » pour "
                                       f"rembourser en espèces."}, status=409)
    elif not client_reel:
        return refus({"detail": "Avoir sur compte client impossible : la vente était "
                                   "au comptant anonyme."}, status=400)

    # quantités déjà retournées (tous avoirs confondus)
    deja: dict[str, float] = {}
    avoirs_ids = Facture.objects.filter(origine_id=fac.id, type="avoir_vente").values("id")
    for lr in LigneFacture.objects.filter(facture_id__in=avoirs_ids):
        if lr.origine_ligne_id:
            k = str(lr.origine_ligne_id)
            deja[k] = deja.get(k, 0.0) + float(lr.qte)

    jour = date.today()
    with transaction.atomic():
        numero = services.next_numero("avoir_vente", jour.year, societe.code, societe.id)
        avoir = Facture.objects.create(
            societe_id=sid, type="avoir_vente", numero=numero, tiers_id=fac.tiers_id,
            date_facture=jour, statut="validee", point_vente_id=fac.point_vente_id,
            origine_id=fac.id, note=(payload.get("motif") or "").strip() or None,
            created_by=request.user.id, created_at=services.maintenant())

        lignes_par_id = {str(l.id): l
                         for l in LigneFacture.objects.filter(facture_id=fac.id)}
        total_ht = total_tva = valeur_stock = points_repris = 0.0
        stock_par_compte: dict[str, float] = {}
        la_list = []
        for rl in payload["lignes"]:
            orig = lignes_par_id.get(str(rl.get("ligne_id")))
            if not orig:
                return refus({"detail": "Ligne étrangère au ticket d'origine."},
                                status=400)
            qte_r = float(rl.get("qte", 0))
            if qte_r <= 0:
                return refus({"detail": "Quantité de retour invalide."}, status=422)
            restant = float(orig.qte) - deja.get(str(orig.id), 0.0)
            if qte_r > restant + 1e-6:
                return refus({"detail": f"Retour impossible : {qte_r} demandé, "
                                           f"{restant} restant sur "
                                           f"« {orig.designation} »."}, status=409)
            ht = round(float(orig.montant_ht) * qte_r / float(orig.qte), 2)
            tva = round(float(orig.montant_tva) * qte_r / float(orig.qte), 2)
            total_ht += ht
            total_tva += tva
            la = LigneFacture.objects.create(
                facture_id=avoir.id, article_id=orig.article_id,
                designation=orig.designation, qte=qte_r,
                prix_unitaire=float(orig.prix_unitaire),
                remise_pct=float(orig.remise_pct or 0),
                taux_tva=float(orig.taux_tva), montant_ht=ht, montant_tva=tva,
                origine_ligne_id=orig.id)
            la_list.append(la)
            art = Article.objects.filter(id=orig.article_id).first() \
                if orig.article_id else None
            if art and art.gere_stock:
                mvt = MouvementStock.objects.filter(reference=fac.numero,
                                                    article_id=art.id,
                                                    sens="sortie").first()
                cout = float(mvt.cout_unitaire) if mvt else \
                    (float(art.stock_valeur) / float(art.stock_qte)
                     if art.stock_qte else 0.0)
                val = round(qte_r * cout, 2)
                # le retour rentre dans le dépôt d'où la vente est sortie
                depot_retour = None
                if mvt and mvt.depot_id:
                    depot_retour = Depot.objects.filter(id=mvt.depot_id).first()
                if not depot_retour:
                    depot_retour = stock_lib.depot_central(sid)
                stock_lib.entree(art, depot_retour, qte_r, val, "retour_vente",
                                 numero, jour=jour)
                valeur_stock += val
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            if art and client_reel:
                points_repris += qte_r * float(art.points_fidelite)

        t_ht, t_tva = round(total_ht, 2), round(total_tva, 2)
        t_ttc = round(t_ht + t_tva, 2)
        avoir.total_ht, avoir.total_tva, avoir.total_ttc = t_ht, t_tva, t_ttc
        avoir.cout_ventes = round(valeur_stock, 2)
        avoir.marge = round(t_ht - valeur_stock, 2)
        avoir.save()

        compte_remb = caisse.compte_comptable if mode == "espece" \
            else comptabilite._compte("compte_client", sid)
        remboursements = [{"compte": compte_remb, "montant_usd": t_ttc,
                           "tiers_id": tiers.id if mode == "credit" else None,
                           "libelle": f"Remboursement {numero}" if mode == "espece"
                           else f"Avoir {numero} — {tiers.nom}"}]
        statut_piece = intersociete_lib._statut_piece(avoir.societe_id, "vente")
        ecr = comptabilite.comptabiliser_retour_pos(avoir, la_list, remboursements,
                                                    request.user.id,
                                                    statut=statut_piece)
        avoir.ecriture_id = ecr.id
        avoir.save(update_fields=["ecriture_id"])
        for compte_stock, val in stock_par_compte.items():
            if val > 0:
                comptabilite.comptabiliser_variation_stock(avoir, compte_stock, val,
                                                           entree=True,
                                                           created_by=request.user.id,
                                                           statut=statut_piece)

        PaiementFacture.objects.create(
            facture_id=avoir.id, mode="espece" if mode == "espece" else "credit",
            devise="USD", montant=t_ttc, montant_usd=t_ttc, compte=compte_remb)
        if mode == "espece":
            MouvementCaisse.objects.create(
                caisse_id=caisse.id, session_id=sess.id,
                numero=services.next_numero("bon_caisse", jour.year, societe.code,
                                            societe.id),
                reference=numero, sens="sortie", nature="Retour POS", devise="USD",
                montant=t_ttc, montant_usd=t_ttc,
                tiers_id=tiers.id if client_reel else None,
                tiers_nom=tiers.nom if client_reel else None,
                reference_type="facture", reference_id=avoir.id,
                libelle=f"Remboursement retour {numero} (ticket {fac.numero})",
                created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())

        if client_reel and points_repris:
            tiers.points_fidelite = round(float(tiers.points_fidelite or 0)
                                          - points_repris, 2)
            tiers.save(update_fields=["points_fidelite"])

        services.enregistrer_audit(request.user.id, "INSERT", "facture", avoir.id, None,
                                   {"numero": numero, "origine": fac.numero,
                                    "ttc": t_ttc, "mode": mode})
    return Response(_ticket_dict(avoir), status=201)


@api_view(["GET"])
def pos_rapport(request):
    """Rapport X : synthèse de la journée d'un point de vente."""
    sid = _societe_param(request)
    _acces(request, sid, ROLES_POS)
    point_vente_id = request.query_params.get("point_vente_id")
    if not point_vente_id:
        return refus({"detail": "point_vente_id requis"}, status=422)
    jour = date.fromisoformat(request.query_params["jour"]) \
        if request.query_params.get("jour") else date.today()
    facs = list(Facture.objects.filter(societe_id=sid, point_vente_id=point_vente_id,
                                       type__in=["vente", "avoir_vente"],
                                       date_facture=jour))
    ventes = [f for f in facs if f.type == "vente"]
    avoirs = [f for f in facs if f.type == "avoir_vente"]

    ca_ht = round(sum(float(f.total_ht) for f in ventes), 2)
    tva = round(sum(float(f.total_tva) for f in ventes), 2)
    ttc = round(sum(float(f.total_ttc) for f in ventes), 2)
    remises = round(sum(float(f.remise_totale or 0) for f in ventes), 2)
    marge = round(sum(float(f.marge or 0) for f in ventes)
                  - sum(float(a.marge or 0) for a in avoirs), 2)
    retours_ttc = round(sum(float(a.total_ttc) for a in avoirs), 2)
    monnaie = round(sum(float(f.pos_monnaie_usd or 0) for f in ventes), 2)

    par_mode: dict[str, dict] = {}
    for f in facs:
        signe = 1 if f.type == "vente" else -1
        for p in PaiementFacture.objects.filter(facture_id=f.id):
            m = par_mode.setdefault(p.mode, {"usd": 0.0, "cdf": 0.0, "nb": 0})
            m["nb"] += 1
            if p.devise == "CDF":
                m["cdf"] = round(m["cdf"] + signe * float(p.montant), 0)
            m["usd"] = round(m["usd"] + signe * float(p.montant_usd), 2)
    if monnaie and "espece" in par_mode:
        par_mode["espece"]["usd"] = round(par_mode["espece"]["usd"] - monnaie, 2)

    par_article: dict = {}
    par_categorie: dict[str, float] = {}
    for f in facs:
        signe = 1 if f.type == "vente" else -1
        for l in LigneFacture.objects.filter(facture_id=f.id):
            art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
            key = art.code if art else l.designation
            a = par_article.setdefault(key, {"code": key, "designation": l.designation,
                                             "qte": 0.0, "ht": 0.0})
            a["qte"] = round(a["qte"] + signe * float(l.qte), 3)
            a["ht"] = round(a["ht"] + signe * float(l.montant_ht), 2)
            cat = (art.categorie if art else None) or "Sans catégorie"
            par_categorie[cat] = round(par_categorie.get(cat, 0.0)
                                       + signe * float(l.montant_ht), 2)

    par_vendeur: dict = {}
    for f in ventes:
        v = Utilisateur.objects.filter(id=f.created_by).first() if f.created_by else None
        nom = f"{v.prenom or ''} {v.nom}".strip() if v else "—"
        s = par_vendeur.setdefault(nom, {"vendeur": nom, "nb": 0, "ttc": 0.0})
        s["nb"] += 1
        s["ttc"] = round(s["ttc"] + float(f.total_ttc), 2)

    taux = _taux_cdf(jour)
    net = round(ttc - retours_ttc, 2)
    return Response({
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
    })
