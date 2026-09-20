"""Dépôts & transferts internes — le dépôt central approvisionne les
dépôts dédiés (bar, restaurant, cuisine…) liés aux points de vente.

Les transferts sont valorisés au CUMP du dépôt source et ne génèrent
aucune écriture comptable (le stock reste au même compte 3x) ; seuls les
soldes par dépôt bougent. Invariant : le stock société (Article) est la
somme des dépôts.
"""
from __future__ import annotations

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.stocks.models import Depot
from apps.stocks.serializers import DepotSerializer
from apps.stocks.models import TransfertDepot
from apps.stocks.serializers import TransfertDepotSerializer

from datetime import date

from django.db import transaction
from rest_framework.response import Response

from apps.comptabilite import services as comptabilite
from apps.groupe import services as intersociete_lib
from core import services as services
from apps.stocks import services as stock_lib
from core.auth import assert_acces_societe, assert_role
from core.erreurs import refus
from apps.stocks.models import Article, Depot, InventaireDepot, LigneInventaireDepot, LigneTransfertDepot, StockDepot, TransfertDepot
from apps.comptabilite.models import Ecriture
from apps.commercial.models import PointVente
from core.models import Societe
from core.views import _societe_param

ROLES = {"COMPTABLE", "DFI", "DG", "PRESIDENT", "ADMIN_SYS",
         "CAISSIER_CENTRAL", "CAISSIER_VENDEUR", "RECEPTIONNISTE"}
ROLES_GESTION = {"DFI", "PRESIDENT", "ADMIN_SYS", "DG"}


def _depot_dict(d: Depot) -> dict:
    return DepotSerializer(d).data


class DepotViewSet(MetierModelViewSet):
    """Ressource Depot ; contrats HTTP et validations métier conservés."""
    queryset = Depot.objects.all()
    serializer_class = DepotSerializer
    lookup_url_kwarg = 'depot_id'

    def list(self, request):
        return self._traiter_depots(request)


    def create(self, request):
        return self._traiter_depots(request)


    def _traiter_depots(self, request):
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        if request.method == "POST":
            assert_role(roles, ROLES_GESTION)
            payload = request.data or {}
            libelle = (payload.get("libelle") or "").strip()
            if len(libelle) < 2:
                return refus({"detail": "libelle requis."}, status=422)
            code = (payload.get("code") or "").strip().upper() \
                or libelle.upper().replace(" ", "-")[:20]
            if Depot.objects.filter(societe_id=sid, code=code).exists():
                return refus({"detail": f"Le dépôt {code} existe déjà."}, status=409)
            with transaction.atomic():
                stock_lib.depot_central(sid)   # garantit l'existence du central
                d = Depot.objects.create(societe_id=sid, code=code, libelle=libelle,
                                         type="dedie", created_by=request.user.id,
                                         created_at=services.maintenant())
                services.enregistrer_audit(request.user.id, "INSERT", "depot", d.id,
                                           None, {"libelle": libelle})
            return Response(self.get_serializer(d).data, status=201)
        assert_role(roles, ROLES)
        stock_lib.depot_central(sid)
        q = self.get_queryset()
        if request.query_params.get("toutes") != "1":
            q = q.filter(actif=True)
        ordre = {"central": 0, "dedie": 1}
        rows = sorted(q, key=lambda d: (ordre.get(d.type, 2), d.libelle))
        return Response(self.get_serializer(rows, many=True).data)


    def partial_update(self, request, depot_id):
        d = Depot.objects.filter(id=depot_id).first()
        if not d:
            return refus({"detail": "Dépôt introuvable."}, status=404)
        roles = assert_acces_societe(request.user, d.societe_id)
        assert_role(roles, ROLES_GESTION)
        payload = request.data or {}
        avant = self.get_serializer(d).data
        if "libelle" in payload:
            libelle = (payload["libelle"] or "").strip()
            if len(libelle) < 2:
                return refus({"detail": "libelle requis."}, status=422)
            d.libelle = libelle
        if "actif" in payload and bool(payload["actif"]) != bool(d.actif):
            if not payload["actif"]:
                if d.type == "central":
                    return refus({"detail": "Le dépôt central ne peut pas être "
                                            "fermé."}, status=409)
                reste = round(sum(float(s.valeur) for s in
                                  StockDepot.objects.filter(depot_id=d.id)), 2)
                if reste > 0.009:
                    return refus({"detail": f"Le dépôt contient encore "
                                            f"{reste:.2f} USD de stock — transférez-"
                                            f"le d'abord vers un autre dépôt."},
                                 status=409)
                pv = PointVente.objects.filter(depot_id=d.id, actif=True).first()
                if pv:
                    return refus({"detail": f"Le point de vente « {pv.libelle} » "
                                            f"puise dans ce dépôt — changez son "
                                            f"dépôt d'abord."}, status=409)
            d.actif = bool(payload["actif"])
        with transaction.atomic():
            d.save()
            services.enregistrer_audit(request.user.id, "UPDATE", "depot", d.id,
                                       avant, self.get_serializer(d).data)
        return Response(self.get_serializer(d).data)

    def get_queryset(self):
        sid = _societe_param(self.request)
        assert_role(assert_acces_societe(self.request.user, sid), ROLES)
        return Depot.objects.filter(societe_id=sid)


class EtatDepotViewSet(MetierViewSet):
    """Ressource EtatDepot ; contrats HTTP et validations métier conservés."""

    @action(detail=False, methods=['get'])
    def etat_depot(self, request):
        """État du stock d'un dépôt : article, qté, CUMP dépôt, valeur."""
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, ROLES)
        d = Depot.objects.filter(id=request.query_params.get("depot_id")).first()
        if not d or str(d.societe_id) != str(sid):
            return refus({"detail": "Dépôt invalide."}, status=400)
        arts = {str(a.id): a for a in Article.objects.filter(societe_id=sid)}
        out = []
        for s in StockDepot.objects.filter(depot_id=d.id):
            if abs(float(s.qte)) < 1e-9 and abs(float(s.valeur)) < 0.005:
                continue
            a = arts.get(str(s.article_id))
            if not a:
                continue
            qte = float(s.qte)
            out.append({"article_id": str(a.id), "code": a.code,
                        "designation": a.designation, "unite": a.unite,
                        "qte": qte, "valeur": float(s.valeur),
                        "cump": round(float(s.valeur) / qte, 4) if qte else 0.0})
        out.sort(key=lambda x: x["designation"])
        catalogue = []
        if request.query_params.get('inventaire') == '1':
            catalogue = [{"article_id": str(a.id), "code": a.code, "designation": a.designation,
                "unite": a.unite, "qte": stock_lib.qte_disponible(d.id, a.id),
                "cump": round(stock_lib.cump_depot(d.id, a), 4)} for a in arts.values() if a.gere_stock and a.actif]
        return Response({"depot": _depot_dict(d), "articles": out, "catalogue": catalogue,
                         "valeur_totale": round(sum(x["valeur"] for x in out), 2)})


def _transfert_dict(t: TransfertDepot) -> dict:
    src = Depot.objects.filter(id=t.depot_source_id).first()
    cib = Depot.objects.filter(id=t.depot_cible_id).first()
    lignes = list(LigneTransfertDepot.objects.filter(transfert_id=t.id))
    arts = {str(a.id): a for a in Article.objects.filter(
        id__in=[ln.article_id for ln in lignes])}
    return {"id": str(t.id), "numero": t.numero,
            "date": t.date_transfert.isoformat(),
            "source": src.libelle if src else "?",
            "cible": cib.libelle if cib else "?",
            "note": t.note,
            "lignes": [{"article_id": str(ln.article_id),
                        "code": arts[str(ln.article_id)].code
                        if str(ln.article_id) in arts else "?",
                        "designation": arts[str(ln.article_id)].designation
                        if str(ln.article_id) in arts else "(supprimé)",
                        "qte": float(ln.qte), "valeur": float(ln.valeur)}
                       for ln in lignes],
            "valeur_totale": round(sum(float(ln.valeur) for ln in lignes), 2)}


class TransfertDepotViewSet(MetierModelViewSet):
    """Ressource TransfertDepot ; contrats HTTP et validations métier conservés."""
    queryset = TransfertDepot.objects.none()
    serializer_class = TransfertDepotSerializer

    def list(self, request):
        return self._traiter_transferts(request)


    def create(self, request):
        return self._traiter_transferts(request)


    def _traiter_transferts(self, request):
        sid = _societe_param(request)
        roles = assert_acces_societe(request.user, sid)
        assert_role(roles, ROLES)
        if request.method == "POST":
            payload = request.data or {}
            source = Depot.objects.filter(id=payload.get("depot_source_id"),
                                          actif=True).first()
            cible = Depot.objects.filter(id=payload.get("depot_cible_id"),
                                         actif=True).first()
            if not source or str(source.societe_id) != str(sid) \
                    or not cible or str(cible.societe_id) != str(sid):
                return refus({"detail": "Dépôts invalides."}, status=400)
            if source.id == cible.id:
                return refus({"detail": "Source et cible identiques."}, status=422)
            lignes = payload.get("lignes") or []
            if not lignes:
                return refus({"detail": "Aucune ligne à transférer."}, status=422)
            societe = Societe.objects.filter(id=sid).first()
            jour = date.today()
            with transaction.atomic():
                t = TransfertDepot.objects.create(
                    societe_id=sid,
                    numero=services.next_numero("transfert_depot", jour.year,
                                                societe.code, societe.id),
                    depot_source_id=source.id, depot_cible_id=cible.id,
                    date_transfert=jour,
                    note=(payload.get("note") or "").strip() or None,
                    created_by=request.user.id, created_at=services.maintenant())
                for ln in lignes:
                    art = Article.objects.filter(id=ln.get("article_id")).first()
                    if not art or str(art.societe_id) != str(sid) \
                            or not art.gere_stock:
                        return refus({"detail": "Article invalide."}, status=400)
                    try:
                        qte = round(float(ln.get("qte")), 3)
                        if qte <= 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        return refus({"detail": f"Quantité invalide pour "
                                                f"{art.code}."}, status=422)
                    dispo = stock_lib.qte_disponible(source.id, art.id)
                    if dispo < qte - 1e-6:
                        return refus({"detail": f"Stock insuffisant pour {art.code} "
                                                f"au dépôt « {source.libelle} » : "
                                                f"{dispo} {art.unite} disponible(s), "
                                                f"{qte} à transférer."}, status=409)
                    valeur = stock_lib.transferer(art, source, cible, qte, t.numero,
                                                  jour=jour)
                    LigneTransfertDepot.objects.create(
                        transfert_id=t.id, article_id=art.id, qte=qte, valeur=valeur)
                services.enregistrer_audit(request.user.id, "INSERT",
                                           "transfert_depot", t.id, None,
                                           {"numero": t.numero,
                                            "source": source.libelle,
                                            "cible": cible.libelle,
                                            "lignes": len(lignes)})
            return Response(_transfert_dict(t), status=201)
        rows = TransfertDepot.objects.filter(societe_id=sid) \
            .order_by("-created_at")[:100]
        return Response([_transfert_dict(t) for t in rows])


# ═══ Inventaires de dépôt (cuisine, bar…) : théorique vs réel ════════

def _inventaire_dict(inv: InventaireDepot) -> dict:
    depot = Depot.objects.filter(id=inv.depot_id).first()
    lignes = list(LigneInventaireDepot.objects.filter(inventaire_id=inv.id))
    arts = {str(a.id): a for a in Article.objects.filter(
        id__in=[ln.article_id for ln in lignes])}
    ecriture = Ecriture.objects.filter(id=inv.ecriture_id, societe_id=inv.societe_id).first() if inv.ecriture_id else None
    return {"id": str(inv.id), "numero": inv.numero,
            "statut": inv.statut, "created_by": str(inv.created_by) if inv.created_by else None,
            "depot_id": str(inv.depot_id),
            "ecriture": ecriture.numero if ecriture else None,
            "statut_comptable": ecriture.statut if ecriture else None,
            "date": inv.date_inventaire.isoformat(),
            "depot": depot.libelle if depot else "?",
            "valeur_theorique": float(inv.valeur_theorique),
            "valeur_reelle": float(inv.valeur_reelle),
            "ecart_valeur": float(inv.ecart_valeur),
            "note": inv.note,
            "lignes": [{"code": arts[str(ln.article_id)].code
                        if str(ln.article_id) in arts else "?",
                        "designation": arts[str(ln.article_id)].designation
                        if str(ln.article_id) in arts else "(supprimé)",
                        "qte_theorique": float(ln.qte_theorique),
                        "cump": float(ln.cump),
                        "unite": arts[str(ln.article_id)].unite if str(ln.article_id) in arts else '',
                        "qte_reelle": float(ln.qte_reelle),
                        "ecart_qte": float(ln.ecart_qte),
                        "ecart_valeur": float(ln.ecart_valeur)}
                       for ln in lignes]}


# Le circuit de comptage et validation est défini dans inventaires_views.py.

# Anciens points d’entrée conservés pour les intégrations existantes.
depots = DepotViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='depot')
maj_depot = DepotViewSet.as_view({'patch': 'partial_update'}, http_method_names=['patch', 'options'], detail=True, basename='depot')
etat_depot = EtatDepotViewSet.as_view({'get': 'etat_depot'}, http_method_names=['get', 'options'], detail=False, basename='etat_depot')
transferts = TransfertDepotViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='transfert_depot')
