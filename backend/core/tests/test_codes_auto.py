"""Codes de suivi proposés par le système : un article, un client ou un
fournisseur créé sans code reçoit le prochain numéro libre (ART/CLI/FRS-0001),
les codes saisis à la main restant prioritaires et pris en compte."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role


class CodesAutoTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QC', nom='Société codes')
        self.dfi = Utilisateur.objects.create(email='dfi@codes.local', nom='DFI',
                                              password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(self.dfi.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(self.dfi)

    def _creer_article(self, designation, **extra):
        return self.client.post(f'/api/commercial/articles?societe_id={self.soc.id}',
                                {'designation': designation, **extra}, format='json')

    def test_articles_numerotes(self):
        r = self._creer_article('Savon liquide')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['code'], 'ART-0001')
        # Un code saisi à la main est conservé tel quel…
        r = self._creer_article('Brosse', code='bal-77')
        self.assertEqual(r.json()['code'], 'BAL-77')
        # …et un code manuel suivant le motif ART fait avancer la séquence.
        self._creer_article('Seau', code='ART-7')
        r = self._creer_article('Raclette')
        self.assertEqual(r.json()['code'], 'ART-0008')
        # La désignation reste obligatoire.
        self.assertEqual(self._creer_article('').status_code, 422)

    def test_tiers_numerotes_par_type(self):
        url = f'/api/commercial/tiers?societe_id={self.soc.id}'
        r = self.client.post(url, {'type': 'client', 'nom': 'Client Alpha'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['code'], 'CLI-0001')
        r = self.client.post(url, {'type': 'fournisseur', 'nom': 'Fournisseur Beta'}, format='json')
        self.assertEqual(r.json()['code'], 'FRS-0001')
        r = self.client.post(url, {'type': 'client', 'nom': 'Client Gamma'}, format='json')
        self.assertEqual(r.json()['code'], 'CLI-0002')

    def test_beneficiaire_sans_code(self):
        r = self.client.post(f'/api/beneficiaires?societe_id={self.soc.id}',
                             {'type': 'agent', 'nom': 'Porteur de fonds'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['code'], 'AGT-0001')
