"""Module Maintenance — le métier du maintenancier, séparé du dispatching.

Vue transversale du parc (camions du transport + engins de location) avec
l'usage réel tiré des modules opérationnels, plans d'entretien préventif
périodiques (heures / courses / jours) et planification des interventions.
Les interventions elles-mêmes restent la table mutualisée
`intervention_camion` (endpoints /transport/interventions).
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.maintenance.models import PlanEntretien
from apps.maintenance.serializers import PlanEntretienSerializer

from datetime import date

from django.db import transaction
from rest_framework.response import Response

from apps.engins import services as engins_lib
from apps.maintenance import services as maintenance_lib
from core import services as services
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.transport.models import Camion
from apps.engins.models import Engin
from apps.maintenance.models import InterventionCamion, PlanEntretien
from core.models import Societe
from core.views import _societe_param

# Le maintenancier + la direction technique et financière. Le DISPATCHER
# n'y figure pas : séparation voulue des métiers dispatch / maintenance.
ROLES = {"MAINTENANCIER", "DT", "ASSISTANT_TECHNIQUE", "ASSISTANT_TECH",
         "COMPTABLE", "DFI", "DG"}


def _acces(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES)
    return roles


def _vehicule_du_plan(plan: PlanEntretien):
    if plan.camion_id:
        cam = Camion.objects.filter(id=plan.camion_id).first()
        return cam, "camion", (cam.immatriculation if cam else None)
    eng = Engin.objects.filter(id=plan.engin_id).first()
    return eng, "engin", (eng.nom if eng else None)


def _usage(vehicule, genre: str, mode: str) -> dict:
    return maintenance_lib.usage_camion(vehicule) if genre == "camion" \
        else maintenance_lib.usage_engin(vehicule, mode)


class ParcViewSet(MetierViewSet):
    """Ressource Parc ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def parc(self, request):
        """Le parc complet de la société avec usage, plans et alertes."""
        sid = _societe_param(request)
        _acces(request, sid)
        mode = engins_lib.reglages(sid)["arrondi"]
        plans = list(PlanEntretien.objects.filter(societe_id=sid, actif=True))
        ouvertes = {}
        for i in InterventionCamion.objects.filter(societe_id=sid) \
                .exclude(statut="terminee"):
            cle = ("camion", i.camion_id) if i.camion_id else ("engin", i.engin_id)
            ouvertes[cle] = ouvertes.get(cle, 0) + 1

        vehicules = []
        alertes = {"echu": 0, "bientot": 0}
        ensembles = [("camion", Camion.objects.filter(societe_id=sid, actif=True)
                      .order_by("immatriculation")),
                     ("engin", Engin.objects.filter(societe_id=sid, actif=True)
                      .order_by("nom"))]
        # Dernière intervention terminée de chaque véhicule : point de départ
        # du suivi « usage depuis le dernier entretien exécuté ».
        dernieres = {}
        for i in InterventionCamion.objects.filter(
                societe_id=sid, statut="terminee",
                date_fin__isnull=False).order_by("date_fin"):
            cle = ("camion", i.camion_id) if i.camion_id else ("engin", i.engin_id)
            dernieres[cle] = i.date_fin

        for genre, queryset in ensembles:
            for v in queryset:
                usage = _usage(v, genre, mode)
                derniere = dernieres.get((genre, v.id))
                depuis = None
                if derniere:
                    brut = (maintenance_lib.usage_camion(v, depuis=derniere)
                            if genre == "camion"
                            else maintenance_lib.usage_engin(v, mode,
                                                             depuis=derniere))
                    depuis = {"date": derniere.isoformat(),
                              "heures": brut["heures"],
                              "km": brut.get("km"),
                              "courses": brut.get("courses")}
                mes_plans = [p for p in plans
                             if (p.camion_id if genre == "camion" else p.engin_id) == v.id]
                dicts = [maintenance_lib.plan_dict(p, usage) for p in mes_plans]
                for d in dicts:
                    if d["etat"]["statut"] in alertes:
                        alertes[d["etat"]["statut"]] += 1
                vehicules.append({
                    "type": genre, "id": str(v.id),
                    "nom": v.immatriculation if genre == "camion" else v.nom,
                    "detail": (v.marque if genre == "camion" else v.categorie) or None,
                    "statut": v.statut,
                    "motif_immobilisation": v.motif_immobilisation,
                    "usage": usage,
                    "depuis_entretien": depuis,
                    "interventions_ouvertes": ouvertes.get((genre, v.id), 0),
                    "plans": dicts})
        return Response({"vehicules": vehicules, "alertes": alertes})


class PlanEntretienViewSet(MetierModelViewSet):
    """Ressource PlanEntretien ; contrats HTTP et validations métier conservés."""
    queryset = PlanEntretien.objects.none()
    serializer_class = PlanEntretienSerializer
    lookup_url_kwarg = 'plan_id'

    def list(self, request):
        return self._traiter_plans(request)


    def create(self, request):
        return self._traiter_plans(request)


    def _traiter_plans(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method == "POST":
            payload = request.data or {}
            cam = eng = None
            if payload.get("engin_id"):
                eng = Engin.objects.filter(id=payload["engin_id"]).first()
                if not eng or str(eng.societe_id) != str(sid):
                    return refus({"detail": "Engin invalide."}, status=400)
            else:
                cam = Camion.objects.filter(id=payload.get("camion_id")).first()
                if not cam or str(cam.societe_id) != str(sid):
                    return refus({"detail": "Camion invalide."}, status=400)
            libelle = (payload.get("libelle") or "").strip()
            if len(libelle) < 3:
                return refus({"detail": "libelle requis."}, status=422)
            ptype = payload.get("periodicite_type", "heures")
            if ptype not in ("heures", "courses", "km", "jours"):
                return refus({"detail": "periodicite_type : heures, courses, km "
                                        "ou jours."}, status=422)
            if ptype in ("courses", "km") and not cam:
                return refus({"detail": f"La périodicité en {ptype} ne vaut que pour "
                                        f"un camion."}, status=422)
            try:
                valeur = float(payload.get("periodicite_valeur"))
                if valeur <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return refus({"detail": "periodicite_valeur invalide."}, status=422)
            mode = engins_lib.reglages(sid)["arrondi"]
            vehicule, genre = (cam, "camion") if cam else (eng, "engin")
            usage = _usage(vehicule, genre, mode)
            with transaction.atomic():
                p = PlanEntretien.objects.create(
                    societe_id=sid,
                    camion_id=cam.id if cam else None,
                    engin_id=eng.id if eng else None,
                    libelle=libelle, periodicite_type=ptype,
                    periodicite_valeur=valeur,
                    # le compteur démarre à l'usage actuel : on n'exige pas un
                    # entretien immédiat pour un véhicule qui a déjà roulé
                    derniere_date=date.today(),
                    derniere_valeur=None if ptype == "jours"
                    else (usage.get(ptype) or 0.0),
                    note=(payload.get("note") or "").strip() or None,
                    created_by=request.user.id, created_at=services.maintenant())
                services.enregistrer_audit(request.user.id, "INSERT", "plan_entretien",
                                           p.id, None, {"libelle": libelle,
                                                        "periodicite": f"{valeur} {ptype}"})
            nom = vehicule.immatriculation if genre == "camion" else vehicule.nom
            return Response(maintenance_lib.plan_dict(p, usage, nom), status=201)
        mode = engins_lib.reglages(sid)["arrondi"]
        out = []
        for p in PlanEntretien.objects.filter(societe_id=sid).order_by("libelle"):
            vehicule, genre, nom = _vehicule_du_plan(p)
            usage = _usage(vehicule, genre, mode) if vehicule else {}
            out.append(maintenance_lib.plan_dict(p, usage, nom))
        return Response(out)


    def partial_update(self, request, plan_id):
        return self._traiter_maj_plan(request, plan_id)


    def destroy(self, request, plan_id):
        return self._traiter_maj_plan(request, plan_id)


    def _traiter_maj_plan(self, request, plan_id):
        p = PlanEntretien.objects.filter(id=plan_id).first()
        if not p:
            return refus({"detail": "Plan introuvable."}, status=404)
        _acces(request, p.societe_id)
        if request.method == "DELETE":
            with transaction.atomic():
                services.enregistrer_audit(request.user.id, "DELETE", "plan_entretien",
                                           p.id, {"libelle": p.libelle}, None)
                p.delete()
            return Response({"ok": True})
        payload = request.data or {}
        if "libelle" in payload:
            libelle = (payload["libelle"] or "").strip()
            if len(libelle) < 3:
                return refus({"detail": "libelle requis."}, status=422)
            p.libelle = libelle
        if "periodicite_valeur" in payload:
            try:
                valeur = float(payload["periodicite_valeur"])
                if valeur <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return refus({"detail": "periodicite_valeur invalide."}, status=422)
            p.periodicite_valeur = valeur
        if "note" in payload:
            p.note = (payload["note"] or "").strip() or None
        if "actif" in payload:
            p.actif = bool(payload["actif"])
        with transaction.atomic():
            p.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "plan_entretien",
                                       p.id, None, {"libelle": p.libelle})
        vehicule, genre, nom = _vehicule_du_plan(p)
        mode = engins_lib.reglages(p.societe_id)["arrondi"]
        usage = _usage(vehicule, genre, mode) if vehicule else {}
        return Response(maintenance_lib.plan_dict(p, usage, nom))


    @action(detail=True, methods=['post'])
    def planifier(self, request, plan_id):
        """Crée l'intervention d'entretien du plan (planifiée si date future)."""
        p = PlanEntretien.objects.filter(id=plan_id).first()
        if not p:
            return refus({"detail": "Plan introuvable."}, status=404)
        _acces(request, p.societe_id)
        deja = (InterventionCamion.objects.filter(plan_id=p.id)
                .exclude(statut="terminee").first())
        if deja:
            return refus({"detail": f"Une intervention est déjà ouverte pour ce plan "
                                    f"({deja.numero})."}, status=409)
        vehicule, genre, nom = _vehicule_du_plan(p)
        if not vehicule:
            return refus({"detail": "Véhicule introuvable."}, status=404)
        payload = request.data or {}
        date_prevue = None
        if payload.get("date_prevue"):
            try:
                date_prevue = date.fromisoformat(payload["date_prevue"])
            except ValueError:
                return refus({"detail": "date_prevue invalide."}, status=422)
        planifiee = bool(date_prevue and date_prevue > date.today())
        immobilise = payload.get("immobilise", True)
        if immobilise and not planifiee and genre == "camion" \
                and vehicule.statut == "en_course":
            return refus({"detail": f"{nom} est en course — clôturez la course avant "
                                    f"d'immobiliser, ou planifiez à une date future."},
                         status=409)
        societe = Societe.objects.filter(id=p.societe_id).first()
        with transaction.atomic():
            i = InterventionCamion.objects.create(
                societe_id=p.societe_id,
                camion_id=p.camion_id, engin_id=p.engin_id,
                numero=services.next_numero("intervention", date.today().year,
                                            societe.code, societe.id),
                type="entretien", description=p.libelle,
                prestataire=(payload.get("prestataire") or "").strip() or None,
                cout_estime=payload.get("cout_estime"),
                immobilise=immobilise,
                date_signalement=date.today(), date_prevue=date_prevue,
                plan_id=p.id,
                statut="planifiee" if planifiee else "en_cours",
                created_by=request.user.id, created_at=services.maintenant())
            if immobilise and not planifiee:
                vehicule.statut = "immobilise"
                vehicule.motif_immobilisation = f"entretien — {p.libelle[:80]}"
                vehicule.immobilise_depuis = date.today()
                vehicule.save(update_fields=["statut", "motif_immobilisation",
                                             "immobilise_depuis"])
            services.enregistrer_audit(request.user.id, "INSERT", "intervention", i.id,
                                       None, {"plan": p.libelle, "vehicule": nom,
                                              "statut": i.statut})
        return Response({"id": str(i.id), "numero": i.numero, "statut": i.statut,
                         "vehicule": nom, "date_prevue":
                         date_prevue.isoformat() if date_prevue else None}, status=201)


# ═══ Pièces de rechange : réquisition d'achat ou bon de consommation ═══

def _bon_dict(b, depots=None, interventions=None) -> dict:
    depot = (depots or {}).get(b.depot_id)
    inter = (interventions or {}).get(b.intervention_id) if b.intervention_id else None
    return {"id": str(b.id), "numero": b.numero,
            "date": b.created_at.date().isoformat() if b.created_at else None,
            "depot": depot, "motif": b.motif,
            "intervention": inter,
            "lignes": b.lignes, "total_usd": float(b.total_usd or 0)}


class PiecesInterventionViewSet(MetierViewSet):
    """Pièces de rechange d'une intervention : demande d'achat (réquisition)
    ou sortie du stock (bon de consommation remis au gestionnaire)."""

    @action(detail=True, methods=['post'])
    def requisition(self, request, intervention_id):
        'Génère la réquisition d\'achat des pièces et la lie à l\'intervention\n    (son avancement et ses dépenses justifiées alimentent le coût réel).'
        from apps.approbations.models import Requisition, RequisitionLigne
        from core import domain as domain
        from apps.maintenance.models import InterventionRequisition
        i = InterventionCamion.objects.filter(id=intervention_id).first()
        if not i:
            return refus({"detail": "Intervention introuvable."}, status=404)
        _acces(request, i.societe_id)
        if i.statut == "terminee":
            return refus({"detail": "Intervention terminée."}, status=409)
        lignes = (request.data or {}).get("lignes") or []
        if not isinstance(lignes, list) or not lignes:
            return refus({"detail": "Ajoutez au moins une pièce."}, status=422)
        propres = []
        for l in lignes:
            description = str((l or {}).get("description") or "").strip()
            if len(description) < 2:
                return refus({"detail": "Chaque pièce doit être décrite."},
                             status=422)
            try:
                qte = float(l.get("quantite") or 1)
                pu = float(l.get("prix_unitaire") or 0)
            except (TypeError, ValueError):
                return refus({"detail": f"Quantité ou prix invalide "
                                        f"({description})."}, status=422)
            if qte <= 0 or pu < 0:
                return refus({"detail": f"Quantité ou prix invalide "
                                        f"({description})."}, status=422)
            propres.append((description, qte, pu))
        from apps.transport.views import _cible_intervention
        _v, _g, libelle = _cible_intervention(i)
        societe = Societe.objects.filter(id=i.societe_id).first()
        jour = date.today()
        with transaction.atomic():
            numero = services.next_numero("requisition", jour.year, societe.code,
                                          societe.id)
            req = Requisition.objects.create(
                numero=numero, societe_id=i.societe_id,
                initiateur_id=request.user.id,
                objet=f"Pièces de rechange — {i.numero} ({libelle or 'véhicule'})",
                justification=i.description[:500],
                mode_decaissement=(request.data or {}).get("mode_decaissement")
                if (request.data or {}).get("mode_decaissement")
                in ("avance", "paiement_direct") else "avance",
                nature="charge", priorite="urgent"
                if i.priorite in ("haute", "urgente") else "normal",
                devise="USD", statut="soumise",
                date_requisition=services.maintenant().date(),
                created_at=services.maintenant())
            total = domain.quantize(0)
            for ordre, (description, qte, pu) in enumerate(propres):
                montant = domain.quantize(domain.quantize(qte) * domain.quantize(pu))
                total += montant
                RequisitionLigne.objects.create(
                    requisition_id=req.id, ordre=ordre, description=description,
                    quantite=qte, prix_unitaire=pu, montant=montant,
                    devise="USD", montant_usd=montant)
            req.montant_total = total
            req.montant_total_usd = total
            req.save(update_fields=["montant_total", "montant_total_usd"])
            InterventionRequisition.objects.create(
                intervention_id=i.id, requisition_id=req.id,
                created_at=services.maintenant())
            if not i.requisition_id:
                i.requisition_id = req.id
                i.save(update_fields=["requisition_id"])
            services.enregistrer_audit(request.user.id, "INSERT", "requisition",
                                       req.id, None,
                                       {"numero": numero, "module": "maintenance",
                                        "intervention": i.numero,
                                        "montant_usd": float(total)})
        return Response({"requisition": {"id": str(req.id), "numero": numero,
                                         "montant_usd": float(total)}},
                        status=201)


    @action(detail=True, methods=['post'])
    def consommer(self, request, intervention_id):
        'Sort les pièces du stock (bon de consommation) : le stock est\n    décrémenté au coût moyen, l\'écriture D entretien / C stock est passée,\n    et le bon s\'imprime pour le gestionnaire de stock.'
        from apps.comptabilite import services as comptabilite
        from apps.groupe import services as intersociete_lib
        from apps.maintenance.models import BonConsommationStock
        from apps.stocks import services as stock_lib
        from apps.stocks.models import Article, Depot
        i = InterventionCamion.objects.filter(id=intervention_id).first()
        if not i:
            return refus({"detail": "Intervention introuvable."}, status=404)
        _acces(request, i.societe_id)
        if i.statut == "terminee":
            return refus({"detail": "Intervention terminée."}, status=409)
        sid = i.societe_id
        payload = request.data or {}
        if payload.get("depot_id"):
            depot = Depot.objects.filter(id=payload["depot_id"]).first()
            if not depot or str(depot.societe_id) != str(sid):
                return refus({"detail": "Dépôt invalide."}, status=400)
        else:
            depot = stock_lib.depot_central(sid)
        lignes = payload.get("lignes") or []
        if not isinstance(lignes, list) or not lignes:
            return refus({"detail": "Ajoutez au moins une pièce du stock."},
                         status=422)
        demandes = []
        for l in lignes:
            art = Article.objects.filter(id=(l or {}).get("article_id")).first()
            if not art or str(art.societe_id) != str(sid) or not art.gere_stock:
                return refus({"detail": "Article de stock invalide."}, status=400)
            try:
                qte = float(l.get("qte"))
            except (TypeError, ValueError):
                return refus({"detail": f"Quantité invalide ({art.code})."},
                             status=422)
            if qte <= 0:
                return refus({"detail": f"Quantité invalide ({art.code})."},
                             status=422)
            dispo = stock_lib.qte_disponible(depot.id, art.id)
            if qte > dispo + 1e-6:
                return refus({"detail": f"Stock insuffisant pour {art.code} — "
                                        f"{art.designation} : {dispo:g} "
                                        f"{art.unite or ''} au dépôt "
                                        f"« {depot.libelle} », {qte:g} "
                                        f"demandé(s). Faites plutôt une demande "
                                        f"d'achat (réquisition)."}, status=409)
            demandes.append((art, qte))
        societe = Societe.objects.filter(id=sid).first()
        jour = date.today()
        with transaction.atomic():
            numero = services.next_numero("bon_consommation", jour.year,
                                          societe.code, societe.id)
            stock_par_compte: dict = {}
            lignes_bon = []
            total = 0.0
            for art, qte in demandes:
                valeur = stock_lib.sortie(art, depot, qte,
                                          "consommation_maintenance", numero,
                                          jour=jour)
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + valeur, 2)
                total = round(total + valeur, 2)
                lignes_bon.append({"article_id": str(art.id), "code": art.code,
                                   "designation": art.designation,
                                   "qte": qte, "unite": art.unite,
                                   "cout_usd": round(valeur, 2)})
            bon = BonConsommationStock.objects.create(
                societe_id=sid, numero=numero, depot_id=depot.id,
                intervention_id=i.id,
                motif=f"Pièces — {i.numero} — {i.description[:120]}",
                lignes=lignes_bon, total_usd=total,
                created_by=request.user.id, created_at=services.maintenant())
            compte = comptabilite._compte_cree(
                "compte_entretien", sid,
                "Entretien, réparations et maintenance")
            comptabilite.comptabiliser_stock_sortie(
                sid, stock_par_compte, numero, jour, "bon_consommation", bon.id,
                request.user.id,
                statut=intersociete_lib._statut_piece(sid, "achat"),
                compte_debit=compte,
                libelle_debit=f"Pièces maintenance {i.numero}")
            i.cout_pieces = round(float(i.cout_pieces or 0) + total, 2)
            i.save(update_fields=["cout_pieces"])
            services.enregistrer_audit(request.user.id, "INSERT",
                                       "bon_consommation_stock", bon.id, None,
                                       {"numero": numero, "intervention": i.numero,
                                        "total_usd": total})
        return Response({"bon": _bon_dict(bon, {depot.id: depot.libelle},
                                          {i.id: i.numero})}, status=201)


    @action(detail=False, methods=['get'])
    def bons(self, request):
        'Journal des bons de consommation de stock (pour le gestionnaire).'
        from apps.maintenance.models import BonConsommationStock
        from apps.stocks.models import Depot
        sid = _societe_param(request)
        _acces(request, sid)
        q = BonConsommationStock.objects.filter(societe_id=sid)
        du, au = request.query_params.get("du"), request.query_params.get("au")
        if du:
            q = q.filter(created_at__date__gte=du)
        if au:
            q = q.filter(created_at__date__lte=au)
        bons = list(q.order_by("-created_at")[:300])
        depots = {d.id: d.libelle for d in Depot.objects.filter(societe_id=sid)}
        inters = {x.id: x.numero for x in InterventionCamion.objects.filter(
            id__in=[b.intervention_id for b in bons if b.intervention_id])}
        return Response([_bon_dict(b, depots, inters) for b in bons])


# Anciens points d’entrée conservés pour les intégrations existantes.
parc = ParcViewSet.as_view({'get': 'parc'}, http_method_names=['get', 'options'], detail=False, basename='parc')
plans = PlanEntretienViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='plan_entretien')
maj_plan = PlanEntretienViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='plan_entretien')
planifier = PlanEntretienViewSet.as_view({'post': 'planifier'}, http_method_names=['post', 'options'], detail=True, basename='plan_entretien')
