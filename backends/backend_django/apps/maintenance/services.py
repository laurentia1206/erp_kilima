"""Module Maintenance — usage réel des véhicules et échéances d'entretien.

Le métier maintenance est séparé du dispatching : ce module puise l'usage
dans les modules opérationnels sans les modifier :
- engins de location : heures prestées (fiches de prestation, arrondi 5 min)
  et dernier index compteur relevé ;
- camions : courses effectuées et heures de route (départ → retour).

L'échéance d'un plan d'entretien = usage consommé depuis la dernière
exécution vs la périodicité (heures, courses ou jours).
"""
from __future__ import annotations

from datetime import date

from apps.engins import services as engins_lib
from apps.transport.models import Course
from apps.maintenance.models import InterventionCamion, PlanEntretien
from apps.engins.models import PrestationEngin

SEUIL_BIENTOT = 80  # % de la périodicité à partir duquel on alerte


def usage_engin(engin, mode: str) -> dict:
    """Heures prestées cumulées + dernier index compteur d'un engin."""
    prestations = list(PrestationEngin.objects.filter(engin_id=engin.id))
    arrets = engins_lib.arrets_par_prestation([p.id for p in prestations])
    minutes = sum(engins_lib.minutes_prestation(p, arrets.get(p.id, []), mode)
                  for p in prestations)
    dernier_index = None
    for p in sorted(prestations, key=lambda x: (x.date_prestation, x.poste)):
        if p.index_fin is not None:
            dernier_index = float(p.index_fin)
    return {"heures": round(minutes / 60, 1), "courses": None,
            "fiches": len(prestations), "dernier_index": dernier_index}


def usage_camion(camion) -> dict:
    """Courses effectuées, heures de route et km parcourus d'un camion."""
    courses = (Course.objects.filter(camion_id=camion.id,
                                     heure_depart__isnull=False)
               .exclude(statut="annulee"))
    heures = km = 0.0
    n = 0
    dernier_km = None
    for c in courses.order_by("date_course"):
        n += 1
        if c.heure_retour:
            heures += (c.heure_retour - c.heure_depart).total_seconds() / 3600
        if c.km_depart is not None and c.km_retour is not None:
            km += max(0.0, float(c.km_retour) - float(c.km_depart))
        if c.km_retour is not None:
            dernier_km = float(c.km_retour)
    return {"heures": round(heures, 1), "courses": n, "km": round(km, 1),
            "fiches": n, "dernier_index": dernier_km}


def etat_plan(plan: PlanEntretien, usage: dict) -> dict:
    """Consommation du plan depuis la dernière exécution → ok/bientot/echu."""
    periode = float(plan.periodicite_valeur or 0) or 1.0
    if plan.periodicite_type == "jours":
        depart = plan.derniere_date or \
            (plan.created_at.date() if plan.created_at else date.today())
        consomme = max(0, (date.today() - depart).days)
        unite = "j"
    else:
        courant = usage.get(plan.periodicite_type) or 0.0
        consomme = round(max(0.0, float(courant) - float(plan.derniere_valeur or 0)), 1)
        unite = {"heures": "h", "courses": "courses", "km": "km"}.get(
            plan.periodicite_type, plan.periodicite_type)
    pct = round(consomme / periode * 100, 1)
    statut = "echu" if consomme >= periode else \
        ("bientot" if pct >= SEUIL_BIENTOT else "ok")
    intervention = (InterventionCamion.objects.filter(plan_id=plan.id)
                    .exclude(statut="terminee").order_by("-date_signalement").first())
    return {"consomme": consomme, "periode": periode, "pct": min(pct, 100.0),
            "restant": round(periode - consomme, 1), "unite": unite,
            "statut": statut,
            "intervention_ouverte": intervention.numero if intervention else None,
            "intervention_ouverte_id": str(intervention.id) if intervention else None}


def valeur_compteur(plan: PlanEntretien, usage: dict):
    """Valeur du compteur d'usage au moment présent, pour figer la
    « dernière exécution » quand l'intervention liée au plan est clôturée."""
    if plan.periodicite_type == "jours":
        return None
    return usage.get(plan.periodicite_type) or 0.0


def plan_dict(plan: PlanEntretien, usage: dict, nom_vehicule: str | None = None) -> dict:
    return {"id": str(plan.id), "libelle": plan.libelle,
            "camion_id": str(plan.camion_id) if plan.camion_id else None,
            "engin_id": str(plan.engin_id) if plan.engin_id else None,
            "vehicule": nom_vehicule,
            "periodicite_type": plan.periodicite_type,
            "periodicite_valeur": float(plan.periodicite_valeur),
            "derniere_date": plan.derniere_date.isoformat()
            if plan.derniere_date else None,
            "derniere_valeur": float(plan.derniere_valeur)
            if plan.derniere_valeur is not None else None,
            "note": plan.note, "actif": bool(plan.actif),
            "etat": etat_plan(plan, usage)}
