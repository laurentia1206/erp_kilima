"""Suivi carburant détaillé — camions ET engins de location.

Chaque plein est enregistré (litres, prix, montant, compteur, station).
Le rapport de période calcule la consommation réelle :
- camions : litres / km parcourus × 100 (relevés km des courses) ;
- engins : litres / heures prestées (fiches de prestation) ;
et la compare à la consommation théorique du véhicule (surconsommation
signalée au-delà de +10 %) — l'outil classique de détection des
détournements de carburant.
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.transport.models import PleinCarburant
from apps.transport.serializers import PleinCarburantSerializer

from datetime import date

from django.db import transaction
from rest_framework.response import Response

from apps.engins import services as engins_lib
from core import services as services
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.transport.models import Camion, Course, PleinCarburant
from apps.engins.models import Engin, PrestationEngin
from core.views import _societe_param

ROLES = {"DISPATCHER", "MAINTENANCIER", "DT", "ASSISTANT_TECHNIQUE",
         "ASSISTANT_TECH", "COMPTABLE", "DFI", "DG"}
SEUIL_SURCONSO_PCT = 10.0


def _acces(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES)
    return roles


def _porteur(plein: PleinCarburant):
    if plein.camion_id:
        c = Camion.objects.filter(id=plein.camion_id).first()
        return "camion", (c.immatriculation if c else None)
    e = Engin.objects.filter(id=plein.engin_id).first()
    return "engin", (e.nom if e else None)


def _plein_dict(p: PleinCarburant) -> dict:
    genre, nom = _porteur(p)
    course = Course.objects.filter(id=p.course_id).first() if p.course_id else None
    return {"id": str(p.id), "cible": genre, "vehicule": nom,
            "camion_id": str(p.camion_id) if p.camion_id else None,
            "engin_id": str(p.engin_id) if p.engin_id else None,
            "course": course.numero if course else None,
            "course_id": str(p.course_id) if p.course_id else None,
            "date": p.date_plein.isoformat(),
            "litres": float(p.litres),
            "prix_litre_usd": float(p.prix_litre_usd)
            if p.prix_litre_usd is not None else None,
            "montant_usd": float(p.montant_usd or 0),
            "compteur": float(p.compteur) if p.compteur is not None else None,
            "fournisseur": p.fournisseur, "note": p.note}


def _lire_plein(payload, sid):
    """Validation création/modification. Retourne (champs, erreur)."""
    cam = eng = None
    if payload.get("engin_id"):
        eng = Engin.objects.filter(id=payload["engin_id"]).first()
        if not eng or str(eng.societe_id) != str(sid):
            return None, refus({"detail": "Engin invalide."}, status=400)
    else:
        cam = Camion.objects.filter(id=payload.get("camion_id")).first()
        if not cam or str(cam.societe_id) != str(sid):
            return None, refus({"detail": "Camion invalide."}, status=400)
    try:
        jour = date.fromisoformat(payload.get("date"))
    except (TypeError, ValueError):
        return None, refus({"detail": "date invalide."}, status=422)
    try:
        litres = round(float(payload.get("litres")), 2)
        if litres <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, refus({"detail": "litres > 0 requis."}, status=422)
    prix = payload.get("prix_litre_usd")
    if prix is not None and str(prix) != "":
        try:
            prix = round(float(prix), 3)
            if prix < 0:
                raise ValueError
        except (TypeError, ValueError):
            return None, refus({"detail": "prix_litre_usd invalide."}, status=422)
    else:
        prix = None
    montant = payload.get("montant_usd")
    if montant is not None and str(montant) != "":
        try:
            montant = round(float(montant), 2)
            if montant < 0:
                raise ValueError
        except (TypeError, ValueError):
            return None, refus({"detail": "montant_usd invalide."}, status=422)
    elif prix is not None:
        montant = round(litres * prix, 2)
    else:
        montant = 0
    course_id = None
    if payload.get("course_id"):
        course = Course.objects.filter(id=payload["course_id"]).first()
        if not course or (cam and str(course.camion_id) != str(cam.id)):
            return None, refus({"detail": "Course invalide pour ce camion."},
                               status=400)
        course_id = course.id
    compteur = payload.get("compteur")
    if compteur is not None and str(compteur) != "":
        try:
            compteur = round(float(compteur), 1)
        except (TypeError, ValueError):
            return None, refus({"detail": "compteur invalide."}, status=422)
    else:
        compteur = None
    return {"camion_id": cam.id if cam else None,
            "engin_id": eng.id if eng else None,
            "course_id": course_id, "date_plein": jour, "litres": litres,
            "prix_litre_usd": prix, "montant_usd": montant, "compteur": compteur,
            "fournisseur": (payload.get("fournisseur") or "").strip() or None,
            "note": (payload.get("note") or "").strip() or None}, None


class PleinViewSet(MetierModelViewSet):
    """Ressource Plein ; contrats HTTP et validations métier conservés."""
    queryset = PleinCarburant.objects.none()
    serializer_class = PleinCarburantSerializer
    lookup_url_kwarg = 'plein_id'

    def list(self, request):
        return self._traiter_pleins(request)


    def create(self, request):
        return self._traiter_pleins(request)


    def _traiter_pleins(self, request):
        sid = _societe_param(request)
        _acces(request, sid)
        if request.method == "POST":
            champs, erreur = _lire_plein(request.data or {}, sid)
            if erreur:
                return erreur
            with transaction.atomic():
                p = PleinCarburant.objects.create(
                    societe_id=sid, **champs,
                    created_by=request.user.id, created_at=services.maintenant())
                services.enregistrer_audit(request.user.id, "INSERT",
                                           "plein_carburant", p.id, None,
                                           {"litres": champs["litres"],
                                            "montant_usd": champs["montant_usd"]})
            return Response(_plein_dict(p), status=201)
        q = PleinCarburant.objects.filter(societe_id=sid)
        for cle in ("camion_id", "engin_id"):
            if request.query_params.get(cle):
                q = q.filter(**{cle: request.query_params[cle]})
        du, au = request.query_params.get("du"), request.query_params.get("au")
        if du:
            q = q.filter(date_plein__gte=du)
        if au:
            q = q.filter(date_plein__lte=au)
        return Response([_plein_dict(p)
                         for p in q.order_by("-date_plein", "-created_at")])


    def partial_update(self, request, plein_id):
        return self._traiter_maj_plein(request, plein_id)


    def destroy(self, request, plein_id):
        return self._traiter_maj_plein(request, plein_id)


    def _traiter_maj_plein(self, request, plein_id):
        p = PleinCarburant.objects.filter(id=plein_id).first()
        if not p:
            return refus({"detail": "Plein introuvable."}, status=404)
        _acces(request, p.societe_id)
        if request.method == "DELETE":
            avant = _plein_dict(p)
            with transaction.atomic():
                services.enregistrer_audit(request.user.id, "DELETE",
                                           "plein_carburant", plein_id, avant, None)
                p.delete()
            return Response({"ok": True})
        payload = dict(request.data or {})
        payload.setdefault("camion_id", str(p.camion_id) if p.camion_id else None)
        payload.setdefault("engin_id", str(p.engin_id) if p.engin_id else None)
        payload.setdefault("course_id", str(p.course_id) if p.course_id else None)
        payload.setdefault("date", p.date_plein.isoformat())
        payload.setdefault("litres", float(p.litres))
        payload.setdefault("prix_litre_usd", float(p.prix_litre_usd)
                           if p.prix_litre_usd is not None else None)
        payload.setdefault("montant_usd", float(p.montant_usd or 0))
        payload.setdefault("compteur", float(p.compteur)
                           if p.compteur is not None else None)
        payload.setdefault("fournisseur", p.fournisseur)
        payload.setdefault("note", p.note)
        champs, erreur = _lire_plein(payload, p.societe_id)
        if erreur:
            return erreur
        avant = _plein_dict(p)
        with transaction.atomic():
            for champ, valeur in champs.items():
                setattr(p, champ, valeur)
            p.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "plein_carburant",
                                       p.id, avant, _plein_dict(p))
        return Response(_plein_dict(p))


def _km_periode(camion_id, du, au) -> float:
    q = Course.objects.filter(camion_id=camion_id, heure_depart__isnull=False,
                              km_depart__isnull=False, km_retour__isnull=False) \
        .exclude(statut="annulee")
    if du:
        q = q.filter(date_course__gte=du)
    if au:
        q = q.filter(date_course__lte=au)
    return round(sum(max(0.0, float(c.km_retour) - float(c.km_depart))
                     for c in q), 1)


def _heures_periode(engin_id, du, au, mode) -> float:
    q = PrestationEngin.objects.filter(engin_id=engin_id)
    if du:
        q = q.filter(date_prestation__gte=du)
    if au:
        q = q.filter(date_prestation__lte=au)
    prestations = list(q)
    arrets = engins_lib.arrets_par_prestation([p.id for p in prestations])
    minutes = sum(engins_lib.minutes_prestation(p, arrets.get(p.id, []), mode)
                  for p in prestations)
    return round(minutes / 60, 1)


class CarburantViewSet(MetierViewSet):
    """Ressource Carburant ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def rapport(self, request):
        """Consommation réelle vs théorique par véhicule sur une période."""
        sid = _societe_param(request)
        _acces(request, sid)
        du, au = request.query_params.get("du"), request.query_params.get("au")
        q = PleinCarburant.objects.filter(societe_id=sid)
        if du:
            q = q.filter(date_plein__gte=du)
        if au:
            q = q.filter(date_plein__lte=au)
        par_vehicule: dict = {}
        for p in q:
            cle = ("camion", p.camion_id) if p.camion_id else ("engin", p.engin_id)
            e = par_vehicule.setdefault(cle, {"pleins": 0, "litres": 0.0,
                                              "montant": 0.0})
            e["pleins"] += 1
            e["litres"] = round(e["litres"] + float(p.litres), 2)
            e["montant"] = round(e["montant"] + float(p.montant_usd or 0), 2)

        mode = engins_lib.reglages(sid)["arrondi"]
        rows = []
        totaux = {"pleins": 0, "litres": 0.0, "montant": 0.0, "surconso": 0}
        for (genre, vid), e in par_vehicule.items():
            if genre == "camion":
                v = Camion.objects.filter(id=vid).first()
                nom = v.immatriculation if v else "(camion supprimé)"
                usage = _km_periode(vid, du, au)
                unite = "km"
                theorique = float(v.consommation_l_100km) \
                    if v and v.consommation_l_100km else None
                reelle = round(e["litres"] / usage * 100, 1) if usage else None
                cout_unitaire = round(e["montant"] / usage, 2) if usage else None
            else:
                v = Engin.objects.filter(id=vid).first()
                nom = v.nom if v else "(engin supprimé)"
                usage = _heures_periode(vid, du, au, mode)
                unite = "h"
                theorique = float(v.consommation_l_heure) \
                    if v and v.consommation_l_heure else None
                reelle = round(e["litres"] / usage, 1) if usage else None
                cout_unitaire = round(e["montant"] / usage, 2) if usage else None
            ecart_pct = round((reelle - theorique) / theorique * 100, 1) \
                if (reelle is not None and theorique) else None
            statut = "inconnu"
            if ecart_pct is not None:
                statut = "surconso" if ecart_pct > SEUIL_SURCONSO_PCT else "ok"
            rows.append({"cible": genre, "vehicule": nom,
                         "camion_id": str(vid) if genre == "camion" else None,
                         "engin_id": str(vid) if genre == "engin" else None,
                         "pleins": e["pleins"], "litres": e["litres"],
                         "montant_usd": e["montant"],
                         "usage": usage, "unite": unite,
                         "conso_reelle": reelle, "conso_theorique": theorique,
                         "ecart_pct": ecart_pct, "cout_unitaire": cout_unitaire,
                         "statut": statut})
            totaux["pleins"] += e["pleins"]
            totaux["litres"] = round(totaux["litres"] + e["litres"], 2)
            totaux["montant"] = round(totaux["montant"] + e["montant"], 2)
            if statut == "surconso":
                totaux["surconso"] += 1
        rows.sort(key=lambda r: -r["montant_usd"])
        return Response({"rapport": rows, "totaux": totaux})


# Anciens points d’entrée conservés pour les intégrations existantes.
pleins = PleinViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='plein')
maj_plein = PleinViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'}, http_method_names=['patch', 'delete', 'options'], detail=True, basename='plein')
rapport = CarburantViewSet.as_view({'get': 'rapport'}, http_method_names=['get', 'options'], detail=False, basename='carburant')
