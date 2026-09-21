from datetime import date
from django.test import TestCase
from core.tests import test_accounting_screens as fixtures
from core.models import Compte
from apps.comptabilite import etats_financiers, services


class FinancialComparativeTests(TestCase):
    setUp = fixtures.AccountingScreensTests.setUp

    def post(self, year, sens, amount):
        opposite = 'C' if sens == 'D' else 'D'
        return services.post_ecriture(self.soc.id,'OD','Divers','od',date(year,1,1),'Immobilisation',
            [{'sens':sens,'compte':'241','montant_usd':amount},{'sens':opposite,'compte':'401','montant_usd':amount}],
            'od_manuelle','saisie_manuelle',None,None,None)

    def test_fixed_assets_detail_uses_previous_year_amounts(self):
        Compte.objects.create(societe_id=self.soc.id,numero='24',intitule='Matériel',classe='2')
        self.post(2025,'D',100)
        self.post(2026,'C',25)
        data=etats_financiers.bilan(self.soc.id,annee=2026)
        row=data['actif']['immobilise']['lignes'][0]
        self.assertEqual(row['montant'],75)
        self.assertEqual(row['montant_n1'],100)
        self.assertEqual(data['actif']['immobilise']['total_n1'],100)

    def test_disposed_asset_still_appears_in_previous_year_comparison(self):
        self.post(2025,'D',100)
        self.post(2026,'C',100)
        rows=etats_financiers.bilan(self.soc.id,annee=2026)['actif']['immobilise']['lignes']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['montant'],0)
        self.assertEqual(rows[0]['montant_n1'],100)
