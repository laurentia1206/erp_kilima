"""Contrats utilisés par la saisie, la balance et le grand livre React."""
from django.test import TestCase
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role, Tiers, Compte, Journal, Ecriture, LigneEcriture


class AccountingScreensTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='ACCT', nom='Comptabilité test')
        self.other = Societe.objects.create(code='OTHER', nom='Autre société')
        user = Utilisateur.objects.create(email='accounting@test.local', nom='Test', password_hash='unused')
        role, _ = Role.objects.get_or_create(code='DFI', defaults={'libelle': 'DFI'})
        _inserer_affectation(user.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(user)
        for numero in ('601', '401'):
            Compte.objects.create(societe_id=self.soc.id, numero=numero, intitule=numero, classe=numero[0])
        Journal.objects.create(societe_id=self.soc.id, code='OD', libelle='Opérations diverses', type='od')
        self.shared = Tiers.objects.create(code='SH', nom='Homonyme', type='fournisseur')
        self.local = Tiers.objects.create(societe_id=self.soc.id, code='LO', nom='Homonyme', type='fournisseur')
        self.foreign = Tiers.objects.create(societe_id=self.other.id, code='FOR', nom='Autre', type='fournisseur')
        self.path = f'/api/comptabilite/ecritures/saisie?societe_id={self.soc.id}'

    def body(self, year=2026):
        return {'journal_code': 'OD', 'date_ecriture': f'{year}-09-21', 'libelle': 'Test OD', 'lignes': [
            {'sens': 'D', 'compte': '601', 'montant': 12.34, 'tiers_id': str(self.local.id)},
            {'sens': 'C', 'compte': '401', 'montant': 12.34, 'tiers_id': str(self.shared.id)}]}

    def test_entry_is_validated_balanced_and_preserves_distinct_party_ids(self):
        r = self.client.post(self.path, self.body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['statut'], 'valide')
        self.assertEqual(set(LigneEcriture.objects.values_list('tiers_id', flat=True)), {self.local.id, self.shared.id})
        balance = self.client.get(f'/api/comptabilite/balance?societe_id={self.soc.id}&annee=2026&statut=valide').json()
        self.assertTrue(balance['equilibre'])
        self.assertEqual(balance['total_debit'], 12.34)
        ledger = self.client.get(f'/api/comptabilite/grand-livre?societe_id={self.soc.id}&compte=401&statut=valide').json()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]['solde'], -12.34)

    def test_previous_year_is_separate_and_pending_filter_is_honored(self):
        self.assertEqual(self.client.post(self.path, self.body(2025), format='json').status_code, 201)
        self.assertEqual(self.client.post(self.path, self.body(), format='json').status_code, 201)
        Ecriture.objects.filter(date_ecriture__year=2026).update(statut='en_attente')
        url = f'/api/comptabilite/balance?societe_id={self.soc.id}&annee=2026&classe=401'
        b = self.client.get(url).json()
        self.assertEqual(b['lignes'][0]['solde_n1'], -12.34)
        self.assertEqual(b['lignes'][0]['credit'], 12.34)
        validated = self.client.get(url + '&statut=valide').json()
        self.assertEqual(validated['lignes'][0]['credit'], 0)
        self.assertEqual(validated['lignes'][0]['solde_n1'], -12.34)

    def test_foreign_inactive_or_invalid_party_is_rejected_without_writes(self):
        self.local.actif = False
        self.local.save()
        for party_id in (str(self.foreign.id), str(self.local.id), 'bad-id'):
            body = self.body()
            body['lignes'][0]['tiers_id'] = party_id
            r = self.client.post(self.path, body, format='json')
            self.assertIn(r.status_code, (400, 422), r.content)
            self.assertEqual(Ecriture.objects.count(), 0)

    def test_invalid_amount_date_and_unbalanced_entry_do_not_write(self):
        for amount in ('invalid', 'Infinity', '-1', '12.33'):
            body = self.body()
            body['lignes'][0]['montant'] = amount
            r = self.client.post(self.path, body, format='json')
            self.assertIn(r.status_code, (400, 422), r.content)
        body = self.body()
        body['date_ecriture'] = '2026-02-31'
        self.assertEqual(self.client.post(self.path, body, format='json').status_code, 422)
        self.assertFalse(Ecriture.objects.exists())

    def test_accounting_endpoints_reject_unassigned_company(self):
        for endpoint in ('balance', 'grand-livre'):
            self.assertEqual(self.client.get(f'/api/comptabilite/{endpoint}?societe_id={self.other.id}').status_code, 403)
