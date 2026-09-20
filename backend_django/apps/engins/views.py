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
from apps.engins.models import ArretPrestationEngin, Engin, PrestationEngin
from apps.commercial.models import Facture, LigneFacture
from apps.maintenance.models import InterventionCamion
from core.models import Parametre, Societe, Tiers
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI", "ASSISTANT_TECH", "ASSISTANT_TECHNIQUE", "DT",
         "DISPATCHER", "DG"}
ROLES_CONFIG = {"DFI", "PRESIDENT", "ADMIN_SYS"}

CLES_CONFIG = {
    "engins.forfait_mensuel_h": ("number", "Forfait mensuel d'heures par engin"),
    "engins.arrondi": ("string", "Arrondi des heures (nearest | down | up)"),
    "engins.rpe_prefix": ("string", "Préfixe des numéros de RPE"),
    "engins.locataire": ("string", "Nom du locataire affiché sur les RPE"),
}


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
            "montant_forfait": montant_forfait,
            "montant_supp": montant_supp,
            "montant_total": round(montant_forfait + montant_supp, 2),
        })
    tot = lambda k: round(sum(r[k] for r in rows), 2)  # noqa: E731
    fac = _facture_du_mois(sid, ym)
    return {"ym": ym, "reglages": reg,
            "numero_rpe": engins_lib.numero_rpe(ym, reg["rpe_prefix"]),
            "rows": rows,
            "totaux": {"jour_dec": tot("jour_dec"), "nuit_dec": tot("nuit_dec"),
                       "total_dec": tot("total_dec"), "supp_dec": tot("supp_dec"),
                       "montant_forfait": tot("montant_forfait"),
                       "montant_supp": tot("montant_supp"),
                       "montant_total": tot("montant_total")},
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


# Anciens points d’entrée conservés pour les intégrations existantes.
config_engins = ExploitationEnginViewSet.as_view({'get': 'get_config', 'post': 'post_config'}, http_method_names=['get', 'post', 'options'], detail=False, basename='exploitation_engin')
engins = EnginViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='engin')
maj_engin = EnginViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='engin')
prestations = PrestationViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='prestation')
maj_prestation = PrestationViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='prestation')
rpe = ExploitationEnginViewSet.as_view({'get': 'rpe'}, http_method_names=['get', 'options'], detail=False, basename='exploitation_engin')
facturer = ExploitationEnginViewSet.as_view({'post': 'facturer'}, http_method_names=['post', 'options'], detail=False, basename='exploitation_engin')
