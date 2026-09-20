"""Location d'engins — règles de calcul des heures prestées.

Portage exact de l'application desktop « Horizon Prestations » :
- tout est compté en minutes ; net = durée brute - arrêts ;
- arrondi aux multiples de 5 minutes (paramètre engins.arrondi :
  nearest | down | up) appliqué au net et à toute conversion en nombre ;
- poste de nuit : fin <= début => passage au jour suivant (fin + 24 h) ;
- valeur « en nombre » = minutes arrondies / 60 (ex. 8h30 -> 8,50) —
  c'est la base de tous les calculs de facturation ;
- forfait mensuel (208 h par défaut, paramètre engins.forfait_mensuel_h) ;
  heures supplémentaires = max(0, total - forfait).
"""
from __future__ import annotations

import calendar
import re

from . import services
from .models import ArretPrestationEngin, Engin, PrestationEngin

_RE_HHMM = re.compile(r"^(\d{1,2})[h:.](\d{2})$", re.IGNORECASE)
_RE_H = re.compile(r"^(\d{1,2})$")


def parse_time(hhmm) -> int | None:
    """"HH:MM" / "8h30" / "8" -> minutes depuis minuit, None si invalide."""
    if not hhmm:
        return None
    s = str(hhmm).strip()
    m = _RE_HHMM.match(s) or _RE_H.match(s)
    if not m:
        return None
    h = int(m.group(1))
    mn = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
    if h > 23 or mn > 59:
        return None
    return h * 60 + mn


def duree(debut, fin) -> int:
    """Durée en minutes ; fin <= début => jour suivant (poste de nuit)."""
    d, f = parse_time(debut), parse_time(fin)
    if d is None or f is None:
        return 0
    return f - d if f > d else f + 1440 - d


def arrondir(minutes: float, mode: str) -> int:
    """Arrondi aux multiples de 5 minutes selon le réglage."""
    step = 5
    if mode == "down":
        return int(minutes // step) * step
    if mode == "up":
        return int(-(-minutes // step)) * step
    # Math.round de JS : ,5 arrondi vers le haut (round() Python fait
    # banker's rounding — on reproduit le comportement du desktop)
    return int((minutes / step) + 0.5) * step


def reglages(societe_id) -> dict:
    """Paramètres du module pour une société (valeurs desktop par défaut)."""
    return {
        "arrondi": services.get_parametre("engins.arrondi", societe_id, "nearest"),
        "forfait_mensuel_h": float(services.get_parametre(
            "engins.forfait_mensuel_h", societe_id, "208")),
        "rpe_prefix": services.get_parametre("engins.rpe_prefix", societe_id, "HRZ"),
        "locataire": services.get_parametre("engins.locataire", societe_id, ""),
    }


def minutes_prestation(p: PrestationEngin, arrets: list, mode: str) -> int:
    """Minutes nettes prestées : brut - arrêts, arrondi 5 min."""
    brut = duree(p.heure_debut, p.heure_fin)
    total_arrets = sum(duree(a.debut, a.fin) for a in arrets if a.debut and a.fin)
    return arrondir(max(0, brut - total_arrets), mode)


def fmt_hm(minutes) -> str:
    """480 -> "8h00" (affichage heures/minutes)."""
    if minutes is None:
        return "—"
    neg = minutes < 0
    m = abs(int(round(minutes)))
    return ("-" if neg else "") + f"{m // 60}h{m % 60:02d}"


def dec_val(minutes: int, mode: str) -> float:
    """Minutes -> heures décimales arrondies 5 min (base de facturation)."""
    return round(arrondir(minutes, mode) / 60, 2)


def arrets_par_prestation(prestation_ids) -> dict:
    """Précharge les arrêts : {prestation_id: [ArretPrestationEngin]}."""
    out: dict = {}
    for a in ArretPrestationEngin.objects.filter(prestation_id__in=prestation_ids):
        out.setdefault(a.prestation_id, []).append(a)
    return out


def synthese_mois(societe_id, ym: str) -> dict:
    """Synthèse mensuelle par engin : minutes jour/nuit/total, forfait, supp.

    ym au format "YYYY-MM". Retourne {"reglages", "rows": [{engin, min_jour,
    min_nuit, min_total, forfait_min, supp_min}]} — engins actifs seulement.
    """
    reg = reglages(societe_id)
    mode = reg["arrondi"]
    annee, mois = int(ym[:4]), int(ym[5:7])
    dernier = calendar.monthrange(annee, mois)[1]
    du, au = f"{ym}-01", f"{ym}-{dernier:02d}"

    prestations = list(PrestationEngin.objects.filter(
        societe_id=societe_id, date_prestation__gte=du, date_prestation__lte=au))
    arrets = arrets_par_prestation([p.id for p in prestations])

    par_engin: dict = {}
    for p in prestations:
        e = par_engin.setdefault(p.engin_id, {"jour": 0, "nuit": 0})
        e["nuit" if p.poste == "nuit" else "jour"] += \
            minutes_prestation(p, arrets.get(p.id, []), mode)

    forfait_min = int(reg["forfait_mensuel_h"] * 60)
    rows = []
    for engin in Engin.objects.filter(societe_id=societe_id, actif=True).order_by("nom"):
        mins = par_engin.get(engin.id, {"jour": 0, "nuit": 0})
        total = mins["jour"] + mins["nuit"]
        rows.append({
            "engin": engin,
            "min_jour": mins["jour"], "min_nuit": mins["nuit"], "min_total": total,
            "forfait_min": forfait_min,
            "supp_min": max(0, total - forfait_min),
        })
    return {"reglages": reg, "rows": rows}


def numero_rpe(ym: str, prefix: str) -> str:
    """Numéro RPE auto, format du desktop : HRZ07-0726 (préfixe + mois - mois + année)."""
    annee, mois = ym[:4], ym[5:7]
    return f"{prefix}{mois}-{mois}{annee[2:]}"
