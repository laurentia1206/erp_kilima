"""Modules affichés par société : réglage admin `modules.masques` (JSON),
relayé aux navigateurs par GET /societes."""
from django.test import TestCase
from rest_framework.test import APIClient

from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role


class ModulesSocieteTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QM', nom='Société test')
        self.dfi = Utilisateur.objects.create(email='dfi@test.local', nom='DFI',
                                              password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(self.dfi.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(self.dfi)

    def test_reglage_et_menu(self):
        url = f'/api/config/modules-societe?societe_id={self.soc.id}'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.content)
        corps = r.json()
        self.assertTrue(all(not m['masque'] for m in corps['modules']))
        codes = {m['code'] for m in corps['modules']}
        self.assertIn('hotel', codes)
        self.assertNotIn('administration', codes)  # jamais masquable
        # Masquer hôtel et engins.
        r = self.client.post('/api/config/modules-societe',
                             {'societe_id': str(self.soc.id),
                              'masques': ['hotel', 'engins']}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['masques'], ['engins', 'hotel'])
        # Un code inconnu est refusé.
        self.assertEqual(self.client.post(
            '/api/config/modules-societe',
            {'societe_id': str(self.soc.id), 'masques': ['administration']},
            format='json').status_code, 422)
        # GET /societes relaie la liste aux navigateurs.
        r = self.client.get('/api/societes')
        self.assertEqual(r.status_code, 200)
        entree = next(s for s in r.json() if s['id'] == str(self.soc.id))
        self.assertEqual(entree['modules_masques'], ['engins', 'hotel'])

    def test_reserve_aux_admins(self):
        caissier = Utilisateur.objects.create(email='c@test.local', nom='C',
                                              password_hash='unused')
        role, _ = Role.objects.get_or_create(code='CAISSIER_CENTRAL',
                                             defaults={'libelle': 'Caissier'})
        _inserer_affectation(caissier.id, self.soc.id, role.id)
        client = APIClient()
        client.force_authenticate(caissier)
        self.assertEqual(client.get(
            f'/api/config/modules-societe?societe_id={self.soc.id}').status_code,
            403)
