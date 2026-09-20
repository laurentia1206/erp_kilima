"""Documents & échéances de la flotte — camions, engins ET chauffeurs.

Standard des logiciels de gestion de flotte : chaque document administratif
(assurance, contrôle technique, carte rose, permis de conduire…) porte une
date d'expiration ; le système alerte avant l'échéance (30 jours) et signale
les documents échus. Les fichiers scannés s'attachent via le système
générique piece_jointe (document_type='document_flotte').
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core import services as services
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.transport.models import Camion, Chauffeur
from apps.maintenance.models import DocumentFlotte
from apps.engins.models import Engin
from core.models import PieceJointe
from core.views import _societe_param

# Dispatch, maintenance et direction : les documents concernent les deux métiers.
ROLES = {"DISPATCHER", "MAINTENANCIER", "DT", "ASSISTANT_TECHNIQUE",
         "ASSISTANT_TECH", "COMPTABLE", "DFI", "DG"}

TYPES = ("assurance", "controle_technique", "carte_rose", "vignette",
         "permis", "certificat", "autre")
JOURS_ALERTE = 30


def _acces(request, societe_id):
    roles = assert_acces_societe(request.user, societe_id)
    assert_role(roles, ROLES)
    return roles


def _cible(doc: DocumentFlotte):
    if doc.camion_id:
        c = Camion.objects.filter(id=doc.camion_id).first()
        return "camion", (c.immatriculation if c else None)
    if doc.engin_id:
        e = Engin.objects.filter(id=doc.engin_id).first()
        return "engin", (e.nom if e else None)
    c = Chauffeur.objects.filter(id=doc.chauffeur_id).first()
    return "chauffeur", (c.nom if c else None)


def _etat(doc: DocumentFlotte) -> dict:
    if not doc.date_expiration:
        return {"statut": "permanent", "jours_restants": None}
    restants = (doc.date_expiration - date.today()).days
    statut = "echu" if restants < 0 else \
        ("bientot" if restants <= JOURS_ALERTE else "valide")
    return {"statut": statut, "jours_restants": restants}


def _doc_dict(doc: DocumentFlotte) -> dict:
    genre, nom = _cible(doc)
    pieces = list(PieceJointe.objects.filter(document_type="document_flotte",
                                             document_id=doc.id))
    return {"id": str(doc.id), "cible": genre, "porteur": nom,
            "camion_id": str(doc.camion_id) if doc.camion_id else None,
            "engin_id": str(doc.engin_id) if doc.engin_id else None,
            "chauffeur_id": str(doc.chauffeur_id) if doc.chauffeur_id else None,
            "type_document": doc.type_document, "libelle": doc.libelle,
            "numero": doc.numero,
            "date_emission": doc.date_emission.isoformat()
            if doc.date_emission else None,
            "date_expiration": doc.date_expiration.isoformat()
            if doc.date_expiration else None,
            "note": doc.note, "nb_pieces": len(pieces),
            "etat": _etat(doc)}


def _lire_cible(payload, sid):
    """Exactement un porteur : camion, engin ou chauffeur de la société."""
    donnes = [k for k in ("camion_id", "engin_id", "chauffeur_id")
              if payload.get(k)]
    if len(donnes) != 1:
        return None, refus({"detail": "Indiquez un porteur : camion_id, engin_id "
                                      "ou chauffeur_id."}, status=422)
    cle = donnes[0]
    modele = {"camion_id": Camion, "engin_id": Engin,
              "chauffeur_id": Chauffeur}[cle]
    obj = modele.objects.filter(id=payload[cle]).first()
    if not obj or str(obj.societe_id) != str(sid):
        return None, refus({"detail": "Porteur invalide."}, status=400)
    return {cle: obj.id}, None


@api_view(["GET", "POST"])
def documents(request):
    sid = _societe_param(request)
    _acces(request, sid)
    if request.method == "POST":
        payload = request.data or {}
        cible, erreur = _lire_cible(payload, sid)
        if erreur:
            return erreur
        libelle = (payload.get("libelle") or "").strip()
        if len(libelle) < 2:
            return refus({"detail": "libelle requis."}, status=422)
        type_document = payload.get("type_document", "autre")
        if type_document not in TYPES:
            return refus({"detail": f"type_document : {', '.join(TYPES)}."},
                         status=422)
        champs = {}
        for cle in ("date_emission", "date_expiration"):
            if payload.get(cle):
                try:
                    champs[cle] = date.fromisoformat(payload[cle])
                except ValueError:
                    return refus({"detail": f"{cle} invalide."}, status=422)
        with transaction.atomic():
            doc = DocumentFlotte.objects.create(
                societe_id=sid, **cible, **champs,
                type_document=type_document, libelle=libelle,
                numero=(payload.get("numero") or "").strip() or None,
                note=(payload.get("note") or "").strip() or None,
                created_by=request.user.id, created_at=services.maintenant())
            services.enregistrer_audit(request.user.id, "INSERT",
                                       "document_flotte", doc.id, None,
                                       {"libelle": libelle,
                                        "type": type_document})
        return Response(_doc_dict(doc), status=201)
    docs = [_doc_dict(d) for d in DocumentFlotte.objects.filter(societe_id=sid)]
    # tri : échus d'abord, puis par urgence
    ordre = {"echu": 0, "bientot": 1, "valide": 2, "permanent": 3}
    docs.sort(key=lambda d: (ordre[d["etat"]["statut"]],
                             d["etat"]["jours_restants"]
                             if d["etat"]["jours_restants"] is not None else 99999))
    alertes = {"echu": sum(1 for d in docs if d["etat"]["statut"] == "echu"),
               "bientot": sum(1 for d in docs if d["etat"]["statut"] == "bientot")}
    return Response({"documents": docs, "alertes": alertes})


@api_view(["PATCH", "DELETE"])
def maj_document(request, document_id):
    doc = DocumentFlotte.objects.filter(id=document_id).first()
    if not doc:
        return refus({"detail": "Document introuvable."}, status=404)
    _acces(request, doc.societe_id)
    if request.method == "DELETE":
        with transaction.atomic():
            services.enregistrer_audit(request.user.id, "DELETE",
                                       "document_flotte", doc.id,
                                       {"libelle": doc.libelle}, None)
            doc.delete()
        return Response({"ok": True})
    payload = request.data or {}
    if "libelle" in payload:
        libelle = (payload["libelle"] or "").strip()
        if len(libelle) < 2:
            return refus({"detail": "libelle requis."}, status=422)
        doc.libelle = libelle
    if "type_document" in payload:
        if payload["type_document"] not in TYPES:
            return refus({"detail": f"type_document : {', '.join(TYPES)}."},
                         status=422)
        doc.type_document = payload["type_document"]
    if "numero" in payload:
        doc.numero = (payload["numero"] or "").strip() or None
    if "note" in payload:
        doc.note = (payload["note"] or "").strip() or None
    for cle in ("date_emission", "date_expiration"):
        if cle in payload:
            if payload[cle]:
                try:
                    setattr(doc, cle, date.fromisoformat(payload[cle]))
                except (TypeError, ValueError):
                    return refus({"detail": f"{cle} invalide."}, status=422)
            else:
                setattr(doc, cle, None)
    with transaction.atomic():
        doc.save()
        services.enregistrer_audit(request.user.id, "UPDATE", "document_flotte",
                                   doc.id, None, {"libelle": doc.libelle})
    return Response(_doc_dict(doc))
