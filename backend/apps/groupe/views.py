"""Opérations intersociétés — portage exact de backend/app/routers/intersociete.py.

Réception physique du PO par l'acheteur (bon / mauvais / manquant, manquants à
la charge du transporteur au prix d'achat), confirmation par le transporteur,
annulation avec contre-passation, liaisons tiers↔sociétés, positions groupe,
factures intra-groupe et règlement réel double-face, traçabilité, badges.
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.commercial.models import Commande
from apps.groupe.serializers import CommandeSerializer
from apps.groupe.models import ReceptionInter
from apps.groupe.serializers import ReceptionInterSerializer
from apps.commercial.models import Facture
from apps.groupe.serializers import FactureSerializer

from datetime import date

from django.db import transaction
from django.db.models import Q, Sum
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from apps.groupe import services as intersociete_lib
from core import services as services
from core.erreurs import refus
from core.auth import assert_acces_societe, assert_role
from apps.tresorerie.views import _session_ouverte
from apps.commercial.views import _reglement_facture
from apps.groupe.services import _mapping_lignes_po, _recu_cumule_po, reception_po_resume, tiers_reciproque
from apps.stocks.models import Article, MouvementStock
from apps.tresorerie.models import Caisse, MouvementCaisse
from apps.transport.models import Camion, Course
from apps.commercial.models import Commande, Devis, Facture, LigneCommande, LigneDevis, LigneLivraison, Livraison, PaiementFacture
from apps.comptabilite.models import LigneEcriture
from apps.groupe.models import LigneReceptionInter, ReceptionInter
from core.models import Societe, Tiers, UtilisateurSociete
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI", "PRESIDENT"}


# ── Réception physique du PO (acheteur) ──────────────────────────────
class CommandeViewSet(MetierModelViewSet):
    """Ressource Commande ; contrats HTTP et validations métier conservés."""
    queryset = Commande.objects.none()
    serializer_class = CommandeSerializer
    lookup_url_kwarg = 'commande_id'

    @action(detail=True, methods=['post'])
    def receptionner(self, request, commande_id):
        "L'acheteur constate bon/mauvais/manquant ; stock = reçu ; manquants à la\n    charge du transporteur du groupe au prix d'achat (écritures croisées)."
        cmd = Commande.objects.filter(id=commande_id).first()
        if not cmd or not cmd.devis_lie_id:
            return refus({"detail": "Commande intersociété introuvable."}, status=404)
        roles = assert_acces_societe(request.user, cmd.societe_id)
        assert_role(roles, ROLES)
        payload = request.data or {}
        lignes_in = payload.get("lignes") or []
        if not lignes_in or all(
                float(l.get("qte_bon", 0)) + float(l.get("qte_mauvais", 0))
                + float(l.get("qte_manquante", 0)) <= 0 for l in lignes_in):
            return refus({"detail": "Aucune quantité constatée."}, status=400)
        # Étapes dans l'ordre : la réception attend l'ARRIVÉE du camion
        if cmd.transporteur_societe_id:
            crs = intersociete_lib.course_active(cmd.id)
            if crs and crs.statut in ("demande", "brouillon", "validee", "en_cours"):
                transporteur = Societe.objects.filter(
                    id=cmd.transporteur_societe_id).first()
                return refus({"detail": f"Réception bloquée : le camion n'est pas encore "
                                        f"marqué arrivé — on attend "
                                        f"{transporteur.nom if transporteur else 'le transporteur'} "
                                        f"(signaler l'arrivée à destination)."},
                             status=409)

        mapping = _mapping_lignes_po(cmd)
        deja = _recu_cumule_po(cmd)
        lignes_cmd = {str(l.id): l for l in LigneCommande.objects.filter(commande_id=cmd.id)}
        societe = Societe.objects.filter(id=cmd.societe_id).first()
        jour = date.today()
        with transaction.atomic():
            numero = services.next_numero("reception_inter", jour.year, societe.code,
                                          societe.id)
            rec = ReceptionInter.objects.create(
                societe_id=cmd.societe_id, commande_id=cmd.id, numero=numero,
                date_reception=jour, note=(payload.get("note") or "").strip() or None,
                statut="a_confirmer" if cmd.transporteur_societe_id else "confirmee",
                created_by=request.user.id, created_at=services.maintenant())

            stock_par_compte: dict[str, float] = {}
            valeur_manquants = 0.0
            for pl in lignes_in:
                lc = lignes_cmd.get(str(pl.get("ligne_commande_id")))
                if not lc:
                    return refus({"detail": "Ligne étrangère à la commande."}, status=400)
                qte_bon = float(pl.get("qte_bon", 0))
                qte_mauvais = float(pl.get("qte_mauvais", 0))
                qte_manquante = float(pl.get("qte_manquante", 0))
                if qte_bon < 0 or qte_mauvais < 0 or qte_manquante < 0:
                    return refus({"detail": "Quantités négatives interdites."}, status=422)
                constate = round(qte_bon + qte_mauvais + qte_manquante, 3)
                if constate <= 0:
                    continue
                ld = mapping.get(str(lc.id))
                livre = float(ld.qte_livree) if ld else 0.0
                d = deja.get(str(lc.id), {"bon": 0.0, "mauvais": 0.0, "manquant": 0.0})
                deja_constate = d["bon"] + d["mauvais"] + d["manquant"]
                if constate + deja_constate > livre + 1e-6:
                    return refus({"detail": f"« {lc.designation} » : {constate} constaté + "
                                            f"{deja_constate} déjà réceptionné > {livre} "
                                            f"chargé par le vendeur."}, status=409)
                LigneReceptionInter.objects.create(
                    reception_id=rec.id, ligne_commande_id=lc.id, qte_bon=qte_bon,
                    qte_mauvais=qte_mauvais, qte_manquante=qte_manquante)
                recu = round(qte_bon + qte_mauvais, 3)
                lc.qte_recue = round(float(lc.qte_recue) + recu, 3)
                lc.save(update_fields=["qte_recue"])
                pu = float(lc.prix_unitaire)
                valeur_manquants += round(qte_manquante * pu, 2)
                # stock chez l'acheteur : uniquement ce qui est physiquement là
                if recu > 0 and lc.article_id:
                    art = Article.objects.filter(id=lc.article_id).first()
                    if art and art.gere_stock:
                        val = round(recu * pu, 2)
                        from apps.stocks import services as stock_lib
                        stock_lib.entree(art, stock_lib.depot_central(cmd.societe_id),
                                         recu, val, "achat", numero, jour=jour)
                        stock_par_compte[art.compte_stock] = round(
                            stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
            if stock_par_compte:
                # entrée en stock EN ATTENTE — le comptable valide avec les pièces (NB3)
                comptabilite.comptabiliser_stock_entree(
                    cmd.societe_id, stock_par_compte, numero, jour, "reception_inter",
                    rec.id, request.user.id, statut="en_attente")
            # le statut de la course évolue : « réceptionnée »
            course_po = Course.objects.filter(commande_origine_id=cmd.id).first()
            if course_po and course_po.statut in ("en_cours", "arrivee"):
                course_po.statut = "receptionnee"
                course_po.save(update_fields=["statut"])

            # ── Manquants : à la charge du transporteur, au prix d'achat ──
            manquants_factures = False
            if valeur_manquants > 0.004 and cmd.transporteur_societe_id:
                transporteur = Societe.objects.filter(id=cmd.transporteur_societe_id).first()
                soc_transp_chez_acheteur = tiers_reciproque(cmd.societe_id, transporteur,
                                                            "fournisseur")
                acheteur_chez_transp = tiers_reciproque(transporteur.id, societe, "client")
                m = round(valeur_manquants, 2)
                # acheteur : D 401 transporteur / C 758
                comptabilite.post_ecriture(
                    cmd.societe_id, "OD", "Opérations diverses", "od", jour,
                    f"Manquants {numero} à charge du transporteur {transporteur.nom}",
                    [{"sens": "D",
                      "compte": comptabilite._compte("compte_fournisseur", cmd.societe_id),
                      "montant_usd": m, "tiers_id": soc_transp_chez_acheteur.id,
                      "libelle": f"Manquants {numero} — {transporteur.nom}"},
                     {"sens": "C",
                      "compte": comptabilite._compte("manquants_produit", cmd.societe_id),
                      "montant_usd": m, "libelle": f"Indemnité manquants {numero}"}],
                    "manquants_transport", "reception_inter", rec.id, numero,
                    request.user.id, statut="en_attente")
                # transporteur : D 658 / C 411 acheteur
                comptabilite.post_ecriture(
                    transporteur.id, "OD", "Opérations diverses", "od", jour,
                    f"Manquants {numero} supportés — commande {cmd.numero}",
                    [{"sens": "D",
                      "compte": comptabilite._compte("manquants_charge", transporteur.id),
                      "montant_usd": m, "libelle": f"Manquants transport {cmd.numero}"},
                     {"sens": "C",
                      "compte": comptabilite._compte("compte_client", transporteur.id),
                      "montant_usd": m, "tiers_id": acheteur_chez_transp.id,
                      "libelle": f"Manquants dus à {societe.nom} — {numero}"}],
                    "manquants_transport", "reception_inter", rec.id, numero,
                    request.user.id, statut="en_attente")
                manquants_factures = True

            services.enregistrer_audit(request.user.id, "RECEPTION", "reception_inter",
                                       rec.id, None,
                                       {"numero": numero, "commande": cmd.numero,
                                        "manquants_usd": round(valeur_manquants, 2)})
        return Response({"numero": numero, "manquants_usd": round(valeur_manquants, 2),
                         "manquants_imputes_transporteur": manquants_factures}, status=201)


def _annuler_reception(request, reception_id):
    """Annulation du constat (avant confirmation) : contre-passe tout."""
    rec = ReceptionInter.objects.filter(id=reception_id).first()
    if not rec:
        return refus({"detail": "Réception introuvable."}, status=404)
    cmd = Commande.objects.filter(id=rec.commande_id).first()
    roles = assert_acces_societe(request.user, rec.societe_id)
    assert_role(roles, ROLES)
    if rec.statut == "confirmee":
        return refus({"detail": "Réception confirmée par le transporteur — elle ne se "
                                "modifie plus."}, status=409)
    if rec.statut == "annulee":
        return refus({"detail": "Déjà annulée."}, status=409)
    societe = Societe.objects.filter(id=rec.societe_id).first()
    jour = date.today()
    lignes_cmd = {str(l.id): l for l in LigneCommande.objects.filter(commande_id=cmd.id)}
    with transaction.atomic():
        stock_par_compte: dict[str, float] = {}
        valeur_manquants = 0.0
        for lr in LigneReceptionInter.objects.filter(reception_id=rec.id):
            lc = lignes_cmd.get(str(lr.ligne_commande_id))
            if not lc:
                continue
            recu = round(float(lr.qte_bon) + float(lr.qte_mauvais), 3)
            pu = float(lc.prix_unitaire)
            valeur_manquants += round(float(lr.qte_manquante) * pu, 2)
            lc.qte_recue = round(float(lc.qte_recue) - recu, 3)
            lc.save(update_fields=["qte_recue"])
            if recu > 0 and lc.article_id:
                art = Article.objects.filter(id=lc.article_id).first()
                if art and art.gere_stock:
                    val = round(recu * pu, 2)
                    from apps.stocks import services as stock_lib
                    stock_lib.sortie(art, stock_lib.depot_central(rec.societe_id),
                                     recu, "annulation_reception",
                                     f"ANN-{rec.numero}", jour=jour, valeur=val)
                    stock_par_compte[art.compte_stock] = round(
                        stock_par_compte.get(art.compte_stock, 0.0) + val, 2)
        if stock_par_compte:
            comptabilite.comptabiliser_stock_sortie(
                rec.societe_id, stock_par_compte, f"ANN-{rec.numero}", jour,
                "reception_inter", rec.id, request.user.id)
        if valeur_manquants > 0.004 and cmd.transporteur_societe_id:
            transporteur = Societe.objects.filter(id=cmd.transporteur_societe_id).first()
            soc_transp_chez_acheteur = tiers_reciproque(rec.societe_id, transporteur,
                                                        "fournisseur")
            acheteur_chez_transp = tiers_reciproque(transporteur.id, societe, "client")
            m = round(valeur_manquants, 2)
            comptabilite.post_ecriture(
                rec.societe_id, "OD", "Opérations diverses", "od", jour,
                f"Annulation manquants {rec.numero}",
                [{"sens": "D",
                  "compte": comptabilite._compte("manquants_produit", rec.societe_id),
                  "montant_usd": m, "libelle": f"Annulation indemnité {rec.numero}"},
                 {"sens": "C",
                  "compte": comptabilite._compte("compte_fournisseur", rec.societe_id),
                  "montant_usd": m, "tiers_id": soc_transp_chez_acheteur.id,
                  "libelle": f"Annulation manquants {rec.numero}"}],
                "manquants_transport", "reception_inter", rec.id, f"ANN-{rec.numero}",
                request.user.id, statut="en_attente")
            comptabilite.post_ecriture(
                transporteur.id, "OD", "Opérations diverses", "od", jour,
                f"Annulation manquants {rec.numero}",
                [{"sens": "D",
                  "compte": comptabilite._compte("compte_client", transporteur.id),
                  "montant_usd": m, "tiers_id": acheteur_chez_transp.id,
                  "libelle": f"Annulation manquants {rec.numero}"},
                 {"sens": "C",
                  "compte": comptabilite._compte("manquants_charge", transporteur.id),
                  "montant_usd": m, "libelle": f"Annulation manquants {rec.numero}"}],
                "manquants_transport", "reception_inter", rec.id, f"ANN-{rec.numero}",
                request.user.id, statut="en_attente")
        rec.statut = "annulee"
        rec.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "ANNULATION", "reception_inter",
                                   rec.id, None, {"numero": rec.numero})
    return Response({"ok": True, "numero": rec.numero})


def _detail_reception(request, reception_id):
    """Détail complet pour le bon de réception imprimable."""
    rec = ReceptionInter.objects.filter(id=reception_id).first()
    if not rec:
        return refus({"detail": "Réception introuvable."}, status=404)
    assert_acces_societe(request.user, rec.societe_id)
    cmd = Commande.objects.filter(id=rec.commande_id).first()
    fourn = Tiers.objects.filter(id=cmd.tiers_id).first() if cmd else None
    transporteur = Societe.objects.filter(id=cmd.transporteur_societe_id).first() \
        if cmd and cmd.transporteur_societe_id else None
    lignes_cmd = {str(l.id): l for l in
                  (LigneCommande.objects.filter(commande_id=cmd.id) if cmd else [])}
    lignes = []
    for lr in LigneReceptionInter.objects.filter(reception_id=rec.id):
        lc = lignes_cmd.get(str(lr.ligne_commande_id))
        pu = float(lc.prix_unitaire) if lc else 0.0
        lignes.append({"designation": lc.designation if lc else "?",
                       "bon": float(lr.qte_bon), "mauvais": float(lr.qte_mauvais),
                       "manquant": float(lr.qte_manquante), "prix_unitaire": pu,
                       "valeur_manquants": round(float(lr.qte_manquante) * pu, 2)})
    return Response({"id": str(rec.id), "numero": rec.numero,
                     "date": rec.date_reception.isoformat(),
                     "statut": rec.statut, "note": rec.note,
                     "commande": cmd.numero if cmd else None,
                     "reference_producteur": cmd.reference_fournisseur if cmd else None,
                     "destination": cmd.destination if cmd else None,
                     "fournisseur": fourn.nom if fourn else None,
                     "transporteur": transporteur.nom if transporteur else None,
                     "lignes": lignes,
                     "valeur_manquants_usd": round(sum(l["valeur_manquants"]
                                                       for l in lignes), 2)})


class ReceptionViewSet(MetierModelViewSet):
    """Ressource Reception ; contrats HTTP et validations métier conservés."""
    queryset = ReceptionInter.objects.none()
    serializer_class = ReceptionInterSerializer
    lookup_url_kwarg = 'reception_id'

    def list(self, request):
        """Achats › Réceptions de l'acheteur : PO à réceptionner + historique."""
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, ROLES)
        cmds = (Commande.objects.filter(societe_id=sid, devis_lie_id__isnull=False)
                .order_by("-created_at"))
        a_recevoir, historique = [], []
        socs = dict(Societe.objects.values_list("id", "nom"))
        tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
        for cmd in cmds:
            fourn_nom = tiers_noms.get(cmd.tiers_id)
            r = reception_po_resume(cmd)
            course = Course.objects.filter(commande_origine_id=cmd.id).first()
            en_route = bool(course and course.statut in ("en_cours", "arrivee", "livree"))
            if (r["a_receptionner"] or en_route) and cmd.statut not in ("soldee", "annulee") \
                    and not r["complete"]:
                a_recevoir.append({"commande_id": str(cmd.id), "numero": cmd.numero,
                                   "fournisseur": fourn_nom or "?",
                                   "destination": cmd.destination,
                                   "reference_producteur": cmd.reference_fournisseur,
                                   "receptionnable": r["a_receptionner"],
                                   "en_attente": round(r["totaux"]["livre"]
                                                       - r["totaux"]["bon"]
                                                       - r["totaux"]["mauvais"]
                                                       - r["totaux"]["manquant"], 3),
                                   "course": course.numero if course else None,
                                   "course_statut": course.statut if course else None})
            for rec in r["receptions"]:
                historique.append({**rec, "commande": cmd.numero,
                                   "fournisseur": fourn_nom or "?",
                                   "transporteur": socs.get(cmd.transporteur_societe_id)})
        return Response({"a_recevoir": a_recevoir, "historique": historique})


    def retrieve(self, request, reception_id):
        return self._traiter_reception_detail_ou_annulation(request, reception_id)


    def destroy(self, request, reception_id):
        return self._traiter_reception_detail_ou_annulation(request, reception_id)


    def _traiter_reception_detail_ou_annulation(self, request, reception_id):
        """GET : détail du bon de réception ; DELETE : annulation du constat."""
        if request.method == "GET":
            return _detail_reception(request, reception_id)
        return _annuler_reception(request, reception_id)


    @action(detail=True, methods=['post'])
    def confirmer(self, request, reception_id):
        """Le TRANSPORTEUR confirme le constat de l'acheteur (il assume les manquants)."""
        rec = ReceptionInter.objects.filter(id=reception_id).first()
        if not rec:
            return refus({"detail": "Réception introuvable."}, status=404)
        cmd = Commande.objects.filter(id=rec.commande_id).first()
        if not cmd or not cmd.transporteur_societe_id:
            return refus({"detail": "Réception sans transporteur du groupe."}, status=400)
        roles = assert_acces_societe(request.user, cmd.transporteur_societe_id)
        assert_role(roles, {"COMPTABLE", "DFI", "DG", "ASSISTANT_TECH"})
        if rec.statut == "confirmee":
            return refus({"detail": "Déjà confirmée."}, status=409)
        rec.statut = "confirmee"
        rec.confirme_par = request.user.id
        rec.date_confirmation = services.maintenant()
        rec.save(update_fields=["statut", "confirme_par", "date_confirmation"])
        services.enregistrer_audit(request.user.id, "CONFIRMATION", "reception_inter",
                                   rec.id, None, {"numero": rec.numero})
        return Response({"numero": rec.numero, "statut": "confirmee"})


# ── Liaison tiers ↔ société du groupe ────────────────────────────────


# ── Positions intersociétés ──────────────────────────────────────────
def _solde_tiers(societe_id, tiers_id, prefixe: str) -> float:
    total = 0.0
    for sens, montant in (LigneEcriture.objects
                          .filter(societe_id=societe_id, tiers_id=tiers_id,
                                  compte_numero__startswith=prefixe)
                          .values_list("sens").annotate(t=Sum("montant_usd"))
                          .values_list("sens", "t")):
        total += float(montant or 0) if sens == "D" else -float(montant or 0)
    return round(total, 2)


class GroupeViewSet(MetierViewSet):
    """Ressource Groupe ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def tracer(self, request):
        """Traçabilité de bout en bout par n° producteur (ou n° de commande)."""
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        q = request.query_params.get("q")
        if not q:
            from core.erreurs import Parametre422
            raise Parametre422({"detail": [{"type": "missing", "loc": ["query", "q"],
                                            "msg": "Field required", "input": None}]})
        ql = q.strip()
        cmds = (Commande.objects.filter(Q(reference_fournisseur__icontains=ql)
                                        | Q(numero__icontains=ql))
                .order_by("-created_at")[:10])
        socs = dict(Societe.objects.values_list("id", "nom"))
        tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
        dossiers = []
        for cmd in cmds:
            lignes_cmd = list(LigneCommande.objects.filter(commande_id=cmd.id))
            dv = Devis.objects.filter(id=cmd.devis_lie_id).first() \
                if cmd.devis_lie_id else None
            course = Course.objects.filter(commande_origine_id=cmd.id).first()
            r = reception_po_resume(cmd) if cmd.devis_lie_id else None
            livraisons = []
            factures = []
            if dv:
                for bl in Livraison.objects.filter(devis_id=dv.id):
                    livraisons.append({"numero": bl.numero,
                                       "date": bl.date_livraison.isoformat(),
                                       "qte": round(sum(
                                           float(x.qte) for x in
                                           LigneLivraison.objects.filter(
                                               livraison_id=bl.id)), 3)})
                for f in Facture.objects.filter(devis_id=dv.id):
                    factures.append({"numero": f.numero,
                                     "date": f.date_facture.isoformat(),
                                     "ttc": float(f.total_ttc), "statut": f.statut})
            camion = Camion.objects.filter(id=course.camion_id).first() \
                if course and course.camion_id else None
            dossiers.append({
                "reference_producteur": cmd.reference_fournisseur,
                "commande": {"numero": cmd.numero,
                             "date": cmd.date_commande.isoformat(),
                             "acheteur": socs.get(cmd.societe_id),
                             "vendeur": tiers_noms.get(cmd.tiers_id) or "?",
                             "destination": cmd.destination, "statut": cmd.statut,
                             "qte_commandee": round(sum(float(l.qte)
                                                        for l in lignes_cmd), 3),
                             "total_ht": float(cmd.total_ht)},
                "prise_en_charge": {"numero": dv.numero, "statut": dv.statut,
                                    "date": dv.date_confirmation.isoformat()
                                    if dv.date_confirmation else None} if dv else None,
                "chargements": livraisons,
                "transport": {"transporteur": socs.get(cmd.transporteur_societe_id),
                              "course": course.numero, "statut": course.statut,
                              "camion": camion.immatriculation if camion else None,
                              "unite": course.unite,
                              "depart": course.heure_depart.isoformat()
                              if course.heure_depart else None,
                              "retour": course.heure_retour.isoformat()
                              if course.heure_retour else None} if course else None,
                "reception": {"totaux": r["totaux"], "complete": r["complete"],
                              "toutes_confirmees": r["toutes_confirmees"],
                              "receptions": r["receptions"],
                              "valeur_manquants_usd": r["valeur_manquants_usd"]}
                if r else None,
                "factures_vendeur": factures,
            })
        return Response(dossiers)


    @action(detail=False, methods=['get'])
    def badges(self, request):
        """Compteurs des opérations en attente pour les bannières de menus."""
        sid = _societe_param(request)
        assert_acces_societe(request.user, sid)
        devis_po = Devis.objects.filter(societe_id=sid, statut="envoye",
                                        commande_origine_id__isnull=False).count()
        n_rec = 0
        for cmd in Commande.objects.filter(societe_id=sid, devis_lie_id__isnull=False) \
                .exclude(statut__in=["soldee", "annulee"]):
            if reception_po_resume(cmd)["a_receptionner"]:
                n_rec += 1
        n_dem = Course.objects.filter(societe_id=sid, statut="demande").count()
        n_conf = ReceptionInter.objects.filter(
            statut="a_confirmer",
            commande_id__in=Commande.objects.filter(
                transporteur_societe_id=sid).values("id")).count()
        return Response({"devis_po": devis_po, "receptions": n_rec,
                         "courses": n_dem + n_conf})


    @action(detail=False, methods=['get'])
    def liaisons(self, request):
        """Tiers de la société marqués intra-groupe + leur société liée."""
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, ROLES)
        socs = {str(s.id): {"id": str(s.id), "code": s.code, "nom": s.nom}
                for s in Societe.objects.all()}
        ts = (Tiers.objects.filter(societe_id=sid)
              .filter(Q(intra_groupe=True) | Q(societe_liee_id__isnull=False))
              .order_by("nom"))
        return Response({"societes": list(socs.values()),
                         "tiers": [{"id": str(t.id), "type": t.type, "code": t.code,
                                    "nom": t.nom,
                                    "societe_liee": socs.get(str(t.societe_liee_id))
                                    if t.societe_liee_id else None} for t in ts]})


    @action(detail=False, methods=['post'])
    def lier(self, request):
        payload = request.data or {}
        t = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not t:
            return refus({"detail": "Tiers introuvable."}, status=404)
        roles = assert_acces_societe(request.user, t.societe_id)
        assert_role(roles, ROLES)
        if payload.get("societe_liee_id"):
            s = Societe.objects.filter(id=payload["societe_liee_id"]).first()
            if not s:
                return refus({"detail": "Société introuvable."}, status=400)
            if str(s.id) == str(t.societe_id):
                return refus({"detail": "Un tiers ne peut pas être lié à sa propre "
                                        "société."}, status=400)
            t.societe_liee_id = s.id
            t.intra_groupe = True
        else:
            t.societe_liee_id = None
            t.intra_groupe = False
        t.save(update_fields=["societe_liee_id", "intra_groupe"])
        services.enregistrer_audit(request.user.id, "LIAISON", "tiers", t.id, None,
                                   {"societe_liee": str(payload.get("societe_liee_id"))})
        return Response({"ok": True})


    @action(detail=False, methods=['get'])
    def positions(self, request):
        """Qui doit quoi à qui : créance vendeur, dette miroir acheteur, écart."""
        societes_ids = list(UtilisateurSociete.objects.filter(
            utilisateur_id=request.user.id).values_list("societe_id", flat=True))
        socs = {s.id: s for s in Societe.objects.all()}
        out = []
        for sid in set(societes_ids):
            ts = Tiers.objects.filter(societe_id=sid, societe_liee_id__isnull=False)
            for t in ts:
                creance = _solde_tiers(sid, t.id, "41") if t.type == "client" else 0.0
                dette = -_solde_tiers(sid, t.id, "40") if t.type == "fournisseur" else 0.0
                if abs(creance) < 0.01 and abs(dette) < 0.01:
                    continue
                liee = socs.get(t.societe_liee_id)
                recip = Tiers.objects.filter(
                    societe_id=t.societe_liee_id, societe_liee_id=sid,
                    type=("fournisseur" if t.type == "client" else "client")).first()
                miroir = 0.0
                if recip:
                    miroir = (-_solde_tiers(t.societe_liee_id, recip.id, "40")
                              if t.type == "client"
                              else _solde_tiers(t.societe_liee_id, recip.id, "41"))
                montant = creance if t.type == "client" else dette
                out.append({
                    "creancier": socs[sid].nom if t.type == "client"
                    else (liee.nom if liee else "?"),
                    "debiteur": (liee.nom if liee else "?") if t.type == "client"
                    else socs[sid].nom,
                    "vu_par": socs[sid].nom, "sens": t.type,
                    "montant_usd": round(montant, 2), "miroir_usd": round(miroir, 2),
                    "ecart_usd": round(montant - miroir, 2),
                })
        vues_client = [o for o in out if o["sens"] == "client"]
        couverts = {(o["creancier"], o["debiteur"]) for o in vues_client}
        vues_fourn = [o for o in out if o["sens"] == "fournisseur"
                      and (o["creancier"], o["debiteur"]) not in couverts]
        return Response(vues_client + vues_fourn)


# ── Factures intra-groupe & règlement réel double-face ───────────────


class FactureViewSet(MetierModelViewSet):
    """Ressource Facture ; contrats HTTP et validations métier conservés."""
    queryset = Facture.objects.none()
    serializer_class = FactureSerializer
    lookup_url_kwarg = 'facture_id'

    def list(self, request):
        societes_ids = set(UtilisateurSociete.objects.filter(
            utilisateur_id=request.user.id).values_list("societe_id", flat=True))
        socs = dict(Societe.objects.values_list("id", "nom"))
        facs = (Facture.objects.filter(type="vente", intra_groupe=True,
                                       societe_id__in=societes_ids)
                .order_by("-created_at"))
        tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
        out = []
        for f in facs:
            miroir = Facture.objects.filter(id=f.facture_liee_id).first() \
                if f.facture_liee_id else None
            out.append({"id": str(f.id), "numero": f.numero,
                        "date": f.date_facture.isoformat(),
                        "vendeur": socs.get(f.societe_id),
                        "acheteur": tiers_noms.get(f.tiers_id) or "?",
                        "vendeur_societe_id": str(f.societe_id),
                        "acheteur_societe_id": str(miroir.societe_id) if miroir else None,
                        "total_ttc": float(f.total_ttc), **_reglement_facture(f),
                        "miroir_numero": miroir.numero if miroir else None,
                        "miroir_statut": miroir.statut if miroir else None})
        return Response(out)


    @action(detail=True, methods=['post'])
    def regler(self, request, facture_id):
        "Règlement réel en une action : sortie chez l'acheteur ET entrée chez le\n    vendeur (pièces en attente des deux côtés)."
        fac_v = Facture.objects.filter(id=facture_id).first()
        if not fac_v or fac_v.type != "vente" or not fac_v.intra_groupe \
                or not fac_v.facture_liee_id:
            return refus({"detail": "Facture intersociété introuvable (miroir manquant)."},
                         status=404)
        fac_a = Facture.objects.filter(id=fac_v.facture_liee_id).first()
        roles_v = assert_acces_societe(request.user, fac_v.societe_id)
        assert_role(roles_v, ROLES)
        roles_a = assert_acces_societe(request.user, fac_a.societe_id)
        assert_role(roles_a, ROLES)
        payload = request.data or {}

        sit = _reglement_facture(fac_v)
        solde = sit["solde_du_usd"]
        if solde <= 0.009:
            return refus({"detail": "Cette facture est déjà réglée."}, status=409)
        montant = round(float(payload["montant_usd"]), 2) \
            if payload.get("montant_usd") else solde
        if montant > solde + 0.01:
            return refus({"detail": f"Montant supérieur au solde dû ({solde:.2f} USD)."},
                         status=400)

        soc_v = Societe.objects.filter(id=fac_v.societe_id).first()
        soc_a = Societe.objects.filter(id=fac_a.societe_id).first()
        tiers_client = Tiers.objects.filter(id=fac_v.tiers_id).first()
        tiers_fourn = Tiers.objects.filter(id=fac_a.tiers_id).first()
        jour = date.today()
        ref = (payload.get("reference") or "").strip() \
            or f"Règlement intersociété {fac_v.numero}"

        def _tresorerie(societe_id, mode, caisse_id):
            """(compte, caisse, session) — ou Response d'erreur."""
            if mode == "espece":
                if not caisse_id:
                    return refus({"detail": "Choisissez la caisse concernée."}, status=400)
                c = Caisse.objects.filter(id=caisse_id).first()
                if not c or str(c.societe_id) != str(societe_id):
                    return refus({"detail": "Caisse invalide pour cette société."},
                                 status=400)
                s = _session_ouverte(c.id)
                if not s:
                    return refus({"detail": f"Ouvrez la caisse « {c.libelle} »."},
                                 status=409)
                return c.compte_comptable, c, s
            return comptabilite._compte("compte_banque", societe_id), None, None

        with transaction.atomic():
            res_a = _tresorerie(fac_a.societe_id, payload.get("acheteur_mode", "banque"),
                                payload.get("acheteur_caisse_id"))
            if isinstance(res_a, Response):
                return res_a
            cpt_a, caisse_a, sess_a = res_a
            res_v = _tresorerie(fac_v.societe_id, payload.get("vendeur_mode", "banque"),
                                payload.get("vendeur_caisse_id"))
            if isinstance(res_v, Response):
                return res_v
            cpt_v, caisse_v, sess_v = res_v

            # Côté acheteur : D 401 (fournisseur lié) / C trésorerie
            ecr_a = comptabilite.post_ecriture(
                fac_a.societe_id, "TR", "Trésorerie", "tresorerie", jour, ref,
                [{"sens": "D",
                  "compte": comptabilite._compte("compte_fournisseur", fac_a.societe_id),
                  "montant_usd": montant, "tiers_id": tiers_fourn.id,
                  "libelle": f"Règlement {fac_a.numero} — {tiers_fourn.nom}"},
                 {"sens": "C", "compte": cpt_a, "montant_usd": montant, "libelle": ref}],
                "reglement_intersociete", "facture", fac_a.id, fac_a.numero,
                request.user.id, statut="en_attente")
            # Côté vendeur : D trésorerie / C 411 (client lié)
            ecr_v = comptabilite.post_ecriture(
                fac_v.societe_id, "TR", "Trésorerie", "tresorerie", jour, ref,
                [{"sens": "D", "compte": cpt_v, "montant_usd": montant, "libelle": ref},
                 {"sens": "C",
                  "compte": comptabilite._compte("compte_client", fac_v.societe_id),
                  "montant_usd": montant, "tiers_id": tiers_client.id,
                  "libelle": f"Règlement {fac_v.numero} — {tiers_client.nom}"}],
                "reglement_intersociete", "facture", fac_v.id, fac_v.numero,
                request.user.id, statut="en_attente")

            for fac, mode in ((fac_v, payload.get("vendeur_mode", "banque")),
                              (fac_a, payload.get("acheteur_mode", "banque"))):
                PaiementFacture.objects.create(
                    facture_id=fac.id, mode=mode, devise="USD",
                    montant=montant, montant_usd=montant, reference=ref,
                    compte=cpt_v if fac is fac_v else cpt_a)
            if caisse_a:
                MouvementCaisse.objects.create(
                    caisse_id=caisse_a.id, session_id=sess_a.id,
                    numero=services.next_numero("bon_caisse", jour.year, soc_a.code,
                                                soc_a.id),
                    reference=fac_a.numero, sens="sortie",
                    nature="Règlement intersociété", devise="USD",
                    montant=montant, montant_usd=montant, tiers_id=tiers_fourn.id,
                    tiers_nom=tiers_fourn.nom, reference_type="facture",
                    reference_id=fac_a.id, libelle=ref, created_by=request.user.id,
                    date_mouvement=services.maintenant().date(), heure=services.maintenant())
            if caisse_v:
                MouvementCaisse.objects.create(
                    caisse_id=caisse_v.id, session_id=sess_v.id,
                    numero=services.next_numero("bon_caisse", jour.year, soc_v.code,
                                                soc_v.id),
                    reference=fac_v.numero, sens="entree",
                    nature="Règlement intersociété", devise="USD",
                    montant=montant, montant_usd=montant, tiers_id=tiers_client.id,
                    tiers_nom=tiers_client.nom, reference_type="facture",
                    reference_id=fac_v.id, libelle=ref, created_by=request.user.id,
                    date_mouvement=services.maintenant().date(), heure=services.maintenant())

            services.enregistrer_audit(request.user.id, "REGLEMENT_INTER", "facture",
                                       fac_v.id, None,
                                       {"montant_usd": montant, "vendeur": soc_v.code,
                                        "acheteur": soc_a.code})
        return Response({"ecriture_vendeur": ecr_v.numero,
                         "ecriture_acheteur": ecr_a.numero,
                         **_reglement_facture(fac_v)}, status=201)


# Anciens points d’entrée conservés pour les intégrations existantes.
receptionner_po = CommandeViewSet.as_view({'post': 'receptionner'}, http_method_names=['post', 'options'], detail=True, basename='commande')
reception_detail_ou_annulation = ReceptionViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}, http_method_names=['get', 'delete', 'options'], detail=True, basename='reception')
receptions_intersociete = ReceptionViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='reception')
confirmer_reception = ReceptionViewSet.as_view({'post': 'confirmer'}, http_method_names=['post', 'options'], detail=True, basename='reception')
tracer = GroupeViewSet.as_view({'get': 'tracer'}, http_method_names=['get', 'options'], detail=False, basename='groupe')
badges = GroupeViewSet.as_view({'get': 'badges'}, http_method_names=['get', 'options'], detail=False, basename='groupe')
liaisons = GroupeViewSet.as_view({'get': 'liaisons'}, http_method_names=['get', 'options'], detail=False, basename='groupe')
lier_tiers = GroupeViewSet.as_view({'post': 'lier'}, http_method_names=['post', 'options'], detail=False, basename='groupe')
positions = GroupeViewSet.as_view({'get': 'positions'}, http_method_names=['get', 'options'], detail=False, basename='groupe')
factures_intragroupe = FactureViewSet.as_view({'get': 'list'}, http_method_names=['get', 'options'], detail=False, basename='facture')
regler_intersociete = FactureViewSet.as_view({'post': 'regler'}, http_method_names=['post', 'options'], detail=True, basename='facture')
