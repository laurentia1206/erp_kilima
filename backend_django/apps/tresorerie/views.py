"""Caisse & transferts — portage exact de backend/app/routers/{caisse,transferts}.py
(+ /api/caisse/journal de lecture.py).

Sessions (ouverture, clôture avec comptage/écart/rapport Z), mouvements avec
billetage, opérations multi-devises atomiques (pièce 471 en attente), bons de
caisse imprimables, transferts à double validation avec constat d'écart.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from core import domain as domain
from core import services as services
from core.erreurs import refus
from core.auth import assert_acces_societe, assert_role
from apps.approbations.models import BonReception, OrdreDepense, Requisition
from apps.tresorerie.models import Caisse, CompteBancaire, MouvementCaisse, SessionCaisse, Transfert
from core.models import Societe, Utilisateur
from core.views import _societe_param

ROLES_CAISSE = {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "DFI"}
ROLES_TRANSFERT = {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "COMPTABLE", "DFI"}
ROLES_GESTION_CAISSES = {"DFI", "PRESIDENT", "ADMIN_SYS", "DG"}


# ═══ Gestion du parc de caisses (plusieurs caisses par société) ═══════

def _caisse_dict(c: Caisse) -> dict:
    from apps.commercial.models import PointVente
    sess = _session_ouverte(c.id)
    pv = PointVente.objects.filter(caisse_id=c.id, actif=True).first()
    return {"id": str(c.id), "libelle": c.libelle, "compte": c.compte_comptable,
            "est_principale": bool(c.est_principale), "actif": bool(c.actif),
            "point_vente": pv.libelle if pv else None,
            "session_ouverte": sess is not None,
            "ouverte_depuis": sess.date_ouverture.isoformat()
            if sess and sess.date_ouverture else None,
            "soldes": _soldes(sess) if sess else None}


def _prochain_compte_caisse(societe_id) -> str:
    """Sous-compte 571x libre (la principale garde 571)."""
    pris = set(Caisse.objects.filter(societe_id=societe_id)
               .values_list("compte_comptable", flat=True))
    for i in range(1, 10):
        if f"571{i}" not in pris:
            return f"571{i}"
    return "571"


def _assurer_compte(societe_id, numero: str, intitule: str):
    from apps.comptabilite.models import Compte
    if not Compte.objects.filter(societe_id=societe_id, numero=numero).exists():
        Compte.objects.create(societe_id=societe_id, numero=numero,
                              intitule=intitule, classe="5")


@api_view(["GET", "POST"])
def caisses(request):
    """GET : caisses de la société (actives ; ?toutes=1 inclut les fermées).
    POST : créer une caisse (une par point de vente, par ex.)."""
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    if request.method == "POST":
        assert_role(roles, ROLES_GESTION_CAISSES)
        payload = request.data or {}
        libelle = (payload.get("libelle") or "").strip()
        if len(libelle) < 2:
            return refus({"detail": "libelle requis."}, status=422)
        if Caisse.objects.filter(societe_id=sid, libelle__iexact=libelle,
                                 actif=True).exists():
            return refus({"detail": f"La caisse « {libelle} » existe déjà."},
                         status=409)
        compte = (payload.get("compte_comptable") or "").strip() \
            or _prochain_compte_caisse(sid)
        if not compte.startswith("57"):
            return refus({"detail": "Le compte d'une caisse doit être en 57x "
                                    "(trésorerie espèces SYSCOHADA)."}, status=422)
        with transaction.atomic():
            c = Caisse.objects.create(societe_id=sid, libelle=libelle,
                                      compte_comptable=compte,
                                      est_principale=False)
            _assurer_compte(sid, compte, f"Caisse — {libelle}")
            services.enregistrer_audit(request.user.id, "INSERT", "caisse", c.id,
                                       None, {"libelle": libelle,
                                              "compte": compte})
        return Response(_caisse_dict(c), status=201)
    q = Caisse.objects.filter(societe_id=sid)
    if request.query_params.get("toutes") != "1":
        q = q.filter(actif=True)
    return Response([_caisse_dict(c)
                     for c in q.order_by("-est_principale", "libelle")])


@api_view(["PATCH"])
def maj_caisse(request, caisse_id):
    c = Caisse.objects.filter(id=caisse_id).first()
    if not c:
        return refus({"detail": "Caisse introuvable."}, status=404)
    roles = assert_acces_societe(request.user, c.societe_id)
    assert_role(roles, ROLES_GESTION_CAISSES)
    payload = request.data or {}
    avant = _caisse_dict(c)
    if "libelle" in payload:
        libelle = (payload["libelle"] or "").strip()
        if len(libelle) < 2:
            return refus({"detail": "libelle requis."}, status=422)
        c.libelle = libelle
    if "compte_comptable" in payload:
        compte = (payload["compte_comptable"] or "").strip()
        if not compte.startswith("57"):
            return refus({"detail": "Le compte d'une caisse doit être en 57x."},
                         status=422)
        c.compte_comptable = compte
        _assurer_compte(c.societe_id, compte, f"Caisse — {c.libelle}")
    if "actif" in payload and bool(payload["actif"]) != bool(c.actif):
        if not payload["actif"]:
            if c.est_principale:
                return refus({"detail": "La caisse principale ne peut pas être "
                                        "fermée."}, status=409)
            if _session_ouverte(c.id):
                return refus({"detail": "Session ouverte — clôturez la caisse "
                                        "avant de la fermer."}, status=409)
            from apps.commercial.models import PointVente
            pv = PointVente.objects.filter(caisse_id=c.id, actif=True).first()
            if pv:
                return refus({"detail": f"Le point de vente « {pv.libelle} » "
                                        f"utilise cette caisse — changez sa "
                                        f"caisse d'abord."}, status=409)
        c.actif = bool(payload["actif"])
    with transaction.atomic():
        c.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "caisse", c.id,
                                   avant, _caisse_dict(c))
    return Response(_caisse_dict(c))


def _caisse_ou_404(request, caisse_id):
    caisse = Caisse.objects.filter(id=caisse_id).first()
    if not caisse:
        return None, None
    roles = assert_acces_societe(request.user, caisse.societe_id)
    assert_role(roles, ROLES_CAISSE)
    return caisse, roles


def _session_ouverte(caisse_id) -> SessionCaisse | None:
    return SessionCaisse.objects.filter(caisse_id=caisse_id, statut="ouverte").first()


def _soldes(sess: SessionCaisse) -> dict:
    """Solde théorique par devise = fond initial + entrées − sorties (session)."""
    soldes = {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)}
    rows = (MouvementCaisse.objects.filter(session_id=sess.id)
            .values("devise", "sens").annotate(total=Sum("montant"))
            .values_list("devise", "sens", "total"))
    for devise, sens, total in rows:
        soldes.setdefault(devise, 0.0)
        soldes[devise] += float(total or 0) if sens == "entree" else -float(total or 0)
    return {k: round(v, 2) for k, v in soldes.items()}


def _verif_billetage(billetage: dict | None, montant, contexte: str) -> str | None:
    if not billetage:
        return None
    total_bill = sum(float(c) * float(n) for c, n in billetage.items() if n)
    if abs(total_bill - float(montant)) > 0.01:
        # float(montant) : Pydantic coerce en float côté FastAPI → "5.0", pas "5"
        return contexte.format(total=total_bill, montant=float(montant))
    return None


# ── Sessions ─────────────────────────────────────────────────────────
@api_view(["POST"])
def ouvrir(request, caisse_id):
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    if _session_ouverte(caisse_id):
        return refus({"detail": "Une session de caisse est déjà ouverte."}, status=409)
    payload = request.data or {}
    sess = SessionCaisse.objects.create(
        caisse_id=caisse_id, ouvert_par=request.user.id,
        fond_initial_usd=payload.get("fond_initial_usd", 0),
        fond_initial_cdf=payload.get("fond_initial_cdf", 0),
        statut="ouverte", date_ouverture=services.maintenant())
    services.enregistrer_audit(request.user.id, "OUVERTURE_CAISSE", "session_caisse",
                               sess.id, None,
                               {"fond_usd": payload.get("fond_initial_usd", 0),
                                "fond_cdf": payload.get("fond_initial_cdf", 0)})
    return Response({"id": str(sess.id), "statut": "ouverte"}, status=201)


@api_view(["GET"])
def session_courante(request, caisse_id):
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    sess = _session_ouverte(caisse_id)
    if not sess:
        return Response({"ouverte": False, "caisse": caisse.libelle})
    return Response({
        "ouverte": True, "session_id": str(sess.id), "caisse": caisse.libelle,
        "date_ouverture": sess.date_ouverture.isoformat() if sess.date_ouverture else None,
        "fond_initial_usd": float(sess.fond_initial_usd),
        "fond_initial_cdf": float(sess.fond_initial_cdf),
        "soldes": _soldes(sess),
    })


# ── Mouvements ───────────────────────────────────────────────────────
@api_view(["POST"])
def mouvement(request, caisse_id):
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    sess = _session_ouverte(caisse_id)
    if not sess:
        return refus({"detail": "Aucune session ouverte. Ouvrez d'abord la caisse."},
                        status=409)
    payload = request.data or {}
    sens = payload.get("sens")
    montant = payload.get("montant")
    if sens not in ("entree", "sortie") or not payload.get("nature") \
            or not montant or float(montant) <= 0:
        return refus({"detail": "sens (entree|sortie), nature et montant > 0 requis."},
                        status=422)
    devise = payload.get("devise", "USD")

    jour = date.today()
    taux = services.get_taux_jour(jour, devise)
    if devise != "USD" and taux is None:
        return refus({"detail": f"Aucun taux {devise}/USD défini pour le {jour}."},
                        status=400)
    montant_usd = domain.to_usd(devise, montant, taux)

    err = _verif_billetage(payload.get("billetage"), montant,
                           "Le billetage ({total}) ne correspond pas au montant ({montant}).")
    if err:
        return refus({"detail": err}, status=400)

    soldes = _soldes(sess)
    if sens == "sortie" and soldes.get(devise, 0) < float(montant):
        return refus({"detail": f"Solde caisse insuffisant en {devise} "
                                   f"(disponible {soldes.get(devise, 0)})."}, status=409)

    mvt = MouvementCaisse.objects.create(
        caisse_id=caisse_id, session_id=sess.id, sens=sens, nature=payload["nature"],
        devise=devise, taux_jour=taux, montant=montant, montant_usd=montant_usd,
        libelle=payload.get("libelle"), tiers_nom=payload.get("beneficiaire") or None,
        billetage=payload.get("billetage") or None, created_by=request.user.id,
        date_mouvement=services.maintenant().date(), heure=services.maintenant())
    services.enregistrer_audit(request.user.id, "MOUVEMENT_CAISSE", "mouvement_caisse",
                               mvt.id, None,
                               {"sens": sens, "devise": devise, "montant": montant})
    return Response({"id": str(mvt.id), "soldes": _soldes(sess)}, status=201)


@api_view(["POST"])
def operation(request, caisse_id):
    """Opération de caisse pouvant mélanger plusieurs devises — atomique."""
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    sess = _session_ouverte(caisse_id)
    if not sess:
        return refus({"detail": "Aucune session ouverte."}, status=409)
    payload = request.data or {}
    sens = payload.get("sens")
    legs = payload.get("legs") or []
    if sens not in ("entree", "sortie") or not payload.get("nature"):
        return refus({"detail": "sens (entree|sortie) et nature requis."}, status=422)
    if not legs:
        return refus({"detail": "Au moins un volet de devise requis."}, status=400)

    jour = date.today()
    prepared = []
    besoin = {}   # sorties par devise, pour le contrôle de solde
    for leg in legs:
        devise = leg.get("devise", "USD")
        montant = leg.get("montant")
        if not montant or float(montant) <= 0:
            return refus({"detail": "Montant de volet invalide."}, status=422)
        taux = services.get_taux_jour(jour, devise)
        if devise != "USD" and taux is None:
            return refus({"detail": f"Aucun taux {devise}/USD pour le {jour}."},
                            status=400)
        err = _verif_billetage(leg.get("billetage"), montant,
                               f"Billetage {devise} ({{total}}) ≠ montant ({{montant}}).")
        if err:
            return refus({"detail": err}, status=400)
        prepared.append((leg, taux, domain.to_usd(devise, montant, taux)))
        if sens == "sortie":
            besoin[devise] = besoin.get(devise, 0) + float(montant)

    soldes = _soldes(sess)
    for devise, montant in besoin.items():
        if soldes.get(devise, 0) < montant:
            return refus({"detail": f"Solde caisse insuffisant en {devise} "
                                       f"(disponible {soldes.get(devise, 0)}, "
                                       f"requis {montant})."}, status=409)

    societe = Societe.objects.filter(id=caisse.societe_id).first()
    with transaction.atomic():
        numero = services.next_numero("bon_caisse", date.today().year, societe.code,
                                      caisse.societe_id)
        premier_id = None
        total_usd = 0.0
        for leg, taux, montant_usd in prepared:
            mvt = MouvementCaisse.objects.create(
                caisse_id=caisse_id, session_id=sess.id, sens=sens,
                nature=payload["nature"], numero=numero,
                reference=payload.get("reference") or None,
                devise=leg.get("devise", "USD"), taux_jour=taux, montant=leg["montant"],
                montant_usd=montant_usd, libelle=payload.get("libelle"),
                tiers_nom=payload.get("beneficiaire") or None,
                billetage=leg.get("billetage") or None, created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
            premier_id = premier_id or mvt.id
            total_usd += float(montant_usd)

        # Pièce comptable en attente (contrepartie 471, à reclasser par le comptable)
        parts = [caisse.libelle, payload.get("nature")
                 or ("Encaissement" if sens == "entree" else "Sortie de caisse")]
        if payload.get("beneficiaire"):
            parts.append(payload["beneficiaire"])
        if payload.get("libelle"):
            parts.append(payload["libelle"])
        if payload.get("reference"):
            parts.append(f"réf {payload['reference']}")
        lib = " · ".join(parts)
        ecr = comptabilite.comptabiliser_operation_caisse(
            societe.id, sens, round(total_usd, 2), lib, premier_id, numero,
            request.user.id, nature=payload.get("nature", ""))

        services.enregistrer_audit(request.user.id, "OPERATION_CAISSE", "session_caisse",
                                   sess.id, None,
                                   {"sens": sens, "volets": len(legs), "numero": numero,
                                    "ecriture": ecr.numero})
    return Response({"soldes": _soldes(sess), "numero": numero,
                     "mouvement_id": str(premier_id), "piece_comptable": ecr.numero},
                    status=201)


@api_view(["GET"])
def journal_session(request, caisse_id):
    """Journal de la session ouverte, avec solde courant par devise."""
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    sess = _session_ouverte(caisse_id)
    if not sess:
        return Response({"ouverte": False, "caisse": caisse.libelle, "mouvements": [],
                         "soldes": {"USD": 0, "CDF": 0}})
    mvts = MouvementCaisse.objects.filter(session_id=sess.id).order_by("heure")
    soldes = {"USD": float(sess.fond_initial_usd), "CDF": float(sess.fond_initial_cdf)}
    lignes = []
    for m in mvts:
        soldes.setdefault(m.devise, 0.0)
        soldes[m.devise] += float(m.montant) if m.sens == "entree" else -float(m.montant)
        lignes.append({
            "id": str(m.id), "heure": m.heure.isoformat() if m.heure else None,
            "sens": m.sens, "nature": m.nature, "libelle": m.libelle,
            "tiers": m.tiers_nom, "devise": m.devise, "montant": float(m.montant),
            "a_billetage": bool(m.billetage), "numero": m.numero,
            "reference": m.reference, "solde_apres": round(soldes[m.devise], 2),
        })
    return Response({"ouverte": True, "caisse": caisse.libelle,
                     "fond_initial_usd": float(sess.fond_initial_usd),
                     "fond_initial_cdf": float(sess.fond_initial_cdf),
                     "soldes": {k: round(v, 2) for k, v in soldes.items()},
                     "mouvements": lignes})


# ── Clôture + rapport Z ──────────────────────────────────────────────
def _totaux_session(sess: SessionCaisse) -> dict:
    rows = (MouvementCaisse.objects.filter(session_id=sess.id)
            .values("devise", "sens").annotate(total=Sum("montant"), nb=Count("id"))
            .values_list("devise", "sens", "total", "nb"))
    t = {}
    for devise, sens, total, nb in rows:
        d = t.setdefault(devise, {"entrees": 0.0, "sorties": 0.0, "nb": 0})
        d["entrees" if sens == "entree" else "sorties"] += float(total or 0)
        d["nb"] += int(nb)
    return {k: {"entrees": round(v["entrees"], 2), "sorties": round(v["sorties"], 2),
                "nb": v["nb"]} for k, v in t.items()}


def _rapport_z(sess: SessionCaisse, caisse: Caisse) -> dict:
    societe = Societe.objects.filter(id=caisse.societe_id).first()
    ouvreur = Utilisateur.objects.filter(id=sess.ouvert_par).first()
    clotureur = Utilisateur.objects.filter(id=sess.cloture_par).first() \
        if sess.cloture_par else None
    return {
        "societe": societe.nom, "caisse": caisse.libelle, "session_id": str(sess.id),
        "date_ouverture": sess.date_ouverture.isoformat() if sess.date_ouverture else None,
        "date_cloture": sess.date_cloture.isoformat() if sess.date_cloture else None,
        "ouvert_par": ouvreur.nom if ouvreur else None,
        "cloture_par": clotureur.nom if clotureur else None,
        "fond_initial": {"USD": float(sess.fond_initial_usd),
                         "CDF": float(sess.fond_initial_cdf)},
        "totaux": _totaux_session(sess),
        "theorique": {"USD": float(sess.solde_theorique_usd or 0),
                      "CDF": float(sess.solde_theorique_cdf or 0)},
        "physique": {"USD": float(sess.solde_physique_usd or 0),
                     "CDF": float(sess.solde_physique_cdf or 0)},
        "ecart": {"USD": float(sess.ecart_usd or 0), "CDF": float(sess.ecart_cdf or 0)},
        "billetage": sess.billetage_cloture,
        "commentaire": sess.commentaire_cloture,
    }


@api_view(["POST"])
def cloturer(request, caisse_id):
    """Clôture : comptage physique, écart théorique/physique, verrouillage, rapport Z."""
    caisse, _ = _caisse_ou_404(request, caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    sess = _session_ouverte(caisse_id)
    if not sess:
        return refus({"detail": "Aucune session ouverte à clôturer."}, status=409)
    payload = request.data or {}
    physique_usd = float(payload.get("physique_usd", 0) or 0)
    physique_cdf = float(payload.get("physique_cdf", 0) or 0)

    theorique = _soldes(sess)
    th_usd, th_cdf = theorique.get("USD", 0.0), theorique.get("CDF", 0.0)

    for devise, bill, phys in (("USD", payload.get("billetage_usd"), physique_usd),
                               ("CDF", payload.get("billetage_cdf"), physique_cdf)):
        if bill:
            total_bill = sum(float(c) * float(n) for c, n in bill.items() if n)
            if abs(total_bill - float(phys)) > 0.01:
                return refus({"detail": f"Billetage {devise} ({total_bill}) ≠ physique "
                                           f"déclaré ({phys})."}, status=400)

    ecart_usd = round(physique_usd - th_usd, 2)
    ecart_cdf = round(physique_cdf - th_cdf, 2)

    if (abs(ecart_usd) > 0.01 or abs(ecart_cdf) > 0.01) \
            and not (payload.get("commentaire") or "").strip():
        return refus({"detail": "Un écart de caisse a été constaté : une justification "
                                   "est obligatoire."}, status=400)

    seuil = float(services.get_parametre("caisse.ecart_max_usd", caisse.societe_id, "5")
                  or 5)
    escalade = abs(ecart_usd) > seuil

    sess.solde_theorique_usd, sess.solde_theorique_cdf = th_usd, th_cdf
    sess.solde_physique_usd, sess.solde_physique_cdf = physique_usd, physique_cdf
    sess.ecart_usd, sess.ecart_cdf = ecart_usd, ecart_cdf
    sess.billetage_cloture = {"USD": payload.get("billetage_usd"),
                              "CDF": payload.get("billetage_cdf")}
    sess.commentaire_cloture = (payload.get("commentaire") or "").strip() or None
    sess.statut = "cloturee"
    sess.date_cloture = services.maintenant()
    sess.cloture_par = request.user.id
    sess.save()
    services.enregistrer_audit(request.user.id, "CLOTURE_CAISSE", "session_caisse",
                               sess.id, None,
                               {"ecart_usd": ecart_usd, "ecart_cdf": ecart_cdf,
                                "escalade": escalade})
    rapport = _rapport_z(sess, caisse)
    rapport["escalade_dfi"] = escalade
    rapport["seuil_ecart_usd"] = seuil
    return Response(rapport)


@api_view(["GET"])
def rapport_z(request, session_id):
    """Ré-impression du rapport Z d'une session clôturée."""
    sess = SessionCaisse.objects.filter(id=session_id).first()
    if not sess:
        return refus({"detail": "Session introuvable."}, status=404)
    caisse, _ = _caisse_ou_404(request, sess.caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    rapport = _rapport_z(sess, caisse)
    rapport["statut"] = sess.statut
    return Response(rapport)


@api_view(["GET"])
def bon_mouvement(request, mvt_id):
    """Bon de caisse imprimable, avec le lien vers la pièce d'origine."""
    m = MouvementCaisse.objects.filter(id=mvt_id).first()
    if not m:
        return refus({"detail": "Mouvement introuvable."}, status=404)
    caisse, _ = _caisse_ou_404(request, m.caisse_id)
    if not caisse:
        return refus({"detail": "Caisse introuvable."}, status=404)
    societe = Societe.objects.filter(id=caisse.societe_id).first()
    legs = [m] if not m.numero else list(MouvementCaisse.objects.filter(
        numero=m.numero, caisse_id=m.caisse_id))

    lien = None
    if m.reference_type == "bon_reception" and m.reference_id:
        brf = BonReception.objects.filter(id=m.reference_id).first()
        odp = OrdreDepense.objects.filter(id=brf.ordre_depense_id).first() if brf else None
        req = Requisition.objects.filter(id=odp.requisition_id).first() if odp else None
        lien = {"type": "decaissement", "ordre": odp.numero if odp else None,
                "requisition": req.numero if req else None,
                "objet": req.objet if req else None}
    elif m.reference_type == "transfert" and m.reference_id:
        t = Transfert.objects.filter(id=m.reference_id).first()
        lien = {"type": "transfert", "transfert": t.numero if t else None,
                "motif": t.motif if t else None}

    caissier = Utilisateur.objects.filter(id=m.created_by).first()
    return Response({
        "societe": societe.nom, "caisse": caisse.libelle, "numero": m.numero,
        "date": m.heure.isoformat() if m.heure else None, "sens": m.sens,
        "nature": m.nature, "tiers": m.tiers_nom, "reference": m.reference, "lien": lien,
        "caissier": caissier.nom if caissier else None,
        "legs": [{"devise": l.devise, "montant": float(l.montant),
                  "billetage": l.billetage} for l in legs],
    })


@api_view(["GET"])
def caisse_journal(request):
    """GET /api/caisse/journal — soldes des caisses + 100 derniers mouvements."""
    sid = _societe_param(request)
    assert_acces_societe(request.user, sid)
    out_caisses = []
    for c in Caisse.objects.filter(societe_id=sid):
        entrees = (MouvementCaisse.objects.filter(caisse_id=c.id, sens="entree")
                   .aggregate(t=Sum("montant_usd"))["t"] or 0)
        sorties = (MouvementCaisse.objects.filter(caisse_id=c.id, sens="sortie")
                   .aggregate(t=Sum("montant_usd"))["t"] or 0)
        out_caisses.append({"id": str(c.id), "libelle": c.libelle,
                            "solde_usd": round(float(entrees) - float(sorties), 2)})
    caisses_ids = dict(Caisse.objects.filter(societe_id=sid).values_list("id", "libelle"))
    mvts = (MouvementCaisse.objects.filter(caisse_id__in=caisses_ids.keys())
            .order_by("-heure")[:100])
    mouvements = [{
        "caisse": caisses_ids.get(m.caisse_id),
        "date": m.date_mouvement.isoformat() if m.date_mouvement else None,
        "sens": m.sens, "nature": m.nature, "devise": m.devise,
        "montant": float(m.montant), "montant_usd": float(m.montant_usd),
        "libelle": m.libelle} for m in mvts]
    return Response({"caisses": out_caisses, "mouvements": mouvements})


# ── Transferts ───────────────────────────────────────────────────────
def _endpoint(type_: str, id_):
    """(objet, libellé, compte_comptable) pour une caisse ou une banque."""
    if type_ == "caisse":
        c = Caisse.objects.filter(id=id_).first()
        return (c, c.libelle, c.compte_comptable or "571") if c else (None, None, None)
    b = CompteBancaire.objects.filter(id=id_).first()
    return (b, f"{b.banque} {b.numero_compte or ''}".strip(),
            b.compte_comptable or "521") if b else (None, None, None)


def _solde_devise(sess: SessionCaisse, devise: str) -> float:
    base = float(sess.fond_initial_usd if devise == "USD" else sess.fond_initial_cdf)
    rows = (MouvementCaisse.objects.filter(session_id=sess.id, devise=devise)
            .values("sens").annotate(total=Sum("montant")).values_list("sens", "total"))
    for sens, total in rows:
        base += float(total or 0) if sens == "entree" else -float(total or 0)
    return round(base, 2)


def _peut_valider(roles: set, dest_type: str) -> bool:
    if dest_type == "caisse":
        return bool(roles & {"CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "DFI"})
    return bool(roles & {"COMPTABLE", "DFI"})


@api_view(["GET", "POST"])
def transferts(request):
    if request.method == "POST":
        return _creer_transfert(request)
    sid = _societe_param(request)
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES_TRANSFERT)
    out = []
    for t in Transfert.objects.filter(societe_id=sid).order_by("-created_at"):
        _, src_lbl, _ = _endpoint(t.source_type, t.source_id)
        _, dst_lbl, _ = _endpoint(t.dest_type, t.dest_id)
        init = Utilisateur.objects.filter(id=t.initie_par).first()
        out.append({
            "id": str(t.id), "numero": t.numero, "source": src_lbl, "dest": dst_lbl,
            "source_type": t.source_type, "dest_type": t.dest_type,
            "devise": t.devise, "montant": float(t.montant),
            "montant_usd": float(t.montant_usd),
            "motif": t.motif, "statut": t.statut,
            "initiateur": init.nom if init else None,
            "peut_valider": t.statut == "a_valider" and _peut_valider(roles, t.dest_type),
        })
    return Response(out)


def _creer_transfert(request):
    payload = request.data or {}
    sid = payload.get("societe_id")
    roles = assert_acces_societe(request.user, sid)
    assert_role(roles, ROLES_TRANSFERT)
    if payload.get("source_type") not in ("caisse", "banque") \
            or payload.get("dest_type") not in ("caisse", "banque") \
            or not payload.get("montant") or float(payload["montant"]) <= 0:
        return refus({"detail": "source/dest (caisse|banque) et montant > 0 requis."},
                        status=422)
    if payload["source_type"] == payload["dest_type"] \
            and str(payload.get("source_id")) == str(payload.get("dest_id")):
        return refus({"detail": "Source et destination identiques."}, status=400)
    src, src_lbl, _ = _endpoint(payload["source_type"], payload.get("source_id"))
    dst, dst_lbl, _ = _endpoint(payload["dest_type"], payload.get("dest_id"))
    if not src or not dst:
        return refus({"detail": "Source ou destination introuvable."}, status=404)

    devise = payload.get("devise", "USD")
    montant = payload["montant"]
    taux = services.get_taux_jour(date.today(), devise)
    if devise != "USD" and taux is None:
        return refus({"detail": f"Taux {devise}/USD manquant."}, status=400)
    montant_usd = float(domain.to_usd(devise, montant, taux))

    societe = Societe.objects.filter(id=sid).first()
    with transaction.atomic():
        t = Transfert.objects.create(
            numero=services.next_numero("transfert", date.today().year, societe.code,
                                        societe.id),
            societe_id=sid, source_type=payload["source_type"],
            source_id=payload["source_id"], dest_type=payload["dest_type"],
            dest_id=payload["dest_id"], devise=devise, taux_jour=taux,
            montant=montant, montant_usd=montant_usd, motif=payload.get("motif"),
            statut="a_valider", initie_par=request.user.id,
            created_at=services.maintenant())

        # Sortie côté source si c'est une caisse (les fonds la quittent physiquement)
        if payload["source_type"] == "caisse":
            sess = _session_ouverte(payload["source_id"])
            if not sess:
                return refus({"detail": "La caisse source doit avoir une session "
                                           "ouverte."}, status=409)
            if _solde_devise(sess, devise) < float(montant):
                return refus({"detail": f"Solde source insuffisant en {devise}."},
                                status=409)
            mvt = MouvementCaisse.objects.create(
                caisse_id=payload["source_id"], session_id=sess.id, sens="sortie",
                numero=services.next_numero("bon_caisse", date.today().year, societe.code,
                                            societe.id),
                reference=t.numero, nature="Transfert émis", devise=devise,
                taux_jour=taux, montant=montant, montant_usd=montant_usd,
                tiers_nom=dst_lbl, reference_type="transfert", reference_id=t.id,
                libelle=f"Transfert {t.numero} → {dst_lbl}", created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
            t.source_mouvement_id = mvt.id
            t.save(update_fields=["source_mouvement_id"])
        services.enregistrer_audit(request.user.id, "TRANSFERT_CREE", "transfert", t.id,
                                   None,
                                   {"de": src_lbl, "vers": dst_lbl, "montant": montant})
    return Response({"id": str(t.id), "numero": t.numero, "statut": t.statut,
                     "mouvement_id": str(t.source_mouvement_id)
                     if t.source_mouvement_id else None}, status=201)


@api_view(["POST"])
def valider_transfert(request, transfert_id):
    t = Transfert.objects.filter(id=transfert_id).first()
    if not t:
        return refus({"detail": "Transfert introuvable."}, status=404)
    roles = assert_acces_societe(request.user, t.societe_id)
    assert_role(roles, ROLES_TRANSFERT)
    if t.statut != "a_valider":
        return refus({"detail": "Transfert déjà traité."}, status=409)
    if not _peut_valider(roles, t.dest_type):
        return refus({"detail": "Non autorisé à valider la destination."}, status=403)

    _, src_lbl, compte_src = _endpoint(t.source_type, t.source_id)
    _, dst_lbl, compte_dst = _endpoint(t.dest_type, t.dest_id)

    payload = request.data or {}
    recu = float(payload["montant_recu"]) if payload.get("montant_recu") is not None \
        else float(t.montant)
    if recu < 0:
        return refus({"detail": "Montant reçu invalide."}, status=400)
    recu_usd = float(domain.to_usd(t.devise, recu, t.taux_jour))

    with transaction.atomic():
        # Entrée effective côté destination si c'est une caisse (au montant reçu)
        if t.dest_type == "caisse":
            sess = _session_ouverte(t.dest_id)
            if not sess:
                return refus({"detail": "Ouvrez d'abord la caisse destination."},
                                status=409)
            societe = Societe.objects.filter(id=t.societe_id).first()
            # t.montant reste un Decimal dans le libellé ("émis 4.00", pas "4.0")
            ecart_note = "" if abs(recu - float(t.montant)) < 1e-9 \
                else f" (reçu {recu} / émis {t.montant})"
            mvt = MouvementCaisse.objects.create(
                caisse_id=t.dest_id, session_id=sess.id, sens="entree",
                nature="Transfert reçu",
                numero=services.next_numero("bon_caisse", date.today().year, societe.code,
                                            societe.id),
                reference=t.numero, devise=t.devise, taux_jour=t.taux_jour,
                montant=recu, montant_usd=recu_usd,
                tiers_nom=src_lbl, reference_type="transfert", reference_id=t.id,
                libelle=f"Transfert {t.numero} ← {src_lbl}{ecart_note}",
                created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
            t.dest_mouvement_id = mvt.id

        # Pièce comptable en attente : D destination / C source (+ écart 658/758)
        ecr = comptabilite.comptabiliser_transfert(t, compte_dst, compte_src,
                                                   f"{src_lbl} → {dst_lbl}",
                                                   request.user.id,
                                                   montant_recu_usd=recu_usd)
        t.statut = "valide"
        t.valide_par = request.user.id
        t.valide_at = services.maintenant_micro()
        t.save()
        services.enregistrer_audit(request.user.id, "TRANSFERT_VALIDE", "transfert", t.id,
                                   None, {"ecriture": ecr.numero, "recu": recu,
                                          "emis": float(t.montant)})
    return Response({"id": str(t.id), "statut": "valide", "ecriture": ecr.numero,
                     "ecart_usd": round(float(t.montant_usd) - recu_usd, 2),
                     "mouvement_id": str(t.dest_mouvement_id)
                     if t.dest_mouvement_id else None})


@api_view(["POST"])
def rejeter_transfert(request, transfert_id):
    t = Transfert.objects.filter(id=transfert_id).first()
    if not t:
        return refus({"detail": "Transfert introuvable."}, status=404)
    roles = assert_acces_societe(request.user, t.societe_id)
    assert_role(roles, ROLES_TRANSFERT)
    if t.statut != "a_valider":
        return refus({"detail": "Transfert déjà traité."}, status=409)
    if not _peut_valider(roles, t.dest_type):
        return refus({"detail": "Non autorisé."}, status=403)
    motif = (request.data or {}).get("motif")
    if not motif:
        return refus({"detail": "motif requis"}, status=422)

    with transaction.atomic():
        # Retour des fonds côté source (si la sortie avait été enregistrée en caisse)
        if t.source_type == "caisse" and t.source_mouvement_id:
            sess = _session_ouverte(t.source_id)
            if not sess:
                return refus({"detail": "Caisse source fermée : réouvrez-la pour le "
                                           "retour des fonds."}, status=409)
            societe = Societe.objects.filter(id=t.societe_id).first()
            MouvementCaisse.objects.create(
                caisse_id=t.source_id, session_id=sess.id, sens="entree",
                numero=services.next_numero("bon_caisse", date.today().year, societe.code,
                                            societe.id),
                reference=t.numero, nature="Transfert rejeté — retour", devise=t.devise,
                taux_jour=t.taux_jour, montant=t.montant, montant_usd=t.montant_usd,
                reference_type="transfert", reference_id=t.id,
                libelle=f"Retour transfert {t.numero} (rejeté)",
                created_by=request.user.id,
                date_mouvement=services.maintenant().date(), heure=services.maintenant())
        t.statut = "rejete"
        t.motif_rejet = motif
        t.valide_par = request.user.id
        t.valide_at = services.maintenant_micro()
        t.save()
        services.enregistrer_audit(request.user.id, "TRANSFERT_REJETE", "transfert", t.id,
                                   None, {"motif": motif})
    return Response({"id": str(t.id), "statut": "rejete"})
