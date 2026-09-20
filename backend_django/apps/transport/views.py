"""Module Transport — portage exact de backend/app/routers/transport.py.

Flotte (camions propres/sous-traités), chauffeurs, contrats-cadres + grilles,
fiches de course PROC-KL-01→04 (validation configurable, départ bloqué sans
avance carburant, retour avec sous-traitance figée, facturation sur livré),
réquisitions liées à tout moment, maintenance immobilisante, rentabilité.
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
from apps.tresorerie.models import Avance, Justification
from apps.transport.models import Camion, Chauffeur, ContratTransport, Course, CourseRequisition, TarifContrat
from apps.commercial.models import Commande, Devis, Facture, LigneFacture
from apps.engins.models import Engin
from apps.maintenance.models import InterventionCamion
from apps.approbations.models import OrdreDepense, Requisition
from core.models import Parametre, Role, Societe, Tiers
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI", "ASSISTANT_TECH", "DG"}
# Interventions de maintenance : accessibles aussi au métier maintenance
# (rôles MAINTENANCIER / DT / ASSISTANT_TECHNIQUE), séparé du dispatching.
ROLES_MAINT = ROLES | {"MAINTENANCIER", "DT", "ASSISTANT_TECHNIQUE"}


def _role_validation(societe_id) -> str:
    return services.get_parametre("transport.role_validation", societe_id, "DFI")


@api_view(["GET", "POST"])
def config_transport(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    if request.method == "POST":
        assert_role(roles, {"DFI", "PRESIDENT", "ADMIN_SYS"})
        payload = request.data or {}
        code = (payload.get("role_validation") or "").strip().upper()
        if len(code) < 2:
            return refus({"detail": "role_validation requis."}, status=422)
        if not Role.objects.filter(code=code).exists():
            return refus({"detail": f"Rôle {code} inconnu."}, status=400)
        p = Parametre.objects.filter(cle="transport.role_validation",
                                     societe_id=sid).first()
        if p:
            p.valeur = code
            p.save(update_fields=["valeur"])
        else:
            Parametre.objects.create(societe_id=sid, cle="transport.role_validation",
                                     valeur=code, type_valeur="string",
                                     description="Rôle validateur des fiches de course")
        services.enregistrer_audit(request.user.id, "CONFIG", "transport", None, None,
                                   {"role_validation": code})
        return Response({"role_validation": code})
    assert_role(roles, ROLES)
    tous = [{"code": r.code, "libelle": r.libelle}
            for r in Role.objects.all().order_by("code")]
    return Response({"role_validation": _role_validation(sid), "roles": tous})


# ═══ Flotte ══════════════════════════════════════════════════════════
def _camion_dict(c: Camion) -> dict:
    prop = Tiers.objects.filter(id=c.proprietaire_tiers_id).first() \
        if c.proprietaire_tiers_id else None
    return {"id": str(c.id), "immatriculation": c.immatriculation, "marque": c.marque,
            "capacite_tonnes": float(c.capacite_tonnes or 0),
            "consommation_l_100km": float(c.consommation_l_100km)
            if c.consommation_l_100km else None,
            "type": c.type, "proprietaire": prop.nom if prop else None,
            "proprietaire_tiers_id": str(c.proprietaire_tiers_id)
            if c.proprietaire_tiers_id else None,
            "remuneration_mode": c.remuneration_mode,
            "remuneration_valeur": float(c.remuneration_valeur)
            if c.remuneration_valeur is not None else None,
            "statut": c.statut, "motif_immobilisation": c.motif_immobilisation,
            "immobilise_depuis": c.immobilise_depuis.isoformat()
            if c.immobilise_depuis else None,
            "actif": bool(c.actif)}


@api_view(["GET", "POST"])
def camions(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    if request.method == "POST":
        payload = request.data or {}
        if payload.get("type") == "sous_traite" \
                and not payload.get("proprietaire_tiers_id"):
            return refus({"detail": "Un camion sous-traité doit avoir un propriétaire "
                                    "(tiers fournisseur)."}, status=400)
        immat = (payload.get("immatriculation") or "").strip().upper()
        if len(immat) < 2:
            return refus({"detail": "immatriculation requise."}, status=422)
        if Camion.objects.filter(societe_id=sid, immatriculation=immat).exists():
            return refus({"detail": f"Le camion {immat} existe déjà."}, status=409)
        c = Camion.objects.create(
            societe_id=sid, immatriculation=immat, marque=payload.get("marque"),
            capacite_tonnes=payload.get("capacite_tonnes", 0),
            consommation_l_100km=payload.get("consommation_l_100km"),
            type=payload.get("type", "propre"),
            proprietaire_tiers_id=payload.get("proprietaire_tiers_id"),
            remuneration_mode=payload.get("remuneration_mode"),
            remuneration_valeur=payload.get("remuneration_valeur"))
        return Response(_camion_dict(c), status=201)
    cs = Camion.objects.filter(societe_id=sid).order_by("immatriculation")
    return Response([_camion_dict(c) for c in cs])


@api_view(["PATCH"])
def maj_camion(request, camion_id):
    c = Camion.objects.filter(id=camion_id).first()
    if not c:
        return refus({"detail": "Camion introuvable."}, status=404)
    roles = assert_acces_societe(request.user, c.societe_id)
    assert_role(roles, ROLES)
    payload = request.data or {}
    for f in ("marque", "capacite_tonnes", "consommation_l_100km",
              "proprietaire_tiers_id", "remuneration_mode", "remuneration_valeur",
              "actif"):
        v = payload.get(f)
        if v is not None:
            setattr(c, f, v)
    c.save()
    return Response(_camion_dict(c))


# ═══ Chauffeurs ══════════════════════════════════════════════════════
@api_view(["GET", "POST"])
def chauffeurs(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    if request.method == "POST":
        payload = request.data or {}
        nom = (payload.get("nom") or "").strip()
        if len(nom) < 2:
            return refus({"detail": "nom requis."}, status=422)
        with transaction.atomic():
            tiers = Tiers.objects.create(societe_id=sid, type="personnel",
                                         code=f"CHF-{nom.upper()[:16]}", nom=nom)
            c = Chauffeur.objects.create(societe_id=sid, nom=nom,
                                         telephone=payload.get("telephone"),
                                         numero_permis=payload.get("numero_permis"),
                                         tiers_id=tiers.id)
        return Response({"id": str(c.id), "nom": c.nom}, status=201)
    return Response([{"id": str(c.id), "nom": c.nom, "telephone": c.telephone,
                      "numero_permis": c.numero_permis, "actif": bool(c.actif)}
                     for c in Chauffeur.objects.filter(societe_id=sid, actif=True)
                     .order_by("nom")])


# ═══ Contrats de transport ═══════════════════════════════════════════
def _contrat_dict(c: ContratTransport) -> dict:
    t = Tiers.objects.filter(id=c.client_tiers_id).first()
    nb = Course.objects.filter(contrat_id=c.id).count()
    return {"id": str(c.id), "numero": c.numero, "libelle": c.libelle,
            "client": t.nom if t else None, "client_tiers_id": str(c.client_tiers_id),
            "intra_groupe": bool(t and t.societe_liee_id),
            "date_debut": c.date_debut.isoformat(),
            "date_fin": c.date_fin.isoformat() if c.date_fin else None,
            "statut": c.statut, "note": c.note, "nb_courses": nb,
            "tarifs": [{"id": str(x.id), "trajet": x.trajet, "mode": x.mode,
                        "prix": float(x.prix)}
                       for x in TarifContrat.objects.filter(contrat_id=c.id)]}


@api_view(["GET", "POST"])
def contrats(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    if request.method == "POST":
        payload = request.data or {}
        societe = Societe.objects.filter(id=sid).first()
        tiers = Tiers.objects.filter(id=payload.get("client_tiers_id")).first()
        if not tiers_disponible(tiers, sid) or tiers.type != "client":
            return refus({"detail": "Sélectionnez un client."}, status=400)
        if not payload.get("date_debut") or len((payload.get("libelle") or "")
                                                .strip()) < 2:
            return refus({"detail": "libelle et date_debut requis."}, status=422)
        with transaction.atomic():
            debut = date.fromisoformat(payload["date_debut"])
            c = ContratTransport.objects.create(
                societe_id=sid,
                numero=services.next_numero("contrat_transport", debut.year,
                                            societe.code, societe.id),
                libelle=payload["libelle"].strip(), client_tiers_id=tiers.id,
                date_debut=debut,
                date_fin=date.fromisoformat(payload["date_fin"])
                if payload.get("date_fin") else None,
                note=(payload.get("note") or "").strip() or None,
                created_by=request.user.id, created_at=services.maintenant())
            for t in payload.get("tarifs") or []:
                TarifContrat.objects.create(contrat_id=c.id,
                                            trajet=(t.get("trajet") or "").strip(),
                                            mode=t.get("mode", "tonne"),
                                            prix=t.get("prix", 0))
        return Response(_contrat_dict(c), status=201)
    cs = ContratTransport.objects.filter(societe_id=sid).order_by("-created_at")
    return Response([_contrat_dict(c) for c in cs])


@api_view(["PUT"])
def modifier_contrat(request, contrat_id):
    c = ContratTransport.objects.filter(id=contrat_id).first()
    if not c:
        return refus({"detail": "Contrat introuvable."}, status=404)
    roles = assert_acces_societe(request.user, c.societe_id)
    assert_role(roles, ROLES)
    payload = request.data or {}
    with transaction.atomic():
        c.libelle = (payload.get("libelle") or "").strip()
        c.client_tiers_id = payload.get("client_tiers_id")
        c.date_debut = date.fromisoformat(payload["date_debut"])
        c.date_fin = date.fromisoformat(payload["date_fin"]) \
            if payload.get("date_fin") else None
        c.note = (payload.get("note") or "").strip() or None
        c.save()
        TarifContrat.objects.filter(contrat_id=c.id).delete()
        for t in payload.get("tarifs") or []:
            TarifContrat.objects.create(contrat_id=c.id,
                                        trajet=(t.get("trajet") or "").strip(),
                                        mode=t.get("mode", "tonne"),
                                        prix=t.get("prix", 0))
    return Response(_contrat_dict(c))


# ═══ Fiches de course ════════════════════════════════════════════════
def _recette(c: Course) -> float:
    base = float(c.tonnage_livre if c.tonnage_livre is not None else c.tonnage_prevu)
    return round(base * float(c.prix_unitaire), 2) if c.tarif_mode == "tonne" \
        else round(float(c.prix_unitaire), 2)


def _reqs_course(c: Course) -> list[Requisition]:
    ids = list(CourseRequisition.objects.filter(course_id=c.id)
               .values_list("requisition_id", flat=True))
    return [r for r in (Requisition.objects.filter(id=i).first() for i in ids) if r]


def _frais_course(c: Course) -> float:
    """Frais de route réels : justifications des avances de TOUTES les réquisitions."""
    req_ids = [r.id for r in _reqs_course(c)]
    if not req_ids:
        return 0.0
    total = Justification.objects.filter(
        avance_id__in=Avance.objects.filter(
            ordre_depense_id__in=OrdreDepense.objects.filter(
                requisition_id__in=req_ids).values("id")).values("id")
    ).aggregate(t=Sum("montant_justifie_usd"))["t"]
    return round(float(total or 0), 2)


def _course_dict(c: Course) -> dict:
    cam = Camion.objects.filter(id=c.camion_id).first() if c.camion_id else None
    chf = Chauffeur.objects.filter(id=c.chauffeur_id).first() if c.chauffeur_id else None
    cli = Tiers.objects.filter(id=c.client_tiers_id).first()
    ctr = ContratTransport.objects.filter(id=c.contrat_id).first() \
        if c.contrat_id else None
    fac = Facture.objects.filter(id=c.facture_id).first() if c.facture_id else None
    stf = Facture.objects.filter(id=c.st_facture_id).first() if c.st_facture_id else None
    reqs = _reqs_course(c)
    recette = _recette(c)
    frais = _frais_course(c)
    st = float(c.st_cout or 0)
    cmd = Commande.objects.filter(id=c.commande_origine_id).first() \
        if c.commande_origine_id else None
    deblocable = True
    vendeur_statut = None
    reception_po = None
    if c.statut == "demande" and cmd and cmd.devis_lie_id:
        dv = Devis.objects.filter(id=cmd.devis_lie_id).first()
        vendeur_statut = dv.statut if dv else None
        deblocable = bool(dv and dv.statut == "confirme")
    etapes_po = None
    if cmd:
        etapes_po = intersociete_lib.etapes_po(cmd)
        r = intersociete_lib.reception_po_resume(cmd)
        reception_po = {"recu": round(r["totaux"]["bon"] + r["totaux"]["mauvais"], 3),
                        "manquant": r["totaux"]["manquant"],
                        "livre": r["totaux"]["livre"], "complete": r["complete"],
                        "valeur_manquants_usd": r["valeur_manquants_usd"],
                        "toutes_confirmees": r["toutes_confirmees"],
                        "a_confirmer": [x for x in r["receptions"]
                                        if x["statut"] == "a_confirmer"]}
    return {"id": str(c.id), "numero": c.numero, "statut": c.statut,
            "date": c.date_course.isoformat(),
            "client": cli.nom if cli else None,
            "client_tiers_id": str(c.client_tiers_id),
            "intra_groupe": bool(cli and cli.societe_liee_id),
            "contrat": ctr.libelle if ctr else None,
            "contrat_id": str(c.contrat_id) if c.contrat_id else None,
            "camion": cam.immatriculation if cam else None,
            "camion_id": str(c.camion_id),
            "camion_type": cam.type if cam else None,
            "chauffeur": chf.nom if chf else None,
            "chauffeur_id": str(c.chauffeur_id) if c.chauffeur_id else None,
            "origine": c.origine, "destination": c.destination,
            "marchandise": c.marchandise,
            "tonnage_prevu": float(c.tonnage_prevu),
            "tonnage_livre": float(c.tonnage_livre)
            if c.tonnage_livre is not None else None,
            "unite": c.unite or "tonnes",
            "tarif_mode": c.tarif_mode, "prix_unitaire": float(c.prix_unitaire),
            "recette_usd": recette, "frais_route_usd": frais,
            "st_mode": c.st_mode,
            "st_valeur": float(c.st_valeur) if c.st_valeur is not None else None,
            "st_cout_usd": st, "st_facture": stf.numero if stf else None,
            "marge_usd": round(recette - frais - st, 2)
            if c.statut in ("livree", "facturee") else None,
            "heure_depart": c.heure_depart.isoformat() if c.heure_depart else None,
            "heure_retour": c.heure_retour.isoformat() if c.heure_retour else None,
            "km_depart": float(c.km_depart) if c.km_depart is not None else None,
            "km_retour": float(c.km_retour) if c.km_retour is not None else None,
            "incidents": c.incidents,
            "requisitions": [{"id": str(r.id), "numero": r.numero, "statut": r.statut}
                             for r in reqs],
            "commande_origine": cmd.numero if cmd else None,
            "reference_producteur": cmd.reference_fournisseur if cmd else None,
            "deblocable": deblocable, "vendeur_statut": vendeur_statut,
            "reception_po": reception_po, "etapes_po": etapes_po,
            "facture": fac.numero if fac else None}


def _course_ou_404(request, course_id):
    c = Course.objects.filter(id=course_id).first()
    if not c:
        return None, None
    roles = assert_acces_societe(request.user, c.societe_id)
    assert_role(roles, ROLES)
    return c, roles


@api_view(["GET", "POST"])
def courses(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    if request.method == "POST":
        payload = request.data or {}
        societe = Societe.objects.filter(id=sid).first()
        cam = Camion.objects.filter(id=payload.get("camion_id")).first()
        if not cam or str(cam.societe_id) != str(sid) or not cam.actif:
            return refus({"detail": "Camion invalide."}, status=400)
        cli = Tiers.objects.filter(id=payload.get("client_tiers_id")).first()
        if not tiers_disponible(cli, sid) or cli.type != "client":
            return refus({"detail": "Sélectionnez un client."}, status=400)
        if not payload.get("tonnage_prevu") or float(payload["tonnage_prevu"]) <= 0 \
                or not (payload.get("origine") or "").strip() \
                or not (payload.get("destination") or "").strip() \
                or not (payload.get("marchandise") or "").strip():
            return refus({"detail": "origine, destination, marchandise et tonnage > 0 "
                                    "requis."}, status=422)
        with transaction.atomic():
            jour = date.fromisoformat(payload["date_course"]) \
                if payload.get("date_course") else date.today()
            c = Course.objects.create(
                societe_id=sid,
                numero=services.next_numero("course", jour.year, societe.code,
                                            societe.id),
                date_course=jour, client_tiers_id=cli.id,
                contrat_id=payload.get("contrat_id"), camion_id=cam.id,
                chauffeur_id=payload.get("chauffeur_id"),
                origine=payload["origine"].strip(),
                destination=payload["destination"].strip(),
                marchandise=payload["marchandise"].strip(),
                tonnage_prevu=payload["tonnage_prevu"],
                unite=(payload.get("unite") or "tonnes").strip(),
                tarif_mode=payload.get("tarif_mode", "tonne"),
                prix_unitaire=payload.get("prix_unitaire", 0),
                requisition_id=payload.get("requisition_id"),
                created_by=request.user.id, created_at=services.maintenant())
            if payload.get("requisition_id"):
                CourseRequisition.objects.create(
                    course_id=c.id, requisition_id=payload["requisition_id"])
            services.enregistrer_audit(request.user.id, "INSERT", "course", c.id, None,
                                       {"numero": c.numero,
                                        "camion": cam.immatriculation})
        return Response(_course_dict(c), status=201)
    q = Course.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    return Response([_course_dict(c) for c in q.order_by("-created_at")])


@api_view(["POST"])
def prendre_en_charge(request, course_id):
    """Une demande de course (PO intersociété) devient une fiche brouillon."""
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut != "demande":
        return refus({"detail": "Cette course n'est pas une demande en attente."},
                     status=409)
    if c.commande_origine_id:
        cmd = Commande.objects.filter(id=c.commande_origine_id).first()
        dv = Devis.objects.filter(id=cmd.devis_lie_id).first() \
            if cmd and cmd.devis_lie_id else None
        if dv and dv.statut == "annule":
            return refus({"detail": "La commande d'origine a été annulée par le "
                                    "vendeur."}, status=409)
        if not dv or dv.statut != "confirme":
            return refus({"detail": "En attente : le vendeur n'a pas encore confirmé "
                                    "la commande — la course sera prenable en charge "
                                    "dès sa confirmation."}, status=409)
    payload = request.data or {}
    cam = Camion.objects.filter(id=payload.get("camion_id")).first()
    if not cam or str(cam.societe_id) != str(c.societe_id) or not cam.actif:
        return refus({"detail": "Camion invalide."}, status=400)
    with transaction.atomic():
        c.camion_id = cam.id
        c.chauffeur_id = payload.get("chauffeur_id")
        c.contrat_id = payload.get("contrat_id")
        if payload.get("tonnage_prevu"):
            c.tonnage_prevu = payload["tonnage_prevu"]
        if payload.get("unite"):
            c.unite = payload["unite"].strip()
        c.tarif_mode = payload.get("tarif_mode", "tonne")
        c.prix_unitaire = payload.get("prix_unitaire", 0)
        if payload.get("origine"):
            c.origine = payload["origine"].strip()
        if payload.get("destination"):
            c.destination = payload["destination"].strip()
        if payload.get("requisition_id"):
            CourseRequisition.objects.create(course_id=c.id,
                                             requisition_id=payload["requisition_id"])
        c.statut = "brouillon"
        c.save()
        services.enregistrer_audit(request.user.id, "PRISE_EN_CHARGE", "course", c.id,
                                   None, {"numero": c.numero,
                                          "camion": cam.immatriculation})
    return Response(_course_dict(c))


@api_view(["POST"])
def lier_requisition(request, course_id):
    """Rattache une réquisition à la course — à tout moment (PROC-KL-02)."""
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut in ("facturee", "annulee"):
        return refus({"detail": "Course clôturée — plus de rattachement possible."},
                     status=409)
    req = Requisition.objects.filter(id=(request.data or {}).get("requisition_id")).first()
    if not req or str(req.societe_id) != str(c.societe_id):
        return refus({"detail": "Réquisition invalide pour cette société."}, status=400)
    if CourseRequisition.objects.filter(course_id=c.id, requisition_id=req.id).exists():
        return refus({"detail": f"{req.numero} est déjà rattachée à cette course."},
                     status=409)
    CourseRequisition.objects.create(course_id=c.id, requisition_id=req.id)
    services.enregistrer_audit(request.user.id, "LIEN", "course", c.id, None,
                               {"numero": c.numero, "requisition": req.numero})
    return Response(_course_dict(c))


@api_view(["POST"])
def valider_course(request, course_id):
    """Validation de la fiche course par le rôle validateur configuré."""
    c, roles = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    role_requis = _role_validation(c.societe_id)
    if role_requis not in roles:
        return refus({"detail": f"La validation des fiches de course est réservée au "
                                f"rôle {role_requis} (modifiable dans les réglages "
                                f"transport)."}, status=403)
    if c.statut != "brouillon":
        return refus({"detail": "Seule une fiche brouillon se valide."}, status=409)
    c.statut = "validee"
    c.valide_par = request.user.id
    c.save(update_fields=["statut", "valide_par"])
    services.enregistrer_audit(request.user.id, "VALIDATION", "course", c.id, None,
                               {"numero": c.numero})
    return Response(_course_dict(c))


@api_view(["POST"])
def depart_course(request, course_id):
    """Départ : bloqué si camion indisponible ou avance carburant non décaissée."""
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut != "validee":
        return refus({"detail": "La fiche doit d'abord être validée par le DFI."},
                     status=409)
    cam = Camion.objects.filter(id=c.camion_id).first()
    if cam.statut == "immobilise":
        return refus({"detail": f"Camion {cam.immatriculation} immobilisé "
                                f"({cam.motif_immobilisation or 'maintenance'}) — "
                                f"inaffectable."}, status=409)
    if cam.statut == "en_course":
        return refus({"detail": f"Camion {cam.immatriculation} déjà en course."},
                     status=409)
    req_ids = [r.id for r in _reqs_course(c)]
    if req_ids:
        avance = Avance.objects.filter(
            ordre_depense_id__in=OrdreDepense.objects.filter(
                requisition_id__in=req_ids).values("id")).first()
        if not avance:
            return refus({"detail": "L'avance carburant liée n'est pas encore "
                                    "décaissée — pas de départ sans carburant mis "
                                    "(PROC-KL-02)."}, status=409)
    # Course d'un PO du groupe : pas de départ tant que le vendeur n'a pas
    # déclaré le chargement (l'étape « Chargement » précède le départ)
    if c.commande_origine_id:
        cmd_po = Commande.objects.filter(id=c.commande_origine_id).first()
        if cmd_po:
            r = intersociete_lib.reception_po_resume(cmd_po)
            if r["totaux"]["livre"] <= 0:
                fourn = Tiers.objects.filter(id=cmd_po.tiers_id).first()
                vendeur = Societe.objects.filter(id=fourn.societe_liee_id).first() \
                    if fourn and fourn.societe_liee_id else None
                return refus({"detail": f"Départ bloqué : le vendeur "
                                        f"({vendeur.nom if vendeur else '?'}) n'a pas "
                                        f"encore déclaré le chargement de la "
                                        f"marchandise."}, status=409)
    c.statut = "en_cours"
    c.heure_depart = services.maintenant()
    km = (request.data or {}).get("km_depart")
    if km is not None and str(km) != "":
        try:
            c.km_depart = round(float(km), 1)
        except (TypeError, ValueError):
            return refus({"detail": "km_depart invalide."}, status=422)
    c.save(update_fields=["statut", "heure_depart", "km_depart"])
    cam.statut = "en_course"
    cam.save(update_fields=["statut"])
    services.enregistrer_audit(request.user.id, "DEPART", "course", c.id, None,
                               {"numero": c.numero})
    return Response(_course_dict(c))


@api_view(["POST"])
def arrivee_course(request, course_id):
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut != "en_cours":
        return refus({"detail": "La course n'est pas en route."}, status=409)
    c.statut = "arrivee"
    c.save(update_fields=["statut"])
    services.enregistrer_audit(request.user.id, "ARRIVEE", "course", c.id, None,
                               {"numero": c.numero})
    return Response(_course_dict(c))


@api_view(["POST"])
def retour_course(request, course_id):
    """Clôture au retour (PROC-KL-03) : tonnage livré, sous-traitance figée."""
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut not in ("en_cours", "arrivee", "receptionnee"):
        return refus({"detail": "La course n'est pas en cours."}, status=409)
    # Course d'un PO : le retour se déclare après l'arrivée (étapes dans l'ordre)
    if c.commande_origine_id and c.statut == "en_cours":
        return refus({"detail": "Retour bloqué : signalez d'abord l'arrivée à "
                                "destination (le déchargement et la réception de "
                                "l'acheteur précèdent le retour)."}, status=409)
    payload = request.data or {}
    if not payload.get("tonnage_livre") or float(payload["tonnage_livre"]) <= 0:
        return refus({"detail": "tonnage_livre > 0 requis."}, status=422)
    cam = Camion.objects.filter(id=c.camion_id).first()
    km = payload.get("km_retour")
    if km is not None and str(km) != "":
        try:
            km = round(float(km), 1)
        except (TypeError, ValueError):
            return refus({"detail": "km_retour invalide."}, status=422)
        if c.km_depart is not None and km < float(c.km_depart):
            return refus({"detail": f"km_retour ({km}) inférieur au compteur de "
                                    f"départ ({float(c.km_depart)})."}, status=422)
    else:
        km = None
    with transaction.atomic():
        c.tonnage_livre = payload["tonnage_livre"]
        c.incidents = (payload.get("incidents") or "").strip() or None
        c.heure_retour = services.maintenant()
        if km is not None:
            c.km_retour = km
        c.statut = "livree"
        cam.statut = "disponible"

        # ── Sous-traitance : coût figé + facture fournisseur (dette 401) ──
        if cam.type == "sous_traite":
            mode = payload.get("st_mode") or cam.remuneration_mode
            valeur = payload["st_valeur"] if payload.get("st_valeur") is not None else (
                float(cam.remuneration_valeur)
                if cam.remuneration_valeur is not None else None)
            if not mode or valeur is None:
                return refus({"detail": "Camion sous-traité : précisez la rémunération "
                                        "(forfait ou % du prix client)."}, status=400)
            recette = _recette(c)
            cout = round(float(valeur), 2) if mode == "forfait" \
                else round(recette * float(valeur) / 100, 2)
            c.st_mode, c.st_valeur, c.st_cout = mode, valeur, cout
            prop = Tiers.objects.filter(id=cam.proprietaire_tiers_id).first()
            societe = Societe.objects.filter(id=c.societe_id).first()
            numero = services.next_numero("facture_achat", date.today().year,
                                          societe.code, societe.id)
            fa = Facture.objects.create(
                societe_id=c.societe_id, type="achat", numero=numero, tiers_id=prop.id,
                date_facture=date.today(), reference=c.numero, total_ht=cout,
                total_ttc=cout, statut="validee", created_by=request.user.id,
                created_at=services.maintenant())
            LigneFacture.objects.create(
                facture_id=fa.id, designation=(
                    f"Sous-traitance transport {c.numero} — camion "
                    f"{cam.immatriculation} ({c.origine} → {c.destination})"),
                qte=1, prix_unitaire=cout, taux_tva=0, montant_ht=cout, montant_tva=0)
            cpt_st = comptabilite._compte("compte_sous_traitance", c.societe_id)
            ecr = comptabilite.post_ecriture(
                c.societe_id, "AC", "Achats", "achat", date.today(),
                f"Sous-traitance {c.numero} — {prop.nom}",
                [{"sens": "D", "compte": cpt_st, "montant_usd": cout,
                  "libelle": f"Sous-traitance {c.numero} ({cam.immatriculation})"},
                 {"sens": "C",
                  "compte": comptabilite._compte("compte_fournisseur", c.societe_id),
                  "montant_usd": cout, "tiers_id": prop.id,
                  "libelle": f"Dû à {prop.nom} — {c.numero}"}],
                "sous_traitance", "facture", fa.id, numero, request.user.id,
                statut="valide")
            fa.ecriture_id = ecr.id
            fa.save(update_fields=["ecriture_id"])
            c.st_facture_id = fa.id
        c.save()
        cam.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "RETOUR", "course", c.id, None,
                                   {"numero": c.numero,
                                    "tonnage": payload["tonnage_livre"]})
    return Response(_course_dict(c))


@api_view(["POST"])
def annuler_course(request, course_id):
    """Annulation d'une course. Avant le départ : simple. UNE COURSE PARTIE
    (en cours / arrivée) peut aussi être interrompue — avec un MOTIF obligatoire,
    tant qu'aucune réception n'a été constatée : le camion est libéré et, pour un
    PO du groupe, une NOUVELLE demande de course est recréée automatiquement chez
    le transporteur pour réorganiser le transport."""
    c, _ = _course_ou_404(request, course_id)
    if not c:
        return refus({"detail": "Course introuvable."}, status=404)
    if c.statut in ("receptionnee", "livree", "facturee", "annulee"):
        return refus({"detail": "Cette course ne s'annule plus : la marchandise a "
                                "été réceptionnée ou la course est clôturée."},
                     status=409)
    payload = request.data or {}
    entamee = c.statut in ("en_cours", "arrivee")
    motif = (payload.get("motif") or "").strip()
    if entamee:
        if not motif:
            return refus({"detail": "Course déjà partie : un motif d'annulation est "
                                    "obligatoire (panne, incident, retour à vide…)."},
                         status=400)
        if c.commande_origine_id:
            cmd_po = Commande.objects.filter(id=c.commande_origine_id).first()
            if cmd_po:
                r = intersociete_lib.reception_po_resume(cmd_po)
                t = r["totaux"]
                if t["bon"] + t["mauvais"] + t["manquant"] > 0:
                    return refus({"detail": "Annulation impossible : l'acheteur a "
                                            "déjà constaté une réception sur cette "
                                            "course."}, status=409)
    with transaction.atomic():
        c.statut = "annulee"
        if motif:
            c.incidents = (f"{c.incidents} · " if c.incidents else "") \
                + f"ANNULÉE : {motif}"
        c.save(update_fields=["statut", "incidents"])
        # libère le camion s'il était en route
        if entamee and c.camion_id:
            cam = Camion.objects.filter(id=c.camion_id).first()
            if cam and cam.statut == "en_course":
                cam.statut = "disponible"
                cam.save(update_fields=["statut"])
        # PO du groupe encore actif → nouvelle demande de course automatique
        nouvelle = None
        if c.commande_origine_id:
            cmd_po = Commande.objects.filter(id=c.commande_origine_id).first()
            if cmd_po and cmd_po.statut not in ("soldee", "annulee"):
                societe = Societe.objects.filter(id=c.societe_id).first()
                nouvelle = Course.objects.create(
                    societe_id=c.societe_id,
                    numero=services.next_numero("course", date.today().year,
                                                societe.code, societe.id),
                    date_course=date.today(), client_tiers_id=c.client_tiers_id,
                    camion_id=None, origine=c.origine, destination=c.destination,
                    marchandise=c.marchandise, tonnage_prevu=c.tonnage_prevu,
                    unite=c.unite, tarif_mode=c.tarif_mode,
                    prix_unitaire=c.prix_unitaire, statut="demande",
                    commande_origine_id=c.commande_origine_id,
                    created_by=request.user.id, created_at=services.maintenant())
        services.enregistrer_audit(request.user.id, "ANNULATION", "course", c.id, None,
                                   {"numero": c.numero, "motif": motif or None,
                                    "nouvelle_demande": nouvelle.numero
                                    if nouvelle else None})
    out = _course_dict(c)
    if nouvelle:
        out["nouvelle_demande"] = nouvelle.numero
    return Response(out)


@api_view(["POST"])
def facturer_courses(request):
    """Facture une ou plusieurs courses livrées d'un même client (PROC-KL-04)."""
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    payload = request.data or {}
    if not payload.get("course_ids"):
        return refus({"detail": "Sélectionnez au moins une course."}, status=400)
    courses_l = [Course.objects.filter(id=cid).first()
                 for cid in payload["course_ids"]]
    for c in courses_l:
        if not c or str(c.societe_id) != str(sid):
            return refus({"detail": "Course invalide."}, status=400)
        if c.statut != "livree":
            return refus({"detail": f"{c.numero} : seule une course livrée se facture "
                                    f"(statut {c.statut})."}, status=409)
    clients = {c.client_tiers_id for c in courses_l}
    if len(clients) > 1:
        return refus({"detail": "Une facture regroupe des courses d'un même client."},
                     status=400)
    # Course issue d'un PO : facturation après réception acheteur confirmée
    for c in courses_l:
        if c.commande_origine_id:
            cmd_po = Commande.objects.filter(id=c.commande_origine_id).first()
            r = intersociete_lib.reception_po_resume(cmd_po) if cmd_po else None
            if not r or r["totaux"]["bon"] + r["totaux"]["mauvais"] \
                    + r["totaux"]["manquant"] <= 0:
                return refus({"detail": f"{c.numero} : facturation bloquée — l'acheteur "
                                        f"n'a pas encore réceptionné la marchandise "
                                        f"(le transport se facture sur le reçu)."},
                             status=409)
            if not r["toutes_confirmees"]:
                return refus({"detail": f"{c.numero} : facturation bloquée — confirmez "
                                        f"d'abord la réception de l'acheteur (bouton "
                                        f"« Confirmer la réception » sur la course)."},
                             status=409)
    societe = Societe.objects.filter(id=sid).first()
    tiers = Tiers.objects.filter(id=courses_l[0].client_tiers_id).first()
    jour = date.today()
    tva_taux = float(services.get_parametre("tva.taux_defaut", sid, "16"))
    statut_piece = intersociete_lib._statut_piece(sid, "vente")
    with transaction.atomic():
        numero = services.next_numero("facture_vente", jour.year, societe.code,
                                      societe.id)
        fac = Facture.objects.create(
            societe_id=sid, type="vente", numero=numero, tiers_id=tiers.id,
            date_facture=jour,
            echeance=date.fromisoformat(payload["echeance"])
            if payload.get("echeance") else None,
            statut="validee" if statut_piece == "valide" else "en_attente",
            created_by=request.user.id, created_at=services.maintenant())

        total_ht = total_tva = cout_total = 0.0
        for c in courses_l:
            ht = _recette(c)
            tva = round(ht * tva_taux / 100, 2)
            cam = Camion.objects.filter(id=c.camion_id).first()
            des = (f"Transport {c.marchandise} — {c.origine} → {c.destination} "
                   f"({c.numero}, camion {cam.immatriculation}, "
                   f"{float(c.tonnage_livre or 0):g} t)")
            LigneFacture.objects.create(facture_id=fac.id, designation=des, qte=1,
                                        prix_unitaire=ht, taux_tva=tva_taux,
                                        montant_ht=ht, montant_tva=tva)
            total_ht += ht
            total_tva += tva
            cout_total += float(c.st_cout or 0) + _frais_course(c)
            c.statut = "facturee"
            c.facture_id = fac.id
            c.save(update_fields=["statut", "facture_id"])
        fac.total_ht = round(total_ht, 2)
        fac.total_tva = round(total_tva, 2)
        fac.total_ttc = round(total_ht + total_tva, 2)
        fac.cout_ventes = round(cout_total, 2)
        fac.marge = round(fac.total_ht - cout_total, 2)

        # Écriture : D 411 / C 706 (+ C 4431)
        cpt_produit = comptabilite._compte("compte_vente_transport", sid)
        lignes = [{"sens": "D", "compte": comptabilite._compte("compte_client", sid),
                   "montant_usd": float(fac.total_ttc), "tiers_id": tiers.id,
                   "libelle": f"Client {tiers.nom} — {numero}"},
                  {"sens": "C", "compte": cpt_produit,
                   "montant_usd": float(fac.total_ht),
                   "libelle": f"Produits de transport {numero}"}]
        if float(fac.total_tva):
            lignes.append({"sens": "C",
                           "compte": comptabilite._compte("tva_collectee", sid),
                           "montant_usd": float(fac.total_tva),
                           "libelle": f"TVA collectée {numero}"})
        ecr = comptabilite.post_ecriture(sid, "VE", "Ventes", "vente", jour,
                                         f"Facture transport {numero} — {tiers.nom}",
                                         lignes, "facture_vente", "facture", fac.id,
                                         numero, request.user.id, statut=statut_piece)
        fac.ecriture_id = ecr.id
        fac.save()
        # Intersociété : client du groupe → miroir achat chez lui
        intersociete_lib.creer_facture_miroir(fac, request.user.id)
        services.enregistrer_audit(request.user.id, "INSERT", "facture", fac.id, None,
                                   {"numero": numero,
                                    "courses": [c.numero for c in courses_l]})
    return Response({"facture": {"id": str(fac.id), "numero": numero,
                                 "total_ttc": float(fac.total_ttc),
                                 "intra_groupe": bool(fac.intra_groupe)},
                     "courses": [_course_dict(c) for c in courses_l]}, status=201)


# ═══ Maintenance mutualisée camions + engins (PROC-KL-05/06) ═════════
def _cible_intervention(i: InterventionCamion):
    """Le véhicule concerné : (objet, "camion"|"engin", libellé)."""
    if i.camion_id:
        cam = Camion.objects.filter(id=i.camion_id).first()
        return cam, "camion", (cam.immatriculation if cam else None)
    eng = Engin.objects.filter(id=i.engin_id).first()
    return eng, "engin", (eng.nom if eng else None)


def _immobiliser(cible, type_, description):
    cible.statut = "immobilise"
    cible.motif_immobilisation = f"{type_} — {description[:80]}"
    cible.immobilise_depuis = date.today()
    cible.save(update_fields=["statut", "motif_immobilisation",
                              "immobilise_depuis"])


def _intervention_dict(i: InterventionCamion) -> dict:
    cible, genre, libelle = _cible_intervention(i)
    req = Requisition.objects.filter(id=i.requisition_id).first() \
        if i.requisition_id else None
    return {"id": str(i.id), "numero": i.numero, "type": i.type, "statut": i.statut,
            "cible": genre, "vehicule": libelle,
            "camion": libelle if genre == "camion" else None,
            "camion_id": str(i.camion_id) if i.camion_id else None,
            "engin_id": str(i.engin_id) if i.engin_id else None,
            "description": i.description, "prestataire": i.prestataire,
            "cout_estime": float(i.cout_estime) if i.cout_estime is not None else None,
            "cout_reel": float(i.cout_reel) if i.cout_reel is not None else None,
            "immobilise": bool(i.immobilise),
            "date_prevue": i.date_prevue.isoformat() if i.date_prevue else None,
            "date_signalement": i.date_signalement.isoformat(),
            "date_fin": i.date_fin.isoformat() if i.date_fin else None,
            "requisition": req.numero if req else None}


@api_view(["GET", "POST"])
def interventions(request):
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES_MAINT)
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
        cible, libelle = (cam, cam.immatriculation) if cam else (eng, eng.nom)
        if len((payload.get("description") or "").strip()) < 3:
            return refus({"detail": "description requise."}, status=422)
        # Planification : une date prévue crée l'intervention en attente,
        # sans immobiliser — l'immobilisation se fait au démarrage.
        date_prevue = None
        if payload.get("date_prevue"):
            try:
                date_prevue = date.fromisoformat(payload["date_prevue"])
            except ValueError:
                return refus({"detail": "date_prevue invalide."}, status=422)
        planifiee = bool(date_prevue and date_prevue > date.today())
        immobilise = payload.get("immobilise", True)
        if immobilise and not planifiee and cam and cam.statut == "en_course":
            return refus({"detail": f"{cam.immatriculation} est en course — clôturez "
                                    f"la course avant d'immobiliser."}, status=409)
        societe = Societe.objects.filter(id=sid).first()
        with transaction.atomic():
            i = InterventionCamion.objects.create(
                societe_id=sid,
                camion_id=cam.id if cam else None,
                engin_id=eng.id if eng else None,
                numero=services.next_numero("intervention", date.today().year,
                                            societe.code, societe.id),
                type=payload.get("type", "reparation"),
                description=payload["description"].strip(),
                prestataire=(payload.get("prestataire") or "").strip() or None,
                cout_estime=payload.get("cout_estime"), immobilise=immobilise,
                date_signalement=date.today(), date_prevue=date_prevue,
                requisition_id=payload.get("requisition_id"),
                statut="planifiee" if planifiee else "en_cours",
                created_by=request.user.id,
                created_at=services.maintenant())
            if immobilise and not planifiee:
                _immobiliser(cible, payload.get("type", "reparation"),
                             payload["description"].strip())
            services.enregistrer_audit(request.user.id, "INSERT", "intervention", i.id,
                                       None, {"vehicule": libelle,
                                              "type": payload.get("type", "reparation"),
                                              "statut": i.statut})
        return Response(_intervention_dict(i), status=201)
    q = InterventionCamion.objects.filter(societe_id=sid)
    camion_id = request.query_params.get("camion_id")
    if camion_id:
        q = q.filter(camion_id=camion_id)
    engin_id = request.query_params.get("engin_id")
    if engin_id:
        q = q.filter(engin_id=engin_id)
    cible = request.query_params.get("cible")
    if cible == "camion":
        q = q.filter(camion_id__isnull=False)
    elif cible == "engin":
        q = q.filter(engin_id__isnull=False)
    return Response([_intervention_dict(i) for i in q.order_by("-created_at")])


@api_view(["POST"])
def demarrer_intervention(request, intervention_id):
    """Démarre une intervention planifiée (immobilise le véhicule si demandé)."""
    i = InterventionCamion.objects.filter(id=intervention_id).first()
    if not i:
        return refus({"detail": "Intervention introuvable."}, status=404)
    roles = assert_acces_societe(request.user, i.societe_id)
    assert_role(roles, ROLES_MAINT)
    if i.statut != "planifiee":
        return refus({"detail": "Seule une intervention planifiée peut être "
                                "démarrée."}, status=409)
    cible, genre, libelle = _cible_intervention(i)
    if not cible:
        return refus({"detail": "Véhicule introuvable."}, status=404)
    if i.immobilise and genre == "camion" and cible.statut == "en_course":
        return refus({"detail": f"{libelle} est en course — clôturez la course "
                                f"avant d'immobiliser."}, status=409)
    with transaction.atomic():
        i.statut = "en_cours"
        i.save(update_fields=["statut"])
        if i.immobilise:
            _immobiliser(cible, i.type, i.description)
        services.enregistrer_audit(request.user.id, "UPDATE", "intervention", i.id,
                                   None, {"numero": i.numero, "statut": "en_cours"})
    return Response(_intervention_dict(i))


@api_view(["POST"])
def terminer_intervention(request, intervention_id):
    """Remise en service (PROC-KL-06)."""
    i = InterventionCamion.objects.filter(id=intervention_id).first()
    if not i:
        return refus({"detail": "Intervention introuvable."}, status=404)
    roles = assert_acces_societe(request.user, i.societe_id)
    assert_role(roles, ROLES_MAINT)
    if i.statut == "terminee":
        return refus({"detail": "Déjà terminée."}, status=409)
    payload = request.data or {}
    i.statut = "terminee"
    i.date_fin = date.today()
    if payload.get("cout_reel") is not None:
        i.cout_reel = payload["cout_reel"]
    elif i.requisition_id:
        total = Justification.objects.filter(
            avance_id__in=Avance.objects.filter(
                ordre_depense_id__in=OrdreDepense.objects.filter(
                    requisition_id=i.requisition_id).values("id")).values("id")
        ).aggregate(t=Sum("montant_justifie_usd"))["t"]
        i.cout_reel = round(float(total or 0), 2) or None
    i.save()
    cible, genre, _libelle = _cible_intervention(i)
    # Entretien issu d'un plan : la clôture fige la « dernière exécution »
    # du plan à l'usage actuel (le compteur repart de là).
    if i.plan_id:
        from apps.engins import services as engins_lib
        from apps.maintenance import services as maintenance_lib
        from apps.maintenance.models import PlanEntretien
        plan = PlanEntretien.objects.filter(id=i.plan_id).first()
        if plan and cible:
            mode = engins_lib.reglages(i.societe_id)["arrondi"]
            usage = maintenance_lib.usage_camion(cible) if genre == "camion" \
                else maintenance_lib.usage_engin(cible, mode)
            plan.derniere_date = date.today()
            plan.derniere_valeur = maintenance_lib.valeur_compteur(plan, usage)
            plan.save(update_fields=["derniere_date", "derniere_valeur"])
    if i.immobilise and cible:
        filtre = {"camion_id": i.camion_id} if genre == "camion" \
            else {"engin_id": i.engin_id}
        autres = InterventionCamion.objects.filter(
            immobilise=True, **filtre).exclude(
            statut__in=["terminee", "planifiee"]).exclude(id=i.id).exists()
        if not autres:
            cible.statut = "disponible"
            cible.motif_immobilisation = None
            cible.immobilise_depuis = None
            cible.save(update_fields=["statut", "motif_immobilisation",
                                      "immobilise_depuis"])
    services.enregistrer_audit(request.user.id, "FIN", "intervention", i.id, None,
                               {"numero": i.numero,
                                "cout_reel": float(i.cout_reel or 0)})
    return Response(_intervention_dict(i))


# ═══ Rentabilité ═════════════════════════════════════════════════════
@api_view(["GET"])
def rapport_transport(request):
    """Rentabilité par camion et par contrat."""
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES)
    debut = date.fromisoformat(request.query_params["debut"]) \
        if request.query_params.get("debut") else None
    fin = date.fromisoformat(request.query_params["fin"]) \
        if request.query_params.get("fin") else None
    q = Course.objects.filter(societe_id=sid, statut__in=["livree", "facturee"])
    if debut:
        q = q.filter(date_course__gte=debut)
    if fin:
        q = q.filter(date_course__lte=fin)
    courses_l = list(q)

    par_camion: dict = {}
    par_contrat: dict = {}
    tot = {"courses": 0, "recettes": 0.0, "frais": 0.0, "sous_traitance": 0.0,
           "tonnage": 0.0}
    for c in courses_l:
        cam = Camion.objects.filter(id=c.camion_id).first()
        rec, fr, st = _recette(c), _frais_course(c), float(c.st_cout or 0)
        k = cam.immatriculation if cam else "?"
        e = par_camion.setdefault(k, {"camion": k, "type": cam.type if cam else "?",
                                      "courses": 0, "tonnage": 0.0, "recettes": 0.0,
                                      "frais": 0.0, "sous_traitance": 0.0,
                                      "maintenance": 0.0})
        e["courses"] += 1
        e["tonnage"] = round(e["tonnage"] + float(c.tonnage_livre or 0), 2)
        e["recettes"] = round(e["recettes"] + rec, 2)
        e["frais"] = round(e["frais"] + fr, 2)
        e["sous_traitance"] = round(e["sous_traitance"] + st, 2)
        if c.contrat_id:
            ctr = ContratTransport.objects.filter(id=c.contrat_id).first()
            k2 = ctr.libelle if ctr else "?"
            e2 = par_contrat.setdefault(k2, {"contrat": k2, "courses": 0,
                                             "recettes": 0.0, "frais": 0.0,
                                             "sous_traitance": 0.0})
            e2["courses"] += 1
            e2["recettes"] = round(e2["recettes"] + rec, 2)
            e2["frais"] = round(e2["frais"] + fr, 2)
            e2["sous_traitance"] = round(e2["sous_traitance"] + st, 2)
        tot["courses"] += 1
        tot["recettes"] = round(tot["recettes"] + rec, 2)
        tot["frais"] = round(tot["frais"] + fr, 2)
        tot["sous_traitance"] = round(tot["sous_traitance"] + st, 2)
        tot["tonnage"] = round(tot["tonnage"] + float(c.tonnage_livre or 0), 2)

    qi = InterventionCamion.objects.filter(societe_id=sid, cout_reel__isnull=False,
                                           camion_id__isnull=False)
    if debut:
        qi = qi.filter(date_signalement__gte=debut)
    if fin:
        qi = qi.filter(date_signalement__lte=fin)
    maintenance_tot = 0.0
    for i in qi:
        cam = Camion.objects.filter(id=i.camion_id).first()
        k = cam.immatriculation if cam else "?"
        if k in par_camion:
            par_camion[k]["maintenance"] = round(
                par_camion[k]["maintenance"] + float(i.cout_reel), 2)
        maintenance_tot = round(maintenance_tot + float(i.cout_reel), 2)

    for e in par_camion.values():
        e["marge"] = round(e["recettes"] - e["frais"] - e["sous_traitance"]
                           - e["maintenance"], 2)
    for e in par_contrat.values():
        e["marge"] = round(e["recettes"] - e["frais"] - e["sous_traitance"], 2)
    tot["maintenance"] = maintenance_tot
    tot["marge"] = round(tot["recettes"] - tot["frais"] - tot["sous_traitance"]
                         - maintenance_tot, 2)
    return Response({"total": tot,
                     "par_camion": sorted(par_camion.values(),
                                          key=lambda x: -x["recettes"]),
                     "par_contrat": sorted(par_contrat.values(),
                                           key=lambda x: -x["recettes"])})
