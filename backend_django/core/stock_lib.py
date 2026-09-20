"""Stock multi-dépôts — le point de passage UNIQUE des mouvements de stock.

Invariant : Article.stock_qte / stock_valeur restent le TOTAL de la
société (tout le code de lecture existant continue de marcher) ; chaque
mouvement met aussi à jour le solde du dépôt concerné (StockDepot) et le
journal MouvementStock (avec depot_id).

- Les entrées (achats, réceptions, justifications, miroirs) vont au
  dépôt CENTRAL par défaut.
- Les sorties de vente puisent dans le dépôt du point de vente
  (PointVente.depot_id, sinon central), valorisées au CUMP du dépôt.
- Les transferts entre dépôts ne touchent ni les totaux société ni la
  comptabilité (même compte 3x) : sortie source + entrée cible.
"""
from __future__ import annotations

import uuid as uuidlib
import math
from datetime import date
from django.db import transaction
from rest_framework.exceptions import ValidationError

from . import services
from .models import Article, Depot, MouvementStock, StockDepot

PREFIXES_OK = None  # (documentation) numérotation des bons : transfert_depot → TD


def depot_central(societe_id) -> Depot:
    depot = Depot.objects.filter(societe_id=societe_id, type="central").first()
    if not depot:
        depot = Depot.objects.create(societe_id=societe_id, code="CENTRAL",
                                     libelle="Dépôt central", type="central",
                                     created_at=services.maintenant())
    return depot


def depot_du_point_vente(pv, societe_id) -> Depot:
    if pv is not None and pv.depot_id:
        depot = Depot.objects.filter(id=pv.depot_id, societe_id=societe_id, actif=True).first()
        if depot:
            return depot
        raise ValidationError({"detail": "Le dépôt du point de vente est inactif ou appartient à une autre société."})
    return depot_central(societe_id)


def solde_depot(depot_id, article_id) -> StockDepot:
    sd = StockDepot.objects.filter(depot_id=depot_id,
                                   article_id=article_id).first()
    if not sd:
        sd = StockDepot.objects.create(depot_id=depot_id, article_id=article_id,
                                       qte=0, valeur=0)
    return sd


def qte_disponible(depot_id, article_id) -> float:
    sd = StockDepot.objects.filter(depot_id=depot_id,
                                   article_id=article_id).first()
    return float(sd.qte) if sd else 0.0


def cump_depot(depot_id, article) -> float:
    """CUMP du dépôt ; à défaut (dépôt vide), CUMP société de l'article."""
    sd = StockDepot.objects.filter(depot_id=depot_id,
                                   article_id=article.id).first()
    if sd and float(sd.qte) > 0:
        return float(sd.valeur) / float(sd.qte)
    return float(article.stock_valeur) / float(article.stock_qte) \
        if float(article.stock_qte) else 0.0


def _verrouiller(article, *depots):
    courant = Article.objects.select_for_update().get(id=article.id)
    if any(str(d.societe_id) != str(courant.societe_id) for d in depots):
        raise ValidationError({"detail": "L'article et les dépôts doivent appartenir à la même société."})
    if any(not d.actif for d in depots):
        raise ValidationError({"detail": "Ce dépôt est désactivé."})
    article.stock_qte, article.stock_valeur = courant.stock_qte, courant.stock_valeur


def _nombre(valeur, decimales, positif=False):
    try:
        valeur = round(float(valeur), decimales)
        if not math.isfinite(valeur) or valeur < 0 or (positif and valeur == 0):
            raise ValueError
        return valeur
    except (ValueError, TypeError, OverflowError):
        raise ValidationError({"detail": "Quantité ou valeur de stock invalide."})


@transaction.atomic
def entree(article: Article, depot: Depot, qte: float, valeur: float,
           type_operation: str, reference: str, jour: date | None = None):
    """Entrée en stock : totaux société + solde dépôt + journal."""
    qte = _nombre(qte, 3, positif=True)
    valeur = _nombre(valeur, 2)
    _verrouiller(article, depot)
    article.stock_qte = round(float(article.stock_qte) + qte, 3)
    article.stock_valeur = round(float(article.stock_valeur) + valeur, 2)
    article.save(update_fields=["stock_qte", "stock_valeur"])
    sd = solde_depot(depot.id, article.id)
    sd.qte = round(float(sd.qte) + qte, 3)
    sd.valeur = round(float(sd.valeur) + valeur, 2)
    sd.save(update_fields=["qte", "valeur"])
    MouvementStock.objects.create(
        societe_id=article.societe_id, article_id=article.id, depot_id=depot.id,
        date_mvt=jour or date.today(), sens="entree", qte=qte,
        cout_unitaire=round(valeur / qte, 4) if qte else 0,
        valeur=valeur, type_operation=type_operation, reference=reference,
        created_at=services.maintenant())


@transaction.atomic
def sortie(article: Article, depot: Depot, qte: float, type_operation: str,
           reference: str, jour: date | None = None,
           valeur: float | None = None) -> float:
    """Sortie de stock au CUMP du dépôt (sauf valeur imposée).
    Retourne la valeur sortie. Disponibilité revérifiée sous verrou."""
    qte = _nombre(qte, 3, positif=True)
    _verrouiller(article, depot)
    if qte > round(qte_disponible(depot.id, article.id), 3):
        raise ValidationError({"detail": "Stock insuffisant dans le dépôt pour cette sortie."})
    if valeur is None:
        valeur = round(qte * cump_depot(depot.id, article), 2)
    else:
        valeur = _nombre(valeur, 2)
    article.stock_qte = round(float(article.stock_qte) - qte, 3)
    article.stock_valeur = round(float(article.stock_valeur) - valeur, 2)
    article.save(update_fields=["stock_qte", "stock_valeur"])
    sd = solde_depot(depot.id, article.id)
    sd.qte = round(float(sd.qte) - qte, 3)
    sd.valeur = round(float(sd.valeur) - valeur, 2)
    sd.save(update_fields=["qte", "valeur"])
    MouvementStock.objects.create(
        societe_id=article.societe_id, article_id=article.id, depot_id=depot.id,
        date_mvt=jour or date.today(), sens="sortie", qte=qte,
        cout_unitaire=round(valeur / qte, 4) if qte else 0,
        valeur=valeur, type_operation=type_operation, reference=reference,
        created_at=services.maintenant())
    return valeur


@transaction.atomic
def transferer(article: Article, source: Depot, cible: Depot, qte: float,
               reference: str, jour: date | None = None) -> float:
    """Transfert inter-dépôts au CUMP du dépôt source. Ne touche PAS les
    totaux société ni la comptabilité. Retourne la valeur transférée."""
    qte = _nombre(qte, 3, positif=True)
    _verrouiller(article, source, cible)
    if source.id == cible.id:
        raise ValidationError({"detail": "Choisissez deux dépôts différents."})
    if qte > round(qte_disponible(source.id, article.id), 3):
        raise ValidationError({"detail": "Stock insuffisant dans le dépôt source."})
    valeur = round(qte * cump_depot(source.id, article), 2)
    jour = jour or date.today()
    for depot, signe in ((source, -1), (cible, +1)):
        sd = solde_depot(depot.id, article.id)
        sd.qte = round(float(sd.qte) + signe * qte, 3)
        sd.valeur = round(float(sd.valeur) + signe * valeur, 2)
        sd.save(update_fields=["qte", "valeur"])
        MouvementStock.objects.create(
            societe_id=article.societe_id, article_id=article.id,
            depot_id=depot.id, date_mvt=jour,
            sens="sortie" if signe < 0 else "entree", qte=qte,
            cout_unitaire=round(valeur / qte, 4) if qte else 0,
            valeur=valeur, type_operation="transfert", reference=reference,
            created_at=services.maintenant())
    return valeur
