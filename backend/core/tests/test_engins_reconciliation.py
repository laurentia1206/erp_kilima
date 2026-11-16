"""Location d'engins : réconciliation mensuelle, verrouillage du mois,
harmonisations d'heures et RPE provisoire/définitif."""
from django.test import TestCase
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role
from apps.engins.models import Engin, PrestationEngin


class EnginsReconciliationTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='HRZ', nom='ETS HORIZON')
        self.dfi = Utilisateur.objects.create(email='dfi@test.local', nom='DFI',
                                              password_hash='unused')
        role_dfi, _ = Role.objects.get_or_create(code='DFI',
                                                 defaults={'libelle': 'DFI'})
        _inserer_affectation(self.dfi.id, self.soc.id, role_dfi.id)
        self.dispatcher = Utilisateur.objects.create(
            email='dispatch@test.local', nom='Dispatch', password_hash='unused')
        role_disp, _ = Role.objects.get_or_create(
            code='DISPATCHER', defaults={'libelle': 'Dispatcher'})
        _inserer_affectation(self.dispatcher.id, self.soc.id, role_disp.id)
        self.client = APIClient()
        self.client.force_authenticate(self.dfi)
        self.ch1 = Engin.objects.create(societe_id=self.soc.id, nom='Chargeuse 01',
                                        tarif_mensuel_usd=9000,
                                        tarif_heure_supp_usd=55)
        self.ch2 = Engin.objects.create(societe_id=self.soc.id, nom='Chargeuse 02',
                                        tarif_mensuel_usd=9000,
                                        tarif_heure_supp_usd=55)
        self.ym = '2026-10'
        # 8h00 de jour le 1er octobre sur la chargeuse 01.
        self.fiche = self._fiche(self.ch1, '2026-10-01', '08:00', '16:00')

    def _fiche(self, engin, jour, debut, fin, statut_attendu=201):
        r = self.client.post(f'/api/engins/prestations?societe_id={self.soc.id}',
                             {'engin_id': str(engin.id), 'date': jour,
                              'poste': 'jour', 'heure_debut': debut,
                              'heure_fin': fin}, format='json')
        self.assertEqual(r.status_code, statut_attendu, r.content)
        return r.json() if statut_attendu == 201 else None

    def _enregistrer_reconciliation(self, revision=0, retenu=510):
        corps = {'ym': self.ym, 'revision': revision, 'donnees': {
            str(self.ch1.id): {'2026-10-01': {
                'client_jour': 540, 'retenu_jour': retenu,
                'note': 'Divergence pointage GCK'}}}}
        return self.client.post(
            f'/api/engins/reconciliation?societe_id={self.soc.id}',
            corps, format='json')

    def test_retenues_et_mention_provisoire_puis_definitive(self):
        rpe = self.client.get(
            f'/api/engins/rpe?societe_id={self.soc.id}&ym={self.ym}').json()
        self.assertEqual(rpe['mention'], 'PROVISOIRE')
        ligne = next(r for r in rpe['rows'] if r['engin'] == 'Chargeuse 01')
        self.assertEqual(ligne['total_dec'], 8.0)

        r = self._enregistrer_reconciliation()
        self.assertEqual(r.status_code, 200, r.content)
        rpe = self.client.get(
            f'/api/engins/rpe?societe_id={self.soc.id}&ym={self.ym}').json()
        ligne = next(r for r in rpe['rows'] if r['engin'] == 'Chargeuse 01')
        self.assertEqual(ligne['total_dec'], 8.5)   # 510 min retenues
        self.assertEqual(rpe['mention'], 'PROVISOIRE')

        r = self.client.post(
            f'/api/engins/reconciliation/valider?societe_id={self.soc.id}',
            {'ym': self.ym, 'revision': 1}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        rpe = self.client.get(
            f'/api/engins/rpe?societe_id={self.soc.id}&ym={self.ym}').json()
        self.assertEqual(rpe['mention'], 'DEFINITIF')

    def test_mois_valide_verrouille_saisies_et_reouverture_direction(self):
        self.assertEqual(self._enregistrer_reconciliation().status_code, 200)
        self.client.post(
            f'/api/engins/reconciliation/valider?societe_id={self.soc.id}',
            {'ym': self.ym, 'revision': 1}, format='json')
        # Toute saisie du mois est refusée : création, modification, suppression.
        self._fiche(self.ch2, '2026-10-02', '08:00', '12:00', statut_attendu=409)
        pid = self.fiche['id']
        r = self.client.patch(f'/api/engins/prestations/{pid}',
                              {'heure_fin': '17:00'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.delete(
            f'/api/engins/prestations/{pid}').status_code, 409)
        # La grille réconciliée elle-même est figée.
        self.assertEqual(self._enregistrer_reconciliation(revision=1).status_code,
                         409)
        # Le dispatcher ne peut pas rouvrir ; le DG (direction) le peut,
        # avec un motif obligatoire.
        self.client.force_authenticate(self.dispatcher)
        r = self.client.post(
            f'/api/engins/reconciliation/rouvrir?societe_id={self.soc.id}',
            {'ym': self.ym, 'motif': 'Correction demandée par GCK'},
            format='json')
        self.assertEqual(r.status_code, 403)
        dg = Utilisateur.objects.create(email='dg@test.local', nom='DG',
                                        password_hash='unused')
        role_dg, _ = Role.objects.get_or_create(code='DG',
                                                defaults={'libelle': 'DG'})
        _inserer_affectation(dg.id, self.soc.id, role_dg.id)
        self.client.force_authenticate(dg)
        r = self.client.post(
            f'/api/engins/reconciliation/rouvrir?societe_id={self.soc.id}',
            {'ym': self.ym, 'motif': 'court'}, format='json')
        self.assertEqual(r.status_code, 422)
        r = self.client.post(
            f'/api/engins/reconciliation/rouvrir?societe_id={self.soc.id}',
            {'ym': self.ym, 'motif': 'Correction demandée par GCK'},
            format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.client.force_authenticate(self.dfi)
        self._fiche(self.ch2, '2026-10-02', '08:00', '12:00')

    def test_harmonisation_proposee_approuvee_et_appliquee_au_rpe(self):
        self.assertEqual(self._enregistrer_reconciliation().status_code, 200)
        url = f'/api/engins/harmonisations?societe_id={self.soc.id}'
        # Plus que les heures retenues disponibles -> refus.
        r = self.client.post(url, {
            'ym': self.ym, 'engin_source_id': str(self.ch1.id),
            'engin_cible_id': str(self.ch2.id), 'poste': 'jour',
            'minutes': 600, 'motif': 'Transfert trop grand'}, format='json')
        self.assertEqual(r.status_code, 422, r.content)
        # Le dispatcher propose 1h00 de la chargeuse 01 vers la 02.
        self.client.force_authenticate(self.dispatcher)
        r = self.client.post(url, {
            'ym': self.ym, 'engin_source_id': str(self.ch1.id),
            'engin_cible_id': str(self.ch2.id), 'poste': 'jour',
            'minutes': 60, 'motif': 'Accord de séance GCK'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        hid = r.json()['id']
        # Le dispatcher ne décide pas ; la facturation est bloquée en attendant.
        self.assertEqual(self.client.post(
            f'/api/engins/harmonisations/{hid}/decider',
            {'decision': 'approuvee'}, format='json').status_code, 403)
        self.client.force_authenticate(self.dfi)
        self.client.post(
            f'/api/engins/reconciliation/valider?societe_id={self.soc.id}',
            {'ym': self.ym, 'revision': 1}, format='json')
        r = self.client.post(f'/api/engins/facturer?societe_id={self.soc.id}',
                             {'ym': self.ym, 'tiers_id': None}, format='json')
        self.assertEqual(r.status_code, 400)   # tiers invalide avant tout
        r = self.client.post(f'/api/engins/harmonisations/{hid}/decider',
                             {'decision': 'approuvee',
                              'commentaire': 'Vu en séance'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        rpe = self.client.get(
            f'/api/engins/rpe?societe_id={self.soc.id}&ym={self.ym}').json()
        l1 = next(r for r in rpe['rows'] if r['engin'] == 'Chargeuse 01')
        l2 = next(r for r in rpe['rows'] if r['engin'] == 'Chargeuse 02')
        self.assertEqual(l1['total_dec'], 7.5)   # 8h30 retenues - 1h00 cédée
        self.assertEqual(l2['total_dec'], 1.0)
        self.assertEqual(l1['harmonise_min'], -60)
        self.assertEqual(l2['harmonise_min'], 60)

    def test_facturation_exige_reconciliation_validee(self):
        from core.models import Tiers
        client_gck = Tiers.objects.create(societe_id=self.soc.id, type='client',
                                          code='GCK', nom='GCK / Production')
        r = self.client.post(f'/api/engins/facturer?societe_id={self.soc.id}',
                             {'ym': self.ym, 'tiers_id': str(client_gck.id)},
                             format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('réconcili', r.json()['detail'])
