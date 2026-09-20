from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from django.test import TestCase
from core.tests import test_rh as base
from uuid import uuid4
from core.config_views import _inserer_affectation
from core.models import (Role, Utilisateur, RHContrat, RHDocument, RHDette,
    Tiers, Caisse, SessionCaisse, MouvementCaisse, Ecriture, LigneEcriture, Avance)
from core import services


class RHFinancesTests(TestCase):
    call=base.RHTests.call
    def setUp(self):
        base.RHTests.setUp(self)
        for code in ('DRH','DG','ADMIN'):
            role,_=Role.objects.get_or_create(code=code,defaults={'libelle':code})
            u=Utilisateur.objects.create(email=code+'@rh.test',nom=code,password_hash='unused')
            _inserer_affectation(u.id,self.s.id,role.id)
            c=APIClient();c.force_authenticate(u);self.clients[code]=c;self.users[code]=u
        meta={'societe':self.s,'created_by':self.users['RH'].id,'updated_by':self.users['RH'].id}
        self.doc=RHDocument.objects.create(agent=self.a,nom='accord.pdf',nature='accord',mime='application/pdf',empreinte='a'*64,contenu=b'%PDF-1.4 accord',**meta)
        RHContrat.objects.create(agent=self.a,reference='C',type_contrat='CDI',debut=date(2020,1,1),salaire=500,base_salaire='net',devise='USD',**meta)
        self.t=Tiers.objects.create(societe_id=self.s.id,type='agent',nom=self.a.nom)
        self.a.tiers=self.t;self.a.save()
        self.caisse=Caisse.objects.create(societe_id=self.s.id,libelle='Caisse RH',compte_comptable='571')
        SessionCaisse.objects.create(caisse=self.caisse,ouvert_par=self.users['CAISSIER_CENTRAL'].id,fond_initial_usd=1000)

    def preparer(self,montant='100',status=201,**kw):
        req=self.call('demandes',{'agent_id':str(self.a.id),'nature':'avance_salaire','motif':'Demande signée','montant':montant,'devise':'USD'},status=201)
        p={'agent_id':str(self.a.id),'demande_id':req[0]['id'],'accord_id':str(self.doc.id),'motif':'Accord écrit et échéancier convenu',
            'echeancier':[{'mois':date.today().strftime('%Y-%m'),'montant':montant}],**kw}
        return self.call('dettes',p,role='RH',status=status)

    def approuver(self,d,role='DFI',status=200):
        return self.call(f"dettes/{d['id']}/decision",{'revision':d['revision'],'action':'valider','commentaire':'Accord et capacité vérifiés'},role=role,status=status)

    def test_pret_trois_personnes_et_paiement_unique(self):
        d=self.preparer('200');self.assertEqual(d['nature'],'pret_personnel')
        self.approuver(d,'DG',403)
        d=self.approuver(d);self.assertEqual(d['statut'],'attente_drh')
        d=self.approuver(d,'DRH');d=self.approuver(d,'DG')
        self.assertEqual(d['statut'],'approuve');self.assertFalse(Ecriture.objects.exists())
        p={'revision':d['revision'],'caisse_id':str(self.caisse.id),'reference':'Reçu signé 001'}
        r=self.call(f"dettes/{d['id']}/verser",p,role='CAISSIER_CENTRAL')
        self.assertTrue(r['numero']);self.assertEqual(Ecriture.objects.count(),1)
        self.assertEqual(MouvementCaisse.objects.get().date_mouvement,date.today())
        self.assertEqual(list(LigneEcriture.objects.values_list('montant_usd',flat=True)),[Decimal('200'),Decimal('200')])
        self.call(f"dettes/{d['id']}/verser",p,role='CAISSIER_CENTRAL',status=400)
        self.assertEqual(MouvementCaisse.objects.count(),1)

    def test_plafond_cumule_et_rejet_caisse_avant_validation(self):
        d=self.preparer('100');self.assertEqual(d['nature'],'avance_salaire')
        self.call(f"dettes/{d['id']}/verser",{'revision':1,'caisse_id':str(self.caisse.id),'reference':'R'},role='CAISSIER_CENTRAL',status=400)
        d2=self.preparer('60');self.assertEqual(d2['nature'],'pret_personnel')
        self.assertFalse(MouvementCaisse.objects.exists())

    def test_paiement_transactionnel_revision_et_echec_comptable(self):
        d=self.approuver(self.preparer())
        p={'revision':1,'caisse_id':str(self.caisse.id),'reference':'Reçu'}
        self.call(f"dettes/{d['id']}/verser",p,role='CAISSIER_CENTRAL',status=400)
        self.assertFalse(MouvementCaisse.objects.exists());self.assertFalse(Ecriture.objects.exists())
        p['revision']=d['revision']
        with patch('core.rh_finances.comptabilite.post_ecriture',side_effect=ValidationError('Exercice fermé')):
            self.call(f"dettes/{d['id']}/verser",p,role='CAISSIER_CENTRAL',status=400)
        self.assertFalse(MouvementCaisse.objects.exists());self.assertEqual(RHDette.objects.get().statut,'approuve')

    def test_accord_autre_agent_et_mensualites_invalides(self):
        self.doc.agent=self.a2;self.doc.save()
        # L'accord d'une autre personne ne suffit pas.
        self.preparer(status=400)
        self.assertFalse(RHDette.objects.exists())
        self.doc.agent=self.a;self.doc.save()
        self.preparer(status=400,echeancier=[{'mois':date.today().strftime('%Y-%m'),'montant':'99'}])
        self.assertFalse(RHDette.objects.exists())

    def test_recouvrement_delai_et_sans_nouveau_versement(self):
        av=Avance.objects.create(societe_id=self.s.id,ordre_depense_id=uuid4(),numero='AV-RH',beneficiaire_tiers_id=self.t.id,devise='USD',montant_avance=100,montant_avance_usd=100,date_octroi=services.maintenant()-timedelta(days=29))
        p={'agent_id':str(self.a.id),'avance_source_id':str(av.id),'accord_id':str(self.doc.id),'motif':'Accord après relance',
            'echeancier':[{'mois':date.today().strftime('%Y-%m'),'montant':'100'}]}
        self.call('dettes',p,status=400)
        av.date_octroi=services.maintenant()-timedelta(days=31);av.save()
        d=self.call('dettes',p,status=201);self.call('dettes',p,status=400)
        for role in ('DFI','DRH','ADMIN'): d=self.approuver(d,role)
        self.call(f"dettes/{d['id']}/verser",{'revision':d['revision'],'caisse_id':str(self.caisse.id),'reference':'R'},role='CAISSIER_CENTRAL',status=400)
        av.refresh_from_db();self.assertEqual(av.statut,'a_justifier');self.assertFalse(Ecriture.objects.exists())

    def test_paiement_et_decision_personnels_interdits(self):
        self.a.utilisateur=self.users['DFI'];self.a.save()
        d=self.preparer();self.approuver(d,'DFI',403)
