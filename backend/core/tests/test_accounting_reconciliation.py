from django.test import TestCase
from core.tests import test_accounting_screens as fixtures
from core.models import Compte, LigneEcriture, RapprochementBancaire, Ecriture, Parametre


class AccountingReconciliationTests(TestCase):
    setUp = fixtures.AccountingScreensTests.setUp
    body = fixtures.AccountingScreensTests.body

    def test_matching_and_unmatching_preserve_amounts_and_account_balance(self):
        self.assertEqual(self.client.post(self.path, self.body(), format='json').status_code, 201)
        opposite = self.body()
        for line in opposite['lignes']:
            line['sens'] = 'C' if line['sens'] == 'D' else 'D'
        self.assertEqual(self.client.post(self.path, opposite, format='json').status_code, 201)
        ids = list(map(str, LigneEcriture.objects.filter(compte_numero='401').values_list('id', flat=True)))
        r = self.client.post('/api/comptabilite/lettrage', {'societe_id':str(self.soc.id),'ligne_ids':ids},format='json')
        self.assertEqual(r.status_code,200,r.content)
        code = r.json()['code']
        self.assertEqual(self.client.post('/api/comptabilite/lettrage', {'societe_id':str(self.soc.id),'ligne_ids':ids},format='json').status_code,409)
        remaining = self.client.get(f'/api/comptabilite/lettrage?societe_id={self.soc.id}&compte=401&non_lettres=true').json()
        self.assertEqual(remaining['lignes'],[])
        self.assertEqual(remaining['solde_non_lettre'],0)
        r = self.client.post('/api/comptabilite/delettrage',{'societe_id':str(self.soc.id),'compte':'401','code':code},format='json')
        self.assertEqual(r.json()['delettre'],2)
        self.assertEqual(Ecriture.objects.count(),2)

    def test_bank_snapshot_and_cancellation_preserve_entries(self):
        Compte.objects.create(societe_id=self.soc.id,numero='521',intitule='Banque',classe='5')
        body = self.body()
        body['lignes'][0]['compte'] = '521'
        self.assertEqual(self.client.post(self.path, body, format='json').status_code,201)
        ids = list(map(str,LigneEcriture.objects.filter(compte_numero='521').values_list('id',flat=True)))
        payload = {'societe_id':str(self.soc.id),'compte':'521','ligne_ids':ids,'solde_releve':12.34,'date_releve':'2026-09-21'}
        r = self.client.post('/api/comptabilite/rapprochement',payload,format='json')
        self.assertEqual(r.status_code,201,r.content)
        self.assertEqual(r.json()['ecart'],0)
        self.assertEqual(self.client.post('/api/comptabilite/rapprochement',payload,format='json').status_code,409)
        pointer = self.client.get(f'/api/comptabilite/rapprochement/a-pointer?societe_id={self.soc.id}&compte=521').json()
        self.assertEqual(pointer['lignes'],[])
        self.assertEqual(pointer['solde_rapproche'],12.34)
        cancelled = self.client.post(f"/api/comptabilite/rapprochement/{r.json()['id']}/annuler",{},format='json')
        self.assertEqual(cancelled.status_code,200)
        self.assertEqual(cancelled.json()['lignes_depointees'],1)
        self.assertFalse(RapprochementBancaire.objects.exists())
        self.assertEqual(Ecriture.objects.count(),1)

    def test_plan_and_journal_duplicates_are_rejected(self):
        url=f'/api/comptabilite/plan-comptable?societe_id={self.soc.id}'
        payload={'numero':'6059','intitule':'Compte test','auxiliaire':True}
        r=self.client.post(url,payload,format='json')
        self.assertEqual(r.status_code,201,r.content)
        self.assertEqual(self.client.post(url,payload,format='json').status_code,409)
        updated=self.client.patch('/api/comptabilite/plan-comptable/'+r.json()['id'],{'intitule':'Renommé','actif':False},format='json')
        self.assertEqual(updated.status_code,200)
        self.assertTrue(updated.json()['auxiliaire'])
        self.assertFalse(updated.json()['actif'])
        url=f'/api/comptabilite/journaux?societe_id={self.soc.id}'
        payload={'code':'BQ2','libelle':'Deuxième banque','type':'banque'}
        self.assertEqual(self.client.post(url,payload,format='json').status_code,201)
        self.assertEqual(self.client.post(url,payload,format='json').status_code,409)

    def test_account_configuration_does_not_change_review_rules(self):
        suffix=f'?societe_id={self.soc.id}'
        before=self.client.get('/api/comptabilite/revue-config'+suffix).json()
        r=self.client.post('/api/comptabilite/comptes-config'+suffix,{'config':{'compte_charge':'601'},'tva_taux_defaut':16},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.get('/api/comptabilite/revue-config'+suffix).json(),before)
        self.assertEqual(Parametre.objects.get(societe_id=self.soc.id,cle='compte.compte_charge').valeur,'601')
