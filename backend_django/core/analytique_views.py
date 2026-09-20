"""Comptabilité analytique — portage exact de backend/app/routers/analytique.py.

Axes → sections → ventilation des lignes de charge (6x) / produit (7x), et
rapport croisé sections × charges/produits. Mêmes chemins, mêmes JSON.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import services
from .erreurs import refus
from .auth import assert_acces_societe, assert_role
from .models import (AxeAnalytique, Journal, LigneEcriture, SectionAnalytique,
                     VentilationAnalytique)
from .views import _societe_param

ROLES = {"COMPTABLE", "DFI"}


def _acces(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES)


# ── Axes & sections ──────────────────────────────────────────────────
@api_view(["GET", "POST"])
def axes(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        code = (payload.get("code") or "").strip().upper()
        libelle = (payload.get("libelle") or "").strip()
        if not code or not libelle:
            return refus({"detail": "code et libelle requis."}, status=422)
        if AxeAnalytique.objects.filter(societe_id=sid, code=code).exists():
            return refus({"detail": f"L'axe {code} existe déjà."}, status=409)
        a = AxeAnalytique.objects.create(societe_id=sid, code=code, libelle=libelle)
        return Response({"id": str(a.id), "code": a.code, "libelle": a.libelle}, status=201)

    out = []
    for a in AxeAnalytique.objects.filter(societe_id=sid).order_by("code"):
        sections = SectionAnalytique.objects.filter(axe_id=a.id).order_by("code")
        out.append({"id": str(a.id), "code": a.code, "libelle": a.libelle,
                    "actif": bool(a.actif),
                    "sections": [{"id": str(s.id), "code": s.code, "libelle": s.libelle,
                                  "actif": bool(s.actif)} for s in sections]})
    return Response(out)


@api_view(["POST"])
def creer_section(request, axe_id):
    axe = AxeAnalytique.objects.filter(id=axe_id).first()
    if not axe:
        return refus({"detail": "Axe introuvable."}, status=404)
    _acces(request, axe.societe_id)
    payload = request.data or {}
    code = (payload.get("code") or "").strip().upper()
    libelle = (payload.get("libelle") or "").strip()
    if not code or not libelle:
        return refus({"detail": "code et libelle requis."}, status=422)
    s = SectionAnalytique.objects.create(axe_id=axe.id, societe_id=axe.societe_id,
                                         code=code, libelle=libelle)
    return Response({"id": str(s.id), "code": s.code, "libelle": s.libelle}, status=201)


@api_view(["PATCH"])
def maj_section(request, section_id):
    s = SectionAnalytique.objects.filter(id=section_id).first()
    if not s:
        return refus({"detail": "Section introuvable."}, status=404)
    _acces(request, s.societe_id)
    payload = request.data or {}
    if payload.get("libelle") is not None:
        s.libelle = payload["libelle"].strip()
    if payload.get("actif") is not None:
        s.actif = payload["actif"]
    s.save()
    return Response({"id": str(s.id), "libelle": s.libelle, "actif": bool(s.actif)})


# ── Lignes à ventiler ────────────────────────────────────────────────
def _classe_ok(compte: str, classe: str | None) -> bool:
    if classe:
        return compte.startswith(classe)
    return compte[:1] in ("6", "7")


@api_view(["GET"])
def lignes_a_ventiler(request):
    """Lignes de charge (6x) / produit (7x) avec leur état de ventilation pour l'axe."""
    sid = _societe_param(request)
    _acces(request, sid)
    axe_id = request.query_params.get("axe_id")
    if not axe_id:
        return refus({"detail": "axe_id requis"}, status=422)
    classe = request.query_params.get("classe")
    non_ventilees = (request.query_params.get("non_ventilees") or "").lower() in \
        ("1", "true", "yes")
    journaux = dict(Journal.objects.filter(societe_id=sid).values_list("id", "code"))
    sect_noms = dict(SectionAnalytique.objects.filter(axe_id=axe_id)
                     .values_list("id", "libelle"))
    rows = (LigneEcriture.objects.filter(societe_id=sid)
            .select_related("ecriture")
            .order_by("ecriture__date_ecriture", "ecriture__numero"))
    out = []
    for l in rows:
        if not _classe_ok(l.compte_numero, classe):
            continue
        e = l.ecriture
        vents = list(VentilationAnalytique.objects.filter(ligne_ecriture_id=l.id,
                                                          axe_id=axe_id))
        montant = round(float(l.montant_usd), 2)
        ventile = round(sum(float(v.montant_usd) for v in vents), 2)
        if non_ventilees and ventile >= montant - 0.01:
            continue
        out.append({
            "id": str(l.id), "date": e.date_ecriture.isoformat(), "piece": e.numero,
            "journal": journaux.get(e.journal_id, ""), "compte": l.compte_numero,
            "libelle": l.libelle_ligne or e.libelle,
            "type": "charge" if l.compte_numero[:1] == "6" else "produit",
            "montant": montant, "ventile": ventile, "reste": round(montant - ventile, 2),
            "ventilation": [{"section_id": str(v.section_id),
                             "section": sect_noms.get(v.section_id, ""),
                             "montant": round(float(v.montant_usd), 2)} for v in vents]})
    return Response(out)


@api_view(["POST"])
def ventiler(request):
    """Remplace la ventilation d'une ligne sur un axe (somme ≤ montant de la ligne)."""
    payload = request.data or {}
    sid = payload.get("societe_id")
    _acces(request, sid)
    ligne = LigneEcriture.objects.filter(id=payload.get("ligne_id")).first()
    if not ligne or str(ligne.societe_id) != str(sid):
        return refus({"detail": "Ligne invalide."}, status=400)
    axe_id = payload.get("axe_id")
    repartition = payload.get("repartition") or []
    for p in repartition:
        if float(p.get("montant") or 0) <= 0:
            return refus({"detail": "Montant de ventilation invalide."}, status=422)
    sections_axe = {str(i) for i in SectionAnalytique.objects.filter(axe_id=axe_id)
                    .values_list("id", flat=True)}
    total = round(sum(float(p["montant"]) for p in repartition), 2)
    if total > float(ligne.montant_usd) + 0.01:
        return refus({"detail": f"La ventilation ({total}) dépasse le montant de la "
                                   f"ligne ({float(ligne.montant_usd)})."}, status=400)
    for p in repartition:
        if str(p["section_id"]) not in sections_axe:
            return refus({"detail": "Section hors de l'axe choisi."}, status=400)

    with transaction.atomic():
        # remplace les ventilations existantes de cette ligne pour cet axe
        VentilationAnalytique.objects.filter(ligne_ecriture_id=ligne.id,
                                             axe_id=axe_id).delete()
        for p in repartition:
            VentilationAnalytique.objects.create(
                societe_id=sid, ligne_ecriture_id=ligne.id, axe_id=axe_id,
                section_id=p["section_id"], montant_usd=round(float(p["montant"]), 2))
        services.enregistrer_audit(request.user.id, "VENTILATION", "ligne_ecriture",
                                   ligne.id, None,
                                   {"axe": str(axe_id), "parts": len(repartition)})
    return Response({"ligne_id": str(ligne.id), "ventile": total,
                     "parts": len(repartition)})


# ── Rapport analytique ───────────────────────────────────────────────
@api_view(["GET"])
def rapport(request):
    """Charges / produits / résultat par section d'un axe (+ non ventilé)."""
    sid = _societe_param(request)
    _acces(request, sid)
    axe = AxeAnalytique.objects.filter(id=request.query_params.get("axe_id")).first()
    if not axe:
        return refus({"detail": "Axe introuvable."}, status=404)
    sections = SectionAnalytique.objects.filter(axe_id=axe.id).order_by("code")

    # montant + classe de chaque ligne ventilée
    vent_rows = (VentilationAnalytique.objects.filter(axe_id=axe.id, societe_id=sid)
                 .values_list("section_id", "montant_usd",
                              "ligne_ecriture_id"))
    comptes_lignes = dict(LigneEcriture.objects.filter(societe_id=sid)
                          .values_list("id", "compte_numero"))
    par_section: dict[str, dict] = {}
    tot_vent_ch = tot_vent_pr = 0.0
    for section_id, montant, ligne_id in vent_rows:
        compte = comptes_lignes.get(ligne_id, "")
        agg = par_section.setdefault(str(section_id), {"charges": 0.0, "produits": 0.0})
        m = float(montant)
        if compte[:1] == "6":
            agg["charges"] += m
            tot_vent_ch += m
        elif compte[:1] == "7":
            agg["produits"] += m
            tot_vent_pr += m

    # totaux généraux charges/produits (pour le non ventilé)
    tot_ch = tot_pr = 0.0
    for compte, montant in LigneEcriture.objects.filter(societe_id=sid) \
            .values_list("compte_numero", "montant_usd"):
        if compte[:1] == "6":
            tot_ch += float(montant)
        elif compte[:1] == "7":
            tot_pr += float(montant)

    lignes = []
    for s in sections:
        a = par_section.get(str(s.id), {"charges": 0.0, "produits": 0.0})
        ch, pr = round(a["charges"], 2), round(a["produits"], 2)
        lignes.append({"section": s.libelle, "code": s.code, "charges": ch,
                       "produits": pr, "resultat": round(pr - ch, 2)})
    non_vent = {"charges": round(tot_ch - tot_vent_ch, 2),
                "produits": round(tot_pr - tot_vent_pr, 2)}
    return Response({"axe": axe.libelle, "lignes": lignes, "non_ventile": non_vent,
                     "total_charges": round(tot_ch, 2), "total_produits": round(tot_pr, 2),
                     "resultat": round(tot_pr - tot_ch, 2)})
