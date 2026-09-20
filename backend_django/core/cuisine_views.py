"""Cuisine — centre de production & food cost (modèle validé avec le DFI).

1. Chaque plat vendu au POS a une FICHE TECHNIQUE (ingrédients/portion).
2. Chaque soir, en un clic : ventes de plats du jour × fiches → bon de
   consommation THÉORIQUE qui sort les ingrédients du dépôt cuisine au
   CUMP (D 603 / C 3x, pièce en attente selon la règle groupe).
3. L'inventaire périodique du dépôt (depots_views) mesure l'écart réel
   vs théorique = le coulage, valorisé.
4. Ratio food cost = coût consommé / CA plats, seuil d'alerte
   paramétrable (cuisine.seuil_food_cost_pct, défaut 35 %).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import comptabilite, intersociete_lib, services, stock_lib
from .auth import assert_acces_societe, assert_role
from .erreurs import refus
from .models import (Article, ConsommationCuisine, Depot, Facture, InventaireDepot, LigneInventaireDepot,
                     FicheTechnique, LigneConsommationCuisine, LigneFacture,
                     LigneFicheTechnique, Parametre, Societe)
from .views import _societe_param

ROLES = {"COMPTABLE", "DFI", "DG", "PRESIDENT", "ADMIN_SYS",
         "CAISSIER_CENTRAL", "RECEPTIONNISTE"}
ROLES_CONFIG = {"DFI", "PRESIDENT", "ADMIN_SYS", "DG"}


def _acces(request, societe_id, roles_requis=ROLES):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, roles_requis)
    return roles


def _upsert_parametre(sid, cle, valeur, type_valeur, description):
    p = Parametre.objects.filter(cle=cle, societe_id=sid).first()
    if p:
        p.valeur = str(valeur)
        p.save(update_fields=["valeur"])
    else:
        Parametre.objects.create(societe_id=sid, cle=cle, valeur=str(valeur),
                                 type_valeur=type_valeur,
                                 description=description)


def _depot_cuisine(sid) -> Depot:
    depot_id = services.get_parametre("cuisine.depot_id", sid)
    if depot_id:
        d = Depot.objects.filter(id=depot_id, societe_id=sid, actif=True).first()
        if d:
            return d
    return stock_lib.depot_central(sid)


def _seuil(sid) -> float:
    return float(services.get_parametre("cuisine.seuil_food_cost_pct", sid, "35"))


@api_view(["GET", "POST"])
def config_cuisine(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    if request.method == "POST":
        assert_role(roles, ROLES_CONFIG)
        payload = request.data or {}
        if "depot_id" in payload:
            v = payload["depot_id"] or ""
            if v and not Depot.objects.filter(id=v, societe_id=sid,
                                              actif=True).exists():
                return refus({"detail": "Dépôt invalide."}, status=400)
            _upsert_parametre(sid, "cuisine.depot_id", v, "string",
                              "Dépôt d'où la cuisine consomme (vide = central)")
        if "seuil_food_cost_pct" in payload:
            try:
                s = float(payload["seuil_food_cost_pct"])
                if not (1 <= s <= 100):
                    raise ValueError
            except (TypeError, ValueError):
                return refus({"detail": "seuil_food_cost_pct entre 1 et 100."},
                             status=422)
            _upsert_parametre(sid, "cuisine.seuil_food_cost_pct", s, "number",
                              "Seuil d'alerte du ratio food cost (%)")
        services.enregistrer_audit(request.user.id, "CONFIG", "cuisine",
                                   None, None, dict(payload))
    assert_role(roles, ROLES)
    depot = _depot_cuisine(sid)
    return Response({"depot_id": str(depot.id), "depot": depot.libelle,
                     "depot_est_central": depot.type == "central",
                     "seuil_food_cost_pct": _seuil(sid)})


# ═══ Fiches techniques ═══════════════════════════════════════════════

def _cout_fiche(fiche: FicheTechnique, depot: Depot) -> tuple[float, list]:
    """Coût de revient d'une portion au CUMP du dépôt cuisine + détail."""
    lignes = []
    cout = 0.0
    portions = float(fiche.portions or 1) or 1.0
    for ln in LigneFicheTechnique.objects.filter(fiche_id=fiche.id):
        art = Article.objects.filter(id=ln.ingredient_article_id).first()
        if not art:
            continue
        cump = stock_lib.cump_depot(depot.id, art)
        qte_portion = float(ln.qte) / portions
        cout_ligne = round(qte_portion * cump, 4)
        cout += cout_ligne
        lignes.append({"id": str(ln.id), "article_id": str(art.id),
                       "code": art.code, "designation": art.designation,
                       "unite": art.unite, "qte": float(ln.qte),
                       "qte_par_portion": round(qte_portion, 4),
                       "cump": round(cump, 4),
                       "cout_par_portion": cout_ligne})
    return round(cout, 2), lignes


def _fiche_dict(f: FicheTechnique, depot: Depot) -> dict:
    art = Article.objects.filter(id=f.article_id).first()
    cout, lignes = _cout_fiche(f, depot)
    prix = float(art.prix_vente) if art else 0.0
    return {"id": str(f.id), "article_id": str(f.article_id),
            "plat": art.designation if art else "(article supprimé)",
            "code": art.code if art else "?",
            "prix_vente": prix, "portions": float(f.portions or 1),
            "cout_portion": cout,
            "food_cost_pct": round(cout / prix * 100, 1) if prix else None,
            "marge_portion": round(prix - cout, 2),
            "note": f.note, "actif": bool(f.actif), "lignes": lignes}


@api_view(["GET", "POST"])
def fiches(request):
    sid = _societe_param(request)
    _acces(request, sid)
    depot = _depot_cuisine(sid)
    if request.method == "POST":
        payload = request.data or {}
        art = Article.objects.filter(id=payload.get("article_id")).first()
        if not art or str(art.societe_id) != str(sid):
            return refus({"detail": "Article (plat) invalide."}, status=400)
        lignes = payload.get("lignes") or []
        if not lignes:
            return refus({"detail": "Ajoutez au moins un ingrédient."},
                         status=422)
        try:
            portions = float(payload.get("portions", 1))
            if portions <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return refus({"detail": "portions > 0 requis."}, status=422)
        existante = FicheTechnique.objects.filter(societe_id=sid,
                                                  article_id=art.id).first()
        with transaction.atomic():
            if existante:
                f = existante
                f.portions = portions
                f.note = (payload.get("note") or "").strip() or None
                f.actif = True
                f.save()
                LigneFicheTechnique.objects.filter(fiche_id=f.id).delete()
            else:
                f = FicheTechnique.objects.create(
                    societe_id=sid, article_id=art.id, portions=portions,
                    note=(payload.get("note") or "").strip() or None,
                    created_by=request.user.id,
                    created_at=services.maintenant())
            for ln in lignes:
                ing = Article.objects.filter(id=ln.get("article_id")).first()
                if not ing or str(ing.societe_id) != str(sid) \
                        or not ing.gere_stock:
                    return refus({"detail": "Ingrédient invalide (article géré "
                                            "en stock requis)."}, status=400)
                if str(ing.id) == str(art.id):
                    return refus({"detail": "Un plat ne peut pas être son "
                                            "propre ingrédient."}, status=422)
                try:
                    q = float(ln.get("qte"))
                    if q <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return refus({"detail": f"Quantité invalide pour "
                                            f"{ing.code}."}, status=422)
                LigneFicheTechnique.objects.create(
                    fiche_id=f.id, ingredient_article_id=ing.id, qte=q)
            services.enregistrer_audit(request.user.id, "UPSERT",
                                       "fiche_technique", f.id, None,
                                       {"plat": art.designation,
                                        "ingredients": len(lignes)})
        return Response(_fiche_dict(f, depot), status=201)
    out = [_fiche_dict(f, depot)
           for f in FicheTechnique.objects.filter(societe_id=sid, actif=True)]
    out.sort(key=lambda x: x["plat"])
    return Response(out)


@api_view(["DELETE"])
def supprimer_fiche(request, fiche_id):
    f = FicheTechnique.objects.filter(id=fiche_id).first()
    if not f:
        return refus({"detail": "Fiche introuvable."}, status=404)
    _acces(request, f.societe_id)
    with transaction.atomic():
        f.actif = False
        f.save(update_fields=["actif"])
        services.enregistrer_audit(request.user.id, "DELETE", "fiche_technique",
                                   f.id, None, None)
    return Response({"ok": True})


# ═══ Consommation théorique journalière ══════════════════════════════

def _ventes_plats_du_jour(sid, jour, fiches_par_article) -> tuple[dict, float]:
    """{article_id_plat: qte vendue} et CA HT des plats (ventes - avoirs)."""
    qtes: dict = {}
    ca = 0.0
    factures = Facture.objects.filter(societe_id=sid, date_facture=jour,
                                      type__in=["vente", "avoir_vente"]) \
        .exclude(statut="annulee")
    for fac in factures:
        signe = -1.0 if fac.type == "avoir_vente" else 1.0
        for lf in LigneFacture.objects.filter(facture_id=fac.id):
            if not lf.article_id or str(lf.article_id) not in fiches_par_article:
                continue
            qtes[str(lf.article_id)] = round(
                qtes.get(str(lf.article_id), 0.0) + signe * float(lf.qte), 3)
            ca = round(ca + signe * float(lf.montant_ht), 2)
    return qtes, ca


def _conso_dict(c: ConsommationCuisine, seuil: float) -> dict:
    depot = Depot.objects.filter(id=c.depot_id).first()
    lignes = list(LigneConsommationCuisine.objects.filter(consommation_id=c.id))
    arts = {str(a.id): a for a in Article.objects.filter(
        id__in=[ln.article_id for ln in lignes])}
    ratio = round(float(c.cout_total) / float(c.ca_total) * 100, 1) \
        if float(c.ca_total) else None
    return {"id": str(c.id), "numero": c.numero,
            "date": c.date_conso.isoformat(),
            "depot": depot.libelle if depot else "?",
            "cout_total": float(c.cout_total), "ca_total": float(c.ca_total),
            "nb_plats": float(c.nb_plats),
            "food_cost_pct": ratio,
            "alerte": bool(ratio is not None and ratio > seuil),
            "lignes": [{"code": arts[str(ln.article_id)].code
                        if str(ln.article_id) in arts else "?",
                        "designation": arts[str(ln.article_id)].designation
                        if str(ln.article_id) in arts else "(supprimé)",
                        "qte": float(ln.qte), "valeur": float(ln.valeur)}
                       for ln in lignes]}


@api_view(["GET", "POST"])
def consommations(request):
    sid = _societe_param(request)
    _acces(request, sid)
    seuil = _seuil(sid)
    if request.method == "POST":
        payload = request.data or {}
        try:
            jour = date.fromisoformat(payload.get("date")) \
                if payload.get("date") else date.today()
        except ValueError:
            return refus({"detail": "date invalide."}, status=422)
        if jour > date.today():
            return refus({"detail": "Impossible de consommer le futur."},
                         status=422)
        if ConsommationCuisine.objects.filter(societe_id=sid,
                                              date_conso=jour).exists():
            return refus({"detail": f"La consommation du {jour} est déjà "
                                    f"générée."}, status=409)
        fiches_actives = list(FicheTechnique.objects.filter(societe_id=sid,
                                                            actif=True))
        if not fiches_actives:
            return refus({"detail": "Aucune fiche technique — créez d'abord "
                                    "les recettes de vos plats."}, status=400)
        fiches_par_article = {str(f.article_id): f for f in fiches_actives}
        qtes_plats, ca = _ventes_plats_du_jour(sid, jour, fiches_par_article)
        if not qtes_plats:
            return refus({"detail": f"Aucune vente de plat le {jour} — rien à "
                                    f"consommer."}, status=400)
        # explosion des recettes → besoins agrégés par ingrédient
        besoins: dict = {}
        nb_plats = 0.0
        for art_id, qte_vendue in qtes_plats.items():
            if qte_vendue <= 0:
                continue
            nb_plats += qte_vendue
            fiche = fiches_par_article[art_id]
            portions = float(fiche.portions or 1) or 1.0
            for ln in LigneFicheTechnique.objects.filter(fiche_id=fiche.id):
                cle = str(ln.ingredient_article_id)
                besoins[cle] = round(besoins.get(cle, 0.0)
                                     + float(ln.qte) / portions * qte_vendue, 4)
        depot = _depot_cuisine(sid)
        societe = Societe.objects.filter(id=sid).first()
        alertes = []
        with transaction.atomic():
            numero = services.next_numero("consommation_cuisine", jour.year,
                                          societe.code, societe.id)
            c = ConsommationCuisine.objects.create(
                societe_id=sid, numero=numero, depot_id=depot.id,
                date_conso=jour, ca_total=ca, nb_plats=round(nb_plats, 2),
                created_by=request.user.id, created_at=services.maintenant())
            cout_total = 0.0
            stock_par_compte: dict = {}
            for art_id, qte in besoins.items():
                if qte <= 0:
                    continue
                art = Article.objects.filter(id=art_id).first()
                if not art or not art.gere_stock:
                    continue
                dispo = stock_lib.qte_disponible(depot.id, art.id)
                if dispo < qte - 1e-6:
                    alertes.append(f"{art.code} : {qte} consommé pour {dispo} "
                                   f"en stock au dépôt « {depot.libelle} » "
                                   f"(solde négatif — à régulariser à "
                                   f"l'inventaire)")
                valeur = stock_lib.sortie(art, depot, qte, "consommation",
                                          numero, jour=jour)
                cout_total = round(cout_total + valeur, 2)
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + valeur, 2)
                LigneConsommationCuisine.objects.create(
                    consommation_id=c.id, article_id=art.id, qte=qte,
                    valeur=valeur)
            c.cout_total = cout_total
            if stock_par_compte:
                ecr = comptabilite.comptabiliser_stock_sortie(
                    sid, stock_par_compte, numero, jour,
                    "consommation_cuisine", c.id, request.user.id,
                    statut=intersociete_lib._statut_piece(sid, "achat"))
                c.ecriture_id = ecr.id
            c.save()
            services.enregistrer_audit(request.user.id, "INSERT",
                                       "consommation_cuisine", c.id, None,
                                       {"numero": numero,
                                        "date": jour.isoformat(),
                                        "cout": cout_total, "ca": ca})
        return Response({**_conso_dict(c, seuil), "alertes": alertes},
                        status=201)
    q = ConsommationCuisine.objects.filter(societe_id=sid)
    du, au = request.query_params.get("du"), request.query_params.get("au")
    if du:
        q = q.filter(date_conso__gte=du)
    if au:
        q = q.filter(date_conso__lte=au)
    return Response([_conso_dict(c, seuil)
                     for c in q.order_by("-date_conso")[:60]])


@api_view(["GET"])
def rapport_cuisine(request):
    """Food cost de la période : coût théorique, CA plats, ratio, alertes."""
    sid = _societe_param(request)
    _acces(request, sid)
    seuil = _seuil(sid)
    try:
        du = date.fromisoformat(request.query_params.get("du"))
        au = date.fromisoformat(request.query_params.get("au"))
    except (TypeError, ValueError):
        au = date.today()
        du = au.replace(day=1)
    consos = list(ConsommationCuisine.objects.filter(
        societe_id=sid, date_conso__gte=du, date_conso__lte=au))
    cout = round(sum(float(c.cout_total) for c in consos), 2)
    ca = round(sum(float(c.ca_total) for c in consos), 2)
    plats = round(sum(float(c.nb_plats) for c in consos), 2)
    ratio = round(cout / ca * 100, 1) if ca else None
    depot = _depot_cuisine(sid)
    inventaires = InventaireDepot.objects.filter(societe_id=sid, depot_id=depot.id,
        date_inventaire__range=(du, au), statut='valide')
    ecarts = list(LigneInventaireDepot.objects.filter(inventaire_id__in=inventaires.values_list('id', flat=True)).values_list('ecart_valeur', flat=True))
    return Response({"du": du.isoformat(), "au": au.isoformat(),
                     "inventaires_valides": inventaires.count(),
                     "depot_inventaire": depot.libelle,
                     "manquants_inventaire": round(sum(-float(v) for v in ecarts if v < 0), 2),
                     "excedents_inventaire": round(sum(float(v) for v in ecarts if v > 0), 2),
                     "jours_generes": len(consos),
                     "cout_theorique": cout, "ca_plats": ca,
                     "nb_plats": plats,
                     "food_cost_pct": ratio, "seuil_pct": seuil,
                     "alerte": bool(ratio is not None and ratio > seuil)})
