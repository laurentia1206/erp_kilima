"""Contrats métier utilisés par les nouveaux écrans de cuisine React."""
from datetime import date
from django.test import TestCase
from django.db import transaction
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role, Article, Depot, Facture, LigneFacture, Tiers
from apps.hotel.models import ConsommationCuisine
from apps.stocks import services as stock


class KitchenContractTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='KITCH', nom='Cuisine de recette')
        user = Utilisateur.objects.create(email='kitchen-contract@test.local', nom='Test', password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(user.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(user)
        self.depot = Depot.objects.create(societe_id=self.soc.id, code='CUISINE', libelle='Cuisine')
        self.rice = Article.objects.create(societe_id=self.soc.id, code='RIZ', designation='Riz', nature='matiere_premiere', gere_stock=True, compte_stock='32')
        self.dish = Article.objects.create(societe_id=self.soc.id, code='PLAT', designation='Plat de riz', nature='marchandise', gere_stock=False, prix_vente=20)
        stock.entree(self.rice, self.depot, 10, 20, 'achat', 'RECETTE')
        self.post('cuisine/config', {'depot_id': str(self.depot.id), 'seuil_food_cost_pct': 35})
        self.recipe = self.post('cuisine/fiches', {'article_id': str(self.dish.id), 'portions': 2, 'lignes': [{'article_id': str(self.rice.id), 'qte': 0.5}]}, 201)

    def post(self, path, body, expected=200):
        with transaction.atomic():
            response = self.client.post(f'/api/{path}?societe_id={self.soc.id}', body, format='json')
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def test_recipe_consumption_and_report_preserve_portion_cost_and_single_generation(self):
        self.assertEqual(self.recipe['cout_portion'], 0.5)
        self.assertEqual(self.recipe['lignes'][0]['qte_par_portion'], 0.25)
        client = Tiers.objects.create(societe_id=self.soc.id, type='client', code='CLI', nom='Client recette')
        invoice = Facture.objects.create(societe_id=self.soc.id, tiers_id=client.id, type='vente', numero='RECETTE-V1', date_facture=date.today(), statut='validee')
        LigneFacture.objects.create(facture_id=invoice.id, article_id=self.dish.id, designation='Plat de riz', qte=3, prix_unitaire=20, montant_ht=60)
        body = {'date': date.today().isoformat()}
        result = self.post('cuisine/consommations', body, 201)
        self.assertEqual(result['nb_plats'], 3)
        self.assertEqual(result['cout_total'], 1.5)
        self.assertEqual(result['ca_total'], 60)
        self.assertEqual(result['lignes'][0]['qte'], 0.75)
        self.assertEqual(stock.qte_disponible(self.depot.id, self.rice.id), 9.25)
        self.assertTrue(ConsommationCuisine.objects.get().ecriture_id)
        self.post('cuisine/consommations', body, 409)
        self.assertEqual(ConsommationCuisine.objects.count(), 1)
        report = self.client.get(f'/api/cuisine/rapport?societe_id={self.soc.id}').json()
        self.assertEqual(report['food_cost_pct'], 2.5)
        self.assertEqual(report['manquants_inventaire'], 0)
        self.assertEqual(report['inventaires_valides'], 0)

    def test_empty_sales_do_not_create_consumption_and_recipe_can_be_updated(self):
        self.post('cuisine/consommations', {'date': date.today().isoformat()}, 400)
        self.assertFalse(ConsommationCuisine.objects.exists())
        updated = self.post('cuisine/fiches', {'article_id': str(self.dish.id), 'portions': 4, 'lignes': [{'article_id': str(self.rice.id), 'qte': 0.5}]}, 201)
        self.assertEqual(updated['id'], self.recipe['id'])
        self.assertEqual(updated['cout_portion'], 0.25)
        self.assertEqual(stock.qte_disponible(self.depot.id, self.rice.id), 10)
