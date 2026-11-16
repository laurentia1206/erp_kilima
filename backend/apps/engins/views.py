"""Module Location d'engins (ETS HORIZON) — parc, heures prestées, RPE,
facturation réelle.

Reprend les règles de l'application desktop « Horizon Prestations »
(engins_lib) : arrondi 5 min, poste de nuit à cheval sur minuit, arrêts
déduits, forfait mensuel 208 h, heures supplémentaires facturées au tarif
de l'engin. La facturation génère une vraie facture de vente (FV) avec
écriture comptable D 411 / C produit location / C TVA collectée.
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.engins.models import Engin
from apps.engins.serializers import EnginSerializer
from apps.engins.models import PrestationEngin
from apps.engins.serializers import PrestationEnginSerializer

from apps.stocks.catalogue import tiers_disponible

from datetime import date, timedelta

from django.db import transaction
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from apps.engins import services as engins_lib
from apps.groupe import services as intersociete_lib
from core import services as services
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.engins.models import (ArretPrestationEngin, Engin, HarmonisationEngin,
                                PrestationEngin, ReconciliationEngins)
from apps.commercial.models import Facture, LigneFacture
from apps.maintenance.models import InterventionCamion
from core.models import Parametre, Societe, Tiers, Utilisateur
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI", "ASSISTANT_TECH", "ASSISTANT_TECHNIQUE", "DT",
         "DISPATCHER", "DG"}
ROLES_CONFIG = {"DFI", "PRESIDENT", "ADMIN_SYS"}
# Réouverture d'un mois verrouillé : très haut niveau uniquement.
ROLES_REOUVERTURE = {"PRESIDENT", "DG", "ADMIN_SYS"}

CLES_CONFIG = {
    "engins.forfait_mensuel_h": ("number", "Forfait mensuel d'heures par engin"),
    "engins.arrondi": ("string", "Arrondi des heures (nearest | down | up)"),
    "engins.rpe_prefix": ("string", "Préfixe des numéros de RPE"),
    "engins.locataire": ("string", "Nom du locataire affiché sur les RPE"),
    "engins.roles_validation_reconciliation": (
        "string", "Rôles habilités à valider la réconciliation mensuelle "
                  "(codes séparés par des virgules)"),
}


def _roles_validation_reconciliation(sid) -> set:
    brut = services.get_parametre("engins.roles_validation_reconciliation",
                                  sid, "DT,DFI,DG")
    return {r.strip().upper() for r in str(brut).split(",") if r.strip()}


def _verrou_mois(sid, jour) -> object | None:
    """Refus 409 si le mois de `jour` est verrouillé par une réconciliation
    validée (seule la direction peut rouvrir)."""
    ym = jour.isoformat()[:7]
    if engins_lib.mois_verrouille(sid, ym):
        return refus({"detail": f"Mois {ym} verrouillé : la réconciliation a été "
                                f"validée. Toute correction exige une réouverture "
                                f"par la direction (PRESIDENT/DG), motivée et "
                                f"tracée."}, status=409)
    return None


def _acces(request, societe_id, roles_requis=ROLES):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, roles_requis)
    return roles


# ═══ Configuration ═══════════════════════════════════════════════════


# ═══ Parc d'engins ═══════════════════════════════════════════════════

def _engin_dict(e: Engin) -> dict:
    inter = (InterventionCamion.objects.filter(engin_id=e.id)
             .exclude(statut="terminee").order_by("date_signalement").first())
    return {"id": str(e.id), "nom": e.nom, "categorie": e.categorie,
            "immatriculation": e.immatriculation,
            "tarif_mensuel_usd": float(e.tarif_mensuel_usd or 0),
            "tarif_heure_supp_usd": float(e.tarif_heure_supp_usd or 0),
            "consommation_l_heure": float(e.consommation_l_heure)
            if e.consommation_l_heure is not None else None,
            "statut": e.statut,
            "motif_immobilisation": e.motif_immobilisation,
            "immobilise_depuis": e.immobilise_depuis.isoformat()
            if e.immobilise_depuis else None,
            "actif": bool(e.actif),
            "intervention_en_cours": inter.numero if inter else None}


class EnginViewSet(MetierModelViewSet):
    """Ressource Engin ; contrats HTTP et validations métier conservés."""
    queryset = Engin.objects.none()
    serializer_class = EnginSerializer
    lookup_url_kwarg = 'engin_id'

    def list(self, request):
        return self._traiter_engins(request)


    def create(self, request):
        return self._traiter_engins(request)


    def _traiter_engins(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method == "POST":
            payload = request.data or {}
            nom = (payload.get("nom") or "").strip()
            if len(nom) < 2:
                return refus({"detail": "nom requis."}, status=422)
            if Engin.objects.filter(societe_id=sid, nom__iexact=nom, actif=True).exists():
                return refus({"detail": f"L'engin « {nom} » existe déjà."}, status=409)
            with transaction.atomic():
                e = Engin.objects.create(
                    societe_id=sid, nom=nom,
                    categorie=(payload.get("categorie") or "").strip() or None,
                    immatriculation=(payload.get("immatriculation") or "").strip() or None,
                    tarif_mensuel_usd=payload.get("tarif_mensuel_usd") or 0,
                    tarif_heure_supp_usd=payload.get("tarif_heure_supp_usd") or 0,
                    consommation_l_heure=payload.get("consommation_l_heure") or None,
                    created_by=request.user.id, created_at=services.maintenant())
                services.enregistrer_audit(request.user.id, "INSERT", "engin", e.id,
                                           None, {"nom": nom})
            return Response(_engin_dict(e), status=201)
        q = Engin.objects.filter(societe_id=sid)
        if request.query_params.get("actifs") == "1":
            q = q.filter(actif=True)
        return Response([_engin_dict(e) for e in q.order_by("nom")])


    def partial_update(self, request, engin_id):
        e = Engin.objects.filter(id=engin_id).first()
        if not e:
            return refus({"detail": "Engin introuvable."}, status=404)
        _acces(request, e.societe_id)
        payload = request.data or {}
        avant = _engin_dict(e)
        for champ in ("nom", "categorie", "immatriculation"):
            if champ in payload:
                setattr(e, champ, (payload[champ] or "").strip() or None)
        if not e.nom:
            return refus({"detail": "nom requis."}, status=422)
        for champ in ("tarif_mensuel_usd", "tarif_heure_supp_usd"):
            if champ in payload:
                setattr(e, champ, payload[champ] or 0)
        if "consommation_l_heure" in payload:
            e.consommation_l_heure = payload["consommation_l_heure"] or None
        if "actif" in payload:
            e.actif = bool(payload["actif"])
        with transaction.atomic():
            e.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "engin", e.id,
                                       avant, _engin_dict(e))
        return Response(_engin_dict(e))


# ═══ Prestations (fiches de service) ═════════════════════════════════

def _prestation_dict(p: PrestationEngin, arrets=None, mode=None,
                     noms_engins=None) -> dict:
    if arrets is None:
        arrets = list(ArretPrestationEngin.objects.filter(prestation_id=p.id))
    if mode is None:
        mode = engins_lib.reglages(p.societe_id)["arrondi"]
    minutes = engins_lib.minutes_prestation(p, arrets, mode)
    brut = engins_lib.duree(p.heure_debut, p.heure_fin)
    total_arrets = sum(engins_lib.duree(a.debut, a.fin) for a in arrets)
    if noms_engins is not None:
        nom_engin = noms_engins.get(p.engin_id, "(engin supprimé)")
    else:
        e = Engin.objects.filter(id=p.engin_id).first()
        nom_engin = e.nom if e else "(engin supprimé)"
    index = (float(p.index_fin) - float(p.index_debut)
             if p.index_debut is not None and p.index_fin is not None else None)
    return {"id": str(p.id), "engin_id": str(p.engin_id), "engin": nom_engin,
            "date": p.date_prestation.isoformat(), "poste": p.poste,
            "operateur": p.operateur,
            "heure_debut": p.heure_debut, "heure_fin": p.heure_fin,
            "index_debut": float(p.index_debut) if p.index_debut is not None else None,
            "index_fin": float(p.index_fin) if p.index_fin is not None else None,
            "index_delta": round(index, 1) if index is not None else None,
            "affectation": p.affectation,
            "arrets": [{"nature": a.nature, "debut": a.debut, "fin": a.fin}
                       for a in arrets],
            "minutes_brutes": brut, "minutes_arrets": total_arrets,
            "minutes": minutes,
            "heures_hm": engins_lib.fmt_hm(minutes),
            "heures_dec": engins_lib.dec_val(minutes, mode)}


def _lire_prestation(payload, sid):
    """Validation commune création/modification. Retourne (champs, arrets, erreur)."""
    engin = Engin.objects.filter(id=payload.get("engin_id")).first()
    if not engin or str(engin.societe_id) != str(sid):
        return None, None, refus({"detail": "Engin invalide."}, status=400)
    jour = payload.get("date")
    try:
        jour = date.fromisoformat(jour)
    except (TypeError, ValueError):
        return None, None, refus({"detail": "date invalide."}, status=422)
    poste = payload.get("poste", "jour")
    if poste not in ("jour", "nuit"):
        return None, None, refus({"detail": "poste : jour ou nuit."}, status=422)
    debut, fin = payload.get("heure_debut"), payload.get("heure_fin")
    if engins_lib.duree(debut, fin) == 0:
        return None, None, refus(
            {"detail": "Heures de début et de fin invalides."}, status=422)
    arrets = []
    for a in payload.get("arrets") or []:
        if not (a.get("debut") and a.get("fin")):
            continue
        if engins_lib.duree(a["debut"], a["fin"]) == 0:
            return None, None, refus(
                {"detail": f"Arrêt invalide ({a.get('nature', '')})."}, status=422)
        arrets.append({"nature": (a.get("nature") or "Pause").strip()[:32],
                       "debut": a["debut"], "fin": a["fin"]})
    champs = {"engin_id": engin.id, "date_prestation": jour, "poste": poste,
              "operateur": (payload.get("operateur") or "").strip() or None,
              "heure_debut": debut, "heure_fin": fin,
              "index_debut": payload.get("index_debut"),
              "index_fin": payload.get("index_fin"),
              "affectation": (payload.get("affectation") or "").strip() or None}
    return champs, arrets, None


class PrestationViewSet(MetierModelViewSet):
    """Ressource Prestation ; contrats HTTP et validations métier conservés."""
    queryset = PrestationEngin.objects.none()
    serializer_class = PrestationEnginSerializer
    lookup_url_kwarg = 'prestation_id'

    def list(self, request):
        return self._traiter_prestations(request)


    def create(self, request):
        return self._traiter_prestations(request)


    def _traiter_prestations(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method == "POST":
            champs, arrets, erreur = _lire_prestation(request.data or {}, sid)
            if erreur:
                return erreur
            verrou = _verrou_mois(sid, champs["date_prestation"])
            if verrou:
                return verrou
            with transaction.atomic():
                p = PrestationEngin.objects.create(
                    societe_id=sid, **champs,
                    created_by=request.user.id, created_at=services.maintenant())
                for a in arrets:
                    ArretPrestationEngin.objects.create(prestation_id=p.id, **a)
                services.enregistrer_audit(
                    request.user.id, "INSERT", "prestation_engin", p.id, None,
                    {"date": champs["date_prestation"].isoformat(),
                     "poste": champs["poste"]})
            return Response(_prestation_dict(p), status=201)
        q = PrestationEngin.objects.filter(societe_id=sid)
        engin_id = request.query_params.get("engin_id")
        if engin_id:
            q = q.filter(engin_id=engin_id)
        du, au = request.query_params.get("du"), request.query_params.get("au")
        if du:
            q = q.filter(date_prestation__gte=du)
        if au:
            q = q.filter(date_prestation__lte=au)
        rows = list(q.order_by("date_prestation", "poste"))
        arrets = engins_lib.arrets_par_prestation([p.id for p in rows])
        mode = engins_lib.reglages(sid)["arrondi"]
        noms = {e.id: e.nom for e in Engin.objects.filter(societe_id=sid)}
        return Response([_prestation_dict(p, arrets.get(p.id, []), mode, noms)
                         for p in rows])


    def partial_update(self, request, prestation_id):
        return self._traiter_maj_prestation(request, prestation_id)


    def destroy(self, request, prestation_id):
        return self._traiter_maj_prestation(request, prestation_id)


    def _traiter_maj_prestation(self, request, prestation_id):
        p = PrestationEngin.objects.filter(id=prestation_id).first()
        if not p:
            return refus({"detail": "Fiche introuvable."}, status=404)
        _acces(request, p.societe_id)
        verrou = _verrou_mois(p.societe_id, p.date_prestation)
        if verrou:
            return verrou
        if request.method == "DELETE":
            avant = _prestation_dict(p)
            with transaction.atomic():
                ArretPrestationEngin.objects.filter(prestation_id=p.id).delete()
                p.delete()
                services.enregistrer_audit(request.user.id, "DELETE",
                                           "prestation_engin", prestation_id,
                                           avant, None)
            return Response({"ok": True})
        payload = dict(request.data or {})
        payload.setdefault("engin_id", str(p.engin_id))
        payload.setdefault("date", p.date_prestation.isoformat())
        payload.setdefault("poste", p.poste)
        payload.setdefault("heure_debut", p.heure_debut)
        payload.setdefault("heure_fin", p.heure_fin)
        payload.setdefault("operateur", p.operateur)
        payload.setdefault("index_debut", p.index_debut)
        payload.setdefault("index_fin", p.index_fin)
        payload.setdefault("affectation", p.affectation)
        if "arrets" not in payload:
            payload["arrets"] = [
                {"nature": a.nature, "debut": a.debut, "fin": a.fin}
                for a in ArretPrestationEngin.objects.filter(prestation_id=p.id)]
        champs, arrets, erreur = _lire_prestation(payload, p.societe_id)
        if erreur:
            return erreur
        verrou = _verrou_mois(p.societe_id, champs["date_prestation"])
        if verrou:
            return verrou
        avant = _prestation_dict(p)
        with transaction.atomic():
            for champ, valeur in champs.items():
                setattr(p, champ, valeur)
            p.save()
            ArretPrestationEngin.objects.filter(prestation_id=p.id).delete()
            for a in arrets:
                ArretPrestationEngin.objects.create(prestation_id=p.id, **a)
            services.enregistrer_audit(request.user.id, "UPDATE", "prestation_engin",
                                       p.id, avant, _prestation_dict(p))
        return Response(_prestation_dict(p))


# ═══ RPE (relevé mensuel) & facturation ══════════════════════════════

def _valider_ym(ym) -> str | None:
    if not ym or len(ym) != 7 or ym[4] != "-":
        return None
    try:
        annee, mois = int(ym[:4]), int(ym[5:7])
    except ValueError:
        return None
    if not (2000 <= annee <= 2100 and 1 <= mois <= 12):
        return None
    return ym


def _facture_du_mois(sid, ym):
    return (Facture.objects.filter(societe_id=sid, type="vente",
                                   reference=f"ENGINS-{ym}")
            .exclude(statut="annulee").first())


def _rpe_data(sid, ym: str) -> dict:
    synthese = engins_lib.synthese_mois(sid, ym)
    reg = synthese["reglages"]
    mode = reg["arrondi"]
    rec = synthese["reconciliation"]
    rows = []
    for r in synthese["rows"]:
        e = r["engin"]
        supp_h = engins_lib.dec_val(r["supp_min"], mode)
        montant_forfait = float(e.tarif_mensuel_usd or 0)
        montant_supp = round(supp_h * float(e.tarif_heure_supp_usd or 0), 2)
        rows.append({
            "engin_id": str(e.id), "engin": e.nom, "categorie": e.categorie,
            "tarif_mensuel_usd": montant_forfait,
            "tarif_heure_supp_usd": float(e.tarif_heure_supp_usd or 0),
            "jour_hm": engins_lib.fmt_hm(r["min_jour"]),
            "jour_dec": engins_lib.dec_val(r["min_jour"], mode),
            "nuit_hm": engins_lib.fmt_hm(r["min_nuit"]),
            "nuit_dec": engins_lib.dec_val(r["min_nuit"], mode),
            "total_hm": engins_lib.fmt_hm(r["min_total"]),
            "total_dec": engins_lib.dec_val(r["min_total"], mode),
            "supp_hm": engins_lib.fmt_hm(r["supp_min"]),
            "supp_dec": supp_h,
            "harmonise_min": r["harmonise_min"],
            "harmonise_hm": engins_lib.fmt_hm(r["harmonise_min"])
            if r["harmonise_min"] else None,
            "montant_forfait": montant_forfait,
            "montant_supp": montant_supp,
            "montant_total": round(montant_forfait + montant_supp, 2),
        })
    tot = lambda k: round(sum(r[k] for r in rows), 2)  # noqa: E731
    fac = _facture_du_mois(sid, ym)
    noms_engins = {str(e.id): e.nom
                   for e in Engin.objects.filter(societe_id=sid)}
    harmonisations = [
        {"id": str(h.id), "source": noms_engins.get(str(h.engin_source_id), "?"),
         "cible": noms_engins.get(str(h.engin_cible_id), "?"), "poste": h.poste,
         "minutes": h.minutes, "hm": engins_lib.fmt_hm(h.minutes),
         "statut": h.statut, "motif": h.motif}
        for h in engins_lib.harmonisations_mois(
            sid, ym, statuts=("proposee", "approuvee"))]
    en_attente = sum(1 for h in harmonisations if h["statut"] == "proposee")
    valide = bool(rec and rec.statut == "validee")
    return {"ym": ym, "reglages": reg,
            "numero_rpe": engins_lib.numero_rpe(ym, reg["rpe_prefix"]),
            "rows": rows,
            "totaux": {"jour_dec": tot("jour_dec"), "nuit_dec": tot("nuit_dec"),
                       "total_dec": tot("total_dec"), "supp_dec": tot("supp_dec"),
                       "montant_forfait": tot("montant_forfait"),
                       "montant_supp": tot("montant_supp"),
                       "montant_total": tot("montant_total")},
            # Mention du RPE : DÉFINITIF après validation de la réconciliation.
            "mention": "DEFINITIF" if valide else "PROVISOIRE",
            "reconciliation": {
                "statut": rec.statut, "revision": rec.revision,
                "valide_at": rec.valide_at.isoformat() if rec.valide_at else None,
            } if rec else None,
            "harmonisations": harmonisations,
            "harmonisations_en_attente": en_attente,
            "facture": {"id": str(fac.id), "numero": fac.numero,
                        "total_ttc": float(fac.total_ttc)} if fac else None}


class ExploitationEnginViewSet(MetierViewSet):
    """Ressource ExploitationEngin ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def get_config(self, request):
        return self._traiter_config_engins(request)


    @action(detail=False, methods=['post'])
    def post_config(self, request):
        return self._traiter_config_engins(request)


    def _traiter_config_engins(self, request):
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        if request.method == "POST":
            assert_role(roles, ROLES_CONFIG)
            payload = request.data or {}
            modifs = {}
            for cle, (type_valeur, description) in CLES_CONFIG.items():
                court = cle.split(".", 1)[1]
                if court not in payload:
                    continue
                valeur = str(payload[court]).strip()
                if cle == "engins.arrondi" and valeur not in ("nearest", "down", "up"):
                    return refus({"detail": "arrondi : nearest, down ou up."}, status=422)
                if cle == "engins.forfait_mensuel_h":
                    try:
                        if float(valeur) <= 0:
                            raise ValueError
                    except ValueError:
                        return refus({"detail": "forfait_mensuel_h invalide."}, status=422)
                p = Parametre.objects.filter(cle=cle, societe_id=sid).first()
                if p:
                    p.valeur = valeur
                    p.save(update_fields=["valeur"])
                else:
                    Parametre.objects.create(societe_id=sid, cle=cle, valeur=valeur,
                                             type_valeur=type_valeur,
                                             description=description)
                modifs[court] = valeur
            if modifs:
                services.enregistrer_audit(request.user.id, "CONFIG", "engins",
                                           None, None, modifs)
        assert_role(roles, ROLES)
        return Response(engins_lib.reglages(sid))


    @action(detail=False, methods=['get'])
    def rpe(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        ym = _valider_ym(request.query_params.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        return Response(_rpe_data(sid, ym))


    @action(detail=False, methods=['post'])
    def facturer(self, request):
        'Facture le mois : forfait mensuel de chaque engin actif + heures\n    supplémentaires × tarif. Une seule facture par mois (référence ENGINS-YYYY-MM).'
        sid = _societe_param(request)
        _acces(request, sid, {"COMPTABLE", "DFI", "DG"})
        payload = request.data or {}
        ym = _valider_ym(payload.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        tiers = Tiers.objects.filter(id=payload.get("tiers_id")).first()
        if not tiers_disponible(tiers, sid) or tiers.type != "client":
            return refus({"detail": "Client (tiers_id) invalide."}, status=400)
        existante = _facture_du_mois(sid, ym)
        if existante:
            return refus({"detail": f"Le mois {ym} est déjà facturé "
                                    f"({existante.numero}). Annulez d'abord cette "
                                    f"facture pour refacturer."}, status=409)
        if not engins_lib.mois_verrouille(sid, ym):
            return refus({"detail": f"Le mois {ym} n'est pas encore réconcilié : "
                                    f"enregistrez la réconciliation avec le "
                                    f"planning du locataire puis faites-la "
                                    f"valider avant de facturer."}, status=409)
        if engins_lib.harmonisations_mois(sid, ym, statuts=("proposee",)):
            return refus({"detail": f"Des harmonisations d'heures du mois {ym} "
                                    f"attendent encore la décision de la "
                                    f"hiérarchie : approuvez-les ou rejetez-les "
                                    f"avant de facturer."}, status=409)
        data = _rpe_data(sid, ym)
        lignes_payload = []
        libelle_mois = f"{ym[5:7]}/{ym[:4]}"
        for r in data["rows"]:
            if r["montant_forfait"]:
                lignes_payload.append({
                    "designation": f"Location {r['engin']} — forfait mensuel "
                                   f"{int(data['reglages']['forfait_mensuel_h'])}h "
                                   f"({libelle_mois})",
                    "qte": 1, "pu": r["montant_forfait"]})
            if r["supp_dec"] > 0 and r["tarif_heure_supp_usd"] > 0:
                lignes_payload.append({
                    "designation": f"Heures supplémentaires {r['engin']} — "
                                   f"{r['supp_hm']} soit {r['supp_dec']:.2f} h "
                                   f"({libelle_mois})",
                    "qte": r["supp_dec"], "pu": r["tarif_heure_supp_usd"]})
        if not lignes_payload:
            return refus({"detail": "Rien à facturer sur ce mois (aucun tarif "
                                    "ni heure supplémentaire)."}, status=400)
        societe = Societe.objects.filter(id=sid).first()
        jour = date.today()
        taux_tva = float(services.get_parametre("tva.taux_defaut", sid, "16"))
        with transaction.atomic():
            numero = services.next_numero("facture_vente", jour.year,
                                          societe.code, societe.id)
            fac = Facture.objects.create(
                societe_id=sid, type="vente", numero=numero, tiers_id=tiers.id,
                date_facture=jour, echeance=jour + timedelta(days=30),
                reference=f"ENGINS-{ym}",
                intra_groupe=bool(tiers.intra_groupe), statut="validee",
                created_by=request.user.id, created_at=services.maintenant())
            total_ht = total_tva = 0.0
            for lp in lignes_payload:
                ht = round(float(lp["qte"]) * float(lp["pu"]), 2)
                tva = round(ht * taux_tva / 100, 2)
                LigneFacture.objects.create(
                    facture_id=fac.id, article_id=None,
                    designation=lp["designation"][:255], qte=lp["qte"],
                    prix_unitaire=lp["pu"], taux_tva=taux_tva,
                    montant_ht=ht, montant_tva=tva)
                total_ht = round(total_ht + ht, 2)
                total_tva = round(total_tva + tva, 2)
            fac.total_ht = total_ht
            fac.total_tva = total_tva
            fac.total_ttc = round(total_ht + total_tva, 2)
            cpt_produit = comptabilite._compte("compte_vente_location", sid)
            lignes_ecr = [{"sens": "D", "compte": comptabilite._compte("compte_client", sid),
                           "montant_usd": float(fac.total_ttc), "tiers_id": tiers.id,
                           "libelle": f"Facture location engins {numero} — {tiers.nom}"},
                          {"sens": "C", "compte": cpt_produit,
                           "montant_usd": float(fac.total_ht),
                           "libelle": f"Location d'engins {libelle_mois}"}]
            if total_tva:
                lignes_ecr.append({"sens": "C",
                                   "compte": comptabilite._compte("tva_collectee", sid),
                                   "montant_usd": total_tva,
                                   "libelle": f"TVA collectée {numero}"})
            statut_piece = intersociete_lib._statut_piece(sid, "vente")
            ecr = comptabilite.post_ecriture(
                sid, "VE", "Ventes", "vente", jour,
                f"Facture location engins {numero} — {tiers.nom}",
                lignes_ecr, "facture_vente", "facture", fac.id, numero,
                request.user.id, statut=statut_piece)
            fac.ecriture_id = ecr.id
            fac.save()
            services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id,
                                       None, {"numero": numero, "module": "engins",
                                              "ym": ym,
                                              "total_ttc": float(fac.total_ttc)})
        return Response({"facture": {"id": str(fac.id), "numero": numero,
                                     "total_ht": total_ht, "total_tva": total_tva,
                                     "total_ttc": float(fac.total_ttc),
                                     "tiers": tiers.nom},
                         "lignes": len(lignes_payload)}, status=201)


# ═══ Réconciliation mensuelle, harmonisations & rapports ═════════════

def _nom_utilisateur(uid) -> str | None:
    if not uid:
        return None
    u = Utilisateur.objects.filter(id=uid).first()
    return (f"{u.prenom} {u.nom}".strip() if u and u.prenom else u.nom) if u else None


def _harmonisation_dict(h: HarmonisationEngin, noms_engins: dict) -> dict:
    return {"id": str(h.id), "ym": h.ym,
            "engin_source_id": str(h.engin_source_id),
            "engin_cible_id": str(h.engin_cible_id),
            "source": noms_engins.get(str(h.engin_source_id), "?"),
            "cible": noms_engins.get(str(h.engin_cible_id), "?"),
            "poste": h.poste, "minutes": h.minutes,
            "hm": engins_lib.fmt_hm(h.minutes),
            "motif": h.motif, "statut": h.statut,
            "propose_par": _nom_utilisateur(h.propose_par),
            "propose_at": h.propose_at.isoformat() if h.propose_at else None,
            "decide_par": _nom_utilisateur(h.decide_par),
            "decide_at": h.decide_at.isoformat() if h.decide_at else None,
            "commentaire_decision": h.commentaire_decision}


def _disponible_pour_transfert(sid, ym, engin_source_id, poste,
                               exclure_id=None) -> int:
    """Minutes du poste encore cessibles par l'engin source : retenues pures
    moins les transferts sortants déjà proposés ou approuvés."""
    base = engins_lib.totaux_retenus(sid, ym).get(str(engin_source_id),
                                                  {"jour": 0, "nuit": 0})
    sorties = sum(
        h.minutes for h in engins_lib.harmonisations_mois(
            sid, ym, statuts=("proposee", "approuvee"))
        if str(h.engin_source_id) == str(engin_source_id) and h.poste == poste
        and (exclure_id is None or h.id != exclure_id))
    return base.get(poste, 0) - sorties


class ReconciliationEnginViewSet(MetierViewSet):
    """Réconciliation mensuelle avec le planning du locataire, arrangements
    d'heures entre engins et rapports d'exploitation."""

    @action(detail=False, methods=['get'])
    def get_reconciliation(self, request):
        return self._traiter_reconciliation(request)


    @action(detail=False, methods=['post'])
    def post_reconciliation(self, request):
        return self._traiter_reconciliation(request)


    def _traiter_reconciliation(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method == "POST":
            return self._enregistrer_reconciliation(request, sid)
        ym = _valider_ym(request.query_params.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        jours = engins_lib.jours_du_mois(ym)
        grille = {str(k): v for k, v in engins_lib.grille_mois(sid, ym).items()}
        rec = engins_lib.reconciliation_du_mois(sid, ym)
        donnees = rec.donnees if rec else {}
        mode = engins_lib.reglages(sid)["arrondi"]
        engins = list(Engin.objects.filter(societe_id=sid,
                                           actif=True).order_by("nom"))
        noms_engins = {str(e.id): e.nom
                       for e in Engin.objects.filter(societe_id=sid)}
        lignes = []
        for e in engins:
            cle = str(e.id)
            par_jour = grille.get(cle, {})
            saisies = donnees.get(cle) or {}
            detail = {}
            tot_nous = tot_retenu = 0
            for date_iso in jours:
                brut = par_jour.get(date_iso, {"jour": 0, "nuit": 0})
                d = saisies.get(date_iso) or {}
                retenu = engins_lib._minutes_retenues(saisies, date_iso, brut, mode)
                tot_nous += brut["jour"] + brut["nuit"]
                tot_retenu += retenu["jour"] + retenu["nuit"]
                detail[date_iso] = {
                    "nous_jour": brut["jour"], "nous_nuit": brut["nuit"],
                    "client_jour": d.get("client_jour"),
                    "client_nuit": d.get("client_nuit"),
                    "retenu_jour": d.get("retenu_jour"),
                    "retenu_nuit": d.get("retenu_nuit"),
                    "note": d.get("note") or ""}
            lignes.append({"engin_id": cle, "engin": e.nom,
                           "jours": detail,
                           "total_nous_min": tot_nous,
                           "total_retenu_min": tot_retenu})
        harmonisations = [
            _harmonisation_dict(h, noms_engins)
            for h in HarmonisationEngin.objects.filter(societe_id=sid, ym=ym)
            .order_by("propose_at")]
        fac = _facture_du_mois(sid, ym)
        return Response({
            "ym": ym, "jours": jours,
            "statut": rec.statut if rec else None,
            "revision": rec.revision if rec else 0,
            "verrouille": bool(rec and rec.statut == "validee"),
            "valide_par": _nom_utilisateur(rec.valide_par) if rec else None,
            "valide_at": rec.valide_at.isoformat()
            if rec and rec.valide_at else None,
            "reouverte_par": _nom_utilisateur(rec.reouverte_par) if rec else None,
            "motif_reouverture": rec.motif_reouverture if rec else None,
            "roles_validation": sorted(_roles_validation_reconciliation(sid)),
            "engins": lignes,
            "harmonisations": harmonisations,
            "facture": {"numero": fac.numero} if fac else None})


    def _enregistrer_reconciliation(self, request, sid):
        payload = request.data or {}
        ym = _valider_ym(payload.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        rec = engins_lib.reconciliation_du_mois(sid, ym)
        if rec and rec.statut == "validee":
            return refus({"detail": f"Réconciliation {ym} validée : le mois est "
                                    f"verrouillé. Demandez une réouverture à la "
                                    f"direction."}, status=409)
        if int(payload.get("revision") or 0) != (rec.revision if rec else 0):
            return refus({"detail": "La réconciliation a été modifiée par un "
                                    "autre utilisateur. Rechargez-la avant "
                                    "d'enregistrer."}, status=409)
        mode = engins_lib.reglages(sid)["arrondi"]
        jours = set(engins_lib.jours_du_mois(ym))
        engins_ok = {str(e.id) for e in Engin.objects.filter(societe_id=sid)}
        brut = payload.get("donnees")
        if not isinstance(brut, dict):
            return refus({"detail": "donnees invalides."}, status=422)
        propres: dict = {}
        for engin_id, par_jour in brut.items():
            if str(engin_id) not in engins_ok or not isinstance(par_jour, dict):
                continue
            for date_iso, d in par_jour.items():
                if date_iso not in jours or not isinstance(d, dict):
                    continue
                entree = {}
                for cle in ("client_jour", "client_nuit",
                            "retenu_jour", "retenu_nuit"):
                    v = d.get(cle)
                    if v is None or v == "":
                        continue
                    try:
                        minutes = engins_lib.arrondir(float(v), mode)
                    except (TypeError, ValueError):
                        return refus({"detail": f"Valeur invalide ({cle}, "
                                                f"{date_iso})."}, status=422)
                    if not 0 <= minutes <= 1440:
                        return refus({"detail": f"Minutes hors limites ({cle}, "
                                                f"{date_iso})."}, status=422)
                    entree[cle] = minutes
                note = str(d.get("note") or "").strip()[:200]
                if note:
                    entree["note"] = note
                if entree:
                    propres.setdefault(str(engin_id), {})[date_iso] = entree
        with transaction.atomic():
            if rec:
                rec.donnees = propres
                rec.revision += 1
                rec.save(update_fields=["donnees", "revision"])
            else:
                rec = ReconciliationEngins.objects.create(
                    societe_id=sid, ym=ym, donnees=propres, revision=1,
                    created_by=request.user.id, created_at=services.maintenant())
            services.enregistrer_audit(request.user.id, "RECONCILIATION",
                                       "reconciliation_engins", rec.id, None,
                                       {"ym": ym, "revision": rec.revision})
        return Response({"ok": True, "revision": rec.revision})


    @action(detail=False, methods=['post'])
    def valider(self, request):
        'Valide la réconciliation du mois : le responsable fige les valeurs\n    retenues et verrouille toute saisie du mois.'
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, _roles_validation_reconciliation(sid))
        payload = request.data or {}
        ym = _valider_ym(payload.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        rec = engins_lib.reconciliation_du_mois(sid, ym)
        if not rec:
            return refus({"detail": "Enregistrez d'abord la réconciliation du "
                                    "mois (même sans divergence) avant de la "
                                    "valider."}, status=400)
        if rec.statut == "validee":
            return refus({"detail": "Réconciliation déjà validée."}, status=409)
        if int(payload.get("revision") or 0) != rec.revision:
            return refus({"detail": "La réconciliation a changé depuis votre "
                                    "lecture. Rechargez-la avant de valider."},
                         status=409)
        with transaction.atomic():
            rec.statut = "validee"
            rec.valide_par = request.user.id
            rec.valide_at = services.maintenant()
            rec.save(update_fields=["statut", "valide_par", "valide_at"])
            services.enregistrer_audit(request.user.id, "VALIDE_RECONCILIATION",
                                       "reconciliation_engins", rec.id, None,
                                       {"ym": ym})
        return Response({"ok": True, "statut": "validee"})


    @action(detail=False, methods=['post'])
    def rouvrir(self, request):
        'Réouverture de très haut niveau (PRESIDENT/DG) d\'un mois verrouillé,\n    motif obligatoire et tracé dans le journal d\'audit.'
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, ROLES_REOUVERTURE)
        payload = request.data or {}
        ym = _valider_ym(payload.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        rec = engins_lib.reconciliation_du_mois(sid, ym)
        if not rec or rec.statut != "validee":
            return refus({"detail": "Ce mois n'est pas verrouillé."}, status=409)
        fac = _facture_du_mois(sid, ym)
        if fac:
            return refus({"detail": f"Le mois {ym} est facturé "
                                    f"({fac.numero}) : annulez d'abord la "
                                    f"facture avant de rouvrir la "
                                    f"réconciliation."}, status=409)
        motif = str(payload.get("motif") or "").strip()
        if len(motif) < 10:
            return refus({"detail": "Motif de réouverture requis "
                                    "(au moins 10 caractères)."}, status=422)
        with transaction.atomic():
            rec.statut = "en_cours"
            rec.reouverte_par = request.user.id
            rec.reouverte_at = services.maintenant()
            rec.motif_reouverture = motif[:255]
            rec.save(update_fields=["statut", "reouverte_par", "reouverte_at",
                                    "motif_reouverture"])
            services.enregistrer_audit(request.user.id, "ROUVRE_RECONCILIATION",
                                       "reconciliation_engins", rec.id, None,
                                       {"ym": ym, "motif": motif[:255]})
        return Response({"ok": True, "statut": "en_cours"})


    @action(detail=False, methods=['get'])
    def get_harmonisations(self, request):
        return self._traiter_harmonisations(request)


    @action(detail=False, methods=['post'])
    def post_harmonisations(self, request):
        return self._traiter_harmonisations(request)


    def _traiter_harmonisations(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method != "POST":
            ym = _valider_ym(request.query_params.get("ym"))
            if not ym:
                return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
            noms = {str(e.id): e.nom for e in Engin.objects.filter(societe_id=sid)}
            return Response([
                _harmonisation_dict(h, noms)
                for h in HarmonisationEngin.objects.filter(societe_id=sid, ym=ym)
                .order_by("propose_at")])
        payload = request.data or {}
        ym = _valider_ym(payload.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        fac = _facture_du_mois(sid, ym)
        if fac:
            return refus({"detail": f"Le mois {ym} est déjà facturé "
                                    f"({fac.numero}) : plus d'harmonisation "
                                    f"possible sans annuler la facture."},
                         status=409)
        source = Engin.objects.filter(id=payload.get("engin_source_id")).first()
        cible = Engin.objects.filter(id=payload.get("engin_cible_id")).first()
        if not source or not cible or str(source.societe_id) != str(sid) \
                or str(cible.societe_id) != str(sid):
            return refus({"detail": "Engins source et cible requis."}, status=400)
        if source.id == cible.id:
            return refus({"detail": "La source et la cible doivent être deux "
                                    "engins différents."}, status=422)
        poste = payload.get("poste", "jour")
        if poste not in ("jour", "nuit"):
            return refus({"detail": "poste : jour ou nuit."}, status=422)
        mode = engins_lib.reglages(sid)["arrondi"]
        try:
            minutes = engins_lib.arrondir(float(payload.get("minutes")), mode)
        except (TypeError, ValueError):
            return refus({"detail": "minutes invalides."}, status=422)
        if minutes <= 0:
            return refus({"detail": "minutes invalides."}, status=422)
        motif = str(payload.get("motif") or "").strip()
        if len(motif) < 5:
            return refus({"detail": "Motif de l'arrangement requis."}, status=422)
        disponible = _disponible_pour_transfert(sid, ym, source.id, poste)
        if minutes > disponible:
            return refus({"detail": f"{source.nom} ne dispose que de "
                                    f"{engins_lib.fmt_hm(max(0, disponible))} "
                                    f"cessibles en poste {poste} sur {ym} "
                                    f"(retenues moins transferts déjà "
                                    f"proposés)."}, status=422)
        with transaction.atomic():
            h = HarmonisationEngin.objects.create(
                societe_id=sid, ym=ym, engin_source_id=source.id,
                engin_cible_id=cible.id, poste=poste, minutes=minutes,
                motif=motif[:255], propose_par=request.user.id,
                propose_at=services.maintenant())
            services.enregistrer_audit(request.user.id, "INSERT",
                                       "harmonisation_engin", h.id, None,
                                       {"ym": ym, "source": source.nom,
                                        "cible": cible.nom, "minutes": minutes})
        noms = {str(source.id): source.nom, str(cible.id): cible.nom}
        return Response(_harmonisation_dict(h, noms), status=201)


    @action(detail=True, methods=['post'])
    def decider(self, request, harmonisation_id):
        'La hiérarchie approuve ou rejette un arrangement d\'heures proposé.'
        h = HarmonisationEngin.objects.filter(id=harmonisation_id).first()
        if not h:
            return refus({"detail": "Harmonisation introuvable."}, status=404)
        sid = h.societe_id
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, _roles_validation_reconciliation(sid))
        if h.statut != "proposee":
            return refus({"detail": f"Déjà {h.statut}."}, status=409)
        fac = _facture_du_mois(sid, h.ym)
        if fac:
            return refus({"detail": f"Le mois {h.ym} est déjà facturé "
                                    f"({fac.numero})."}, status=409)
        decision = (request.data or {}).get("decision")
        if decision not in ("approuvee", "rejetee"):
            return refus({"detail": "decision : approuvee ou rejetee."},
                         status=422)
        if decision == "approuvee":
            disponible = _disponible_pour_transfert(sid, h.ym, h.engin_source_id,
                                                    h.poste, exclure_id=h.id)
            if h.minutes > disponible:
                return refus({"detail": "Les heures cessibles de la source ne "
                                        "suffisent plus pour approuver ce "
                                        "transfert."}, status=409)
        with transaction.atomic():
            h.statut = decision
            h.decide_par = request.user.id
            h.decide_at = services.maintenant()
            h.commentaire_decision = str((request.data or {})
                                         .get("commentaire") or "").strip()[:255] \
                or None
            h.save(update_fields=["statut", "decide_par", "decide_at",
                                  "commentaire_decision"])
            services.enregistrer_audit(request.user.id, "DECISION",
                                       "harmonisation_engin", h.id, None,
                                       {"ym": h.ym, "decision": decision})
        noms = {str(e.id): e.nom
                for e in Engin.objects.filter(societe_id=sid)}
        return Response(_harmonisation_dict(h, noms))


    @action(detail=False, methods=['get'])
    def rapport_technique(self, request):
        'Suivi du target journalier : cumul des heures retenues vs forfait\n    réparti sur le mois, écart en heures et en jours, comparaison N-1.'
        sid = _societe_param(request)
        _acces(request, sid)
        ym = _valider_ym(request.query_params.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        reg = engins_lib.reglages(sid)
        mode = reg["arrondi"]
        jours = engins_lib.jours_du_mois(ym)
        nb_jours = len(jours)
        jusquau = request.query_params.get("jusquau") or ""
        j_lim = nb_jours
        if jusquau[:7] == ym:
            try:
                j_lim = min(nb_jours, max(1, int(jusquau[8:10])))
            except ValueError:
                pass
        elif date.today().isoformat()[:7] == ym:
            j_lim = min(nb_jours, date.today().day)
        forfait_min = int(reg["forfait_mensuel_h"] * 60)
        target_jour = forfait_min / nb_jours
        target_cumule = target_jour * j_lim

        annee, mois = int(ym[:4]), int(ym[5:7])
        pym = f"{annee - 1}-12" if mois == 1 else f"{annee}-{mois - 1:02d}"
        nb_jours_prec = len(engins_lib.jours_du_mois(pym))
        j_lim_prec = min(j_lim, nb_jours_prec)
        target_cumule_prec = (forfait_min / nb_jours_prec) * j_lim_prec

        cumuls = engins_lib.totaux_retenus(sid, ym, jusqu_au_jour=j_lim)
        cumuls_prec = engins_lib.totaux_retenus(sid, pym,
                                                jusqu_au_jour=j_lim_prec)
        rows = []
        for e in Engin.objects.filter(societe_id=sid, actif=True).order_by("nom"):
            c = cumuls.get(str(e.id), {"jour": 0, "nuit": 0})
            cumul = c["jour"] + c["nuit"]
            cp = cumuls_prec.get(str(e.id), {"jour": 0, "nuit": 0})
            cumul_prec = cp["jour"] + cp["nuit"]
            ecart = cumul - target_cumule
            rows.append({
                "engin_id": str(e.id), "engin": e.nom,
                "cumul_hm": engins_lib.fmt_hm(cumul),
                "cumul_dec": engins_lib.dec_val(cumul, mode),
                "target_dec": round(target_cumule / 60, 2),
                "ecart_dec": round(ecart / 60, 2),
                "ecart_jours": round(ecart / target_jour, 1) if target_jour else 0,
                "pct": round(cumul / target_cumule * 100, 1)
                if target_cumule else 0,
                "cumul_prec_dec": engins_lib.dec_val(cumul_prec, mode),
                "ecart_vs_prec_dec": round((cumul - cumul_prec) / 60, 2),
            })
        cumul_parc = sum(r["cumul_dec"] for r in rows)
        target_parc = round(target_cumule / 60, 2) * len(rows)
        return Response({
            "ym": ym, "mois_precedent": pym, "nb_jours": nb_jours,
            "jusqu_au_jour": j_lim,
            "target_jour_dec": round(target_jour / 60, 2),
            "target_cumule_dec": round(target_cumule / 60, 2),
            "target_cumule_prec_dec": round(target_cumule_prec / 60, 2),
            "rows": rows,
            "parc": {"cumul_dec": round(cumul_parc, 2),
                     "target_dec": round(target_parc, 2),
                     "ecart_dec": round(cumul_parc - target_parc, 2),
                     "ecart_jours": round((cumul_parc - target_parc)
                                          / (target_jour / 60), 1)
                     if target_jour else 0}})


    @action(detail=False, methods=['get'])
    def disponibilite(self, request):
        'Grille mensuelle : sollicitation (1 = deux postes, ½ = un poste,\n    NS = disponible non presté) et indisponibilités (P panne, E entretien)\n    déduites des interventions de maintenance immobilisantes.'
        sid = _societe_param(request)
        _acces(request, sid)
        ym = _valider_ym(request.query_params.get("ym"))
        if not ym:
            return refus({"detail": "ym requis (format YYYY-MM)."}, status=422)
        jours = engins_lib.jours_du_mois(ym)
        aujourd_hui = date.today().isoformat()
        grille = {str(k): v for k, v in engins_lib.grille_mois(sid, ym).items()}
        engins = list(Engin.objects.filter(societe_id=sid,
                                           actif=True).order_by("nom"))
        inters = list(InterventionCamion.objects.filter(
            societe_id=sid, engin_id__in=[e.id for e in engins],
            immobilise=True))

        def indispo(engin_id, date_iso):
            for i in inters:
                if str(i.engin_id) != str(engin_id):
                    continue
                debut = i.date_signalement.isoformat()
                if i.date_fin:
                    fin = i.date_fin.isoformat()
                elif i.statut == "terminee":
                    fin = debut
                else:
                    fin = aujourd_hui
                if debut <= date_iso <= fin:
                    return "e" if "entretien" in (i.type or "").lower() \
                        or "prevent" in (i.type or "").lower() else "p"
            return None

        rows = []
        for e in engins:
            par_jour = grille.get(str(e.id), {})
            cells = []
            stats = {"dispo": 0, "panne": 0, "entretien": 0,
                     "s": 0, "demi": 0, "ns": 0, "minutes": 0, "sol": 0.0}
            ecoules = 0
            for date_iso in jours:
                d = par_jour.get(date_iso, {"jour": 0, "nuit": 0})
                minutes = d["jour"] + d["nuit"]
                stats["minutes"] += minutes
                code = indispo(e.id, date_iso)
                if code is None:
                    if d["jour"] and d["nuit"]:
                        code, val = "1", 1.0
                    elif d["jour"] or d["nuit"]:
                        code, val = "05", 0.5
                    else:
                        code, val = "ns", 0.0
                    if date_iso <= aujourd_hui:
                        stats["dispo"] += 1
                        stats["sol"] += val
                        stats["s" if code == "1" else
                              "demi" if code == "05" else "ns"] += 1
                else:
                    if date_iso <= aujourd_hui:
                        stats["panne" if code == "p" else "entretien"] += 1
                if date_iso <= aujourd_hui:
                    ecoules += 1
                cells.append(code)
            rows.append({
                "engin_id": str(e.id), "engin": e.nom, "cells": cells,
                "dispo": stats["dispo"], "panne": stats["panne"],
                "entretien": stats["entretien"], "s": stats["s"],
                "demi": stats["demi"], "ns": stats["ns"],
                "heures_hm": engins_lib.fmt_hm(stats["minutes"]),
                "taux_dispo": round(stats["dispo"] / ecoules * 100)
                if ecoules else 0,
                "taux_sollicitation": round(stats["sol"] / stats["dispo"] * 100)
                if stats["dispo"] else 0})
        return Response({"ym": ym, "jours": jours, "rows": rows})


    @action(detail=False, methods=['get'])
    def evolution(self, request):
        'Série mensuelle (12 derniers mois) : heures retenues, heures supp,\n    statut de réconciliation et facture du mois.'
        sid = _societe_param(request)
        _acces(request, sid)
        try:
            n = max(1, min(24, int(request.query_params.get("n") or 12)))
        except ValueError:
            n = 12
        annee, mois = date.today().year, date.today().month
        serie = []
        for _ in range(n):
            ym = f"{annee}-{mois:02d}"
            synthese = engins_lib.synthese_mois(sid, ym)
            mode = synthese["reglages"]["arrondi"]
            total = sum(r["min_total"] for r in synthese["rows"])
            supp = sum(r["supp_min"] for r in synthese["rows"])
            rec = synthese["reconciliation"]
            fac = _facture_du_mois(sid, ym)
            serie.append({
                "ym": ym,
                "total_dec": engins_lib.dec_val(total, mode),
                "supp_dec": engins_lib.dec_val(supp, mode),
                "reconciliation": rec.statut if rec else None,
                "facture": {"numero": fac.numero,
                            "total_ttc": float(fac.total_ttc)} if fac else None})
            mois -= 1
            if mois == 0:
                annee, mois = annee - 1, 12
        serie.reverse()
        return Response({"serie": serie})


# Anciens points d’entrée conservés pour les intégrations existantes.
config_engins = ExploitationEnginViewSet.as_view({'get': 'get_config', 'post': 'post_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='exploitation_engin')
engins = EnginViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='engin')
maj_engin = EnginViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='engin')
prestations = PrestationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='prestation')
maj_prestation = PrestationViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='prestation')
rpe = ExploitationEnginViewSet.as_view({'get': 'rpe'}, http_method_names=['get', 'options'], detail=False, basename='exploitation_engin')
facturer = ExploitationEnginViewSet.as_view({'post': 'facturer'}, http_method_names=['post', 'options'], detail=False, basename='exploitation_engin')
reconciliation = ReconciliationEnginViewSet.as_view({'get': 'get_reconciliation', 'post': 'post_reconciliation'}, http_method_names=['get', 'post', 'options'], detail=False, basename='reconciliation_engin')
valider_reconciliation = ReconciliationEnginViewSet.as_view({'post': 'valider'}, http_method_names=['post', 'options'], detail=False, basename='reconciliation_engin')
rouvrir_reconciliation = ReconciliationEnginViewSet.as_view({'post': 'rouvrir'}, http_method_names=['post', 'options'], detail=False, basename='reconciliation_engin')
harmonisations = ReconciliationEnginViewSet.as_view({'get': 'get_harmonisations', 'post': 'post_harmonisations'}, http_method_names=['get', 'post', 'options'], detail=False, basename='reconciliation_engin')
decider_harmonisation = ReconciliationEnginViewSet.as_view({'post': 'decider'}, http_method_names=['post', 'options'], detail=True, basename='reconciliation_engin')
rapport_technique = ReconciliationEnginViewSet.as_view({'get': 'rapport_technique'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')
disponibilite = ReconciliationEnginViewSet.as_view({'get': 'disponibilite'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')
evolution = ReconciliationEnginViewSet.as_view({'get': 'evolution'}, http_method_names=['get', 'options'], detail=False, basename='reconciliation_engin')
