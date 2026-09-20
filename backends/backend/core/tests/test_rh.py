from datetime import date
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from core.models import (Societe, Role, Utilisateur, RHAgent, RHEquipe, RHPointage,
                         RHContrat, RHDocument, RHDemande, MouvementCaisse, Ecriture)
from core.config_views import _inserer_affectation
from core.rh_views import heures


class RHTests(TestCase):
    def setUp(self):
        self.s=Societe.objects.create(code='RH1',nom='RH Test')
        self.autre=Societe.objects.create(code='RH2',nom='Autre employeur')
        self.users={};self.clients={}
        for code in ('DFI','RH','RESP_EQUIPE','COMPTABLE','CAISSIER_CENTRAL'):
            role,_=Role.objects.get_or_create(code=code,defaults={'libelle':code})
            u=Utilisateur.objects.create(email=code+'@rh.test',nom=code,password_hash='unused')
            _inserer_affectation(u.id,self.s.id,role.id)
            c=APIClient();c.force_authenticate(u);self.users[code]=u;self.clients[code]=c
        self.e=RHEquipe.objects.create(societe=self.s,nom='Cuisine',responsable=self.users['RESP_EQUIPE'],created_by=self.users['DFI'].id,updated_by=self.users['DFI'].id)
        self.a=RHAgent.objects.create(societe=self.s,matricule='A01',nom='Agent Exemple',nom_normalise='agent exemple',date_engagement=date(2020,1,1),equipe=self.e,created_by=self.users['DFI'].id,updated_by=self.users['DFI'].id)
        self.a2=RHAgent.objects.create(societe=self.s,matricule='A02',nom='Autre Agent',nom_normalise='autre agent',date_engagement=date(2020,1,1),created_by=self.users['DFI'].id,updated_by=self.users['DFI'].id)

    def call(self,route,p=None,role='DFI',status=200,method=None,sid=None):
        c=self.clients[role];path='/api/rh/'+route+('&' if '?' in route else '?')+'societe_id='+str(sid or self.s.id)
        r=getattr(c,method or ('post' if p is not None else 'get'))(path,p,format='json') if p is not None else c.get(path)
        self.assertEqual(r.status_code,status,r.content)
        return r.json()

    def pointage(self,**kw):
        return {'agent_id':str(self.a.id),'jour':'2026-09-01','nature':'present','debut':'19:00','fin':'05:00','lendemain':True,'pause_debut':'23:00','pause_fin':'00:00',**kw}

    def test_nuit_retire_pause_et_chevauchement_interdit(self):
        p=self.call('pointages',self.pointage(),role='RESP_EQUIPE',status=201)
        self.assertEqual(p['minutes'],540);self.assertEqual(p['minutes_nuit'],540)
        self.call('pointages',self.pointage(jour='2026-09-02',debut='04:00',fin='08:00',lendemain=False,pause_debut='',pause_fin=''),status=400)
        self.assertEqual(RHPointage.objects.count(),1)

    def test_responsable_limite_a_equipe_sans_dossier_prive(self):
        r=self.call('agents',role='RESP_EQUIPE')
        self.assertEqual(len(r),1);self.assertNotIn('numero_cnss',r[0])
        self.call(f'agents/{self.a.id}/dossier',role='RESP_EQUIPE',status=403)
        self.call('pointages',self.pointage(agent_id=str(self.a2.id)),role='RESP_EQUIPE',status=404)
        self.call('agents',role='COMPTABLE',status=403)
        self.call('agents',sid=self.autre.id,status=403)

    def test_validation_et_reouverture_revision(self):
        p=self.call('pointages',self.pointage(),status=201)
        route=f"pointages/{p['id']}/decision"
        self.call(route,{'action':'valider','revision':1},role='RESP_EQUIPE',status=403)
        self.call(route,{'action':'valider','revision':1},role='RH')
        self.call('pointages',self.pointage(revision=2),status=400)
        self.call(route,{'action':'rouvrir','revision':2,'motif':'Heure de pause mal saisie'})
        self.call('pointages',self.pointage(revision=1),status=400)
        self.call('pointages',self.pointage(revision=3,fin='04:30'))
        self.assertEqual(RHPointage.objects.get().minutes,510)

    def test_creation_agent_doublons_et_homonyme_explique(self):
        p={'matricule':'N01','nom':'agent éxemple','date_engagement':'2020-01-01'}
        self.call('agents',p,status=400)
        p['motif_homonyme']='Deux personnes distinctes, pièces vérifiées.'
        self.call('agents',p,status=201)
        self.call('agents',p,status=400)
        self.assertEqual(RHAgent.objects.count(),3)

    def test_contrat_net_historise_et_chevauchement_refuse(self):
        p={'nature':'contrat','type_contrat':'CDI','reference':'CTR1','debut':'2020-01-01','salaire':'500.00','base_salaire':'net','devise':'USD'}
        d=self.call(f'agents/{self.a.id}/dossier',p,status=201)
        self.assertEqual(d['contrats'][0]['base_salaire'],'net')
        p['reference']='CTR2';self.call(f'agents/{self.a.id}/dossier',p,status=400)
        self.assertFalse(Ecriture.objects.exists());self.assertFalse(MouvementCaisse.objects.exists())

    def test_documents_prives_doublons_refuses(self):
        path=f'/api/rh/agents/{self.a.id}/documents?societe_id={self.s.id}'
        r=self.clients['RH'].post(path,{'nature':'contrat','fichier':SimpleUploadedFile('contrat.pdf',b'%PDF-1.4 test')},format='multipart')
        self.assertEqual(r.status_code,201,r.content);doc=r.json()['id']
        self.call(f'documents/{doc}',role='RESP_EQUIPE',status=403)
        r=self.clients['DFI'].get(f'/api/rh/documents/{doc}?societe_id={self.s.id}')
        self.assertEqual(r.content,b'%PDF-1.4 test');self.assertIn('no-store',r['Cache-Control'])
        r=self.clients['RH'].post(path,{'nature':'contrat','fichier':SimpleUploadedFile('copie.pdf',b'%PDF-1.4 test')},format='multipart')
        self.assertEqual(r.status_code,400);self.assertEqual(RHDocument.objects.count(),1)

    def test_organisation_responsable_et_horaires(self):
        self.call('organisation',{'nature':'horaire','nom':'Nuit','semaine':[{'jour':1,'debut':'22:00','fin':'06:00','lendemain':True}]},status=201)
        data=self.call('organisation')
        self.assertEqual(data['horaires'][0]['semaine'][0]['minutes_nuit'],420)
        self.assertTrue(data['utilisateurs'])
        self.call('organisation',{'nature':'equipe','nom':'Equipe fantôme','responsable_id':'bad'},status=400)

    def test_absence_ne_calcule_pas_de_retenue_et_demandes_sans_paiement(self):
        p=self.call('pointages',self.pointage(nature='absence'),status=201)
        self.assertEqual(p['minutes'],0);self.assertIsNone(p['debut'])
        self.call('demandes',{'agent_id':str(self.a.id),'nature':'avance_salaire','motif':'Demande signée','montant':'50','devise':'USD'},status=201)
        self.assertEqual(RHDemande.objects.get().statut,'soumis')
        self.assertFalse(MouvementCaisse.objects.exists());self.assertFalse(Ecriture.objects.exists())

    def test_pointages_dates_et_heures_invalides(self):
        self.call('pointages',self.pointage(jour='2099-01-01'),status=400)
        self.call('pointages',self.pointage(lendemain='true'),status=400)
        self.call('pointages',self.pointage(pause_fin='20:00'),status=400)
        self.call('pointages',self.pointage(agent_id='bad'),status=400)
