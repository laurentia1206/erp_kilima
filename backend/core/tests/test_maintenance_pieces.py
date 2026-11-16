"""Maintenance : pièces de rechange d'une intervention — réquisition d'achat
liée et bon de consommation de stock (sortie + écriture + coût)."""
from django.test import TestCase
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role
from apps.engins.models import Engin
from apps.maintenance.models import BonConsommationStock, InterventionCamion
from apps.stocks.models import Article
from apps.stocks import services as stock_lib
from apps.comptabilite.models import Ecriture, LigneEcriture


class MaintenancePiecesTests(TestCase):
    def setUp(self):
        self.soc = Societe.objects.create(code='QA', nom='Société test')
        self.meca = Utilisateur.objects.create(email='meca@test.local',
                                               nom='Mécanicien',
                                               password_hash='unused')
        role, _ = Role.objects.get_or_create(code='MAINTENANCIER',
                                             defaults={'libelle': 'Maintenance'})
        _inserer_affectation(self.meca.id, self.soc.id, role.id)
        self.client = APIClient()
        self.client.force_authenticate(self.meca)
        self.engin = Engin.objects.create(societe_id=self.soc.id, nom='Chargeuse 01')
        r = self.client.post(f'/api/transport/interventions?societe_id={self.soc.id}',
                             {'engin_id': str(self.engin.id), 'type': 'reparation',
                              'description': 'Fuite hydraulique',
                              'priorite': 'haute', 'technicien': 'KAMBALE'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.intervention = r.json()
        self.filtre = Article.objects.create(
            societe_id=self.soc.id, code='FLT-01', designation='Filtre hydraulique',
            nature='consommable', gere_stock=True, unite='pièce',
            compte_stock='31')
        depot = stock_lib.depot_central(self.soc.id)
        stock_lib.entree(self.filtre, depot, 4, 200.0, 'achat', 'TEST')

    def test_fiche_atelier_et_checklist(self):
        iid = self.intervention['id']
        r = self.client.patch(f'/api/transport/interventions/{iid}',
                              {'checklist': [{'t': 'Vidanger le circuit', 'ok': True},
                                             {'t': 'Remplacer le filtre', 'ok': False}],
                               'priorite': 'urgente', 'compteur': 1250.5},
                              format='json')
        self.assertEqual(r.status_code, 200, r.content)
        corps = r.json()
        self.assertEqual(corps['priorite'], 'urgente')
        self.assertEqual(len(corps['checklist']), 2)
        self.assertEqual(corps['compteur'], 1250.5)
        self.assertEqual(self.client.patch(
            f'/api/transport/interventions/{iid}',
            {'priorite': 'critique'}, format='json').status_code, 422)

    def test_requisition_de_pieces_liee(self):
        iid = self.intervention['id']
        url = f'/api/maintenance/interventions/{iid}/requisition'
        r = self.client.post(url, {'lignes': [
            {'description': 'Flexible hydraulique 3/4', 'quantite': 2,
             'prix_unitaire': 85},
            {'description': 'Huile hydraulique 20L', 'quantite': 1,
             'prix_unitaire': 120}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['requisition']['montant_usd'], 290.0)
        i = InterventionCamion.objects.get(id=iid)
        self.assertIsNotNone(i.requisition_id)
        # Plusieurs demandes d'achat possibles pour la même intervention.
        r = self.client.post(url, {'lignes': [
            {'description': 'Joint torique', 'quantite': 4, 'prix_unitaire': 5}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.get(
            f'/api/transport/interventions?societe_id={self.soc.id}')
        self.assertEqual(r.status_code, 200)
        fiche = next(x for x in r.json() if x['id'] == iid)
        self.assertEqual(len(fiche['requisitions']), 2)
        self.assertEqual(sorted(q['montant_usd'] for q in fiche['requisitions']),
                         [20.0, 290.0])

    def test_bon_de_consommation_stock(self):
        iid = self.intervention['id']
        url = f'/api/maintenance/interventions/{iid}/consommer'
        # Plus que le stock disponible -> refus explicite.
        r = self.client.post(url, {'lignes': [
            {'article_id': str(self.filtre.id), 'qte': 9}]}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('Stock insuffisant', r.json()['detail'])
        # Sortie de 2 filtres (CUMP 50 USD) -> bon de 100 USD.
        r = self.client.post(url, {'lignes': [
            {'article_id': str(self.filtre.id), 'qte': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        bon = r.json()['bon']
        self.assertEqual(bon['total_usd'], 100.0)
        depot = stock_lib.depot_central(self.soc.id)
        self.assertEqual(stock_lib.qte_disponible(depot.id, self.filtre.id), 2)
        # Écriture D 624 (entretien) / C 31 (stock).
        ecr = Ecriture.objects.get(source_type='bon_consommation')
        lignes = {(l.sens, l.compte_numero): float(l.montant_usd)
                  for l in LigneEcriture.objects.filter(ecriture_id=ecr.id)}
        self.assertEqual(lignes[('D', '624')], 100.0)
        self.assertEqual(lignes[('C', '31')], 100.0)
        # Le coût des pièces alimente l'intervention puis le coût réel.
        i = InterventionCamion.objects.get(id=iid)
        self.assertEqual(float(i.cout_pieces), 100.0)
        r = self.client.post(f'/api/transport/interventions/{iid}/terminer',
                             {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['cout_reel'], 100.0)
        # Journal des bons pour le gestionnaire de stock.
        r = self.client.get(
            f'/api/maintenance/bons-consommation?societe_id={self.soc.id}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(BonConsommationStock.objects.count(), 1)
