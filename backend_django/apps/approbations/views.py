"""Décaissements G01→G04 — portage exact de backend/app/routers/{requisitions,
ordres_depense, avances, approbations}.py + bon-sortie/avances/dashboard de lecture.py.

Réquisition (validation par paliers) → ordre de dépense (sortie de fonds) →
exécution caisse/banque (avance ou paiement direct) → justification (charges,
marchandises→stock, frais, rendu de monnaie) → retards & blocages.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from core import domain as domain
from core import services as services
from core.erreurs import refus
from core.auth import assert_acces_societe, assert_role
from apps.stocks.models import Article, MouvementStock
from apps.tresorerie.models import Avance, BlocageBeneficiaire, Caisse, CompteBancaire, Justification, JustificationLigne, MouvementCaisse, SessionCaisse
from apps.approbations.models import BonReception, OrdreDepense, Requisition, RequisitionCommentaire, RequisitionLigne, Validation
from core.models import PieceJointe, Role, Societe, Tiers, Utilisateur, UtilisateurSociete
from core.views import _societe_param
from apps.tresorerie.beneficiaires import resoudre as resoudre_beneficiaire


def _req_out(r: Requisition) -> dict:
    """Sérialisation RequisitionOut — Pydantic v2 sérialise les Decimal en CHAÎNES
    ("100.00"), on reproduit exactement ce format."""
    return {"id": str(r.id), "numero": r.numero, "societe_id": str(r.societe_id),
            "objet": r.objet, "priorite": r.priorite, "devise": r.devise,
            "montant_total": str(r.montant_total),
            "montant_total_usd": str(r.montant_total_usd), "statut": r.statut}


def _odp_out(o: OrdreDepense) -> dict:
    return {"id": str(o.id), "numero": o.numero,
            "montant_autorise_usd": str(o.montant_autorise_usd),
            "palier_applique": o.palier_applique, "statut": o.statut}


def _decision_in(payload) -> tuple[str, str | None, str] | None:
    d = (payload or {}).get("decision")
    if d not in ("valide", "rejete"):
        return None
    return d, payload.get("commentaire"), payload.get("canal", "in_app")


# ── G01 Réquisitions ─────────────────────────────────────────────────
def _progression(req: Requisition) -> dict:
    """Avancement de la validation de la demande (niveau par niveau)."""
    palier = services.palier_pour_montant("requisition", "demande", req.societe_id,
                                          req.montant_total_usd)
    roles = [a.role_code for a in palier.approbateurs] if palier else []
    decisions = services.decisions_par_role("requisition", req.id, "demande")
    etapes = [{"role": rc, "decision": decisions.get(rc, "en_attente")} for rc in roles]
    valides = sum(1 for e in etapes if e["decision"] == "valide")
    if req.statut == "rejetee":
        label = "Rejetée"
    elif req.statut == "en_attente_info":
        label = "Précisions demandées à l'initiateur"
    elif req.statut == "demande_validee":
        label = "Demande validée — prête pour ordre de dépense"
    elif req.statut in ("transformee", "cloturee"):
        label = req.statut.capitalize()
    elif roles:
        label = f"Validation demande : {valides}/{len(roles)} — " + \
                " · ".join(f"{e['role']} {'OK' if e['decision'] == 'valide' else ('NON' if e['decision'] == 'rejete' else 'en attente')}"
                           for e in etapes)
    else:
        label = req.statut
    return {"label": label, "niveau_valides": valides, "niveau_total": len(roles),
            "etapes": etapes}


@api_view(["GET", "POST"])
def requisitions(request):
    if request.method == "POST":
        return _creer_requisition(request)
    sid = _societe_param(request)
    assert_acces_societe(request.user, sid)
    q = Requisition.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    out = []
    for r in q.order_by("-created_at"):
        nb_comm = RequisitionCommentaire.objects.filter(requisition_id=r.id).count()
        out.append({
            "id": str(r.id), "numero": r.numero, "objet": r.objet, "priorite": r.priorite,
            "devise": r.devise, "montant_total_usd": float(r.montant_total_usd),
            "statut": r.statut, "initiateur_id": str(r.initiateur_id),
            "mode_decaissement": r.mode_decaissement,
            "est_initiateur": r.initiateur_id == request.user.id,
            "progression": _progression(r), "nb_commentaires": nb_comm,
        })
    return Response(out)


def _creer_requisition(request):
    payload = request.data or {}
    sid = payload.get("societe_id")
    if not sid or not payload.get("objet") or not payload.get("lignes"):
        return refus({"detail": "societe_id, objet et lignes requis."}, status=422)
    assert_acces_societe(request.user, sid)
    societe = Societe.objects.filter(id=sid).first()
    if not societe:
        return refus({"detail": "Société introuvable."}, status=404)

    devise = payload.get("devise", "USD")
    jour = date.today()
    taux = services.get_taux_jour(jour, devise)
    if devise != "USD" and taux is None:
        return refus({"detail": f"Aucun taux {devise}/USD défini pour le {jour}. "
                                   f"Le DFI doit le saisir."}, status=400)

    with transaction.atomic():
        numero = services.next_numero("requisition", jour.year, societe.code, societe.id)
        req = Requisition.objects.create(
            numero=numero, societe_id=societe.id, site_id=payload.get("site_id"),
            initiateur_id=request.user.id, objet=payload["objet"],
            justification=payload.get("justification"),
            mode_decaissement=payload.get("mode_decaissement", "avance"),
            nature=payload.get("nature", "charge"),
            priorite=payload.get("priorite", "normal"), devise=devise, taux_jour=taux,
            statut="soumise", date_requisition=services.maintenant().date(),
            created_at=services.maintenant())
        total = Decimal("0")
        total_usd = Decimal("0")
        for i, l in enumerate(payload["lignes"]):
            montant = domain.quantize(Decimal(str(l.get("quantite", 1)))
                                      * Decimal(str(l.get("prix_unitaire", 0))))
            montant_usd = domain.to_usd(devise, montant, taux)
            total += montant
            total_usd += montant_usd
            RequisitionLigne.objects.create(
                requisition_id=req.id, ordre=i, compte_impute=l.get("compte_impute"),
                code_article=l.get("code_article"), description=l.get("description", ""),
                unite=l.get("unite"), quantite=Decimal(str(l.get("quantite", 1))),
                prix_unitaire=Decimal(str(l.get("prix_unitaire", 0))), montant=montant,
                devise=devise, montant_usd=montant_usd)
        req.montant_total = domain.quantize(total)
        req.montant_total_usd = domain.quantize(total_usd)
        req.save(update_fields=["montant_total", "montant_total_usd"])
        services.enregistrer_audit(request.user.id, "INSERT", "requisition", req.id, None,
                                   {"numero": numero,
                                    "montant_usd": float(req.montant_total_usd)})
    return Response(_req_out(req), status=201)


@api_view(["GET"])
def requisition_detail(request, requisition_id):
    r = Requisition.objects.filter(id=requisition_id).first()
    if not r:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    assert_acces_societe(request.user, r.societe_id)
    initiateur = Utilisateur.objects.filter(id=r.initiateur_id).first()
    lignes = RequisitionLigne.objects.filter(requisition_id=r.id).order_by("ordre")
    nb_pj = PieceJointe.objects.filter(document_type="requisition", document_id=r.id).count()
    return Response({
        "id": str(r.id), "numero": r.numero, "objet": r.objet,
        "justification": r.justification, "priorite": r.priorite, "devise": r.devise,
        "mode_decaissement": r.mode_decaissement,
        "montant_total": float(r.montant_total),
        "montant_total_usd": float(r.montant_total_usd),
        "statut": r.statut, "initiateur": initiateur.nom if initiateur else None,
        "date": r.date_requisition.isoformat() if r.date_requisition else None,
        "progression": _progression(r), "nb_pieces_jointes": nb_pj,
        "lignes": [{"description": l.description, "code_article": l.code_article,
                    "unite": l.unite, "quantite": float(l.quantite),
                    "prix_unitaire": float(l.prix_unitaire), "montant": float(l.montant),
                    "compte_impute": l.compte_impute} for l in lignes],
    })


@api_view(["GET"])
def requisition_commentaires(request, requisition_id):
    req = Requisition.objects.filter(id=requisition_id).first()
    if not req:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    assert_acces_societe(request.user, req.societe_id)
    noms = dict(Utilisateur.objects.values_list("id", "nom"))
    rows = (RequisitionCommentaire.objects.filter(requisition_id=requisition_id)
            .order_by("created_at"))
    return Response([{"auteur": noms.get(c.auteur_id), "type": c.type, "message": c.message,
                      "created_at": c.created_at.isoformat() if c.created_at else None}
                     for c in rows])


@api_view(["POST"])
def demander_precisions(request, requisition_id):
    """Un validateur renvoie la réquisition à l'initiateur pour précisions."""
    req = Requisition.objects.filter(id=requisition_id).first()
    if not req:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    roles = assert_acces_societe(request.user, req.societe_id)
    if req.statut not in ("soumise", "en_attente_info"):
        return refus({"detail": "Réquisition non éligible."}, status=409)
    palier = services.palier_pour_montant("requisition", "demande", req.societe_id,
                                          req.montant_total_usd)
    roles_requis = {a.role_code for a in palier.approbateurs} if palier else set()
    if not (roles & roles_requis):
        return refus({"detail": "Vous n'êtes pas validateur de cette demande."},
                        status=403)
    commentaire = (request.data or {}).get("commentaire")
    if not commentaire:
        return refus({"detail": "Précisez ce qui est demandé (commentaire requis)."},
                        status=400)
    req.statut = "en_attente_info"
    req.save(update_fields=["statut"])
    RequisitionCommentaire.objects.create(
        requisition_id=req.id, auteur_id=request.user.id, type="precision_demandee",
        message=commentaire, created_at=services.maintenant())
    services.enregistrer_audit(request.user.id, "DEMANDE_PRECISIONS", "requisition", req.id,
                               None, {"commentaire": commentaire})
    return Response(_req_out(req))


@api_view(["POST"])
def repondre(request, requisition_id):
    """L'initiateur répond aux précisions et resoumet la réquisition."""
    req = Requisition.objects.filter(id=requisition_id).first()
    if not req:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    assert_acces_societe(request.user, req.societe_id)
    if req.initiateur_id != request.user.id:
        return refus({"detail": "Seul l'initiateur peut répondre."}, status=403)
    if req.statut != "en_attente_info":
        return refus({"detail": "Aucune demande de précisions en cours."}, status=409)
    commentaire = (request.data or {}).get("commentaire")
    if not commentaire:
        return refus({"detail": "Réponse requise."}, status=400)
    RequisitionCommentaire.objects.create(
        requisition_id=req.id, auteur_id=request.user.id, type="reponse",
        message=commentaire, created_at=services.maintenant())
    req.statut = "soumise"   # re-soumise aux validateurs
    req.save(update_fields=["statut"])
    services.enregistrer_audit(request.user.id, "REPONSE_PRECISIONS", "requisition", req.id,
                               None, {"commentaire": commentaire})
    return Response(_req_out(req))


@api_view(["POST"])
def valider_demande(request, requisition_id):
    req = Requisition.objects.filter(id=requisition_id).first()
    if not req:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    roles = assert_acces_societe(request.user, req.societe_id)
    if req.statut not in ("soumise", "en_attente_info"):
        return refus({"detail": f"La demande n'est pas en attente de validation "
                                   f"(statut={req.statut})."}, status=409)
    if request.user.id == req.initiateur_id:
        return refus({"detail": "Interdiction de valider sa propre demande "
                                   "(séparation des tâches)."}, status=403)
    dec = _decision_in(request.data)
    if not dec:
        return refus({"detail": "decision invalide (valide|rejete)."}, status=422)
    decision, commentaire, canal = dec

    palier = services.palier_pour_montant("requisition", "demande", req.societe_id,
                                          req.montant_total_usd)
    if not palier:
        return refus({"detail": "Aucune règle de validation configurée."}, status=500)
    roles_requis = {a.role_code for a in palier.approbateurs}
    role_agissant = roles & roles_requis
    if not role_agissant:
        return refus({"detail": f"Votre rôle ne fait pas partie des validateurs requis "
                                   f"{sorted(roles_requis)}."}, status=403)

    with transaction.atomic():
        for rc in role_agissant:
            rid = services.role_id_by_code(rc)
            existante = Validation.objects.filter(
                document_type="requisition", document_id=req.id, etape="demande",
                role_attendu_id=rid).first()
            if existante is None:
                existante = Validation(document_type="requisition", document_id=req.id,
                                       etape="demande", role_attendu_id=rid,
                                       created_at=services.maintenant())
            existante.utilisateur_id = request.user.id
            existante.decision = decision
            existante.commentaire = commentaire
            existante.canal = canal
            existante.save()

        decisions = services.decisions_par_role("requisition", req.id, "demande")
        if any(d == "rejete" for d in decisions.values()):
            req.statut = "rejetee"
        elif domain.est_pleinement_approuve(palier, decisions):
            req.statut = "demande_validee"
        req.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "VALIDATE", "requisition", req.id, None,
                                   {"decision": decision, "statut": req.statut})
    return Response(_req_out(req))


# ── G02 Ordres de dépense ────────────────────────────────────────────
@api_view(["GET", "POST"])
@transaction.atomic
def ordres_depense(request):
    if request.method == "POST":
        return _creer_ordre(request)
    # GET : même liste que phase 1 (déplacée ici pour partager le chemin avec POST)
    sid = _societe_param(request)
    assert_acces_societe(request.user, sid)
    q = OrdreDepense.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    out = []
    for o in q.order_by("-created_at"):
        benef = Tiers.objects.filter(id=o.beneficiaire_tiers_id).first()
        req = Requisition.objects.filter(id=o.requisition_id).first()
        paye = float(o.montant_paye_usd or 0)
        out.append({"id": str(o.id), "numero": o.numero, "devise": o.devise,
                    "requisition_numero": req.numero if req else None,
                    "requisition_objet": req.objet if req else None,
                    "montant_autorise_usd": float(o.montant_autorise_usd),
                    "montant_paye_usd": round(paye, 2),
                    "reste_usd": round(float(o.montant_autorise_usd) - paye, 2),
                    "palier_applique": o.palier_applique, "statut": o.statut,
                    "mode_paiement": o.mode_paiement, "mode_decaissement": o.mode_decaissement,
                    "motif": o.motif, "beneficiaire": benef.nom if benef else None,
                    "beneficiaire_tiers_id": str(o.beneficiaire_tiers_id)})
    return Response(out)


def _creer_ordre(request):
    payload = request.data or {}
    req = Requisition.objects.filter(id=payload.get("requisition_id")).first()
    if not req:
        return refus({"detail": "Réquisition introuvable."}, status=404)
    roles = assert_acces_societe(request.user, req.societe_id)
    assert_role(roles, {"DFI"})   # seul le DFI initie l'ordre de dépense
    if req.statut != "demande_validee":
        return refus({"detail": "La demande doit être validée avant d'émettre un ordre "
                                   "de dépense."}, status=409)
    if not payload.get("beneficiaire_tiers_id"):
        return refus({"detail": "beneficiaire_tiers_id requis."}, status=422)
    beneficiaire = resoudre_beneficiaire(payload['beneficiaire_tiers_id'], req.societe_id)

    societe = Societe.objects.filter(id=req.societe_id).first()
    palier = services.palier_pour_montant("ordre_depense", "sortie_fonds",
                                          req.societe_id, req.montant_total_usd)
    if not palier:
        return refus({"detail": "Aucun palier de sortie de fonds configuré."}, status=500)

    with transaction.atomic():
        numero = services.next_numero("ordre_depense", date.today().year, societe.code,
                                      societe.id)
        odp = OrdreDepense.objects.create(
            numero=numero, requisition_id=req.id, societe_id=req.societe_id,
            beneficiaire_tiers_id=beneficiaire.id,
            motif=payload.get("motif"), mode_paiement=payload.get("mode_paiement", "caisse"),
            mode_decaissement=req.mode_decaissement, devise=req.devise,
            taux_jour=req.taux_jour, montant_autorise=req.montant_total,
            montant_autorise_usd=req.montant_total_usd, palier_applique=palier.libelle,
            statut="a_valider", created_by=request.user.id,
            created_at=services.maintenant())

        # L'ÉMISSION par le DFI VAUT sa validation Niveau 2 (sortie de fonds).
        req.statut = "transformee"
        req.save(update_fields=["statut"])
        now = services.maintenant_micro()
        roles_requis = {a.role_code for a in palier.approbateurs}
        for rc in (roles & roles_requis):
            Validation.objects.create(
                document_type="ordre_depense", document_id=odp.id, etape="sortie_fonds",
                role_attendu_id=services.role_id_by_code(rc),
                utilisateur_id=request.user.id, decision="valide", canal="in_app",
                decided_at=now, created_at=services.maintenant())
        if domain.est_pleinement_approuve(
                palier, services.decisions_par_role("ordre_depense", odp.id, "sortie_fonds")):
            odp.statut = "valide"
            odp.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "INSERT", "ordre_depense", odp.id, None,
                                   {"numero": numero, "palier": palier.libelle, "beneficiaire_provisoire_id":str(beneficiaire.id),
                                    "statut": odp.statut})
    return Response(_odp_out(odp), status=201)


@api_view(["POST"])
def valider_sortie(request, ordre_id):
    odp = OrdreDepense.objects.filter(id=ordre_id).first()
    if not odp:
        return refus({"detail": "Ordre de dépense introuvable."}, status=404)
    roles = assert_acces_societe(request.user, odp.societe_id)
    if odp.statut != "a_valider":
        return refus({"detail": f"Statut non validable ({odp.statut})."}, status=409)
    dec = _decision_in(request.data)
    if not dec:
        return refus({"detail": "decision invalide (valide|rejete)."}, status=422)
    decision, commentaire, canal = dec

    palier = services.palier_pour_montant("ordre_depense", "sortie_fonds",
                                          odp.societe_id, odp.montant_autorise_usd)
    if not palier:
        return refus({"detail": "Aucun palier configuré."}, status=500)
    roles_requis = {a.role_code for a in palier.approbateurs}
    role_agissant = roles & roles_requis
    if not role_agissant:
        return refus({"detail": f"Votre rôle ne fait pas partie des validateurs requis "
                                   f"{sorted(roles_requis)}."}, status=403)

    with transaction.atomic():
        for rc in role_agissant:
            rid = services.role_id_by_code(rc)
            existante = Validation.objects.filter(
                document_type="ordre_depense", document_id=odp.id, etape="sortie_fonds",
                role_attendu_id=rid).first()
            if existante is None:
                existante = Validation(document_type="ordre_depense", document_id=odp.id,
                                       etape="sortie_fonds", role_attendu_id=rid,
                                       created_at=services.maintenant())
            existante.utilisateur_id = request.user.id
            existante.decision = decision
            existante.commentaire = commentaire
            existante.canal = canal
            existante.save()

        decisions = services.decisions_par_role("ordre_depense", odp.id, "sortie_fonds")
        if any(d == "rejete" for d in decisions.values()):
            odp.statut = "rejete"
        elif domain.est_pleinement_approuve(palier, decisions):
            odp.statut = "valide"
        odp.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "VALIDATE", "ordre_depense", odp.id, None,
                                   {"decision": decision, "statut": odp.statut})
    return Response(_odp_out(odp))


@api_view(["POST"])
@transaction.atomic
def executer(request, ordre_id):
    """Exécute le décaissement (caisse par le caissier, banque par le comptable)."""
    odp = OrdreDepense.objects.filter(id=ordre_id).first()
    if not odp:
        return refus({"detail": "Ordre de dépense introuvable."}, status=404)
    roles = assert_acces_societe(request.user, odp.societe_id)
    if odp.statut != "valide":
        return refus({"detail": "Décaissement refusé : l'ordre n'est pas validé selon "
                                   "le palier requis."}, status=409)

    payload = request.data or {}
    caisse_id = payload.get("caisse_id")
    compte_bancaire_id = payload.get("compte_bancaire_id")
    type_avance = payload.get("type_avance")
    reference_paiement = payload.get("reference_paiement")
    beneficiaire_precedent = str(odp.beneficiaire_tiers_id)

    # Le caissier/comptable peut changer le bénéficiaire au moment du paiement
    if payload.get("beneficiaire_tiers_id") and \
            str(payload["beneficiaire_tiers_id"]) != str(odp.beneficiaire_tiers_id):
        nb = resoudre_beneficiaire(payload['beneficiaire_tiers_id'], odp.societe_id)
        odp.beneficiaire_tiers_id = nb.id
    else:
        resoudre_beneficiaire(odp.beneficiaire_tiers_id, odp.societe_id)

    # Décaissement partiel : jamais plus que le reste validé
    reste_usd = float(odp.montant_autorise_usd) - float(odp.montant_paye_usd or 0)
    if reste_usd <= 0.01:
        return refus({"detail": "Ordre déjà entièrement décaissé."}, status=409)
    if odp.mode_decaissement == "paiement_direct" or payload.get("montant") is None:
        montant_pay_usd = reste_usd
        montant_pay_dev = float(domain.from_usd(odp.devise, reste_usd, odp.taux_jour))
    else:
        montant_pay_dev = float(payload["montant"])
        montant_pay_usd = float(domain.to_usd(odp.devise, montant_pay_dev, odp.taux_jour))
        if montant_pay_usd <= 0:
            return refus({"detail": "Montant à décaisser invalide."}, status=400)
        if montant_pay_usd > reste_usd + 0.01:
            return refus({"detail": f"Montant supérieur au reste à décaisser "
                                       f"({round(reste_usd, 2)} USD)."}, status=400)

    # Règle de blocage automatique
    blocage_actif = BlocageBeneficiaire.objects.filter(
        tiers_id=odp.beneficiaire_tiers_id, actif=True).exists()
    en_cours = [domain.AvanceEnCours(statut=s, echeance_justif=e)
                for s, e in Avance.objects.filter(
                    beneficiaire_tiers_id=odp.beneficiaire_tiers_id)
                .values_list("statut", "echeance_justif")]
    if domain.beneficiaire_bloque(blocage_actif, en_cours, datetime.now(timezone.utc)):
        return refus({"detail": "Bénéficiaire bloqué : avance non justifiée. "
                                   "Levée par le DFI requise."}, status=409)

    # Résolution du moyen de paiement (caisse ou banque)
    societe = Societe.objects.filter(id=odp.societe_id).first()
    caisse = sess_c = None
    if odp.mode_paiement == "banque":
        assert_role(roles, {"COMPTABLE", "DFI"})
        if not compte_bancaire_id:
            return refus({"detail": "compte_bancaire_id requis (paiement par banque)."},
                            status=400)
        banque = CompteBancaire.objects.filter(id=compte_bancaire_id).first()
        if not banque or str(banque.societe_id) != str(odp.societe_id):
            return refus({"detail": "Compte bancaire introuvable."}, status=404)
        compte_credit = banque.compte_comptable or "521"
        journal = ("BQ", "Banque", "banque")
    else:
        assert_role(roles, {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR"})
        if not caisse_id:
            return refus({"detail": "caisse_id requis (paiement par caisse)."}, status=400)
        caisse = Caisse.objects.filter(id=caisse_id).first()
        if not caisse or str(caisse.societe_id) != str(odp.societe_id):
            return refus({"detail": "Caisse introuvable."}, status=404)
        sess_c = SessionCaisse.objects.filter(caisse_id=caisse_id, statut="ouverte").first()
        if not sess_c:
            return refus({"detail": "La caisse doit être ouverte pour décaisser."},
                            status=409)
        solde_c = float(sess_c.fond_initial_usd if odp.devise == "USD"
                        else sess_c.fond_initial_cdf)
        for s_, tot_ in (MouvementCaisse.objects
                         .filter(session_id=sess_c.id, devise=odp.devise)
                         .values_list("sens").annotate(total=Sum("montant"))
                         .values_list("sens", "total")):
            solde_c += float(tot_ or 0) if s_ == "entree" else -float(tot_ or 0)
        if solde_c < montant_pay_dev - 0.01:
            return refus({"detail": f"Solde caisse insuffisant : {round(solde_c, 2)} "
                                       f"{odp.devise} disponible, {montant_pay_dev} requis. "
                                       f"Alimentez la caisse ou décaissez une partie."},
                            status=409)
        compte_credit = caisse.compte_comptable or "571"
        journal = ("CA", "Caisse", "caisse")

    annee = date.today().year
    with transaction.atomic():
        odp.save(update_fields=["beneficiaire_tiers_id"])
        services.enregistrer_audit(request.user.id,'CONFIRME_BENEFICIAIRE','ordre_depense',odp.id,
            {'beneficiaire_tiers_id':beneficiaire_precedent},
            {'beneficiaire_tiers_id':str(odp.beneficiaire_tiers_id),'montant_usd':montant_pay_usd})
        brf = BonReception.objects.create(
            numero=services.next_numero("bon_reception", annee, societe.code, societe.id),
            ordre_depense_id=odp.id, caisse_id=caisse_id,
            compte_bancaire_id=compte_bancaire_id,
            receveur_tiers_id=odp.beneficiaire_tiers_id, caissier_id=request.user.id,
            mode=odp.mode_paiement, reference_paiement=reference_paiement,
            devise=odp.devise, taux_jour=odp.taux_jour,
            montant=montant_pay_dev, montant_usd=montant_pay_usd, statut="emis",
            date_reception=services.maintenant())

        # ── Paiement direct sur justificatif : pas d'avance à justifier ──
        if odp.mode_decaissement == "paiement_direct":
            req_lignes = RequisitionLigne.objects.filter(
                requisition_id=odp.requisition_id).order_by("ordre")
            ecr = comptabilite.comptabiliser_paiement_direct(
                odp, req_lignes, compte_credit, request.user.id, *journal)
            odp.montant_paye_usd = odp.montant_autorise_usd
            odp.statut = "paye"
            odp.save(update_fields=["montant_paye_usd", "statut"])
            services.enregistrer_audit(request.user.id, "PAIEMENT_DIRECT", "ordre_depense",
                                       odp.id, None,
                                       {"bon_reception": brf.numero, "ecriture": ecr.numero})
            return Response({"message": "Paiement direct enregistré (sur justificatif)",
                             "bon_reception": brf.numero, "ecriture": ecr.numero,
                             "mode": "paiement_direct"})

        # Délai de justification selon le type d'avance
        delai = services.get_parametre(f"delai_justif.{type_avance}", odp.societe_id) \
            if type_avance else None
        delai = int(delai) if delai else int(
            services.get_parametre("delai_justif_defaut_h", odp.societe_id, "24"))
        now = services.maintenant_micro()
        avance = Avance.objects.create(
            numero=services.next_numero("avance", annee, None, None),
            ordre_depense_id=odp.id, bon_reception_id=brf.id,
            beneficiaire_tiers_id=odp.beneficiaire_tiers_id, societe_id=odp.societe_id,
            type_avance=type_avance, devise=odp.devise, montant_avance=montant_pay_dev,
            montant_avance_usd=montant_pay_usd, date_octroi=now,
            delai_justif_heures=delai,
            echeance_justif=domain.compute_echeance(now, delai),
            statut="a_justifier", created_at=services.maintenant())

        # Mouvement de caisse uniquement si paiement par caisse
        mouvement_caisse_id = None
        if caisse is not None:
            tiers_b = Tiers.objects.filter(id=odp.beneficiaire_tiers_id).first()
            req_o = Requisition.objects.filter(id=odp.requisition_id).first()
            mvt_c = MouvementCaisse.objects.create(
                caisse_id=caisse_id, session_id=sess_c.id,
                numero=services.next_numero("bon_caisse", annee, societe.code, societe.id),
                reference=req_o.numero if req_o else None,
                sens="sortie", nature="Décaissement (ordre)", devise=odp.devise,
                taux_jour=odp.taux_jour, montant=montant_pay_dev,
                montant_usd=montant_pay_usd,
                reference_type="bon_reception", reference_id=brf.id,
                tiers_id=odp.beneficiaire_tiers_id,
                tiers_nom=tiers_b.nom if tiers_b else None,
                billetage=payload.get("billetage") or None,
                libelle=f"Avance {avance.numero} — {odp.numero}",
                created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
            mouvement_caisse_id = str(mvt_c.id)
        odp.montant_paye_usd = float(odp.montant_paye_usd or 0) + montant_pay_usd
        odp.statut = "execute" if float(odp.montant_paye_usd) >= \
            float(odp.montant_autorise_usd) - 0.01 else "valide"
        odp.save(update_fields=["montant_paye_usd", "statut"])

        # Comptabilisation automatique : D 409|421 / C 571|521
        tiers = Tiers.objects.filter(id=odp.beneficiaire_tiers_id).first()
        ecr = comptabilite.comptabiliser_versement_avance(
            avance, odp, tiers, compte_credit, request.user.id, *journal)

        services.enregistrer_audit(request.user.id, "EXECUTE", "ordre_depense", odp.id, None,
                                   {"avance": avance.numero, "bon_reception": brf.numero,
                                    "ecriture": ecr.numero})
    reste = round(float(odp.montant_autorise_usd) - float(odp.montant_paye_usd), 2)
    return Response({"message": "Décaissement exécuté", "avance_numero": avance.numero,
                     "bon_reception": brf.numero,
                     "echeance_justification": avance.echeance_justif.isoformat(),
                     "montant_paye_usd": round(float(odp.montant_paye_usd), 2),
                     "reste_usd": reste, "partiel": odp.statut == "valide",
                     "mouvement_id": mouvement_caisse_id})


@api_view(["GET"])
def bon_sortie(request, ordre_id):
    """Données du bon de sortie de caisse (ou OP/chèque banque) pour impression."""
    odp = OrdreDepense.objects.filter(id=ordre_id).first()
    if not odp:
        return refus({"detail": "Ordre introuvable."}, status=404)
    assert_acces_societe(request.user, odp.societe_id)
    brf = BonReception.objects.filter(ordre_depense_id=odp.id).first()
    if not brf:
        return refus({"detail": "Aucun décaissement exécuté pour cet ordre."}, status=404)
    societe = Societe.objects.filter(id=odp.societe_id).first()
    benef = Tiers.objects.filter(id=odp.beneficiaire_tiers_id).first()
    executant = Utilisateur.objects.filter(id=brf.caissier_id).first()
    moyen = None
    if brf.caisse_id:
        c = Caisse.objects.filter(id=brf.caisse_id).first()
        moyen = c.libelle if c else None
    elif brf.compte_bancaire_id:
        b = CompteBancaire.objects.filter(id=brf.compte_bancaire_id).first()
        moyen = f"{b.banque} {b.numero_compte or ''}".strip() if b else None
    req = Requisition.objects.filter(id=odp.requisition_id).first()
    return Response({
        "societe": societe.nom, "bon_numero": brf.numero,
        "date": brf.date_reception.isoformat() if brf.date_reception else None,
        "ordre_numero": odp.numero, "mode": brf.mode, "moyen": moyen,
        "requisition_numero": req.numero if req else None,
        "requisition_objet": req.objet if req else None,
        "reference_paiement": brf.reference_paiement,
        "beneficiaire": benef.nom if benef else None, "motif": odp.motif,
        "devise": odp.devise, "montant": float(odp.montant_autorise),
        "montant_usd": float(odp.montant_autorise_usd),
        "executant": executant.nom if executant else None,
    })


# ── G04 Avances & justifications ─────────────────────────────────────
@api_view(["GET"])
def lister_avances(request):
    sid = _societe_param(request)
    assert_acces_societe(request.user, sid)
    q = Avance.objects.filter(societe_id=sid)
    statut = request.query_params.get("statut")
    if statut:
        q = q.filter(statut=statut)
    out = []
    for a in q.order_by("-date_octroi"):
        benef = Tiers.objects.filter(id=a.beneficiaire_tiers_id).first()
        ordre = OrdreDepense.objects.filter(id=a.ordre_depense_id).first()
        req = (Requisition.objects.filter(id=ordre.requisition_id).first()
               if ordre and ordre.requisition_id else None)
        out.append({"id": str(a.id), "numero": a.numero, "devise": a.devise,
                    "montant_avance_usd": float(a.montant_avance_usd), "statut": a.statut,
                    "type_avance": a.type_avance,
                    "beneficiaire": benef.nom if benef else None,
                    "nature": req.nature if req else "charge",
                    "objet": req.objet if req else None,
                    "echeance_justif": a.echeance_justif.isoformat()
                    if a.echeance_justif else None})
    return Response(out)


def _resolve_article(societe: Societe, m: dict) -> Article | Response:
    """Retrouve un article, ou le crée à la volée (nouvelles marchandises)."""
    if m.get("article_id"):
        a = Article.objects.filter(id=m["article_id"]).first()
        if not a:
            return refus({"detail": "Article introuvable."}, status=400)
        return a
    code = (m.get("code") or "").strip().upper()
    if code:
        a = Article.objects.filter(societe_id=societe.id, code=code).first()
        if a:
            return a
    if not code:
        n = Article.objects.filter(societe_id=societe.id).count()
        code = f"ART{n + 1:04d}"
    return Article.objects.create(
        societe_id=societe.id, code=code,
        designation=(m.get("designation") or "Article").strip(),
        unite=(m.get("unite") or "unité"),
        prix_achat=Decimal(str(m.get("prix_unitaire", 0))),
        taux_tva=Decimal(str(m["taux_tva"])) if m.get("taux_tva") is not None
        else Decimal("16"))


@api_view(["POST"])
def justifier(request):
    payload = request.data or {}
    avance = Avance.objects.filter(id=payload.get("avance_id")).first()
    if not avance:
        return refus({"detail": "Avance introuvable."}, status=404)
    assert_acces_societe(request.user, avance.societe_id)
    if avance.statut not in ("a_justifier", "en_retard"):
        return refus({"detail": f"Avance non justifiable (statut={avance.statut})."},
                        status=409)

    jour = date.today()
    # Conversion des lignes en USD — (ligne_dict, montant_usd)
    lignes_usd = []
    lignes_models = []
    for l in payload.get("lignes") or []:
        devise_l = l.get("devise", "USD")
        taux = services.get_taux_jour(jour, devise_l)
        if devise_l != "USD" and taux is None:
            return refus({"detail": f"Taux {devise_l}/USD manquant pour le {jour}."},
                            status=400)
        m_usd = domain.to_usd(devise_l, Decimal(str(l.get("montant", 0))), taux)
        lignes_usd.append(m_usd)
        lignes_models.append((l, m_usd))

    societe = Societe.objects.filter(id=avance.societe_id).first()

    with transaction.atomic():
        # ── Circuit 1 : marchandises achetées avec l'avance → entrée en stock ──
        stock_entries = []   # (article, qte, cout_entree)
        marchandises = payload.get("marchandises") or []
        frais = payload.get("frais") or []
        if marchandises:
            items = []
            for m in marchandises:
                art = _resolve_article(societe, m)
                if isinstance(art, Response):
                    return art
                ht = round(float(m.get("qte", 0)) * float(m.get("prix_unitaire", 0)), 2)
                taux_t = float(m["taux_tva"]) if m.get("taux_tva") is not None \
                    else float(art.taux_tva)
                if not art.assujetti_tva:
                    taux_t = 0.0
                items.append({"art": art, "qte": float(m.get("qte", 0)), "ht": ht,
                              "tva": round(ht * taux_t / 100, 2),
                              "des": m.get("designation") or art.designation})
            frais_ht = round(sum(float(f.get("montant_ht", 0)) for f in frais), 2)
            frais_tva = round(sum(
                round(float(f.get("montant_ht", 0))
                      * (float(f["taux_tva"]) if f.get("taux_tva") is not None else 16)
                      / 100, 2) for f in frais), 2)
            if frais_ht > 0 and items:
                repartition_mode = payload.get("repartition", "quantite")
                w = [it["qte"] if repartition_mode != "valeur" else it["ht"] for it in items]
                tw = sum(w) or 1.0
                cumul = 0.0
                for i, it in enumerate(items):
                    part = round(frais_ht * w[i] / tw, 2) if i < len(items) - 1 \
                        else round(frais_ht - cumul, 2)
                    cumul = round(cumul + part, 2)
                    it["cout"] = round(it["ht"] + part, 2)
            else:
                for it in items:
                    it["cout"] = it["ht"]
            tva_totale = round(sum(it["tva"] for it in items) + frais_tva, 2)
            # Op 1 (achat) : marchandise en 601 au PRIX d'achat (HT)
            for it in items:
                li = {"nature": f"Achat : {it['des']}",
                      "compte_impute": it["art"].compte_achat, "devise": "USD",
                      "montant": Decimal(str(it["ht"]))}
                lignes_usd.append(domain._d(it["ht"]))
                lignes_models.append((li, domain._d(it["ht"])))
                stock_entries.append((it["art"], it["qte"], it["cout"]))
            # Frais accessoires → charges (611…), incorporés au coût du stock (op 2)
            for f in frais:
                fht = round(float(f.get("montant_ht", 0)), 2)
                if fht <= 0:
                    continue
                li = {"nature": f"Frais : {f.get('libelle')}",
                      "compte_impute": f.get("compte", "611"), "devise": "USD",
                      "montant": Decimal(str(fht))}
                lignes_usd.append(domain._d(fht))
                lignes_models.append((li, domain._d(fht)))
            if tva_totale > 0:
                li = {"nature": "TVA déductible (marchandises)",
                      "compte_impute": services.get_parametre("compte.tva_deductible",
                                                              societe.id, "4452"),
                      "devise": "USD", "montant": Decimal(str(tva_totale))}
                lignes_usd.append(domain._d(tva_totale))
                lignes_models.append((li, domain._d(tva_totale)))

        if not lignes_models:
            return refus({"detail": "Justification vide : au moins une dépense ou une "
                                       "marchandise."}, status=400)

        devise_solde = payload.get("devise_solde", "USD")
        solde_retourne = Decimal(str(payload.get("solde_retourne", 0)))
        taux_solde = services.get_taux_jour(jour, devise_solde)
        solde_usd = domain.to_usd(devise_solde, solde_retourne, taux_solde) \
            if solde_retourne else domain._d(0)

        eq = domain.controle_equilibre(avance.montant_avance_usd, lignes_usd, solde_usd)

        just = Justification.objects.create(
            numero=services.next_numero("justification", jour.year, societe.code,
                                        societe.id),
            avance_id=avance.id, montant_justifie_usd=eq.total_justifie_usd,
            solde_retourne=solde_retourne, solde_retourne_usd=eq.solde_retourne_usd,
            ecart_usd=eq.ecart_usd, complement_demande=eq.complement_du, statut="soumise",
            created_by=request.user.id, date_justification=services.maintenant().date(),
            created_at=services.maintenant())
        for l, m_usd in lignes_models:
            JustificationLigne.objects.create(
                justification_id=just.id,
                date_achat=date.fromisoformat(l["date_achat"])
                if l.get("date_achat") else None,
                nature=l.get("nature", ""), compte_impute=l.get("compte_impute"),
                fournisseur=l.get("fournisseur"), num_piece=l.get("num_piece"),
                devise=l.get("devise", "USD"), montant=Decimal(str(l.get("montant", 0))),
                montant_usd=m_usd, a_piece_jointe=bool(l.get("a_piece_jointe")))
        avance.statut = "justifiee"
        avance.save(update_fields=["statut"])

        # Retour de monnaie → entrée en caisse SUR LA SESSION OUVERTE
        caisse_compte = None
        if eq.solde_retourne_usd and eq.solde_retourne_usd > 0:
            caisse = None
            if payload.get("caisse_id"):
                caisse = Caisse.objects.filter(id=payload["caisse_id"]).first()
            elif avance.bon_reception_id:
                brf = BonReception.objects.filter(id=avance.bon_reception_id).first()
                if brf and brf.caisse_id:
                    caisse = Caisse.objects.filter(id=brf.caisse_id).first()
            if caisse is None:
                caisse = (Caisse.objects.filter(societe_id=societe.id)
                          .order_by("id").first())
            if caisse is None:
                return refus({"detail": "Aucune caisse pour enregistrer le rendu."},
                                status=400)
            sess = SessionCaisse.objects.filter(caisse_id=caisse.id,
                                                statut="ouverte").first()
            if sess is None:
                return refus({"detail": f"Ouvrez la caisse « {caisse.libelle} » pour "
                                           f"enregistrer le rendu de monnaie."}, status=409)
            caisse_compte = caisse.compte_comptable
            MouvementCaisse.objects.create(
                caisse_id=caisse.id, session_id=sess.id,
                numero=services.next_numero("bon_caisse", jour.year, societe.code,
                                            societe.id),
                reference=avance.numero, tiers_id=avance.beneficiaire_tiers_id,
                sens="entree", nature="Retour d'avance", devise=devise_solde,
                taux_jour=taux_solde, montant=solde_retourne,
                montant_usd=eq.solde_retourne_usd,
                reference_type="justification", reference_id=just.id,
                libelle=f"Retour solde avance {avance.numero}", created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())

        # Entrées de stock des marchandises (coût d'acquisition, dépôt central)
        if stock_entries:
            from apps.stocks import services as stock_lib
            central = stock_lib.depot_central(societe.id)
            for art, qte, cout in stock_entries:
                stock_lib.entree(art, central, qte, cout, "achat", just.numero,
                                 jour=jour)

        # Op 1 : D 601/611 (+ D caisse) / C 421|409 — en attente comptable
        ecr = comptabilite.comptabiliser_justification(just, avance, request.user.id,
                                                       caisse_compte=caisse_compte)
        # Op 2 : entrée en stock au coût d'acquisition (D 31 / C 603)
        if stock_entries:
            stock_par_compte: dict[str, float] = {}
            for art, qte, cout in stock_entries:
                stock_par_compte[art.compte_stock] = round(
                    stock_par_compte.get(art.compte_stock, 0.0) + cout, 2)
            comptabilite.comptabiliser_stock_entree(societe.id, stock_par_compte,
                                                    just.numero, jour, "justification",
                                                    just.id, request.user.id)

        services.enregistrer_audit(request.user.id, "INSERT", "justification", just.id, None,
                                   {"avance": avance.numero, "ecart_usd": float(eq.ecart_usd),
                                    "complement": eq.complement_du, "ecriture": ecr.numero})
    return Response({"id": str(just.id), "numero": just.numero,
                     "montant_justifie_usd": str(just.montant_justifie_usd),
                     "solde_retourne_usd": str(just.solde_retourne_usd),
                     "ecart_usd": str(just.ecart_usd),
                     "complement_demande": bool(just.complement_demande),
                     "statut": just.statut}, status=201)


@api_view(["POST"])
def verifier_retards(request):
    """Passe les avances échues en retard et crée les blocages."""
    now = datetime.now(timezone.utc)
    bloques = 0
    with transaction.atomic():
        for av in Avance.objects.filter(statut="a_justifier"):
            if domain.est_en_retard(
                    domain.AvanceEnCours(statut=av.statut,
                                         echeance_justif=av.echeance_justif), now):
                av.statut = "en_retard"
                av.save(update_fields=["statut"])
                deja = BlocageBeneficiaire.objects.filter(avance_id=av.id,
                                                          actif=True).exists()
                if not deja:
                    BlocageBeneficiaire.objects.create(
                        tiers_id=av.beneficiaire_tiers_id, avance_id=av.id,
                        motif=f"Avance {av.numero} non justifiée dans le délai.",
                        bloque_at=services.maintenant())
                    bloques += 1
    return Response({"avances_en_retard": bloques, "verifie_a": now.isoformat()})


@api_view(["POST"])
def lever_blocage(request, blocage_id):
    """Seul le DFI peut lever un blocage. (motif en paramètre de requête)"""
    blocage = BlocageBeneficiaire.objects.filter(id=blocage_id).first()
    if not blocage:
        return refus({"detail": "Blocage introuvable."}, status=404)
    motif = request.query_params.get("motif")
    if not motif:
        return refus({"detail": "motif requis"}, status=422)
    roles = set(Role.objects.filter(
        id__in=UtilisateurSociete.objects.filter(utilisateur_id=request.user.id)
        .values("role_id")).values_list("code", flat=True))
    if "DFI" not in roles and "PRESIDENT" not in roles:
        return refus({"detail": "Seul le DFI peut lever un blocage."}, status=403)
    if not blocage.actif:
        return refus({"detail": "Blocage déjà levé."}, status=409)
    blocage.actif = False
    blocage.leve_par = request.user.id
    blocage.leve_motif = motif
    blocage.leve_at = services.maintenant_micro()
    blocage.save(update_fields=["actif", "leve_par", "leve_motif", "leve_at"])
    services.enregistrer_audit(request.user.id, "UPDATE", "blocage_beneficiaire",
                               blocage.id, {"actif": True}, {"actif": False, "motif": motif})
    return Response({"message": "Blocage levé", "blocage_id": str(blocage.id)})


# ── Centre d'approbation ─────────────────────────────────────────────
@api_view(["GET"])
def centre_approbation(request):
    """Ce qui attend la validation de l'utilisateur connecté (toutes sociétés)."""
    rows = (UtilisateurSociete.objects.filter(utilisateur_id=request.user.id)
            .values_list("societe_id", "societe__code", "societe__nom", "role__code"))
    contexte: dict = {}
    for sid, code, nom, role_code in rows:
        e = contexte.setdefault(sid, {"roles": set(), "code": code, "nom": nom})
        e["roles"].add(role_code)

    requisitions_l: list[dict] = []
    ordres: list[dict] = []
    a_emettre: list[dict] = []

    for sid, info in contexte.items():
        mes_roles = info["roles"]

        # 0) Réquisitions validées à transformer en ordre de dépense (DFI)
        if "DFI" in mes_roles:
            for r in Requisition.objects.filter(societe_id=sid, statut="demande_validee"):
                a_emettre.append({
                    "id": str(r.id), "numero": r.numero, "societe": info["code"],
                    "objet": r.objet, "devise": r.devise,
                    "montant_total_usd": float(r.montant_total_usd)})

        # 1) Réquisitions dont la DEMANDE attend validation
        for r in Requisition.objects.filter(societe_id=sid,
                                            statut__in=["soumise", "en_attente_info"]):
            if r.initiateur_id == request.user.id:
                continue  # pas d'auto-validation
            palier = services.palier_pour_montant("requisition", "demande", sid,
                                                  r.montant_total_usd)
            if not palier:
                continue
            roles_requis = {a.role_code for a in palier.approbateurs}
            if not (mes_roles & roles_requis):
                continue
            decisions = services.decisions_par_role("requisition", r.id, "demande")
            a_agir = {rc for rc in (mes_roles & roles_requis)
                      if decisions.get(rc) not in ("valide", "rejete")}
            if a_agir:
                requisitions_l.append({
                    "id": str(r.id), "numero": r.numero, "societe": info["code"],
                    "objet": r.objet, "priorite": r.priorite, "devise": r.devise,
                    "montant_total_usd": float(r.montant_total_usd),
                    "etape": "demande", "roles_requis": sorted(roles_requis),
                    "mes_roles_a_agir": sorted(a_agir),
                })

        # 2) Ordres de dépense dont la SORTIE DE FONDS attend validation
        paliers_sf = services.load_paliers("ordre_depense", "sortie_fonds", sid)
        if paliers_sf:
            for o in OrdreDepense.objects.filter(societe_id=sid, statut="a_valider"):
                palier = domain.resolve_palier(o.montant_autorise_usd, paliers_sf)
                roles_requis = {a.role_code for a in palier.approbateurs}
                if not (mes_roles & roles_requis):
                    continue
                decisions = services.decisions_par_role("ordre_depense", o.id,
                                                        "sortie_fonds")
                a_agir = {rc for rc in (mes_roles & roles_requis)
                          if decisions.get(rc) not in ("valide", "rejete")}
                if a_agir:
                    ordres.append({
                        "id": str(o.id), "numero": o.numero, "societe": info["code"],
                        "motif": o.motif, "devise": o.devise,
                        "montant_autorise_usd": float(o.montant_autorise_usd),
                        "palier": palier.libelle, "etape": "sortie_fonds",
                        "roles_requis": sorted(roles_requis),
                        "mes_roles_a_agir": sorted(a_agir),
                    })

    return Response({
        "utilisateur": request.user.email,
        "total": len(requisitions_l) + len(ordres) + len(a_emettre),
        "requisitions": requisitions_l,
        "ordres_depense": ordres,
        "a_emettre": a_emettre,
    })


# ── Tableau de bord décaissements ────────────────────────────────────
@api_view(["GET"])
def dashboard(request):
    sid = _societe_param(request)
    assert_acces_societe(request.user, sid)
    req_soumises = Requisition.objects.filter(societe_id=sid, statut="soumise").count()
    odp_a_valider = OrdreDepense.objects.filter(societe_id=sid, statut="a_valider").count()
    av_en_cours = Avance.objects.filter(societe_id=sid,
                                        statut__in=["a_justifier", "en_retard"]).count()
    av_retard = Avance.objects.filter(societe_id=sid, statut="en_retard").count()
    montant_avances = (Avance.objects.filter(societe_id=sid,
                                             statut__in=["a_justifier", "en_retard"])
                       .aggregate(t=Sum("montant_avance_usd"))["t"] or 0)
    tiers_soc = Tiers.objects.filter(societe_id=sid).values("id")
    blocages = BlocageBeneficiaire.objects.filter(tiers_id__in=tiers_soc,
                                                  actif=True).count()
    return Response({
        "requisitions_soumises": req_soumises,
        "ordres_a_valider": odp_a_valider,
        "avances_en_cours": av_en_cours,
        "avances_en_retard": av_retard,
        "avances_montant_usd": float(montant_avances),
        "beneficiaires_bloques": blocages,
    })
