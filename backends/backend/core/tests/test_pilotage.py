from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from core import models as M
from core.config_views import _inserer_affectation
from core.pilotage import FileTravail, PREFIX, instant


class PilotageTests(TestCase):
    def setUp(self):
        self.s = M.Societe.objects.create(code='PIL', nom='Société pilote')
        self.other = M.Societe.objects.create(code='HORS', nom='Autre société')
        self.dfi = self.user('dfi', 'DFI')
        self.agent = self.user('agent', 'DEMANDEUR')
        self.dg = self.user('dg', 'DG')
        self.comptable = self.user('comptable', 'COMPTABLE')
        self.now = datetime.now(timezone.utc)
        self.old = (self.now-timedelta(hours=80)).replace(tzinfo=None)
        self.client = APIClient()
        self.client.force_authenticate(self.dfi)

    def user(self, name, role):
        u = M.Utilisateur.objects.create(nom=name, email=name+'@test.local', password_hash='unused')
        r, _ = M.Role.objects.get_or_create(code=role, defaults={'libelle': role})
        _inserer_affectation(u.id, self.s.id, r.id, None)
        return u

    def req(self, **kwargs):
        return M.Requisition.objects.create(numero='REQ-'+uuid.uuid4().hex[:10], societe_id=self.s.id,
            initiateur_id=self.agent.id, objet='Demande', created_at=self.old, montant_total_usd=100,
            **kwargs)

    def palier(self, roles=('DG',), type_document='requisition', etape='demande'):
        p = M.PalierValidation.objects.create(societe_id=self.s.id, type_document=type_document, etape=etape)
        for role in roles:
            M.PalierApprobateur.objects.create(palier=p, role=M.Role.objects.get(code=role))
        return p

    def get(self, **params):
        return self.client.get('/api/pilotage/taches', {'societe_id': str(self.s.id), 'portee': 'equipe', **params})

    def test_acces_refuse_hors_societe_et_supervision_reservee_dfi(self):
        self.assertEqual(self.get(societe_id=str(self.other.id)).status_code, 403)
        self.client.force_authenticate(self.agent)
        self.assertEqual(self.get().status_code, 403)
        self.assertEqual(self.get(portee='moi').status_code, 200)
        self.assertEqual(self.client.get('/api/pilotage/delais', {'societe_id':str(self.s.id)}).status_code, 403)
        self.client = APIClient()
        self.assertEqual(self.get().status_code, 401)

    def test_role_partage_sans_double_tache_et_exclusion_autovalidation(self):
        second = self.user('dg2', 'DG')
        self.palier()
        r = self.req(statut='soumise')
        rows = self.get().data['taches']
        self.assertEqual(len(rows), 1)
        self.assertEqual({u['id'] for u in rows[0]['responsables']}, {str(self.dg.id), str(second.id)})
        r.initiateur_id = self.dg.id
        r.save()
        self.client.force_authenticate(self.dg)
        self.assertEqual(self.get(portee='moi').data['taches'], [])
        self.client.force_authenticate(second)
        self.assertEqual(len(self.get(portee='moi').data['taches']), 1)

    def test_role_deja_valide_exclu_et_circuit_absent_visible(self):
        p = self.palier(('DG', 'DFI'))
        r = self.req(statut='soumise')
        M.Validation.objects.create(document_type='requisition', document_id=r.id, etape='demande',
            role_attendu_id=M.Role.objects.get(code='DG').id, decision='valide')
        rows = self.get().data['taches']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['roles'], ['DFI'])
        M.PalierApprobateur.objects.all().delete()
        self.assertEqual(self.get().data['taches'][0]['niveau'], 'a_attribuer')

    def test_precision_retournee_initiateur_puis_disparition_sans_ecriture(self):
        r = self.req(statut='en_attente_info')
        before = M.AuditLog.objects.count()
        self.client.force_authenticate(self.agent)
        response = self.get(portee='moi')
        self.assertEqual(response.data['taches'][0]['type'], 'req_precision')
        self.assertEqual(response.data['taches'][0]['affectation'], 'nominative')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(M.AuditLog.objects.count(), before)
        r.statut='transformee';r.save()
        self.assertEqual(self.get(portee='moi').data['compteurs']['total'], 0)

    def test_delais_audites_concurrence_validation_et_escalade(self):
        r = self.req(statut='demande_validee')
        url='/api/pilotage/delais?societe_id='+str(self.s.id)
        version=self.client.get(url).data['version']
        p={'version':version,'regles':{'ordre_emission':{'relance_h':24,'escalade_h':48}}}
        result=self.client.put(url,p,format='json')
        self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(M.AuditLog.objects.filter(action='DELAIS_PILOTAGE').count(),1)
        self.assertEqual(self.client.put(url,p,format='json').status_code,409)
        self.assertEqual(self.get().data['taches'][0]['niveau'],'escalade')
        p['version']=result.data['version'];p['regles']['ordre_emission']['escalade_h']=12
        self.assertEqual(self.client.put(url,p,format='json').status_code,400)
        self.assertEqual(M.Parametre.objects.filter(cle=PREFIX+'ordre_emission').count(),1)
        r.statut='transformee';r.save()
        self.assertEqual(self.get().data['compteurs']['total'],0)

    def test_echeance_avance_remonte_sans_modifier_le_statut(self):
        t=M.Tiers.objects.create(societe_id=self.s.id,code='A',nom='Agent',type='agent',utilisateur_id=self.agent.id)
        a=M.Avance.objects.create(numero='AV-1',societe_id=self.s.id,ordre_depense_id=uuid.uuid4(),
            beneficiaire_tiers_id=t.id,montant_avance=100,montant_avance_usd=100,
            date_octroi=self.old,echeance_justif=self.old+timedelta(hours=1))
        response=self.get()
        self.assertEqual(response.data['taches'][0]['niveau'],'escalade')
        a.refresh_from_db();self.assertEqual(a.statut,'a_justifier')
        self.assertEqual(M.BlocageBeneficiaire.objects.count(),0)

    def test_paiement_partiel_attribue_au_role_banque_et_paiement_solde_exclu(self):
        r=self.req(statut='transformee')
        o=M.OrdreDepense.objects.create(numero='ODP-1',requisition_id=r.id,societe_id=self.s.id,
            beneficiaire_tiers_id=uuid.uuid4(),montant_autorise=100,montant_autorise_usd=100,
            montant_paye_usd=25,statut='valide',mode_paiement='banque',created_at=self.old)
        row=self.get().data['taches'][0]
        self.assertEqual(row['type'],'ordre_paiement')
        self.assertIn(str(self.comptable.id),[u['id'] for u in row['responsables']])
        o.montant_paye_usd=100;o.save()
        self.assertEqual(self.get().data['compteurs']['total'],0)

    def test_regles_non_activees_et_resume_ne_divulgue_pas_les_dossiers(self):
        self.req(statut='demande_validee')
        self.assertEqual(self.get().data['taches'][0]['niveau'],'a_traiter')
        result=self.get(resume='1')
        self.assertNotIn('taches',result.data)
        self.assertNotIn('utilisateurs',result.data)
        self.assertEqual(result.data['compteurs']['total'],1)

    def test_date_etape_precede_date_creation_et_role_inactif_non_attribue(self):
        r=self.req(statut='en_attente_info')
        recent=self.now.replace(tzinfo=None)-timedelta(hours=1)
        M.AuditLog.objects.create(action='DEMANDE_PRECISIONS',table_cible='requisition',enregistrement_id=str(r.id),horodatage=recent)
        row=self.get().data['taches'][0]
        self.assertLess(row['age_heures'],2)
        self.agent.actif=False;self.agent.save()
        self.assertEqual(self.get().data['taches'][0]['niveau'],'a_attribuer')

    def test_pointages_groupes_et_paie_ne_retombe_pas_sur_son_controleur(self):
        rh=self.user('rh','RH')
        base={'societe_id':self.s.id,'created_by':rh.id,'updated_by':rh.id}
        a=M.RHAgent.objects.create(**base,matricule='A1',nom='Agent',nom_normalise='agent',date_engagement=self.now.date())
        b=M.RHAgent.objects.create(**base,matricule='A2',nom='Agent 2',nom_normalise='agent 2',date_engagement=self.now.date())
        for agent in [a,b]:
            M.RHPointage.objects.create(**base,agent=agent,jour=self.now.date(),nature='present')
        p=M.RHPaieMois.objects.create(**base,mois='2026-09',statut='controle',decisions=[{'action':'controler','utilisateur_id':str(self.dfi.id),'date':self.now.isoformat()}])
        rows=self.get().data['taches']
        pointages=[r for r in rows if r['type']=='pointage_validation']
        self.assertEqual(len(pointages),1)
        self.assertIn('2 pointage',pointages[0]['detail'])
        self.assertEqual(next(r for r in rows if r['type']=='paie_validation')['niveau'],'a_attribuer')
        p.decisions=[{'action':'controler','utilisateur_id':str(rh.id),'date':self.now.isoformat()}];p.save()
        self.assertEqual(next(r for r in self.get().data['taches'] if r['type']=='paie_validation')['responsables'][0]['id'],str(self.dfi.id))

    def test_paie_paiement_puis_cloture_sans_exposer_le_salaire(self):
        self.user('caisse','CAISSIER_CENTRAL')
        base={'societe_id':self.s.id,'created_by':self.dfi.id,'updated_by':self.dfi.id}
        a=M.RHAgent.objects.create(**base,matricule='A1',nom='Agent',nom_normalise='agent',date_engagement=self.now.date())
        c=M.RHContrat.objects.create(**base,agent=a,reference='C1',type_contrat='CDI',debut=self.now.date(),salaire=900,base_salaire='net',devise='USD')
        p=M.RHPaieMois.objects.create(**base,mois='2026-09',statut='valide',decisions=[{'action':'valider','utilisateur_id':str(self.dfi.id),'date':self.now.isoformat()}])
        b=M.RHBulletin.objects.create(**base,periode=p,agent=a,contrat=c,resultat={'net_a_payer':'900.00'},empreinte_sources='x')
        row=self.get().data['taches'][0]
        self.assertEqual(row['type'],'paie_paiement')
        self.assertNotIn('900',str(row))
        M.RHPaiement.objects.create(**base,bulletin=b,mode='banque',date=self.now.date(),reference='VIR1',montant=900,devise='USD',ecriture_id=uuid.uuid4())
        row=self.get().data['taches'][0]
        self.assertEqual(row['type'],'paie_cloture')
        self.assertEqual(row['base_date'],'Dernier paiement du mois')

    def test_dette_exclut_agent_concerne_et_validateurs_precedents(self):
        drh=self.user('drh','DRH')
        base={'societe_id':self.s.id,'created_by':self.dfi.id,'updated_by':self.dfi.id}
        a=M.RHAgent.objects.create(**base,matricule='A1',nom='Agent',nom_normalise='agent',date_engagement=self.now.date(),utilisateur=drh)
        doc=M.RHDocument.objects.create(**base,agent=a,nom='Accord',nature='accord',mime='application/pdf',empreinte='x',contenu=b'PDF')
        d=M.RHDette.objects.create(**base,agent=a,accord=doc,nature='pret',montant=900,devise='USD',salaire_reference=500,plafond_pct=30,
            statut='attente_drh',decisions=[{'utilisateur_id':str(self.dfi.id),'date':self.now.isoformat()}])
        self.assertEqual(self.get().data['taches'][0]['niveau'],'a_attribuer')
        d.statut='approuve';d.save()
        self.assertEqual(self.get().data['taches'][0]['type'],'rh_versement')
        d.nature='recouvrement';d.save()
        self.assertEqual(self.get().data['taches'],[])

    def test_controle_comptable_et_reception_restent_des_actions_distinctes(self):
        M.Ecriture.objects.create(societe_id=self.s.id,exercice_id=uuid.uuid4(),numero='OD-1',date_ecriture=self.now.date(),libelle='À contrôler',statut='en_attente',created_at=self.old)
        M.InventaireDepot.objects.create(societe_id=self.s.id,depot_id=uuid.uuid4(),numero='INV-1',date_inventaire=self.now.date(),statut='brouillon')
        M.Reception.objects.create(societe_id=self.s.id,commande_id=uuid.uuid4(),numero='REC-1',date_reception=self.now.date())
        rows=self.get().data['taches']
        self.assertEqual({r['type'] for r in rows},{'compta_validation','inventaire_validation','reception_facture'})
        self.assertTrue(all(str(self.comptable.id) in [u['id'] for u in r['responsables']] for r in rows))

    def test_hotel_date_prevue_et_flotte_expiree_sans_actions_automatiques(self):
        today=self.now.date()
        M.Sejour.objects.create(societe_id=self.s.id,numero='SEJ-1',chambre_id=uuid.uuid4(),client_nom='Client',
            date_arrivee=today-timedelta(days=2),date_depart_prevue=today-timedelta(days=1),tarif_nuit_usd=100,statut='arrivee')
        M.Sejour.objects.create(societe_id=self.s.id,numero='SEJ-2',chambre_id=uuid.uuid4(),client_nom='Client futur',
            date_arrivee=today+timedelta(days=4),date_depart_prevue=today+timedelta(days=5),tarif_nuit_usd=100,statut='reservee')
        M.DocumentFlotte.objects.create(societe_id=self.s.id,libelle='Assurance',date_expiration=today-timedelta(days=1))
        rows=self.get().data['taches']
        self.assertEqual({r['type'] for r in rows},{'hotel_depart','flotte_document'})
        self.assertTrue(all(r['niveau']=='escalade' for r in rows))
        self.assertEqual(M.Sejour.objects.get(numero='SEJ-1').statut,'arrivee')

    def test_transport_tva_et_facturation_quantites_reellement_facturables(self):
        today=self.now.date()
        M.Course.objects.create(societe_id=self.s.id,numero='FC-1',date_course=today,client_tiers_id=uuid.uuid4(),origine='A',destination='B',marchandise='Fret',statut='livree')
        M.PreparationTVA.objects.create(societe_id=self.s.id,mois=(today.replace(day=1)-timedelta(days=1)).strftime('%Y-%m'),donnees={})
        art=M.Article.objects.create(societe_id=self.s.id,code='S1',designation='Stock',gere_stock=True)
        d=M.Devis.objects.create(societe_id=self.s.id,numero='DEV-1',tiers_id=uuid.uuid4(),date_devis=today,statut='confirme')
        l=M.LigneDevis.objects.create(devis_id=d.id,article_id=art.id,designation='Article',qte=5,qte_livree=0,prix_unitaire=10)
        self.assertEqual({r['type'] for r in self.get().data['taches']},{'course_facture','tva_suivi'})
        l.qte_livree=2;l.save()
        self.assertIn('vente_facture',{r['type'] for r in self.get().data['taches']})
        l.qte_facturee=2;l.save()
        self.assertNotIn('vente_facture',{r['type'] for r in self.get().data['taches']})

    def test_validation_partielle_ne_reinitialise_pas_les_delais(self):
        self.palier(('DFI','DG'))
        r=self.req(statut='soumise')
        M.AuditLog.objects.create(action='VALIDATE',table_cible='requisition',enregistrement_id=str(r.id),
            nouvelle_valeur={'statut':'soumise','decision':'valide'},horodatage=self.now.replace(tzinfo=None))
        self.assertTrue(all(r['age_heures']>=79 for r in self.get().data['taches']))

    def test_nombre_de_requetes_ne_croit_pas_par_requisition(self):
        self.palier()
        self.req(statut='soumise')
        with CaptureQueriesContext(connection) as one:
            self.get()
        M.Requisition.objects.bulk_create([M.Requisition(numero='REQ-BULK-'+str(i),societe_id=self.s.id,initiateur_id=self.agent.id,objet='Demande',created_at=self.old,montant_total_usd=100,statut='soumise') for i in range(50)])
        with CaptureQueriesContext(connection) as many:
            result=self.get()
        self.assertEqual(result.data['compteurs']['total'],51)
        self.assertLessEqual(len(many),len(one)+2)
