"""Contrats des écrans Next : périmètre société et suivi documentaire."""
from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role, Tiers
from apps.transport.models import Camion, ContratTransport
from apps.maintenance.models import DocumentFlotte


class TransportScreensTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QA', nom='Société test')
        self.other = Societe.objects.create(code='AUT', nom='Autre société')
        self.user = Utilisateur.objects.create(email='transport@test.local', nom='Test', password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(self.user.id, self.soc.id, role.id)
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.truck = Camion.objects.create(societe_id=self.soc.id, immatriculation='QA-001')
        self.foreign_truck = Camion.objects.create(societe_id=self.other.id, immatriculation='AUT-001')

    def test_shared_client_allowed_foreign_client_rejected(self):
        shared = Tiers.objects.create(type='client', code='PARTAGE', nom='Client partagé')
        foreign = Tiers.objects.create(societe_id=self.other.id, type='client', code='AUTRE', nom='Client autre société')
        url = f'/api/transport/contrats?societe_id={self.soc.id}'
        body = {'libelle': 'Contrat test', 'client_tiers_id': str(foreign.id), 'date_debut': '2026-09-21', 'tarifs': [{'trajet': 'A vers B', 'mode': 'tonne', 'prix': 12.5}]}
        self.assertEqual(self.client.post(url, body, format='json').status_code, 400)
        self.assertFalse(ContratTransport.objects.exists())
        body['client_tiers_id'] = str(shared.id)
        response = self.client.post(url, body, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['tarifs'][0]['prix'], 12.5)
        self.assertEqual(response.json()['client_tiers_id'], str(shared.id))

    def test_document_renewal_and_removal_are_scoped(self):
        url = f'/api/flotte/documents?societe_id={self.soc.id}'
        body = {'camion_id': str(self.foreign_truck.id), 'type_document': 'assurance', 'libelle': 'Assurance test', 'date_expiration': (date.today() + timedelta(days=9)).isoformat()}
        self.assertEqual(self.client.post(url, body, format='json').status_code, 400)
        body['camion_id'] = str(self.truck.id)
        response = self.client.post(url, body, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['etat']['statut'], 'bientot')
        document_id = response.json()['id']
        update = f'/api/flotte/documents/{document_id}?societe_id={self.soc.id}'
        response = self.client.patch(update, {'date_expiration': None}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['etat']['statut'], 'permanent')
        self.assertEqual(response.json()['camion_id'], str(self.truck.id))
        self.assertEqual(self.client.delete(update).status_code, 200)
        self.assertFalse(DocumentFlotte.objects.exists())

    def test_inaccessible_company_cannot_be_read(self):
        for path in ('dashboard', 'transport/contrats', 'flotte/documents', 'engins/rpe', 'engins/config', 'transport/config'):
            response = self.client.get(f'/api/{path}?societe_id={self.other.id}&ym=2026-09')
            self.assertEqual(response.status_code, 403, (path, response.content))

    def test_maintenance_can_read_documents_without_transport_permissions(self):
        maint = Utilisateur.objects.create(email='maintenance@test.local', nom='Maintenance', password_hash='unused')
        role, _ = Role.objects.get_or_create(code='MAINTENANCIER', defaults={'libelle': 'Maintenance'})
        _inserer_affectation(maint.id, self.soc.id, role.id)
        self.client.force_authenticate(maint)
        self.assertEqual(self.client.get(f'/api/flotte/documents?societe_id={self.soc.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/api/transport/camions?societe_id={self.soc.id}').status_code, 403)

    def test_fuel_picker_allows_dispatcher_without_maintenance_access(self):
        dispatcher = Utilisateur.objects.create(email='dispatch@test.local', nom='Dispatch', password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DISPATCHER', defaults={'libelle': 'Dispatch'})
        _inserer_affectation(dispatcher.id, self.soc.id, role.id)
        self.client.force_authenticate(dispatcher)
        url = f'/api/carburant/vehicules?societe_id={self.soc.id}'
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json(), [{'id': str(self.truck.id), 'type': 'camion', 'nom': 'QA-001'}])
        self.assertEqual(self.client.get(f'/api/carburant/vehicules?societe_id={self.other.id}').status_code, 403)
        self.assertEqual(self.client.get(f'/api/maintenance/parc?societe_id={self.soc.id}').status_code, 403)
