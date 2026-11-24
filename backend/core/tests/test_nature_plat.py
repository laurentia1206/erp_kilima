"""Nature « plat / produit maison » : vendable (POS, factures de vente,
devis) mais jamais achetable (commandes, factures d'achat)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role, Tiers
from apps.stocks.models import Article


class NaturePlatTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QP', nom='Resto test')
        self.dfi = Utilisateur.objects.create(email='dfi@test.local', nom='DFI',
                                              password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(self.dfi.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(self.dfi)
        self.fournisseur = Tiers.objects.create(societe_id=self.soc.id,
                                                type='fournisseur', code='F1',
                                                nom='Fournisseur')
        self.client_t = Tiers.objects.create(societe_id=self.soc.id, type='client',
                                             code='C1', nom='Client')

    def _creer_plat(self):
        r = self.client.post(f'/api/commercial/articles?societe_id={self.soc.id}',
                             {'code': 'PLAT1', 'designation': 'Poulet mayo',
                              'nature': 'plat', 'prix_vente': 12,
                              'gere_stock': True},  # forcé à False côté serveur
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_plat_cree_sans_stock_et_nature_controlee(self):
        corps = self._creer_plat()
        self.assertEqual(corps['nature'], 'plat')
        self.assertFalse(corps['gere_stock'])
        r = self.client.post(f'/api/commercial/articles?societe_id={self.soc.id}',
                             {'code': 'X', 'designation': 'X', 'nature': 'dessert'},
                             format='json')
        self.assertEqual(r.status_code, 422)

    def test_plat_refuse_a_l_achat_mais_accepte_a_la_vente(self):
        plat = self._creer_plat()
        ligne = {'article_id': plat['id'], 'qte': 1, 'prix_unitaire': 12}
        # Commande fournisseur -> refus.
        r = self.client.post(f'/api/commercial/commandes?societe_id={self.soc.id}',
                             {'tiers_id': str(self.fournisseur.id),
                              'lignes': [ligne]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('ne s’achète pas',
                      r.content.decode('utf-8').replace("'", '’'))
        # Facture d'achat -> refus.
        r = self.client.post(f'/api/commercial/factures?societe_id={self.soc.id}',
                             {'type': 'achat', 'tiers_id': str(self.fournisseur.id),
                              'lignes': [ligne]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        # Facture de vente -> acceptée.
        r = self.client.post(f'/api/commercial/factures?societe_id={self.soc.id}',
                             {'type': 'vente', 'tiers_id': str(self.client_t.id),
                              'lignes': [ligne]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_matiere_premiere_toujours_invendable(self):
        far = Article.objects.create(societe_id=self.soc.id, code='FAR',
                                     designation='Farine',
                                     nature='matiere_premiere', compte_stock='32')
        r = self.client.post(f'/api/commercial/factures?societe_id={self.soc.id}',
                             {'type': 'vente', 'tiers_id': str(self.client_t.id),
                              'lignes': [{'article_id': str(far.id), 'qte': 1,
                                          'prix_unitaire': 5}]}, format='json')
        self.assertEqual(r.status_code, 400)
