"""Services transverses — portage exact de backend/app/services.py.

Numérotation des pièces, paramètres (société sinon groupe), taux du jour,
journal d'audit. Mêmes formats de numéros (REQ-PLA-2026-000125).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from django.db import transaction

from .models import AuditLog, Parametre, SequenceCompteur, TauxChange

PREFIXES = {
    "requisition": "REQ", "ordre_depense": "ODP", "bon_reception": "BRF",
    "avance": "AVJ", "justification": "JUST", "cession": "CES", "transfert": "TRF",
    "bon_caisse": "BC", "facture_achat": "FA", "facture_vente": "FV",
    "commande": "CMD", "reception": "REC", "avoir_vente": "AVV",
    "devis": "DEV", "livraison": "BL",
    "course": "FC", "contrat_transport": "CTR", "intervention": "INT",
    "reception_inter": "RI", "sejour": "SEJ", "transfert_depot": "TD",
    "consommation_cuisine": "CC", "inventaire_depot": "INV",
}


def maintenant() -> datetime:
    """Horodatage d'insertion : UTC naïf à la SECONDE, comme CURRENT_TIMESTAMP
    de SQLite (parité stricte avec les lignes écrites par FastAPI — les
    microsecondes de Django fausseraient les tris par created_at)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def maintenant_micro() -> datetime:
    """UTC naïf AVEC microsecondes — pour les colonnes que FastAPI remplit avec
    un datetime.now(timezone.utc) explicite (SQLAlchemy/SQLite tronque l'offset
    mais garde les microsecondes : ex. avance.date_octroi, echeance_justif)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_numero(type_piece: str, annee: int, societe_code: str | None, societe_id) -> str:
    """Numéro séquentiel par société/type/année (verrou par ligne)."""
    with transaction.atomic():
        compteur = (SequenceCompteur.objects.select_for_update()
                    .filter(societe_id=societe_id, type_piece=type_piece, annee=annee).first())
        if compteur is None:
            compteur = SequenceCompteur.objects.create(
                societe_id=societe_id, type_piece=type_piece, annee=annee, dernier_numero=0)
        compteur.dernier_numero += 1
        compteur.save(update_fields=["dernier_numero"])
        n = compteur.dernier_numero
    prefix = PREFIXES.get(type_piece, type_piece[:3].upper())
    return f"{prefix}-{societe_code or 'GRP'}-{annee}-{n:06d}"


def get_parametre(cle: str, societe_id=None, defaut: str | None = None) -> str | None:
    """Paramètre : valeur spécifique société sinon valeur groupe."""
    if societe_id is not None:
        v = (Parametre.objects.filter(societe_id=societe_id, cle=cle)
             .values_list("valeur", flat=True).first())
        if v is not None:
            return v
    v = (Parametre.objects.filter(societe_id__isnull=True, cle=cle)
         .values_list("valeur", flat=True).first())
    return v if v is not None else defaut


def get_taux_jour(jour: date, devise: str = "CDF") -> Decimal | None:
    """Taux du jour fixé par le DFI (1 USD = taux CDF)."""
    if devise == "USD":
        return Decimal("1")
    return (TauxChange.objects.filter(date_taux=jour, devise=devise)
            .values_list("taux_usd", flat=True).first())


def load_paliers(type_document: str, etape: str, societe_id) -> list:
    """Grille de paliers en objets domaine — règles société sinon règles groupe."""
    from .domain import Approbateur, Palier
    from .models import PalierApprobateur, PalierValidation

    def _fetch(sid):
        q = PalierValidation.objects.filter(type_document=type_document, etape=etape)
        return list(q.filter(societe_id=sid) if sid is not None
                    else q.filter(societe_id__isnull=True))

    rows = _fetch(societe_id) if societe_id is not None else []
    if not rows:
        rows = _fetch(None)

    paliers = []
    for pv in rows:
        appros = tuple(
            Approbateur(role_code=a.role.code, mode=a.mode)
            for a in PalierApprobateur.objects.filter(palier_id=pv.id)
            .select_related("role").order_by("ordre"))
        paliers.append(Palier(
            montant_min_usd=Decimal(str(pv.montant_min_usd)),
            montant_max_usd=Decimal(str(pv.montant_max_usd))
            if pv.montant_max_usd is not None else None,
            approbateurs=appros, libelle=pv.libelle or ""))
    return paliers


def role_id_by_code(code: str):
    from .models import Role
    return Role.objects.filter(code=code).values_list("id", flat=True).first()


def decisions_par_role(doc_type: str, doc_id, etape: str) -> dict[str, str]:
    """{role_code: decision} des validations enregistrées pour un document/étape."""
    from .models import Role, Validation
    rows = Validation.objects.filter(document_type=doc_type, document_id=doc_id,
                                     etape=etape).values_list("role_attendu_id", "decision")
    codes = dict(Role.objects.values_list("id", "code"))
    return {codes[rid]: decision for rid, decision in rows if rid in codes}


def palier_pour_montant(type_document: str, etape: str, societe_id, montant_usd):
    """Palier applicable à un montant (USD). None si aucun palier configuré."""
    from .domain import resolve_palier
    paliers = load_paliers(type_document, etape, societe_id)
    if not paliers:
        return None
    try:
        return resolve_palier(montant_usd, paliers)
    except ValueError:
        # Aucun palier ne couvre exactement : on retient le plus proche par le bas.
        candidats = [p for p in paliers if float(p.montant_min_usd) <= float(montant_usd)]
        return max(candidats, key=lambda p: p.montant_min_usd) if candidats else paliers[0]


def enregistrer_audit(user_id, action: str, table: str, enregistrement_id,
                      ancienne=None, nouvelle=None) -> None:
    from .audit import append_event
    append_event(user_id, action, table, enregistrement_id, ancienne, nouvelle)
