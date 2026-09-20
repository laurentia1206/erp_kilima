"""Comptabilité — portage exact de backend/app/routers/compta.py.

Pièces en attente (validation/reclassement), balance/grand livre, plan
comptable, journaux, saisie OD, lettrage, rapprochement bancaire, états
financiers OHADA, comptes de configuration. Mêmes chemins, mêmes JSON.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import comptabilite, etats_financiers, plan_syscohada, services
from .erreurs import refus
from .auth import assert_acces_societe, assert_role
from .models import (Caisse, Compte, Ecriture, Journal, LigneEcriture, MouvementCaisse,
                     Parametre, PieceJointe, RapprochementBancaire, Tiers, Transfert)
from .views import _societe_param

ROLES_COMPTA = {"COMPTABLE", "DFI"}

# Provenance = catégorie d'origine de la pièce (pour regrouper les pièces en attente)
_PROV_JOURNAL = {"caisse": "Caisse", "banque": "Banque", "achat": "Achat",
                 "vente": "Vente", "ouverture": "À-nouveaux"}


def _acces_compta(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES_COMPTA)


def _bool_param(request, nom: str) -> bool:
    return (request.query_params.get(nom) or "").lower() in ("1", "true", "yes")


def _provenance(e: Ecriture, journal) -> tuple[str, str | None]:
    """Retourne (catégorie, détail) : d'où vient la pièce, avec un libellé de source."""
    to = e.type_operation or ""
    cat = "Divers"
    if to == "transfert":
        cat = "Transfert"
    elif to == "operation_caisse":
        cat = "Caisse"
    elif journal and journal.type in _PROV_JOURNAL:
        cat = _PROV_JOURNAL[journal.type]
    elif journal:
        cat = journal.code

    detail = None
    if e.source_type == "mouvement_caisse" and e.source_id:
        m = MouvementCaisse.objects.filter(id=e.source_id).first()
        if m:
            c = Caisse.objects.filter(id=m.caisse_id).first()
            if c:
                detail = c.libelle
                if "POS" in (c.libelle or "").upper():
                    cat = "POS"
    elif e.source_type == "transfert" and e.source_id:
        t = Transfert.objects.filter(id=e.source_id).first()
        detail = t.numero if t else None
    elif e.source_type in ("avance", "ordre_depense") and e.source_id:
        detail = e.numero_piece
    return cat, detail


def _ecriture_dict(e: Ecriture, intitules: dict | None = None) -> dict:
    journal = Journal.objects.filter(id=e.journal_id).first() if e.journal_id else None
    lignes = list(LigneEcriture.objects.filter(ecriture_id=e.id).order_by("ordre"))
    if intitules is None:
        intitules = dict(Compte.objects.filter(societe_id=e.societe_id)
                         .values_list("numero", "intitule"))
    tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
    cat, detail = _provenance(e, journal)
    total = round(sum(float(l.montant_usd) for l in lignes if l.sens == "D"), 2)
    nb_pj = PieceJointe.objects.filter(document_type="ecriture", document_id=e.id).count()
    return {
        "id": str(e.id), "numero": e.numero, "date": e.date_ecriture.isoformat(),
        "libelle": e.libelle, "journal": journal.code if journal else None,
        "provenance": cat, "source": detail, "montant": total,
        "piece": e.numero_piece, "nb_pj": nb_pj,
        "type_operation": e.type_operation, "statut": e.statut,
        "lignes": [{"id": str(l.id), "sens": l.sens, "compte": l.compte_numero,
                    "intitule": intitules.get(l.compte_numero, ""),
                    "tiers": tiers_noms.get(l.tiers_id) if l.tiers_id else None,
                    "montant_usd": float(l.montant_usd), "libelle": l.libelle_ligne}
                   for l in lignes],
    }


@api_view(["GET"])
def lister_ecritures(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    statut = request.query_params.get("statut", "en_attente")
    q = Ecriture.objects.filter(societe_id=sid)
    if statut:
        q = q.filter(statut=statut)
    return Response([_ecriture_dict(e) for e in q.order_by("-created_at")])


@api_view(["POST"])
def valider_ecriture(request, ecriture_id):
    """Le comptable valide la pièce, après reclassement et/ou éclatement des lignes."""
    e = Ecriture.objects.filter(id=ecriture_id).first()
    if not e:
        return refus({"detail": "Écriture introuvable."}, status=404)
    _acces_compta(request, e.societe_id)
    if e.statut != "en_attente":
        return refus({"detail": "Pièce déjà validée."}, status=409)

    payload = request.data or {}
    comptes_valides = set(Compte.objects.filter(societe_id=e.societe_id)
                          .values_list("numero", flat=True))
    lignes_ecr = list(LigneEcriture.objects.filter(ecriture_id=e.id))
    ordre_max = max((l.ordre for l in lignes_ecr), default=0)
    splits_faits, split_ids = 0, set()

    with transaction.atomic():
        for sp in payload.get("splits", []):
            ligne = LigneEcriture.objects.filter(id=sp.get("ligne_id")).first()
            if not ligne or ligne.ecriture_id != e.id:
                return refus({"detail": "Ligne à éclater invalide."}, status=400)
            repartition = sp.get("repartition") or []
            if not repartition:
                continue
            total = round(sum(float(r["montant"]) for r in repartition), 2)
            if abs(total - float(ligne.montant_usd)) > 0.01:
                return refus({"detail": f"L'éclatement ({total}) doit égaler le montant "
                                           f"de la ligne ({float(ligne.montant_usd)})."},
                                status=400)
            for r in repartition:
                if r["compte_numero"] not in comptes_valides:
                    return refus({"detail": f"Compte {r['compte_numero']} absent du plan "
                                               f"comptable."}, status=400)
            # 1ère répartition réutilise la ligne existante
            first = repartition[0]
            ligne.compte_numero = first["compte_numero"]
            ligne.montant_usd = round(float(first["montant"]), 2)
            ligne.tiers_id = first.get("tiers_id")
            if first.get("libelle"):
                ligne.libelle_ligne = first["libelle"]
            ligne.save()
            # les suivantes = nouvelles lignes, même sens
            for r in repartition[1:]:
                ordre_max += 1
                LigneEcriture.objects.create(
                    ecriture_id=e.id, societe_id=e.societe_id, ordre=ordre_max,
                    sens=ligne.sens, compte_numero=r["compte_numero"],
                    tiers_id=r.get("tiers_id"), montant_usd=round(float(r["montant"]), 2),
                    devise_origine=ligne.devise_origine,
                    libelle_ligne=r.get("libelle") or ligne.libelle_ligne)
            split_ids.add(ligne.id)
            splits_faits += 1

        changements = []
        for r in payload.get("reclassements", []):
            ligne = LigneEcriture.objects.filter(id=r.get("ligne_id")).first()
            if not ligne or ligne.ecriture_id != e.id:
                return refus({"detail": "Ligne invalide."}, status=400)
            if ligne.id in split_ids:
                continue
            if r["compte_numero"] not in comptes_valides:
                return refus({"detail": f"Compte {r['compte_numero']} absent du plan "
                                           f"comptable."}, status=400)
            if ligne.compte_numero != r["compte_numero"]:
                changements.append({"ligne": str(ligne.id), "de": ligne.compte_numero,
                                    "vers": r["compte_numero"]})
                ligne.compte_numero = r["compte_numero"]
                ligne.save(update_fields=["compte_numero"])

        e.statut = "valide"
        e.save(update_fields=["statut"])
        services.enregistrer_audit(request.user.id, "VALIDATE", "ecriture", e.id,
                                   {"reclassements": changements, "splits": splits_faits}
                                   if (changements or splits_faits) else None,
                                   {"statut": "valide"})
    return Response({"id": str(e.id), "statut": "valide",
                     "reclassements": len(changements), "splits": splits_faits})


@api_view(["GET"])
def grand_livre(request):
    """Détail des mouvements par compte, avec solde progressif, journal et tiers."""
    sid = _societe_param(request)
    _acces_compta(request, sid)
    compte = request.query_params.get("compte")
    statut = request.query_params.get("statut")
    tiers_id = request.query_params.get("tiers_id")
    journaux = dict(Journal.objects.filter(societe_id=sid).values_list("id", "code"))
    tiers_noms = dict(Tiers.objects.values_list("id", "nom"))

    q = (LigneEcriture.objects.filter(societe_id=sid)
         .select_related("ecriture")
         .order_by("compte_numero", "ecriture__date_ecriture", "ecriture__numero"))
    if compte:
        q = q.filter(compte_numero__startswith=compte)
    if statut:
        q = q.filter(ecriture__statut=statut)
    if tiers_id:
        q = q.filter(tiers_id=tiers_id)
    intitules = dict(Compte.objects.filter(societe_id=sid).values_list("numero", "intitule"))
    comptes: dict[str, dict] = {}
    for ligne in q:
        ecr = ligne.ecriture
        c = comptes.setdefault(ligne.compte_numero, {
            "compte": ligne.compte_numero, "intitule": intitules.get(ligne.compte_numero, ""),
            "mouvements": [], "_solde": 0.0})
        d = float(ligne.montant_usd) if ligne.sens == "D" else 0.0
        cr = float(ligne.montant_usd) if ligne.sens == "C" else 0.0
        c["_solde"] += d - cr
        c["mouvements"].append({
            "date": ecr.date_ecriture.isoformat(), "piece": ecr.numero,
            "journal": journaux.get(ecr.journal_id, ""),
            "tiers": tiers_noms.get(ligne.tiers_id) if ligne.tiers_id else None,
            "lettrage": ligne.lettrage_code,
            "libelle": ligne.libelle_ligne or ecr.libelle,
            "debit": round(d, 2), "credit": round(cr, 2), "solde": round(c["_solde"], 2),
            "statut": ecr.statut})
    for c in comptes.values():
        c["solde"] = round(c.pop("_solde"), 2)
    return Response(sorted(comptes.values(), key=lambda x: x["compte"]))


# ── Plan comptable ───────────────────────────────────────────────────
def _compte_dict(c: Compte) -> dict:
    return {"id": str(c.id), "numero": c.numero, "intitule": c.intitule,
            "classe": c.classe, "auxiliaire": bool(c.auxiliaire), "actif": bool(c.actif)}


@api_view(["GET", "POST"])
def plan_comptable(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        num = (payload.get("numero") or "").strip()
        intitule = (payload.get("intitule") or "").strip()
        if not num or not intitule:
            return refus({"detail": "numero et intitule requis."}, status=422)
        if Compte.objects.filter(societe_id=sid, numero=num).exists():
            return refus({"detail": f"Le compte {num} existe déjà."}, status=409)
        c = Compte.objects.create(societe_id=sid, numero=num, intitule=intitule,
                                  classe=num[0], auxiliaire=bool(payload.get("auxiliaire")),
                                  actif=True)
        services.enregistrer_audit(request.user.id, "INSERT", "compte", c.id, None,
                                   {"numero": num})
        return Response(_compte_dict(c), status=201)

    query = Compte.objects.filter(societe_id=sid)
    classe = request.query_params.get("classe")
    if classe:
        query = query.filter(classe=classe)
    if _bool_param(request, "actifs_only"):
        query = query.filter(actif=True)
    comptes = list(query)
    q = request.query_params.get("q")
    if q:
        ql = q.lower()
        comptes = [c for c in comptes if ql in c.numero.lower() or ql in c.intitule.lower()]
    comptes.sort(key=lambda c: c.numero)
    return Response([_compte_dict(c) for c in comptes])


@api_view(["PATCH"])
def maj_compte(request, compte_id):
    c = Compte.objects.filter(id=compte_id).first()
    if not c:
        return refus({"detail": "Compte introuvable."}, status=404)
    _acces_compta(request, c.societe_id)
    payload = request.data or {}
    if payload.get("intitule") is not None:
        c.intitule = payload["intitule"].strip()
    if payload.get("auxiliaire") is not None:
        c.auxiliaire = payload["auxiliaire"]
    if payload.get("actif") is not None:
        c.actif = payload["actif"]
    c.save()
    return Response(_compte_dict(c))


@api_view(["POST"])
def charger_syscohada(request):
    """(Ré)initialise le plan SYSCOHADA — n'écrase aucun compte existant."""
    sid = _societe_param(request)
    _acces_compta(request, sid)
    crees = plan_syscohada.charger_plan(sid)
    return Response({"comptes_crees": crees})


# ── Journaux ─────────────────────────────────────────────────────────
@api_view(["GET", "POST"])
def journaux(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        code = (payload.get("code") or "").strip().upper()
        libelle = (payload.get("libelle") or "").strip()
        if not code or not libelle:
            return refus({"detail": "code et libelle requis."}, status=422)
        if Journal.objects.filter(societe_id=sid, code=code).exists():
            return refus({"detail": f"Le journal {code} existe déjà."}, status=409)
        j = Journal.objects.create(societe_id=sid, code=code, libelle=libelle,
                                   type=payload.get("type", "od"))
        return Response({"id": str(j.id), "code": j.code, "libelle": j.libelle,
                         "type": j.type}, status=201)
    js = Journal.objects.filter(societe_id=sid).order_by("code")
    return Response([{"id": str(j.id), "code": j.code, "libelle": j.libelle,
                      "type": j.type, "actif": bool(j.actif)} for j in js])


# ── Saisie manuelle d'écriture (OD) ──────────────────────────────────
@api_view(["POST"])
def saisir_ecriture(request):
    """Saisie manuelle d'une écriture équilibrée (OD), en USD — comptable/DFI."""
    sid = _societe_param(request)
    _acces_compta(request, sid)
    payload = request.data or {}
    lignes_in = payload.get("lignes") or []
    if len(lignes_in) < 2:
        return refus({"detail": "Au moins deux lignes (un débit et un crédit)."},
                        status=400)
    for l in lignes_in:
        if l.get("sens") not in ("D", "C") or not l.get("compte") \
                or float(l.get("montant") or 0) <= 0:
            return refus({"detail": "Ligne invalide (sens D/C, compte et montant > 0)."},
                            status=422)

    total_d = round(sum(float(l["montant"]) for l in lignes_in if l["sens"] == "D"), 2)
    total_c = round(sum(float(l["montant"]) for l in lignes_in if l["sens"] == "C"), 2)
    if total_d != total_c:
        return refus({"detail": f"Écriture déséquilibrée : débit {total_d} ≠ "
                                   f"crédit {total_c}."}, status=400)

    comptes_valides = set(Compte.objects.filter(societe_id=sid)
                          .values_list("numero", flat=True))
    lignes = []
    for l in lignes_in:
        if l["compte"] not in comptes_valides:
            return refus({"detail": f"Compte {l['compte']} absent du plan comptable."},
                            status=400)
        lignes.append({"sens": l["sens"], "compte": l["compte"],
                       "montant_usd": round(float(l["montant"]), 2),
                       "tiers_id": l.get("tiers_id"), "libelle": l.get("libelle")})

    jcode_in = (payload.get("journal_code") or "OD").upper()
    j = Journal.objects.filter(societe_id=sid, code=jcode_in).first()
    jcode = j.code if j else jcode_in
    jour = (date.fromisoformat(payload["date_ecriture"])
            if payload.get("date_ecriture") else date.today())
    with transaction.atomic():
        ecr = comptabilite.post_ecriture(
            sid, jcode, j.libelle if j else "Opérations diverses", j.type if j else "od",
            jour, payload.get("libelle") or "", lignes,
            "od_manuelle", "saisie_manuelle", None, payload.get("numero_piece"),
            request.user.id, statut="valide")
    return Response(_ecriture_dict(ecr), status=201)


# ── Lettrage des comptes de tiers ────────────────────────────────────
def _num_to_alpha(n: int) -> str:
    """1→A, 26→Z, 27→AA … pour numéroter les lettrages."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@api_view(["GET", "POST"])
def lettrage(request):
    if request.method == "POST":
        return _lettrer(request)
    sid = _societe_param(request)
    _acces_compta(request, sid)
    compte = request.query_params.get("compte")
    if not compte:
        return refus({"detail": "compte requis"}, status=422)
    tiers_id = request.query_params.get("tiers_id")
    non_lettres = _bool_param(request, "non_lettres")
    journaux_d = dict(Journal.objects.filter(societe_id=sid).values_list("id", "code"))
    tiers_noms = dict(Tiers.objects.values_list("id", "nom"))
    compte_obj = Compte.objects.filter(societe_id=sid, numero=compte).first()

    q = (LigneEcriture.objects.filter(societe_id=sid, compte_numero=compte)
         .select_related("ecriture")
         .order_by("ecriture__date_ecriture", "ecriture__numero"))
    if tiers_id:
        q = q.filter(tiers_id=tiers_id)

    lignes, solde, non_lettre = [], 0.0, 0.0
    for l in q:
        e = l.ecriture
        d = float(l.montant_usd) if l.sens == "D" else 0.0
        c = float(l.montant_usd) if l.sens == "C" else 0.0
        solde += d - c
        if not l.lettrage_code:
            non_lettre += d - c
        if non_lettres and l.lettrage_code:
            continue
        lignes.append({
            "id": str(l.id), "date": e.date_ecriture.isoformat(), "piece": e.numero,
            "journal": journaux_d.get(e.journal_id, ""), "libelle": l.libelle_ligne or e.libelle,
            "tiers": tiers_noms.get(l.tiers_id) if l.tiers_id else None,
            "debit": round(d, 2), "credit": round(c, 2), "lettrage": l.lettrage_code,
            "statut": e.statut})
    return Response({"compte": compte, "intitule": compte_obj.intitule if compte_obj else "",
                     "lignes": lignes, "solde": round(solde, 2),
                     "solde_non_lettre": round(non_lettre, 2)})


def _lettrer(request):
    """Lettre un groupe de lignes équilibré (Σdébit = Σcrédit) d'un même compte."""
    payload = request.data or {}
    sid = payload.get("societe_id")
    _acces_compta(request, sid)
    ligne_ids = payload.get("ligne_ids") or []
    if len(ligne_ids) < 2:
        return refus({"detail": "Sélectionnez au moins deux lignes."}, status=400)
    lignes = [LigneEcriture.objects.filter(id=lid).first() for lid in ligne_ids]
    if any(l is None or str(l.societe_id) != str(sid) for l in lignes):
        return refus({"detail": "Ligne invalide."}, status=400)
    comptes = {l.compte_numero for l in lignes}
    if len(comptes) != 1:
        return refus({"detail": "Toutes les lignes doivent être du même compte."},
                        status=400)
    if any(l.lettrage_code for l in lignes):
        return refus({"detail": "Une ligne sélectionnée est déjà lettrée."}, status=409)
    total_d = round(sum(float(l.montant_usd) for l in lignes if l.sens == "D"), 2)
    total_c = round(sum(float(l.montant_usd) for l in lignes if l.sens == "C"), 2)
    if total_d != total_c:
        return refus({"detail": f"Lettrage déséquilibré : débit {total_d} ≠ "
                                   f"crédit {total_c}."}, status=400)

    compte = comptes.pop()
    with transaction.atomic():
        seq = comptabilite._next_compteur(sid, f"LET_{compte}", 0)
        code = _num_to_alpha(seq)
        for l in lignes:
            l.lettrage_code = code
            l.save(update_fields=["lettrage_code"])
        services.enregistrer_audit(request.user.id, "LETTRAGE", "compte", None, None,
                                   {"compte": compte, "code": code, "lignes": len(lignes)})
    return Response({"code": code, "compte": compte, "lignes": len(lignes)})


@api_view(["POST"])
def delettrer(request):
    """Annule un lettrage (retire le code des lignes concernées)."""
    payload = request.data or {}
    sid = payload.get("societe_id")
    _acces_compta(request, sid)
    lignes = list(LigneEcriture.objects.filter(
        societe_id=sid, compte_numero=payload.get("compte"),
        lettrage_code=payload.get("code")))
    if not lignes:
        return refus({"detail": "Lettrage introuvable."}, status=404)
    for l in lignes:
        l.lettrage_code = None
        l.save(update_fields=["lettrage_code"])
    services.enregistrer_audit(request.user.id, "DELETTRAGE", "compte", None, None,
                               {"compte": payload.get("compte"), "code": payload.get("code")})
    return Response({"delettre": len(lignes)})


# ── Rapprochement bancaire ───────────────────────────────────────────
def _solde_compte(societe_id, compte: str, rapproche: bool | None = None) -> float:
    q = LigneEcriture.objects.filter(societe_id=societe_id, compte_numero=compte)
    if rapproche is True:
        q = q.filter(rapprochement_id__isnull=False)
    elif rapproche is False:
        q = q.filter(rapprochement_id__isnull=True)
    s = 0.0
    for sens, m in q.values_list("sens", "montant_usd"):
        s += float(m) if sens == "D" else -float(m)
    return round(s, 2)


@api_view(["GET"])
def rappro_a_pointer(request):
    """Lignes du compte de banque non encore rapprochées (à pointer)."""
    sid = _societe_param(request)
    _acces_compta(request, sid)
    compte = request.query_params.get("compte", "521")
    journaux_d = dict(Journal.objects.filter(societe_id=sid).values_list("id", "code"))
    compte_obj = Compte.objects.filter(societe_id=sid, numero=compte).first()
    rows = (LigneEcriture.objects.filter(societe_id=sid, compte_numero=compte,
                                         rapprochement_id__isnull=True)
            .select_related("ecriture")
            .order_by("ecriture__date_ecriture", "ecriture__numero"))
    lignes = [{
        "id": str(l.id), "date": l.ecriture.date_ecriture.isoformat(),
        "piece": l.ecriture.numero,
        "journal": journaux_d.get(l.ecriture.journal_id, ""),
        "libelle": l.libelle_ligne or l.ecriture.libelle,
        "debit": round(float(l.montant_usd), 2) if l.sens == "D" else 0.0,
        "credit": round(float(l.montant_usd), 2) if l.sens == "C" else 0.0,
        "statut": l.ecriture.statut} for l in rows]
    return Response({"compte": compte, "intitule": compte_obj.intitule if compte_obj else "",
                     "lignes": lignes,
                     "solde_comptable": _solde_compte(sid, compte),
                     "solde_rapproche": _solde_compte(sid, compte, rapproche=True)})


def _rappro_dict(r: RapprochementBancaire) -> dict:
    return {"id": str(r.id), "compte": r.compte, "date_releve": r.date_releve.isoformat(),
            "solde_releve": float(r.solde_releve_usd),
            "solde_comptable": float(r.solde_comptable_usd),
            "solde_rapproche": float(r.solde_rapproche_usd), "ecart": float(r.ecart_usd),
            "statut": r.statut, "date": r.created_at.isoformat() if r.created_at else None}


@api_view(["GET", "POST"])
def rapprochement(request):
    if request.method == "POST":
        return _creer_rapprochement(request)
    sid = _societe_param(request)
    _acces_compta(request, sid)
    q = RapprochementBancaire.objects.filter(societe_id=sid)
    compte = request.query_params.get("compte")
    if compte:
        q = q.filter(compte=compte)
    return Response([_rappro_dict(r) for r in q.order_by("-date_releve")])


def _creer_rapprochement(request):
    """Pointe les lignes du relevé, calcule l'écart relevé / comptable pointé."""
    payload = request.data or {}
    sid = payload.get("societe_id")
    _acces_compta(request, sid)
    compte = payload.get("compte", "521")
    lignes = [LigneEcriture.objects.filter(id=lid).first()
              for lid in payload.get("ligne_ids") or []]
    for l in lignes:
        if l is None or str(l.societe_id) != str(sid) or l.compte_numero != compte:
            return refus({"detail": "Ligne invalide pour ce compte."}, status=400)
        if l.rapprochement_id is not None:
            return refus({"detail": "Une ligne est déjà rapprochée."}, status=409)

    solde_releve = float(payload.get("solde_releve") or 0)
    solde_comptable = _solde_compte(sid, compte)
    deja = _solde_compte(sid, compte, rapproche=True)
    lot = round(sum(float(l.montant_usd) if l.sens == "D" else -float(l.montant_usd)
                    for l in lignes), 2)
    solde_rapproche = round(deja + lot, 2)
    ecart = round(solde_releve - solde_rapproche, 2)

    with transaction.atomic():
        r = RapprochementBancaire.objects.create(
            societe_id=sid, compte=compte,
            date_releve=date.fromisoformat(payload["date_releve"]),
            solde_releve_usd=round(solde_releve, 2), solde_comptable_usd=solde_comptable,
            solde_rapproche_usd=solde_rapproche, ecart_usd=ecart, statut="cloture",
            created_by=request.user.id, created_at=services.maintenant())
        for l in lignes:
            l.rapprochement_id = r.id
            l.save(update_fields=["rapprochement_id"])
        services.enregistrer_audit(request.user.id, "RAPPROCHEMENT",
                                   "rapprochement_bancaire", r.id, None,
                                   {"compte": compte, "lignes": len(lignes), "ecart": ecart})
    return Response(_rappro_dict(r), status=201)


@api_view(["POST"])
def annuler_rapprochement(request, rappro_id):
    """Annule un rapprochement : dépointe ses lignes."""
    r = RapprochementBancaire.objects.filter(id=rappro_id).first()
    if not r:
        return refus({"detail": "Rapprochement introuvable."}, status=404)
    _acces_compta(request, r.societe_id)
    lignes = list(LigneEcriture.objects.filter(rapprochement_id=rappro_id))
    with transaction.atomic():
        for l in lignes:
            l.rapprochement_id = None
            l.save(update_fields=["rapprochement_id"])
        r.delete()
        services.enregistrer_audit(request.user.id, "ANNUL_RAPPROCHEMENT",
                                   "rapprochement_bancaire", rappro_id, None,
                                   {"lignes": len(lignes)})
    return Response({"annule": True, "lignes_depointees": len(lignes)})


# ── États financiers OHADA + cockpit DAF ─────────────────────────────
@api_view(["GET"])
def compte_resultat(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    return Response(etats_financiers.compte_resultat(sid, request.query_params.get("statut")))


@api_view(["GET"])
def bilan(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    return Response(etats_financiers.bilan(sid, request.query_params.get("statut")))


@api_view(["GET"])
def tft(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    return Response(etats_financiers.tft(sid, request.query_params.get("statut")))


@api_view(["GET"])
def cockpit(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    return Response(etats_financiers.cockpit(sid))


# ── Comptes de configuration (imputations des écritures automatiques) ─
# (clé de paramètre `compte.<cle>`, libellé, compte par défaut)
COMPTES_CONFIG = [
    ("compte_client", "Clients", "411"),
    ("compte_fournisseur", "Fournisseurs", "401"),
    ("fournisseur_fnp", "Fournisseurs, factures non parvenues", "408"),
    ("compte_avance_personnel", "Avances au personnel", "421"),
    ("compte_avance_fournisseur", "Avances aux fournisseurs", "409"),
    ("compte_avance", "Avances — compte par défaut", "409"),
    ("compte_caisse", "Caisse", "571"),
    ("compte_charge", "Charge par défaut", "605"),
    ("compte_attente", "Compte d'attente (à reclasser)", "471"),
    ("variation_stock", "Variation des stocks", "603"),
    ("tva_deductible", "TVA déductible (sur achats)", "4452"),
    ("tva_collectee", "TVA collectée (sur ventes)", "4431"),
    ("ecart_manquant", "Manquant de caisse (cession)", "658"),
    ("ecart_excedent", "Excédent de caisse (cession)", "758"),
    ("compte_banque", "Banque (encaissements POS)", "521"),
    ("compte_mobile_money", "Mobile Money (M-Pesa, Airtel, Orange)", "522"),
    ("compte_vente_transport", "Produits de transport (courses)", "706"),
    ("compte_sous_traitance", "Sous-traitance transport (camions tiers)", "612"),
]


def _set_parametre(cle: str, societe_id, valeur: str) -> None:
    p = Parametre.objects.filter(cle=cle, societe_id=societe_id).first()
    if p:
        p.valeur = valeur
        p.save(update_fields=["valeur"])
    else:
        Parametre.objects.create(cle=cle, societe_id=societe_id, valeur=valeur,
                                 type_valeur="string")


@api_view(["GET", "POST"])
def comptes_config(request):
    sid = _societe_param(request)
    _acces_compta(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        known = {c[0] for c in COMPTES_CONFIG}
        n = 0
        for cle, val in (payload.get("config") or {}).items():
            if cle in known and val and val.strip():
                _set_parametre(f"compte.{cle}", sid, val.strip())
                n += 1
        if payload.get("tva_taux_defaut") is not None:
            _set_parametre("tva.taux_defaut", sid, str(payload["tva_taux_defaut"]))
        services.enregistrer_audit(request.user.id, "CONFIG", "comptes_config", None, None,
                                   {"maj": n})
        return Response({"ok": True, "modifies": n})

    intitules = dict(Compte.objects.filter(societe_id=sid).values_list("numero", "intitule"))
    comptes = []
    for cle, libelle, defaut in COMPTES_CONFIG:
        val = services.get_parametre(f"compte.{cle}", sid, defaut)
        comptes.append({"cle": cle, "libelle": libelle, "valeur": val, "defaut": defaut,
                        "intitule": intitules.get(val, "")})
    tva = services.get_parametre("tva.taux_defaut", sid, "16")
    return Response({"comptes": comptes, "tva_taux_defaut": float(tva)})


# ── Revue comptable (validation des pièces avant définitif) ──────────
@api_view(["GET", "POST"])
def revue_config(request):
    """Quels flux passent par une validation du comptable avant définitif."""
    sid = _societe_param(request)
    _acces_compta(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        if payload.get("revue_achats") is not None:
            _set_parametre("compta.revue_achats", sid, "1" if payload["revue_achats"] else "0")
        if payload.get("revue_ventes") is not None:
            _set_parametre("compta.revue_ventes", sid, "1" if payload["revue_ventes"] else "0")
        services.enregistrer_audit(request.user.id, "CONFIG", "revue_config", None, None,
                                   {"achats": payload.get("revue_achats"),
                                    "ventes": payload.get("revue_ventes")})
        return Response({"ok": True})
    return Response({
        "revue_achats": services.get_parametre("compta.revue_achats", sid, "1") == "1",
        "revue_ventes": services.get_parametre("compta.revue_ventes", sid, "0") == "1",
    })
