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

from core import services as services
from apps.engins.models import (ArretPrestationEngin, Engin, HarmonisationEngin,
                                PrestationEngin, ReconciliationEngins)

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


def jours_du_mois(ym: str) -> list[str]:
    """Liste des dates ISO du mois "YYYY-MM"."""
    annee, mois = int(ym[:4]), int(ym[5:7])
    dernier = calendar.monthrange(annee, mois)[1]
    return [f"{ym}-{j:02d}" for j in range(1, dernier + 1)]


def grille_mois(societe_id, ym: str) -> dict:
    """Minutes brutes par engin/jour/poste : {engin_id: {date: {jour, nuit}}}."""
    mode = reglages(societe_id)["arrondi"]
    jours = jours_du_mois(ym)
    prestations = list(PrestationEngin.objects.filter(
        societe_id=societe_id, date_prestation__gte=jours[0],
        date_prestation__lte=jours[-1]))
    arrets = arrets_par_prestation([p.id for p in prestations])
    grille: dict = {}
    for p in prestations:
        g = grille.setdefault(p.engin_id, {})
        d = g.setdefault(p.date_prestation.isoformat(), {"jour": 0, "nuit": 0})
        d["nuit" if p.poste == "nuit" else "jour"] += \
            minutes_prestation(p, arrets.get(p.id, []), mode)
    return grille


def reconciliation_du_mois(societe_id, ym: str):
    """Fiche de réconciliation du mois, ou None."""
    return ReconciliationEngins.objects.filter(societe_id=societe_id, ym=ym).first()


def mois_verrouille(societe_id, ym: str) -> bool:
    """Un mois dont la réconciliation est validée n'accepte plus de saisie."""
    rec = reconciliation_du_mois(societe_id, ym)
    return bool(rec and rec.statut == "validee")


def _minutes_retenues(donnees_engin: dict, date_iso: str, brut: dict,
                      mode: str) -> dict:
    """Minutes retenues d'un jour : la valeur réconciliée si saisie, sinon la
    valeur brute de nos fiches (règle du desktop Horizon)."""
    d = (donnees_engin or {}).get(date_iso) or {}
    def _val(cle, defaut):
        v = d.get(cle)
        if v is None:
            return defaut
        try:
            return arrondir(max(0.0, float(v)), mode)
        except (TypeError, ValueError):
            return defaut
    return {"jour": _val("retenu_jour", brut["jour"]),
            "nuit": _val("retenu_nuit", brut["nuit"])}


def harmonisations_mois(societe_id, ym: str, statuts=("approuvee",)):
    """Transferts d'heures du mois, filtrés par statut."""
    return list(HarmonisationEngin.objects.filter(
        societe_id=societe_id, ym=ym, statut__in=list(statuts)))


def totaux_retenus(societe_id, ym: str, jusqu_au_jour: int | None = None) -> dict:
    """Minutes retenues par engin et par poste, AVANT harmonisations :
    {str(engin_id): {"jour", "nuit"}}. Les valeurs réconciliées remplacent
    les brutes jour par jour dès qu'elles existent. `jusqu_au_jour` limite
    le cumul aux N premiers jours du mois (rapport technique)."""
    mode = reglages(societe_id)["arrondi"]
    grille = grille_mois(societe_id, ym)
    jours = jours_du_mois(ym)
    if jusqu_au_jour is not None:
        jours = jours[:max(0, jusqu_au_jour)]
    rec = reconciliation_du_mois(societe_id, ym)
    donnees = rec.donnees if rec else {}
    grille_str = {str(k): v for k, v in grille.items()}
    out: dict = {}
    for cle in set(grille_str) | set(donnees):
        par_jour = grille_str.get(cle, {})
        donnees_engin = donnees.get(cle) or {}
        tot = {"jour": 0, "nuit": 0}
        for date_iso in jours:
            brut = par_jour.get(date_iso, {"jour": 0, "nuit": 0})
            v = _minutes_retenues(donnees_engin, date_iso, brut, mode)
            tot["jour"] += v["jour"]
            tot["nuit"] += v["nuit"]
        out[cle] = tot
    return out


def synthese_mois(societe_id, ym: str, reconciliee: bool = True) -> dict:
    """Synthèse mensuelle par engin : minutes jour/nuit/total, forfait, supp.

    ym au format "YYYY-MM". Avec reconciliee=True (défaut), les minutes
    retenues de la réconciliation remplacent nos saisies jour par jour dès
    qu'elles existent, puis les harmonisations APPROUVÉES déplacent les
    heures entre engins. Retourne {"reglages", "reconciliation", "rows":
    [{engin, min_jour, min_nuit, min_total, forfait_min, supp_min,
    harmonise_min}]} — engins actifs seulement.
    """
    reg = reglages(societe_id)
    mode = reg["arrondi"]
    rec = reconciliation_du_mois(societe_id, ym) if reconciliee else None

    # Toutes les clés en str(uuid) : le JSON de réconciliation est en texte.
    if rec:
        par_engin = totaux_retenus(societe_id, ym)
    else:
        par_engin = {}
        for engin_id, par_jour in grille_mois(societe_id, ym).items():
            tot = par_engin.setdefault(str(engin_id), {"jour": 0, "nuit": 0})
            for d in par_jour.values():
                tot["jour"] += d["jour"]
                tot["nuit"] += d["nuit"]

    # Harmonisations approuvées : des heures d'un engin passent à un autre.
    harmonise: dict = {}
    if reconciliee:
        for h in harmonisations_mois(societe_id, ym):
            poste = "nuit" if h.poste == "nuit" else "jour"
            src_cle, dst_cle = str(h.engin_source_id), str(h.engin_cible_id)
            src = par_engin.setdefault(src_cle, {"jour": 0, "nuit": 0})
            dst = par_engin.setdefault(dst_cle, {"jour": 0, "nuit": 0})
            src[poste] -= h.minutes
            dst[poste] += h.minutes
            harmonise[src_cle] = harmonise.get(src_cle, 0) - h.minutes
            harmonise[dst_cle] = harmonise.get(dst_cle, 0) + h.minutes

    forfait_min = int(reg["forfait_mensuel_h"] * 60)
    rows = []
    engins = list(Engin.objects.filter(societe_id=societe_id,
                                       actif=True).order_by("nom"))
    for engin in engins:
        mins = par_engin.get(str(engin.id), {"jour": 0, "nuit": 0})
        total = max(0, mins["jour"]) + max(0, mins["nuit"])
        rows.append({
            "engin": engin,
            "min_jour": max(0, mins["jour"]), "min_nuit": max(0, mins["nuit"]),
            "min_total": total,
            "forfait_min": forfait_min,
            "supp_min": max(0, total - forfait_min),
            "harmonise_min": harmonise.get(str(engin.id), 0),
        })
    return {"reglages": reg, "rows": rows, "reconciliation": rec}


def numero_rpe(ym: str, prefix: str) -> str:
    """Numéro RPE auto, format du desktop : HRZ07-0726 (préfixe + mois - mois + année)."""
    annee, mois = ym[:4], ym[5:7]
    return f"{prefix}{mois}-{mois}{annee[2:]}"
