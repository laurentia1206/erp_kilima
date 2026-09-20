"""Cycle de vente classique — portage exact de backend/app/routers/ventes.py.

Devis → commande client (même document, statuts successifs) → livraisons
partielles (sortie stock CUMP) → facturation des quantités livrées → règlements
clients multi-modes → encours. Gère aussi les PO du groupe (associations
d'articles, n° producteur, facturation conditionnée à la réception acheteur).
"""
from __future__ import annotations

from apps.stocks.catalogue import tiers_disponible

from datetime import date

from django.db import transaction
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from apps.groupe import services as intersociete_lib
from core import services as services
from core.erreurs import refus
from core.auth import assert_acces_societe, assert_role
from apps.tresorerie.views import _session_ouverte
from apps.commercial.views import _reglement_facture
from apps.stocks.models import Article, MouvementStock
from apps.tresorerie.models import Caisse, MouvementCaisse
from apps.commercial.models import Commande, Devis, Facture, LigneDevis, LigneFacture, LigneLivraison, Livraison, PaiementFacture
from apps.transport.models import Course
from apps.comptabilite.models import LigneEcriture
from core.models import Societe, Tiers
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI"}


def _devis_ou_404(request, devis_id):
    d = Devis.objects.filter(id=devis_id).first()
    if not d:
        return None
    roles = assert_acces_societe(request.user, d.societe_id)
    assert_role(roles, ROLES)
    return d


def _facturable(l: LigneDevis, art: Article | None, po: bool = False) -> float:
    """Quantité facturable : le livré non facturé (stock), tout le restant pour
    les lignes libres, TOUT suit le chargement déclaré pour un PO du groupe."""
    base = float(l.qte_livree) if (po or (art and art.gere_stock)) else float(l.qte)
    return round(max(base - float(l.qte_facturee), 0.0), 3)


def _devis_dict(d: Devis, detail: bool = True) -> dict:
    tiers = Tiers.objects.filter(id=d.tiers_id).first()
    po = bool(d.commande_origine_id)
    codes_acheteur = {}
    if po:
        cmd_po = Commande.objects.filter(id=d.commande_origine_id).first()
        if cmd_po:
            from apps.commercial.models import LigneCommande
            for i, lc in enumerate(LigneCommande.objects.filter(commande_id=cmd_po.id)):
                if lc.article_id:
                    a2 = Article.objects.filter(id=lc.article_id).first()
                    if a2:
                        codes_acheteur[i] = {"code": a2.code, "unite": a2.unite}
    lignes = []
    tot_cmd = {"livree": 0.0, "facturee": 0.0, "qte": 0.0, "livrable": 0.0,
               "facturable": 0.0}
    for l in LigneDevis.objects.filter(devis_id=d.id).order_by("ordre"):
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        gere = bool(art and art.gere_stock)
        livrable = round(float(l.qte) - float(l.qte_livree), 3) if (gere or po) else 0.0
        facturable = _facturable(l, art, po)
        tot_cmd["qte"] += float(l.qte)
        tot_cmd["livree"] += float(l.qte_livree)
        tot_cmd["facturee"] += float(l.qte_facturee)
        tot_cmd["livrable"] += livrable
        tot_cmd["facturable"] += facturable
        lignes.append({"id": str(l.id),
                       "article_id": str(l.article_id) if l.article_id else None,
                       "article": art.code if art else None,
                       "designation": l.designation,
                       "qte": float(l.qte), "prix_unitaire": float(l.prix_unitaire),
                       "remise_pct": float(l.remise_pct or 0),
                       "taux_tva": float(l.taux_tva),
                       "montant_ht": float(l.montant_ht),
                       "montant_tva": float(l.montant_tva),
                       "gere_stock": gere, "suivi_livraison": gere or po,
                       "code_acheteur": (codes_acheteur.get(int(l.ordre or 0))
                                         or {}).get("code"),
                       "unite_acheteur": (codes_acheteur.get(int(l.ordre or 0))
                                          or {}).get("unite"),
                       "a_associer": po and not art,
                       "stock_dispo": float(art.stock_qte) if gere else None,
                       "qte_livree": float(l.qte_livree),
                       "qte_facturee": float(l.qte_facturee),
                       "livrable": livrable, "facturable": facturable})
    stockables = [x for x in lignes if x["suivi_livraison"]]
    if not stockables:
        liv = "sans_objet"
    elif all(x["livrable"] <= 0 for x in stockables):
        liv = "livree"
    elif any(x["qte_livree"] > 0 for x in stockables):
        liv = "partielle"
    else:
        liv = "a_livrer"
    expire = bool(d.validite and d.statut in ("brouillon", "envoye")
                  and d.validite < date.today())
    cmd_origine = Commande.objects.filter(id=d.commande_origine_id).first() \
        if d.commande_origine_id else None
    transport = None
    if cmd_origine and cmd_origine.transporteur_societe_id:
        course = Course.objects.filter(commande_origine_id=cmd_origine.id).first()
        transporteur = Societe.objects.filter(
            id=cmd_origine.transporteur_societe_id).first()
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
        "pct_livre": round(tot_cmd["livree"] / tot_cmd["qte"] * 100)
        if tot_cmd["qte"] else 0,
        "pct_facture": round(tot_cmd["facturee"] / tot_cmd["qte"] * 100)
        if tot_cmd["qte"] else 0,
    }
    if detail:
        if cmd_origine:
            out["etapes_po"] = intersociete_lib.etapes_po(cmd_origine)
        out["lignes"] = lignes
        out["livraisons"] = [
            {"id": str(bl.id), "numero": bl.numero,
             "date": bl.date_livraison.isoformat(), "note": bl.note,
             "lignes": [{"designation": x.designation, "qte": float(x.qte)}
                        for x in LigneLivraison.objects.filter(livraison_id=bl.id)]}
            for bl in Livraison.objects.filter(devis_id=d.id).order_by("created_at")]
        facs = Facture.objects.filter(devis_id=d.id).order_by("created_at")
        out["factures"] = [{"id": str(f.id), "numero": f.numero,
                            "date": f.date_facture.isoformat(),
                            "total_ttc": float(f.total_ttc), **_reglement_facture(f)}
                           for f in facs]
    return out


def _calculer_lignes(d: Devis, societe_id, lignes_in: list[dict]):
    """(Re)construit les lignes du devis et ses totaux — retourne None ou Response."""
    tva_defaut = float(services.get_parametre("tva.taux_defaut", societe_id, "16"))
    gr = float(d.remise_globale_pct or 0)
    LigneDevis.objects.filter(devis_id=d.id).delete()
    total_ht = total_tva = remise_totale = 0.0
    for i, l in enumerate(lignes_in):
        art = Article.objects.filter(id=l.get("article_id")).first() \
            if l.get("article_id") else None
        if l.get("article_id") and (not art or str(art.societe_id) != str(societe_id)):
            return refus({"detail": "Article invalide."}, status=400)
        designation = (l.get("designation") or "").strip() \
            or (art.designation if art else None)
        if not designation:
            return refus({"detail": "Désignation requise sur chaque ligne."}, status=400)
        qte = float(l.get("qte", 0))
        if qte <= 0:
            return refus({"detail": "Quantité invalide."}, status=422)
        prix = l["prix_unitaire"] if l.get("prix_unitaire") is not None \
            else (float(art.prix_vente) if art else 0.0)
        if l.get("taux_tva") is not None:
            taux = l["taux_tva"]
        elif art:
            taux = float(art.taux_tva) if art.assujetti_tva else 0.0
        else:
            taux = tva_defaut
        remise = round((1 - (1 - float(l.get("remise_pct", 0)) / 100)
                        * (1 - gr / 100)) * 100, 4)
        brut = round(qte * prix, 2)
        ht = round(brut * (1 - remise / 100), 2)
        tva = round(ht * taux / 100, 2)
        total_ht += ht
        total_tva += tva
        remise_totale += brut - ht
        LigneDevis.objects.create(
            devis_id=d.id, ordre=i, article_id=art.id if art else None,
            designation=designation, qte=qte, prix_unitaire=prix,
            remise_pct=round(remise, 2), taux_tva=taux, montant_ht=ht, montant_tva=tva)
    d.total_ht = round(total_ht, 2)
    d.total_tva = round(total_tva, 2)
    d.total_ttc = round(total_ht + total_tva, 2)
    d.remise_totale = round(remise_totale, 2)
    return None


# ── Devis : CRUD & workflow ──────────────────────────────────────────
@api_view(["GET", "POST"])
def devis(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    if request.method == "POST":
        payload = request.data or {}
        societe = Societe.objects.filter(id=sid).first()
        tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not tiers_disponible(tiers, sid) or tiers.type != "client":
            return refus({"detail": "Sélectionnez un client."}, status=400)
        if not payload.get("lignes"):
            return refus({"detail": "Au moins une ligne."}, status=400)
        with transaction.atomic():
            jour = date.fromisoformat(payload["date_devis"]) \
                if payload.get("date_devis") else date.today()
            d = Devis.objects.create(
                societe_id=sid,
                numero=services.next_numero("devis", jour.year, societe.code, societe.id),
                tiers_id=tiers.id, date_devis=jour,
                validite=date.fromisoformat(payload["validite"])
                if payload.get("validite") else None,
                remise_globale_pct=payload.get("remise_globale_pct", 0),
                conditions=(payload.get("conditions") or "").strip() or None,
                note=(payload.get("note") or "").strip() or None,
                created_by=request.user.id, created_at=services.maintenant())
            err = _calculer_lignes(d, sid, payload["lignes"])
            if err is not None:
                return err
            d.save()
            services.enregistrer_audit(request.user.id, "INSERT", "devis", d.id, None,
                                       {"numero": d.numero, "ttc": float(d.total_ttc)})
        return Response(_devis_dict(d), status=201)
    q = Devis.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    return Response([_devis_dict(d, detail=False) for d in q.order_by("-created_at")])


@api_view(["GET", "PUT"])
def devis_detail(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    if request.method == "PUT":
        payload = request.data or {}
        if d.statut not in ("brouillon", "envoye"):
            return refus({"detail": "Seul un devis brouillon ou envoyé peut être "
                                    "modifié — la commande est confirmée."}, status=409)
        tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not tiers_disponible(tiers, d.societe_id) or tiers.type != "client":
            return refus({"detail": "Sélectionnez un client."}, status=400)
        if not payload.get("lignes"):
            return refus({"detail": "Au moins une ligne."}, status=400)
        with transaction.atomic():
            d.tiers_id = tiers.id
            if payload.get("date_devis"):
                d.date_devis = date.fromisoformat(payload["date_devis"])
            d.validite = date.fromisoformat(payload["validite"]) \
                if payload.get("validite") else None
            d.remise_globale_pct = payload.get("remise_globale_pct", 0)
            d.conditions = (payload.get("conditions") or "").strip() or None
            d.note = (payload.get("note") or "").strip() or None
            err = _calculer_lignes(d, d.societe_id, payload["lignes"])
            if err is not None:
                return err
            d.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "devis", d.id, None,
                                       {"numero": d.numero, "ttc": float(d.total_ttc)})
        return Response(_devis_dict(d))
    return Response(_devis_dict(d))


@api_view(["POST"])
def envoyer_devis(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    if d.statut != "brouillon":
        return refus({"detail": "Seul un brouillon peut être marqué « envoyé »."},
                     status=409)
    d.statut = "envoye"
    d.save(update_fields=["statut"])
    services.enregistrer_audit(request.user.id, "ENVOI", "devis", d.id, None,
                               {"numero": d.numero})
    return Response(_devis_dict(d))


def _associer_ligne(d: Devis, a: dict, user_id):
    """Associe une ligne du PO à un article du vendeur — None ou Response."""
    ligne = LigneDevis.objects.filter(devis_id=d.id, id=a.get("ligne_id")).first()
    if not ligne:
        return refus({"detail": "Ligne étrangère à la commande."}, status=400)
    if float(ligne.qte_livree) > 0:
        return refus({"detail": f"« {ligne.designation} » est déjà chargée — "
                                f"l'association ne se modifie plus (étape passée)."},
                     status=409)
    if a.get("article_id"):
        art = Article.objects.filter(id=a["article_id"]).first()
        if not art or str(art.societe_id) != str(d.societe_id):
            return refus({"detail": "Article invalide pour cette société."}, status=400)
    elif a.get("nouvel_article") and (a["nouvel_article"].get("code") or "").strip():
        na = a["nouvel_article"]
        code = str(na["code"]).strip().upper()
        art = Article.objects.filter(societe_id=d.societe_id, code=code).first()
        if not art:
            art = Article.objects.create(
                societe_id=d.societe_id, code=code,
                designation=str(na.get("designation") or ligne.designation).strip(),
                unite=str(na.get("unite") or "unité"),
                prix_achat=float(na.get("prix_achat") or 0),
                prix_vente=float(na.get("prix_vente") or ligne.prix_unitaire))
    else:
        return None
    ligne.article_id = art.id
    ligne.save(update_fields=["article_id"])
    services.enregistrer_audit(user_id, "ASSOCIATION", "ligne_devis", ligne.id, None,
                               {"article": art.code, "devis": d.numero})
    return None


@api_view(["POST"])
def confirmer_devis(request, devis_id):
    """Prise en charge : le devis devient la commande client (+ n° producteur)."""
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    if d.statut not in ("brouillon", "envoye"):
        return refus({"detail": "Devis déjà confirmé ou annulé."}, status=409)
    payload = request.data or {}
    with transaction.atomic():
        d.statut = "confirme"
        d.date_confirmation = services.maintenant()
        for a in payload.get("associations") or []:
            err = _associer_ligne(d, a, request.user.id)
            if err is not None:
                return err
        if payload.get("reference_producteur") is not None:
            ref = payload["reference_producteur"].strip() or None
            d.reference_producteur = ref
            if ref and d.commande_origine_id:
                cmd = Commande.objects.filter(id=d.commande_origine_id).first()
                if cmd:
                    cmd.reference_fournisseur = ref
                    cmd.save(update_fields=["reference_fournisseur"])
        d.save()
        services.enregistrer_audit(request.user.id, "CONFIRMATION", "devis", d.id, None,
                                   {"numero": d.numero,
                                    "ref_producteur": d.reference_producteur})
    return Response(_devis_dict(d))


@api_view(["POST"])
def associer_articles(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    with transaction.atomic():
        err = _associer_ligne(d, request.data or {}, request.user.id)
        if err is not None:
            return err
    return Response(_devis_dict(d))


@api_view(["POST"])
def maj_reference_producteur(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    payload = request.data or {}
    if not payload.get("reference_producteur"):
        return refus({"detail": "reference_producteur requis."}, status=422)
    ref = payload["reference_producteur"].strip() or None
    d.reference_producteur = ref
    d.save(update_fields=["reference_producteur"])
    if ref and d.commande_origine_id:
        cmd = Commande.objects.filter(id=d.commande_origine_id).first()
        if cmd:
            cmd.reference_fournisseur = ref
            cmd.save(update_fields=["reference_fournisseur"])
    return Response(_devis_dict(d))


@api_view(["POST"])
def annuler_devis(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    lignes = LigneDevis.objects.filter(devis_id=d.id)
    if any(float(l.qte_livree) > 0 or float(l.qte_facturee) > 0 for l in lignes):
        return refus({"detail": "Impossible d'annuler : des livraisons ou factures "
                                "existent déjà."}, status=409)
    if d.statut == "annule":
        return refus({"detail": "Déjà annulé."}, status=409)
    d.statut = "annule"
    d.save(update_fields=["statut"])
    # PO du groupe : l'annulation du vendeur annule aussi les demandes de
    # course encore en attente chez le transporteur
    if d.commande_origine_id:
        Course.objects.filter(commande_origine_id=d.commande_origine_id,
                              statut="demande").update(statut="annulee")
    services.enregistrer_audit(request.user.id, "ANNULATION", "devis", d.id, None,
                               {"numero": d.numero})
    return Response(_devis_dict(d))


# ── Livraison (BL) — sortie de stock au CUMP ─────────────────────────
@api_view(["POST"])
def livrer(request, devis_id):
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    if d.statut != "confirme":
        return refus({"detail": "Confirmez la commande avant de livrer."}, status=409)
    payload = request.data or {}
    if not payload.get("lignes"):
        return refus({"detail": "Aucune quantité à livrer."}, status=400)
    # PO avec transporteur du groupe : chaque étape attend son tour — pas de
    # chargement tant que la fiche de course n'est pas prise en charge ET validée
    if d.commande_origine_id:
        cmd_po = Commande.objects.filter(id=d.commande_origine_id).first()
        if cmd_po and cmd_po.transporteur_societe_id:
            transporteur = Societe.objects.filter(
                id=cmd_po.transporteur_societe_id).first()
            crs = intersociete_lib.course_active(cmd_po.id)
            if not crs or crs.statut in ("demande", "brouillon", "annulee"):
                return refus({"detail": f"Chargement bloqué : la fiche de course n'est "
                                        f"pas encore prête — on attend "
                                        f"{transporteur.nom if transporteur else 'le transporteur'} "
                                        f"(prise en charge puis validation de la "
                                        f"fiche)."}, status=409)
    societe = Societe.objects.filter(id=d.societe_id).first()
    jour = date.today()
    with transaction.atomic():
        numero = services.next_numero("livraison", jour.year, societe.code, societe.id)
        bl = Livraison.objects.create(
            societe_id=d.societe_id, devis_id=d.id, numero=numero, date_livraison=jour,
            note=(payload.get("note") or "").strip() or None,
            created_by=request.user.id, created_at=services.maintenant())

        lignes_par_id = {str(l.id): l for l in LigneDevis.objects.filter(devis_id=d.id)}
        po = bool(d.commande_origine_id)
        stock_par_compte: dict[str, float] = {}
        for rl in payload["lignes"]:
            orig = lignes_par_id.get(str(rl.get("ligne_id")))
            if not orig:
                return refus({"detail": "Ligne étrangère à la commande."}, status=400)
            art = Article.objects.filter(id=orig.article_id).first() \
                if orig.article_id else None
            gere = bool(art and art.gere_stock)
            if po and not art:
                return refus({"detail": f"« {orig.designation} » : associez d'abord "
                                        f"cette ligne à un article de votre stock "
                                        f"(bouton « Associer les articles » de la "
                                        f"commande)."}, status=409)
            if not gere and not po:
                return refus({"detail": f"« {orig.designation} » n'est pas un article "
                                        f"en stock — rien à livrer."}, status=400)
            qte = float(rl.get("qte", 0))
            if qte <= 0:
                return refus({"detail": "Quantité invalide."}, status=422)
            restant = round(float(orig.qte) - float(orig.qte_livree), 3)
            if qte > restant + 1e-6:
                return refus({"detail": f"{qte} demandé mais {restant} restant à livrer "
                                        f"sur « {orig.designation} »."}, status=409)
            cump = val = 0.0
            if gere:
                from apps.stocks import services as stock_lib
                central = stock_lib.depot_central(d.societe_id)
                dispo = stock_lib.qte_disponible(central.id, art.id)
                if dispo < qte - 1e-6:
                    return refus({"detail": f"Stock insuffisant pour {art.code} "
                                            f"au dépôt central : {dispo} "
                                            f"disponible, {qte} à livrer."},
                                 status=409)
                cump = stock_lib.cump_depot(central.id, art)
                val = stock_lib.sortie(art, central, qte, "livraison", numero,
                                       jour=jour)
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            orig.qte_livree = round(float(orig.qte_livree) + qte, 3)
            orig.save(update_fields=["qte_livree"])
            LigneLivraison.objects.create(
                livraison_id=bl.id, ligne_devis_id=orig.id,
                article_id=art.id if art else None, designation=orig.designation,
                qte=qte, cout_unitaire=round(cump, 4), valeur=val)

        if stock_par_compte:
            # Sortie de stock EN ATTENTE du comptable (revue des pièces)
            comptabilite.comptabiliser_stock_sortie(
                d.societe_id, stock_par_compte, numero, jour, "livraison", bl.id,
                request.user.id,
                statut="en_attente" if po
                else intersociete_lib._statut_piece(d.societe_id, "vente"))
        services.enregistrer_audit(request.user.id, "INSERT", "livraison", bl.id, None,
                                   {"numero": numero, "devis": d.numero})
    return Response(_devis_dict(d), status=201)


# ── Facturation des quantités livrées ────────────────────────────────
@api_view(["POST"])
def facturer(request, devis_id):
    """Facture les quantités livrées non encore facturées (+ lignes libres)."""
    d = _devis_ou_404(request, devis_id)
    if not d:
        return refus({"detail": "Devis introuvable."}, status=404)
    if d.statut != "confirme":
        return refus({"detail": "Confirmez la commande avant de facturer."}, status=409)
    payload = request.data or {}
    # PO intersociété : facturation conditionnée à la réception de l'acheteur
    if d.commande_origine_id:
        cmd_po = Commande.objects.filter(id=d.commande_origine_id).first()
        if cmd_po:
            r = intersociete_lib.reception_po_resume(cmd_po)
            if r["totaux"]["livre"] > 0 and not r["complete"]:
                return refus({"detail": "Facturation bloquée : l'acheteur n'a pas encore "
                                        "réceptionné toute la marchandise chargée (règle "
                                        "du groupe — la facture suit la réception)."},
                             status=409)
    societe = Societe.objects.filter(id=d.societe_id).first()
    jour = date.today()
    po = bool(d.commande_origine_id)
    a_facturer = []
    for l in LigneDevis.objects.filter(devis_id=d.id).order_by("ordre"):
        art = Article.objects.filter(id=l.article_id).first() if l.article_id else None
        qf = _facturable(l, art, po)
        if qf > 0:
            a_facturer.append((l, art, qf))
    if not a_facturer:
        return refus({"detail": "Rien à facturer — livrez d'abord (ou tout est déjà "
                                "facturé)."}, status=409)

    with transaction.atomic():
        numero = services.next_numero("facture_vente", jour.year, societe.code,
                                      societe.id)
        statut_piece = "en_attente" if po \
            else intersociete_lib._statut_piece(d.societe_id, "vente")
        fac = Facture.objects.create(
            societe_id=d.societe_id, type="vente", numero=numero, tiers_id=d.tiers_id,
            date_facture=jour,
            echeance=date.fromisoformat(payload["echeance"])
            if payload.get("echeance") else None,
            reference=d.reference_producteur,
            statut="validee" if statut_piece == "valide" else "en_attente",
            devis_id=d.id, created_by=request.user.id, created_at=services.maintenant())

        total_ht = total_tva = cout_total = 0.0
        lm_list = []
        for l, art, qf in a_facturer:
            ht = round(float(l.montant_ht) * qf / float(l.qte), 2)
            tva = round(float(l.montant_tva) * qf / float(l.qte), 2)
            total_ht += ht
            total_tva += tva
            agg = LigneLivraison.objects.filter(ligne_devis_id=l.id).aggregate(
                v=Sum("valeur"), q=Sum("qte"))
            cump_moy = float(agg["v"] or 0) / float(agg["q"]) if float(agg["q"] or 0) \
                else 0.0
            cout = round(qf * cump_moy, 2)
            cout_total += cout
            lm = LigneFacture.objects.create(
                facture_id=fac.id, article_id=l.article_id, designation=l.designation,
                qte=qf, prix_unitaire=float(l.prix_unitaire),
                remise_pct=float(l.remise_pct or 0), taux_tva=float(l.taux_tva),
                montant_ht=ht, montant_tva=tva)
            lm_list.append(lm)
            l.qte_facturee = round(float(l.qte_facturee) + qf, 3)
            l.save(update_fields=["qte_facturee"])

        fac.total_ht = round(total_ht, 2)
        fac.total_tva = round(total_tva, 2)
        fac.total_ttc = round(total_ht + total_tva, 2)
        fac.cout_ventes = round(cout_total, 2)
        fac.marge = round(fac.total_ht - cout_total, 2)
        ecr = comptabilite.comptabiliser_facture(fac, lm_list, request.user.id,
                                                 statut=statut_piece)
        fac.ecriture_id = ecr.id
        fac.save()
        # Intersociété : client du groupe → facture d'achat miroir
        intersociete_lib.creer_facture_miroir(fac, request.user.id)
        # PO d'origine : tout facturé → commande soldée chez l'acheteur
        if d.commande_origine_id and all(
                _facturable(l, Article.objects.filter(id=l.article_id).first()
                            if l.article_id else None, po=True) <= 0
                for l in LigneDevis.objects.filter(devis_id=d.id)):
            cmd_origine = Commande.objects.filter(id=d.commande_origine_id).first()
            if cmd_origine:
                cmd_origine.statut = "soldee"
                cmd_origine.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id, None,
                                   {"numero": numero, "devis": d.numero,
                                    "ttc": float(fac.total_ttc)})
    return Response({"facture": {"id": str(fac.id), "numero": numero,
                                 "total_ttc": float(fac.total_ttc)},
                     "devis": _devis_dict(d)}, status=201)


# ── Règlement client ─────────────────────────────────────────────────
@api_view(["POST"])
def regler_facture(request, facture_id):
    """Encaisse un règlement client : D trésorerie / C 411 (tiers, lettrable)."""
    fac = Facture.objects.filter(id=facture_id).first()
    if not fac or fac.type != "vente":
        return refus({"detail": "Facture de vente introuvable."}, status=404)
    roles = assert_acces_societe(request.user, fac.societe_id)
    assert_role(roles, ROLES | {"CAISSIER_CENTRAL"})
    payload = request.data or {}
    mode = payload.get("mode")
    devise = payload.get("devise", "USD")
    montant = payload.get("montant")
    if mode not in ("espece", "banque", "mobile_money") \
            or devise not in ("USD", "CDF") or not montant or float(montant) <= 0:
        return refus({"detail": "mode (espece|banque|mobile_money), devise et montant "
                                "> 0 requis."}, status=422)
    societe = Societe.objects.filter(id=fac.societe_id).first()
    tiers = Tiers.objects.filter(id=fac.tiers_id).first()
    sit = _reglement_facture(fac)
    solde = sit["solde_du_usd"]
    if solde <= 0.009:
        return refus({"detail": "Cette facture est déjà réglée."}, status=409)

    jour = date.today()
    taux = None
    if devise == "CDF":
        t = services.get_taux_jour(jour, "CDF")
        if not t:
            return refus({"detail": "Aucun taux USD/CDF défini aujourd'hui — définissez "
                                    "le taux du jour."}, status=409)
        taux = float(t)
        montant_usd = round(float(montant) / taux, 2)
    else:
        montant_usd = round(float(montant), 2)
    if montant_usd > solde + 0.01:
        return refus({"detail": f"Règlement de {montant_usd:.2f} USD supérieur au solde "
                                f"dû ({solde:.2f} USD)."}, status=400)

    caisse = sess = None
    if mode == "espece":
        if not payload.get("caisse_id"):
            return refus({"detail": "Choisissez la caisse qui encaisse."}, status=400)
        caisse = Caisse.objects.filter(id=payload["caisse_id"]).first()
        if not caisse or str(caisse.societe_id) != str(fac.societe_id):
            return refus({"detail": "Caisse invalide."}, status=400)
        sess = _session_ouverte(caisse.id)
        if not sess:
            return refus({"detail": f"Ouvrez la caisse « {caisse.libelle} » avant "
                                    f"d'encaisser."}, status=409)
        compte_tres = caisse.compte_comptable
    elif mode == "banque":
        compte_tres = comptabilite._compte("compte_banque", fac.societe_id)
    else:
        compte_tres = comptabilite._compte("compte_mobile_money", fac.societe_id)

    with transaction.atomic():
        lignes = [{"sens": "D", "compte": compte_tres, "montant_usd": montant_usd,
                   "devise_origine": devise, "montant_origine": round(float(montant), 2),
                   "taux_jour": taux, "libelle": f"Règlement {fac.numero} — {tiers.nom}"},
                  {"sens": "C",
                   "compte": comptabilite._compte("compte_client", fac.societe_id),
                   "montant_usd": montant_usd, "tiers_id": tiers.id,
                   "libelle": f"Règlement client {tiers.nom} — {fac.numero}"}]
        ecr = comptabilite.post_ecriture(fac.societe_id, "VE", "Ventes", "vente", jour,
                                         f"Règlement {fac.numero} — {tiers.nom}", lignes,
                                         "reglement_client", "facture", fac.id,
                                         fac.numero, request.user.id,
                                         statut=intersociete_lib._statut_piece(
                                             fac.societe_id, "vente"))
        PaiementFacture.objects.create(
            facture_id=fac.id, mode=mode, devise=devise,
            montant=round(float(montant), 2), taux_jour=taux, montant_usd=montant_usd,
            reference=(payload.get("reference") or "").strip() or None,
            compte=compte_tres)
        if caisse:
            MouvementCaisse.objects.create(
                caisse_id=caisse.id, session_id=sess.id,
                numero=services.next_numero("bon_caisse", jour.year, societe.code,
                                            societe.id),
                reference=fac.numero, sens="entree", nature="Encaissement client",
                devise=devise, taux_jour=taux, montant=round(float(montant), 2),
                montant_usd=montant_usd, tiers_id=tiers.id, tiers_nom=tiers.nom,
                reference_type="facture", reference_id=fac.id,
                libelle=f"Règlement {fac.numero} — {tiers.nom}",
                created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
        services.enregistrer_audit(request.user.id, "REGLEMENT", "facture", fac.id, None,
                                   {"numero": fac.numero, "montant_usd": montant_usd,
                                    "mode": mode})
    sit = _reglement_facture(fac)
    return Response({"ecriture": ecr.numero, **sit}, status=201)


# ── Encours clients ──────────────────────────────────────────────────
@api_view(["GET"])
def encours_clients(request):
    """Créances clients : solde 41x par client + factures non soldées."""
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    rows = (LigneEcriture.objects
            .filter(societe_id=sid, tiers_id__isnull=False,
                    compte_numero__startswith="41")
            .values_list("tiers_id", "sens").annotate(total=Sum("montant_usd"))
            .values_list("tiers_id", "sens", "total"))
    soldes: dict = {}
    for tiers_id, sens, montant in rows:
        soldes[tiers_id] = round(soldes.get(tiers_id, 0.0)
                                 + (float(montant or 0) if sens == "D"
                                    else -float(montant or 0)), 2)
    out = []
    for tiers_id, solde in soldes.items():
        if abs(solde) < 0.01:
            continue
        t = Tiers.objects.filter(id=tiers_id).first()
        facs = Facture.objects.filter(societe_id=sid, tiers_id=tiers_id, type="vente")
        dues = []
        for f in facs:
            sit = _reglement_facture(f)
            if sit["solde_du_usd"] > 0.009:
                dues.append({"numero": f.numero, "date": f.date_facture.isoformat(),
                             "echeance": f.echeance.isoformat() if f.echeance else None,
                             "solde_du_usd": sit["solde_du_usd"],
                             "en_retard": sit["en_retard"]})
        out.append({"tiers_id": str(tiers_id), "client": t.nom if t else "?",
                    "solde_usd": solde,
                    "limite_credit_usd": float(t.limite_credit_usd)
                    if t and t.limite_credit_usd is not None else None,
                    "factures_dues": sorted(dues, key=lambda x: x["date"]),
                    "en_retard": any(x["en_retard"] for x in dues)})
    return Response(sorted(out, key=lambda x: -x["solde_usd"]))
