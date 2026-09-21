import uuid
from unittest.mock import patch
from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.db import transaction
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core import stock_lib
from core.models import (Societe, Utilisateur, Role, Article, Depot, InventaireDepot,
    LigneInventaireDepot, Ecriture, LigneEcriture, MouvementStock, Facture, LigneFacture,
    Tiers, PreparationTVA, Parametre)


class CloturesTests(TestCase):
    def setUp(self):
        self.soc=Societe.objects.create(code='CLOT',nom='Société de test')
        self.autre=Societe.objects.create(code='AUT',nom='Autre société')
        self.clients={}
        for code in ('DFI','COMPTABLE','CAISSIER_CENTRAL'):
            role,_=Role.objects.get_or_create(code=code,defaults={'libelle':code})
            user=Utilisateur.objects.create(email=code+'@test.local',nom=code,password_hash='unused')
            _inserer_affectation(user.id,self.soc.id,role.id)
            c=APIClient();c.force_authenticate(user);self.clients[code]=c
        self.depot=Depot.objects.create(societe_id=self.soc.id,code='CUISINE',libelle='Cuisine')
        self.article=Article.objects.create(societe_id=self.soc.id,code='FAR',designation='Farine',nature='matiere_premiere',compte_stock='32')
        stock_lib.entree(self.article,self.depot,10,100,'achat','TEST')

    def post(self,role,path,body,status=200):
        with transaction.atomic(): r=self.clients[role].post('/api/'+path,body,format='json')
        self.assertEqual(r.status_code,status,r.content)
        return r.json()

    def preparer(self,reel=8):
        return self.post('CAISSIER_CENTRAL',f'stock/inventaires?societe_id={self.soc.id}',
            {'depot_id':str(self.depot.id),'lignes':[{'article_id':str(self.article.id),'qte_reelle':reel,'qte_theorique':10}]},201)

    def test_comptage_ne_modifie_rien_puis_validation_unique_et_equilibree(self):
        inv=self.preparer()
        self.assertEqual(inv['statut'],'brouillon');self.assertFalse(Ecriture.objects.exists())
        self.assertEqual(stock_lib.qte_disponible(self.depot.id,self.article.id),10)
        path=f"stock/inventaires/{inv['id']}/decision"
        self.post('CAISSIER_CENTRAL',path,{'action':'valider'},403)
        valide=self.post('COMPTABLE',path,{'action':'valider'})
        self.assertEqual(valide['statut'],'valide');self.assertEqual(valide['ecart_valeur'],-20)
        self.assertEqual(stock_lib.qte_disponible(self.depot.id,self.article.id),8)
        self.assertEqual(sum(l.montant_usd*(1 if l.sens=='D' else -1) for l in LigneEcriture.objects.all()),0)
        self.assertTrue(LigneEcriture.objects.filter(compte_numero='658',sens='D',montant_usd=20).exists())
        self.post('DFI',path,{'action':'valider'},409)
        self.assertEqual(Ecriture.objects.count(),1)

    def test_stock_change_apres_comptage_refuse_toute_validation(self):
        inv=self.preparer();stock_lib.sortie(self.article,self.depot,1,'vente','APRES-COMPTAGE')
        self.post('DFI',f"stock/inventaires/{inv['id']}/decision",{'action':'valider'},409)
        self.assertEqual(stock_lib.qte_disponible(self.depot.id,self.article.id),9)
        self.assertFalse(Ecriture.objects.exists())
        self.assertEqual(InventaireDepot.objects.get().statut,'brouillon')

    def test_excedent_valorise_sans_imputer_une_charge(self):
        inv=self.preparer(12)
        self.post('DFI',f"stock/inventaires/{inv['id']}/decision",{'action':'valider'})
        self.assertEqual(stock_lib.qte_disponible(self.depot.id,self.article.id),12)
        self.assertTrue(LigneEcriture.objects.filter(compte_numero='758',sens='C',montant_usd=20).exists())

    def test_echec_comptable_annule_tout_ajustement(self):
        inv=self.preparer()
        with patch('core.inventaires_views.comptabilite.post_ecriture',side_effect=RuntimeError('Panne simulée')):
            with self.assertRaises(RuntimeError):
                self.clients['DFI'].post(f"/api/stock/inventaires/{inv['id']}/decision",{'action':'valider'},format='json')
        self.assertEqual(stock_lib.qte_disponible(self.depot.id,self.article.id),10)
        self.assertEqual(InventaireDepot.objects.get().statut,'brouillon')
        self.assertEqual(MouvementStock.objects.count(),1)

    def test_annulation_brouillon_ne_touche_pas_stock(self):
        inv=self.preparer()
        self.post('CAISSIER_CENTRAL',f"stock/inventaires/{inv['id']}/decision",{'action':'annuler'})
        self.assertEqual(InventaireDepot.objects.get().statut,'annule')
        self.assertEqual(MouvementStock.objects.count(),1)

    def test_cuisine_ecarts_uniquement_apres_validation(self):
        Parametre.objects.create(societe_id=self.soc.id,cle='cuisine.depot_id',valeur=str(self.depot.id))
        inv=self.preparer()
        url=f'/api/cuisine/rapport?societe_id={self.soc.id}'
        self.assertEqual(self.clients['DFI'].get(url).json()['manquants_inventaire'],0)
        self.post('DFI',f"stock/inventaires/{inv['id']}/decision",{'action':'valider'})
        r=self.clients['DFI'].get(url).json()
        self.assertEqual(r['manquants_inventaire'],20);self.assertEqual(r['inventaires_valides'],1)

    def test_comptage_refuse_doublons_non_fini_et_autre_societe(self):
        path=f'stock/inventaires?societe_id={self.soc.id}'
        ligne={'article_id':str(self.article.id),'qte_reelle':8}
        self.post('DFI',path,{'depot_id':str(self.depot.id),'lignes':[ligne,ligne]},400)
        self.post('DFI',path,{'depot_id':str(self.depot.id),'lignes':[{**ligne,'qte_reelle':'NaN'}]},400)
        autre=Article.objects.create(societe_id=self.autre.id,code='X',designation='Autre')
        self.post('DFI',path,{'depot_id':str(self.depot.id),'lignes':[{**ligne,'article_id':str(autre.id)}]},400)
        self.assertFalse(InventaireDepot.objects.exists())

    def ligne_tva(self,sens,montant,compte,statut='valide',jour=None,soc=None):
        sid=(soc or self.soc).id
        e=Ecriture.objects.create(societe_id=sid,exercice_id=uuid.uuid4(),numero='E-'+uuid.uuid4().hex[:12],
            date_ecriture=jour or date.today(),libelle='Test TVA',statut=statut)
        LigneEcriture.objects.create(societe_id=sid,ecriture=e,sens=sens,montant_usd=montant,compte_numero=compte)

    def test_tva_mois_societe_avoirs_et_pieces_non_validees(self):
        self.ligne_tva('C',160,'4431');self.ligne_tva('D',16,'4431');self.ligne_tva('D',40,'4452')
        self.ligne_tva('C',999,'4431',statut='brouillon')
        self.ligne_tva('C',123,'4431',jour=date(2020,1,1));self.ligne_tva('C',888,'4431',soc=self.autre)
        r=self.clients['DFI'].get(f'/api/comptabilite/tva-mensuelle?societe_id={self.soc.id}').json()
        self.assertEqual(Decimal(r['totaux']['valide']['collectee']),144)
        self.assertEqual(Decimal(r['solde_mouvements_usd']),104)
        self.assertEqual(Decimal(r['totaux']['en_attente']['collectee']),999)
        self.assertEqual(len(r['lignes']),4)

    def test_tva_ventile_les_taux_historiques_sans_recalcul_a_16(self):
        tiers=Tiers.objects.create(societe_id=self.soc.id,code='C',nom='Client',type='client')
        for typ,signe in [('vente',1),('avoir_vente',-1)]:
            f=Facture.objects.create(societe_id=self.soc.id,numero=typ,type=typ,tiers_id=tiers.id,date_facture=date.today())
            for taux,ht in [(16,100),(8,200),(0,300)]:
                LigneFacture.objects.create(facture_id=f.id,designation='Opération',taux_tva=taux,montant_ht=ht if signe==1 else ht/10,montant_tva=ht*taux/100 if signe==1 else ht*taux/1000)
        r=self.clients['DFI'].get(f'/api/comptabilite/tva-mensuelle?societe_id={self.soc.id}').json()
        values={Decimal(x['taux']):x for x in r['ventilation_taux']}
        self.assertEqual(set(values),{Decimal(0),Decimal(8),Decimal(16)})
        self.assertEqual(Decimal(values[8]['tva_usd']),Decimal('14.4'))
        self.assertEqual(Decimal(values[0]['ht_usd']),270)

    def test_dossier_tva_revision_et_snapshot_sans_ecriture(self):
        path=f'comptabilite/tva-mensuelle/dossier?societe_id={self.soc.id}&mois=2026-08'
        r=self.post('COMPTABLE',path,{'revision':0,'notes':'Exonérations à vérifier'})
        self.assertEqual(r['revision'],1)
        self.post('DFI',path,{'revision':0,'notes':'Ne pas écraser'},409)
        self.assertEqual(PreparationTVA.objects.get().donnees['notes'],'Exonérations à vérifier')
        self.assertFalse(Ecriture.objects.exists())
        self.post('CAISSIER_CENTRAL',path,{'revision':1},403)
        self.post('DFI',path,{'revision':1,'montant_declare_cdf':'NaN'},400)

    def test_tva_refuse_mois_invalide_et_societe_non_autorisee(self):
        for query,status in [(f'societe_id={self.soc.id}&mois=2026-13',400),(f'societe_id={self.autre.id}',403)]:
            r=self.clients['DFI'].get('/api/comptabilite/tva-mensuelle?'+query)
            self.assertEqual(r.status_code,status)
