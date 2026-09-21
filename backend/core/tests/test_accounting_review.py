from django.test import TestCase
from core.tests import test_accounting_screens as fixtures
from core.models import Compte, Ecriture, LigneEcriture
from apps.comptabilite.models import AxeAnalytique, SectionAnalytique, VentilationAnalytique


class AccountingReviewTests(TestCase):
    def setUp(self):
        fixtures.AccountingScreensTests.setUp(self)
        self.client.post(self.path, fixtures.AccountingScreensTests.body(self), format='json')
        self.entry = Ecriture.objects.get()
        self.entry.statut = 'en_attente'
        self.entry.save()
        self.line = LigneEcriture.objects.get(compte_numero='601')
        Compte.objects.create(societe_id=self.soc.id, numero='602', intitule='Autres achats', classe='6')
        self.url = f'/api/comptabilite/ecritures/{self.entry.id}/valider'

    def split(self, amounts=(2.34, 10)):
        return {'splits': [{'ligne_id': str(self.line.id), 'repartition': [
            {'compte_numero': '601' if i == 0 else '602', 'montant': m} for i, m in enumerate(amounts)]}]}

    def test_split_preserves_party_and_balance_and_can_only_validate_once(self):
        response = self.client.post(self.url, self.split(), format='json')
        self.assertEqual(response.status_code, 200, response.content)
        lines = list(LigneEcriture.objects.filter(sens='D'))
        self.assertEqual({l.tiers_id for l in lines}, {self.local.id})
        self.assertEqual(sum(float(l.montant_usd) for l in lines), 12.34)
        self.assertEqual(self.client.post(self.url, {}, format='json').status_code, 409)
        self.assertEqual(LigneEcriture.objects.count(), 3)

    def test_invalid_split_does_not_mutate_any_line(self):
        for amounts in [(2.34, 9.99), (2.34, -1), ('NaN', 12.34), (0.001, 12.339), ()]:
            response = self.client.post(self.url, self.split(amounts), format='json')
            self.assertIn(response.status_code, (400, 422), response.content)
            self.entry.refresh_from_db(); self.line.refresh_from_db()
            self.assertEqual(self.entry.statut, 'en_attente')
            self.assertEqual(float(self.line.montant_usd), 12.34)
            self.assertEqual(LigneEcriture.objects.count(), 2)

    def test_stale_revision_cannot_validate_changed_piece(self):
        loaded = self.client.get(f'/api/comptabilite/ecritures?societe_id={self.soc.id}').json()[0]
        self.line.libelle_ligne = 'Correction entre-temps'; self.line.save()
        response = self.client.post(self.url, {'revision': loaded['revision']}, format='json')
        self.assertEqual(response.status_code, 409)
        self.entry.refresh_from_db(); self.assertEqual(self.entry.statut, 'en_attente')

    def test_existing_allocation_cannot_exceed_remaining_first_part(self):
        axis = AxeAnalytique.objects.create(societe_id=self.soc.id, code='A', libelle='A')
        section = SectionAnalytique.objects.create(societe_id=self.soc.id, axe_id=axis.id, code='S', libelle='S')
        VentilationAnalytique.objects.create(societe_id=self.soc.id, axe_id=axis.id, section_id=section.id, ligne_ecriture_id=self.line.id, montant_usd=12.34)
        self.assertEqual(self.client.post(self.url, self.split(), format='json').status_code, 422)
        self.line.refresh_from_db(); self.assertEqual(float(self.line.montant_usd), 12.34)
        self.assertEqual(LigneEcriture.objects.count(), 2)

    def test_foreign_party_or_account_rejected_and_prior_split_rolled_back(self):
        body = self.split()
        body['splits'][0]['repartition'][1]['tiers_id'] = str(self.foreign.id)
        self.assertEqual(self.client.post(self.url, body, format='json').status_code, 400)
        body = self.split(); body['reclassements'] = [{'ligne_id': str(LigneEcriture.objects.get(sens='C').id), 'compte_numero': 'UNKNOWN'}]
        self.assertEqual(self.client.post(self.url, body, format='json').status_code, 400)
        self.assertEqual(LigneEcriture.objects.count(), 2)
        self.line.refresh_from_db(); self.assertEqual(float(self.line.montant_usd), 12.34)
