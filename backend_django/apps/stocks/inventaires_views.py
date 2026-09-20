"""Comptage préparé, puis validation explicite par la comptabilité ou le DFI."""

from rest_framework.decorators import action
from core.viewsets import MetierModelViewSet, MetierViewSet
from apps.stocks.models import InventaireDepot
from apps.stocks.serializers import InventaireDepotSerializer
import math
from datetime import date
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from core.auth import assert_acces_societe, assert_role
from apps.stocks.models import Article, Depot, StockDepot, InventaireDepot, LigneInventaireDepot
from core.models import Societe
from apps.stocks import services as stock_lib
from core import services as services
from apps.comptabilite import services as comptabilite
from apps.groupe import services as intersociete_lib
from apps.stocks.views import ROLES, _inventaire_dict
from core.erreurs import refus
from core.views import _societe_param
from apps.comptabilite.tva_views import periode_mensuelle


def verrouiller(sid):
    # Le verrou d'écriture protège aussi SQLite, sans modifier la société.
    Societe.objects.filter(id=sid).update(nom=F('nom'))


class InventaireViewSet(MetierModelViewSet):
    """Ressource Inventaire ; contrats HTTP et validations métier conservés."""
    queryset = InventaireDepot.objects.none()
    serializer_class = InventaireDepotSerializer
    lookup_url_kwarg = 'inventaire_id'

    def list(self, request):
        return self._traiter_inventaires(request)


    def create(self, request):
        return self._traiter_inventaires(request)


    @transaction.atomic
    def _traiter_inventaires(self, request):
        sid = _societe_param(request)
        assert_role(assert_acces_societe(request.user, sid), ROLES)
        if request.method == 'GET':
            q = InventaireDepot.objects.filter(societe_id=sid)
            if request.query_params.get('depot_id'):
                q = q.filter(depot_id=request.query_params['depot_id'])
            if request.query_params.get('mois'):
                du, au = periode_mensuelle(request.query_params['mois'])
                q = q.filter(date_inventaire__range=(du, au))
            q = q.order_by('-date_inventaire', '-created_at')
            if not request.query_params.get('mois'): q = q[:50]
            return Response([_inventaire_dict(i) for i in q])
        p = request.data or {}
        d = Depot.objects.filter(id=p.get('depot_id'), societe_id=sid, actif=True).first()
        if not d: raise ValidationError('Dépôt invalide.')
        lignes = p.get('lignes')
        if not isinstance(lignes, list) or not lignes or not all(isinstance(l, dict) for l in lignes):
            raise ValidationError('Renseignez les articles comptés.')
        ids = [str(l.get('article_id')) for l in lignes]
        if len(ids) != len(set(ids)): raise ValidationError('Un article ne peut apparaître deux fois.')
        verrouiller(sid)
        articles = {str(a.id): a for a in Article.objects.select_for_update().filter(societe_id=sid, gere_stock=True).order_by('id')}
        donnees = []
        for l in lignes:
            a = articles.get(str(l.get('article_id')))
            if not a: raise ValidationError('Article invalide ou appartenant à une autre société.')
            try:
                reel = round(float(l.get('qte_reelle')), 3)
                if not math.isfinite(reel) or reel < 0: raise ValueError
            except (ValueError, TypeError, OverflowError): raise ValidationError(f'Comptage invalide : {a.code}.')
            theo = stock_lib.qte_disponible(d.id, a.id)
            sd = StockDepot.objects.filter(depot_id=d.id, article_id=a.id).first()
            valeur = float(sd.valeur) if sd else 0.0
            if l.get('qte_theorique') is not None and round(float(l['qte_theorique']), 3) != round(theo, 3):
                return refus({'detail': f'Le stock de {a.code} a changé pendant la saisie. Rouvrez le comptage et vérifiez la quantité.'}, status=409)
            cump = stock_lib.cump_depot(d.id, a)
            donnees.append((a, theo, reel, cump, valeur))
        jour = date.today()
        soc = Societe.objects.get(id=sid)
        inv = InventaireDepot.objects.create(societe_id=sid, depot_id=d.id, statut='brouillon',
            numero=services.next_numero('inventaire_depot', jour.year, soc.code, soc.id), date_inventaire=jour,
            note=str(p.get('note') or '').strip()[:255] or None,
            created_by=request.user.id, created_at=services.maintenant())
        for a, theo, reel, cump, valeur in donnees:
            LigneInventaireDepot.objects.create(inventaire_id=inv.id, article_id=a.id,
                qte_theorique=theo, qte_reelle=reel, cump=round(cump, 4), valeur_stock_comptee=valeur,
                ecart_qte=round(reel-theo, 3), ecart_valeur=round((reel-theo)*cump, 2))
        inv.valeur_theorique = round(sum(theo*cump for _, theo, _, cump, _ in donnees), 2)
        inv.ecart_valeur = round(sum(round((reel-theo)*cump, 2) for _, theo, reel, cump, _ in donnees), 2)
        inv.valeur_reelle = round(inv.valeur_theorique+inv.ecart_valeur, 2)
        inv.save()
        services.enregistrer_audit(request.user.id, 'PREPARE', 'inventaire_depot', inv.id, None, {'numero': inv.numero})
        return Response(_inventaire_dict(inv), status=201)


    @action(detail=True, methods=['post'])
    @transaction.atomic
    def decision(self, request, inventaire_id):
        inv = InventaireDepot.objects.filter(id=inventaire_id).first()
        if not inv: return refus({'detail': 'Inventaire introuvable.'}, status=404)
        roles = assert_acces_societe(request.user, inv.societe_id)
        assert_role(roles, ROLES)
        action = request.data.get('action')
        if action not in ['valider', 'annuler']: raise ValidationError('Décision invalide.')
        if action == 'valider' or str(inv.created_by) != str(request.user.id): assert_role(roles, {'DFI', 'COMPTABLE'})
        verrouiller(inv.societe_id)
        inv = InventaireDepot.objects.select_for_update().get(id=inv.id)
        if inv.statut != 'brouillon': return refus({'detail': 'Cet inventaire a déjà été traité.'}, status=409)
        if action == 'annuler':
            inv.statut = 'annule'; inv.save(update_fields=['statut'])
            services.enregistrer_audit(request.user.id, 'ANNULE', 'inventaire_depot', inv.id, None, None)
            return Response(_inventaire_dict(inv))
        d = Depot.objects.filter(id=inv.depot_id, societe_id=inv.societe_id, actif=True).first()
        if not d: raise ValidationError('Le dépôt est désactivé.')
        lignes = list(LigneInventaireDepot.objects.filter(inventaire_id=inv.id).order_by('article_id'))
        arts = {a.id: a for a in Article.objects.select_for_update().filter(id__in=[l.article_id for l in lignes], societe_id=inv.societe_id).order_by('id')}
        # Tout contrôler AVANT le premier mouvement ; un stock modifié exige un nouveau comptage.
        for l in lignes:
            a = arts.get(l.article_id)
            if not a or not a.gere_stock: raise ValidationError('Un article du comptage n’est plus disponible.')
            sd = StockDepot.objects.filter(depot_id=d.id, article_id=a.id).first()
            valeur = float(sd.valeur) if sd else 0.0
            if round(stock_lib.qte_disponible(d.id, a.id), 3) != round(float(l.qte_theorique), 3) or round(valeur, 2) != round(float(l.valeur_stock_comptee or 0), 2) or round(stock_lib.cump_depot(d.id, a), 4) != round(float(l.cump), 4):
                return refus({'detail': f'Le stock ou le coût de {a.code} a changé depuis le comptage. Annulez ce brouillon et refaites le comptage ; aucun ajustement n’a été passé.'}, status=409)
        montants = {}
        for l in lignes:
            a = arts[l.article_id]
            q, v = float(l.ecart_qte), float(l.ecart_valeur)
            if q < 0: stock_lib.sortie(a, d, -q, 'inventaire', inv.numero, jour=inv.date_inventaire, valeur=-v)
            elif q > 0: stock_lib.entree(a, d, q, v, 'inventaire', inv.numero, jour=inv.date_inventaire)
            if v:
                cle = ('manquant' if v < 0 else 'excedent', a.compte_stock)
                montants[cle] = round(montants.get(cle, 0)+abs(v), 2)
        ecr_lignes = []
        for (nature, compte), val in montants.items():
            manque = nature == 'manquant'
            ecart = comptabilite._compte('ecart_'+nature, inv.societe_id)
            ecr_lignes += [{'sens': 'D', 'compte': ecart if manque else compte, 'montant_usd': val, 'libelle': inv.numero},
                          {'sens': 'C', 'compte': compte if manque else ecart, 'montant_usd': val, 'libelle': inv.numero}]
        if ecr_lignes:
            e = comptabilite.post_ecriture(inv.societe_id, 'STK', 'Stocks', 'od', inv.date_inventaire,
                f'Écart inventaire {inv.numero} — {d.libelle}', ecr_lignes, 'inventaire', 'inventaire_depot', inv.id,
                inv.numero, request.user.id, statut=intersociete_lib._statut_piece(inv.societe_id, 'achat'))
            inv.ecriture_id = e.id
        inv.statut = 'valide'; inv.valide_par = request.user.id; inv.valide_at = services.maintenant(); inv.save()
        services.enregistrer_audit(request.user.id, 'VALIDE', 'inventaire_depot', inv.id, None,
            {'numero': inv.numero, 'ecart': str(inv.ecart_valeur), 'ecriture_id': str(inv.ecriture_id) if inv.ecriture_id else None})
        return Response(_inventaire_dict(inv))


# Anciens points d’entrée conservés pour les intégrations existantes.
inventaires = InventaireViewSet.as_view({'get': 'list', 'post': 'create'}, http_method_names=['get', 'post', 'options'], detail=False, basename='inventaire')
decision = InventaireViewSet.as_view({'post': 'decision'}, http_method_names=['post', 'options'], detail=True, basename='inventaire')
