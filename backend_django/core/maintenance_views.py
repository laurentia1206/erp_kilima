"""Module Maintenance — le métier du maintenancier, séparé du dispatching.

Vue transversale du parc (camions du transport + engins de location) avec
l'usage réel tiré des modules opérationnels, plans d'entretien préventif
périodiques (heures / courses / jours) et planification des interventions.
Les interventions elles-mêmes restent la table mutualisée
`intervention_camion` (endpoints /transport/interventions).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import engins_lib, maintenance_lib, services
from .auth import assert_acces_societe, assert_role
from .erreurs import refus
from .models import Camion, Engin, InterventionCamion, PlanEntretien, Societe
from .views import _societe_param

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


@api_view(["GET"])
def parc(request):
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
    for genre, queryset in ensembles:
        for v in queryset:
            usage = _usage(v, genre, mode)
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
                "interventions_ouvertes": ouvertes.get((genre, v.id), 0),
                "plans": dicts})
    return Response({"vehicules": vehicules, "alertes": alertes})


@api_view(["GET", "POST"])
def plans(request):
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


@api_view(["PATCH", "DELETE"])
def maj_plan(request, plan_id):
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


@api_view(["POST"])
def planifier(request, plan_id):
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
