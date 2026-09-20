from datetime import date, datetime
from decimal import Decimal as D
from unittest.mock import patch
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from core.tests import test_rh as base
from core.models import (RHContrat,RHPaieMois,RHBulletin,RHPaiement,RHPointage,RHDette,RHDocument,RHRetenue,RHSimulation,Role,
    Tiers,Caisse,SessionCaisse,MouvementCaisse,CompteBancaire,Ecriture,LigneEcriture)
from core.rh_calculs import simulation, arrondi
from core import comptabilite


class PaieMensuelleTests(TestCase):
    call=base.RHTests.call

    def setUp(self):
        base.RHTests.setUp(self)
        self.meta={'societe':self.s,'created_by':self.users['RH'].id,'updated_by':self.users['RH'].id}
        self.t=Tiers.objects.create(societe_id=self.s.id,type='agent',nom=self.a.nom)
        self.a.tiers=self.t;self.a.save()
        p,r=simulation({'date_reference':'2026-09-01','devise':'USD','taux_cdf':'2300','source_taux':'Référence test',
            'brut_base':'600','logement':'150','transport':'50','primes':'25','net_vise':'700','trajet_cdf':'500',
            'jours_transport':26,'charges_famille':0,'justification_indemnites':'Indemnités réelles et pièces conservées'})
        self.c=RHContrat.objects.create(agent=self.a,reference='CTR-PAIE',debut=date(2020,1,1),type_contrat='CDI',
            salaire=D(r['net']),base_salaire='net',devise='USD',remuneration={'parametres':p,'resultat':r},**self.meta)
        self.caisse=Caisse.objects.create(societe_id=self.s.id,libelle='Caisse paie',compte_comptable='571')
        self.session=SessionCaisse.objects.create(caisse=self.caisse,ouvert_par=self.users['CAISSIER_CENTRAL'].id,fond_initial_usd=10000)
        self.banque=CompteBancaire.objects.create(societe_id=self.s.id,banque='Banque test',numero_compte='123',compte_comptable='521',devise='USD')

    def ouvrir(self,**kw):
        return self.call('paies',{'mois':date.today().strftime('%Y-%m'),'taux_cdf':'2400','source_taux':'Taux mensuel validé',
            'effectif':40,'secteur':'prive','reference_reglementaire':'Textes 2026 contrôlés',**kw},role='RH',status=201)

    def preparer(self,o,**kw):
        p={'revision':o['revision'],'contrat_id':str(self.c.id),'jours_payes':'26','tension':100,
            'controle_temps':'Présence, congés et pièces rapprochés par les RH','regime_nuit':'aucun','heures_nuit':'0',
            'jours_transport':26,'trajet_cdf':'500','charges_famille':0,'reference_famille':'',**kw}
        return self.call(f"paies/{o['id']}/preparer",p,role='RH',status=200 if o['nombre'] else 201)

    def decider(self,o,action,role='RH',status=200,**kw):
        return self.call(f"paies/{o['id']}/decision",{'revision':o['revision'],'action':action,
            'commentaire':'Pièces, calculs, variables et effectifs rapprochés','reglementation_verifiee':True,**kw},role=role,status=status)

    def valider(self,o):
        return self.decider(self.decider(o,'controler'),'valider',role='DFI')

    def paiement(self,b,**kw):
        return {'revision':b['revision'],'mode':'caisse','date':date.today().isoformat(),'caisse_id':str(self.caisse.id),'reference':'RECU-PAIE-001',**kw}

    def test_cycle_net_controles_compta_paiement_cloture(self):
        o=self.preparer(self.ouvrir());b=o['bulletins'][0]
        self.assertEqual(D(b['resultat']['net']),self.c.salaire)
        self.assertNotEqual(D(b['resultat']['ajustement_brut_net']),0)
        self.assertFalse(Ecriture.objects.exists())
        self.call(f"bulletins/{b['id']}/payer",self.paiement(b),role='CAISSIER_CENTRAL',status=400)
        o=self.valider(o);self.assertEqual(Ecriture.objects.count(),1)
        self.decider(o,'cloturer',role='DFI',status=400)
        self.call(f"paies/{o['id']}/preparer",{'revision':o['revision']},role='RH',status=400)
        b=o['bulletins'][0]
        self.call(f"bulletins/{b['id']}/payer",self.paiement(b),role='CAISSIER_CENTRAL')
        self.call(f"bulletins/{b['id']}/payer",self.paiement(b),role='CAISSIER_CENTRAL',status=400)
        o=self.call('paies/'+o['id']);o=self.decider(o,'cloturer',role='DFI')
        self.assertEqual(o['statut'],'cloture');self.assertEqual(RHPaiement.objects.count(),1)
        self.assertEqual(MouvementCaisse.objects.count(),1)
        self.assertEqual(sum(LigneEcriture.objects.filter(compte_numero='422',sens='C').values_list('montant_usd',flat=True)),sum(LigneEcriture.objects.filter(compte_numero='422',sens='D').values_list('montant_usd',flat=True)))
        for e in Ecriture.objects.all():
            self.assertEqual(sum(e.ligneecriture_set.filter(sens='D').values_list('montant_usd',flat=True)),sum(e.ligneecriture_set.filter(sens='C').values_list('montant_usd',flat=True)))

    def test_roles_cloisonnement_revision_et_exclusions(self):
        o=self.ouvrir()
        self.call('paies',role='RESP_EQUIPE',status=403)
        self.call('paies/'+o['id'],sid=self.autre.id,status=403)
        self.call('paies/'+o['id'],role='COMPTABLE',status=403)
        o=self.preparer(o)
        self.call(f"paies/{o['id']}/preparer",{'revision':1},role='RH',status=400)
        self.decider(o,'controler',role='DFI',status=403)
        RHContrat.objects.create(agent=self.a2,reference='Autre',debut=date(2020,1,1),type_contrat='CDI',salaire=500,base_salaire='net',devise='USD',**self.meta)
        self.decider(o,'controler',status=400)
        o=self.decider(o,'controler',exclusions=[{'agent_id':str(self.a2.id),'motif':'Congé sans solde documenté, mois entier'}])
        self.decider(o,'valider',role='RH',status=403)
        self.decider(o,'valider',role='DFI',status=400,reglementation_verifiee=False)
        self.decider(o,'valider',role='DFI')

    def test_pointages_modifies_et_controle_non_valide(self):
        o=self.preparer(self.ouvrir())
        pt=RHPointage.objects.create(agent=self.a,jour=date.today(),nature='present',minutes=480,minutes_nuit=0,**self.meta)
        self.decider(o,'controler',status=400)
        o=self.preparer(o);self.decider(o,'controler',status=400)
        pt.statut='valide';pt.revision+=1;pt.save()
        o=self.preparer(o);o=self.decider(o,'controler')
        pt.minutes=420;pt.revision+=1;pt.save()
        self.decider(o,'valider',role='DFI',status=400)
        self.assertFalse(Ecriture.objects.exists())

    def test_paiement_insuffisant_et_rollback_comptabilite(self):
        o=self.valider(self.preparer(self.ouvrir()));b=o['bulletins'][0]
        self.session.fond_initial_usd=0;self.session.save()
        self.call(f"bulletins/{b['id']}/payer",self.paiement(b),role='CAISSIER_CENTRAL',status=400)
        self.session.fond_initial_usd=10000;self.session.save()
        with patch('core.rh_mensuel_views.comptabilite.post_ecriture',side_effect=ValidationError('Exercice fermé')):
            self.call(f"bulletins/{b['id']}/payer",self.paiement(b),role='CAISSIER_CENTRAL',status=400)
        self.assertFalse(MouvementCaisse.objects.exists());self.assertFalse(RHPaiement.objects.exists())
        self.assertEqual(Ecriture.objects.count(),1)

    def test_proration_variables_nuit_et_paiement_bancaire(self):
        o=self.preparer(self.ouvrir(),jours_payes='13',primes_variables='75',reference_variables='PV prime',heures_nuit='12',regime_nuit='alternant_hotel',reference_nuit='Hôtel, alternance qualifiée')
        r=o['bulletins'][0]['resultat']
        self.assertEqual(D(r['net_proratise']),arrondi(self.c.salaire/2))
        self.assertGreater(D(r['majoration_nuit']),0);self.assertGreater(D(r['net']),D(r['net_proratise']))
        o=self.valider(o);b=o['bulletins'][0]
        p=self.paiement(b,mode='banque',compte_bancaire_id=str(self.banque.id),virement_confirme=False)
        self.call(f"bulletins/{b['id']}/payer",p,role='COMPTABLE',status=400)
        p['virement_confirme']=True;self.call(f"bulletins/{b['id']}/payer",p,role='COMPTABLE')
        self.assertFalse(MouvementCaisse.objects.exists());self.assertEqual(RHPaiement.objects.get().mode,'banque')
        detail=self.call('paies/'+o['id'],role='COMPTABLE')
        self.assertNotIn('resultat',detail['bulletins'][0]);self.assertNotIn('parametres',detail)

    def dette(self,montant='100'):
        doc=RHDocument.objects.create(agent=self.a,nom='Accord',nature='accord',mime='application/pdf',empreinte='a'*64,contenu=b'%PDF',**self.meta)
        d=RHDette.objects.create(agent=self.a,accord=doc,nature='avance_salaire',montant=montant,devise='USD',salaire_reference=self.c.salaire,
            plafond_pct=30,echeancier=[{'mois':date.today().strftime('%Y-%m'),'montant':montant}],motif='Accord signé',statut='verse',verse_at=datetime.now(),**self.meta)
        e=comptabilite.post_ecriture(self.s.id,'CA','Caisse','caisse',date.today(),'Versement test',[
            {'sens':'D','compte':'421','montant_usd':D(montant),'tiers_id':str(self.t.id)},
            {'sens':'C','compte':'571','montant_usd':D(montant)}],'rh_versement','rh_dette',d.id,'TEST',self.users['CAISSIER_CENTRAL'].id)
        d.ecriture_id=e.id;d.save();return d

    def test_retenue_apure_dette_selon_echeance_et_quotite(self):
        d=self.dette();o=self.preparer(self.ouvrir(),retenues=[{'dette_id':str(d.id),'montant':'100'}])
        r=o['bulletins'][0]['resultat'];self.assertEqual(D(r['net_a_payer']),D(r['net'])-100)
        o=self.valider(o)
        self.assertEqual(RHRetenue.objects.get().montant_usd,100)
        self.assertEqual(sum(LigneEcriture.objects.filter(compte_numero='421',sens='C').values_list('montant_usd',flat=True)),100)

    def test_retenue_refuse_impaye_depassement_et_recouvrement(self):
        d=self.dette('500');o=self.ouvrir()
        p={'revision':o['revision'],'contrat_id':str(self.c.id),'jours_payes':'26','tension':100,'controle_temps':'Vérifié',
           'regime_nuit':'aucun','jours_transport':26,'trajet_cdf':'500','charges_famille':0,'retenues':[{'dette_id':str(d.id),'montant':'500'}]}
        self.call(f"paies/{o['id']}/preparer",p,role='RH',status=400)
        p['retenues'][0]['montant']='50';d.statut='approuve';d.save()
        self.call(f"paies/{o['id']}/preparer",p,role='RH',status=400)
        d.nature='recouvrement';d.save()
        self.call(f"paies/{o['id']}/preparer",p,role='RH',status=400)
        self.assertFalse(RHBulletin.objects.exists())

    def test_banque_cdf_apurement_422_au_cours_historique(self):
        p,r=simulation({**self.c.remuneration['parametres'],'devise':'CDF','brut_base':'1600000','logement':'300000','transport':'100000','primes':'50000'})
        self.c.devise='CDF';self.c.salaire=D(r['net']);self.c.remuneration={'parametres':p,'resultat':r};self.c.save()
        self.banque.devise='CDF';self.banque.save()
        o=self.valider(self.preparer(self.ouvrir()));b=o['bulletins'][0]
        p=self.paiement(b,mode='banque',compte_bancaire_id=str(self.banque.id),virement_confirme=True)
        with patch('core.rh_mensuel_views.services.get_taux_jour',return_value=None):
            self.call(f"bulletins/{b['id']}/payer",p,role='COMPTABLE',status=400)
        with patch('core.rh_mensuel_views.services.get_taux_jour',return_value=D(2300)):
            self.call(f"bulletins/{b['id']}/payer",p,role='COMPTABLE')
        self.assertTrue(LigneEcriture.objects.filter(compte_numero='676').exists())
        lignes=LigneEcriture.objects.filter(compte_numero='422')
        self.assertEqual(sum(lignes.filter(sens='D').values_list('montant_usd',flat=True)),sum(lignes.filter(sens='C').values_list('montant_usd',flat=True)))

    def test_controle_et_validation_imposent_personnes_distinctes(self):
        from core.config_views import _inserer_affectation
        _inserer_affectation(self.users['RH'].id,self.s.id,Role.objects.get(code='DFI').id)
        o=self.decider(self.preparer(self.ouvrir()),'controler')
        self.decider(o,'valider',role='RH',status=403)
        self.assertFalse(Ecriture.objects.exists())

    def test_composition_contrat_existant_sans_modifier_net(self):
        sim=RHSimulation.objects.create(nom='Composition conservée',parametres=self.c.remuneration['parametres'],resultat=self.c.remuneration['resultat'],**self.meta)
        route=f'contrats/{self.c.id}/composition';p={'revision':self.c.revision,'simulation_id':str(sim.id)}
        self.call(route,p,role='RH',status=400)
        self.c.remuneration={};self.c.save()
        self.call(route,p,role='RH');self.c.refresh_from_db()
        self.assertEqual(self.c.salaire,D(sim.resultat['net']))
        self.assertEqual(self.c.remuneration['simulation_id'],str(sim.id))
