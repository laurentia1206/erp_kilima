from django.test import TestCase
from django.db import transaction
from core.tests import test_accounting_screens as fixtures
from core.models import LigneEcriture
from apps.comptabilite.models import AxeAnalytique, SectionAnalytique, VentilationAnalytique


class AnalyticScreensTests(TestCase):
    def setUp(self):
        fixtures.AccountingScreensTests.setUp(self)
        response = self.client.post(self.path, fixtures.AccountingScreensTests.body(self), format='json')
        self.assertEqual(response.status_code, 201)
        self.line = LigneEcriture.objects.get(compte_numero='601')
        self.axis = AxeAnalytique.objects.create(societe_id=self.soc.id, code='LOCAL', libelle='Local')
        self.section = SectionAnalytique.objects.create(societe_id=self.soc.id, axe_id=self.axis.id, code='S', libelle='Section')
        self.foreign_axis = AxeAnalytique.objects.create(societe_id=self.other.id, code='AUTRE', libelle='Confidentiel')
        self.foreign_section = SectionAnalytique.objects.create(societe_id=self.other.id, axe_id=self.foreign_axis.id, code='S', libelle='Confidentiel')

    def body(self, parts=None, axis=None):
        return {'societe_id': str(self.soc.id), 'ligne_id': str(self.line.id), 'axe_id': str(axis or self.axis.id), 'repartition': parts if parts is not None else [{'section_id': str(self.section.id), 'montant': 2.34}]}

    def test_foreign_axis_cannot_be_read_or_written_under_authorized_company(self):
        for axis in (self.foreign_axis.id, 'invalid'):
            for endpoint in ('lignes', 'rapport'):
                # Les GET refusés marquent le bloc courant pour annulation ;
                # isoler chaque requête du bloc englobant propre à TestCase.
                with transaction.atomic():
                    response = self.client.get(f'/api/analytique/{endpoint}?societe_id={self.soc.id}&axe_id={axis}')
                self.assertEqual(response.status_code, 404)
            response = self.client.post('/api/analytique/ventiler', self.body([], axis), format='json')
            self.assertEqual(response.status_code, 404)
        self.assertFalse(VentilationAnalytique.objects.exists())

    def test_partial_allocation_replace_clear_and_report(self):
        path = '/api/analytique/ventiler'
        response = self.client.post(path, self.body(), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['ventile'], 2.34)
        report = self.client.get(f'/api/analytique/rapport?societe_id={self.soc.id}&axe_id={self.axis.id}').json()
        self.assertEqual(report['non_ventile']['charges'], 10)
        response = self.client.post(path, self.body([{'section_id': str(self.section.id), 'montant': 12.34}]), format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VentilationAnalytique.objects.count(), 1)
        self.assertEqual(self.client.post(path, self.body([]), format='json').status_code, 200)
        self.assertFalse(VentilationAnalytique.objects.exists())
        self.assertEqual(LigneEcriture.objects.count(), 2)

    def test_invalid_amount_or_foreign_section_leaves_existing_allocation_intact(self):
        self.client.post('/api/analytique/ventiler', self.body(), format='json')
        for amount in ('NaN', 'Infinity', '-2', '0.001', '12.36', 'invalid'):
            response = self.client.post('/api/analytique/ventiler', self.body([{'section_id': str(self.section.id), 'montant': amount}]), format='json')
            self.assertIn(response.status_code, (400, 422), response.content)
        response = self.client.post('/api/analytique/ventiler', self.body([{'section_id': str(self.foreign_section.id), 'montant': 1}]), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(float(VentilationAnalytique.objects.get().montant_usd), 2.34)

    def test_duplicate_section_returns_conflict(self):
        response = self.client.post(f'/api/analytique/axes/{self.axis.id}/sections', {'code': 's', 'libelle': 'Doublon'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(SectionAnalytique.objects.filter(axe_id=self.axis.id).count(), 1)
