from datetime import date, timedelta
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient
from core.config_views import _inserer_affectation
from core.models import Societe, Utilisateur, Role, Tiers, Article, Chambre, Sejour


class CatalogueTests(TestCase):
    def setUp(self):
        self.a=Societe.objects.create(code='CA',nom='Société A')
        self.b=Societe.objects.create(code='CB',nom='Société B')
        self.user=Utilisateur.objects.create(email='catalogue@test.local',nom='Test',password_hash='unused')
        role=Role.objects.create(code='DFI',libelle='Direction financière')
        for soc in (self.a,self.b):_inserer_affectation(self.user.id,soc.id,role.id)
        self.client=APIClient();self.client.force_authenticate(self.user)

    def post(self,path,body,status=201,soc=None):
        with transaction.atomic():
            r=self.client.post(f'/api/{path}?societe_id={(soc or self.a).id}',body,format='json')
        self.assertEqual(r.status_code,status,r.content)
        return r.json()

    def test_code_unique_dans_la_societe_mais_reutilisable_ailleurs(self):
        body={'type':'client','code':'CL1','nom':'Client A'}
        self.post('commercial/tiers',body)
        self.post('commercial/tiers',{**body,'code':' cl1 ','nom':'Autre'},409)
        self.post('commercial/tiers',body,soc=self.b)
        self.assertEqual(Tiers.objects.count(),2)

    def test_homonyme_signale_sans_fusion_et_confirmation_explicite(self):
        self.post('commercial/tiers',{'type':'client','code':'CL1','nom':'École   Centrale'})
        body={'type':'client','code':'CL2','nom':'ecole centrale'}
        r=self.post('commercial/tiers',body,409)
        self.assertIn('existing_id',r)
        self.assertEqual(Tiers.objects.count(),1)
        self.post('commercial/tiers',{**body,'confirmer_homonyme':True})
        self.assertEqual(Tiers.objects.count(),2)

    def test_articles_code_barres_et_nature(self):
        body={'code':'A1','designation':'Farine','nature':'matiere_premiere','code_barres':'123456'}
        self.post('commercial/articles',body)
        self.post('commercial/articles',{**body,'code':'A2','designation':'Autre farine'},409)
        self.post('commercial/articles',body,soc=self.b)
        self.assertEqual(Article.objects.count(),2)

    def test_modification_ne_contourne_pas_alerte_sur_homonyme(self):
        self.post('commercial/tiers',{'type':'client','code':'C1','nom':'École Centrale'})
        autre=self.post('commercial/tiers',{'type':'client','code':'C2','nom':'Autre client'})
        url=f"/api/commercial/tiers/{autre['id']}"
        with transaction.atomic():
            r=self.client.patch(url,{'nom':'ecole centrale'},format='json')
        self.assertEqual(r.status_code,409,r.content)
        self.assertEqual(Tiers.objects.get(id=autre['id']).nom,'Autre client')
        r=self.client.patch(url,{'nom':'ecole centrale','confirmer_homonyme':True},format='json')
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(Tiers.objects.count(),2)

    def test_client_hotel_selectionne_sans_creation_doublon(self):
        t=self.post('hotel/clients',{'code':'H01','nom':'Client hôtel'})
        ch=Chambre.objects.create(societe_id=self.a.id,numero='1',tarif_nuit_usd=100)
        self.post('hotel/sejours',{'chambre_id':str(ch.id),'tiers_id':t['id'],'client_nom':'Nom saisi différent',
            'date_arrivee':date.today().isoformat(),'date_depart_prevue':(date.today()+timedelta(days=1)).isoformat(),'arrivee_immediate':True})
        self.assertEqual(Tiers.objects.count(),1)
        s=Sejour.objects.get()
        self.assertEqual(str(s.tiers_id),t['id']);self.assertEqual(s.client_nom,'Client hôtel')

    def test_hotel_refuse_client_autre_societe_et_fournisseur(self):
        ch=Chambre.objects.create(societe_id=self.a.id,numero='1',tarif_nuit_usd=100)
        for soc,kind in [(self.b,'client'),(self.a,'fournisseur')]:
            t=Tiers.objects.create(societe_id=soc.id,code=kind,nom='Test',type=kind)
            self.post('hotel/sejours',{'chambre_id':str(ch.id),'tiers_id':str(t.id),'client_nom':'Test',
                'date_arrivee':date.today().isoformat(),'date_depart_prevue':(date.today()+timedelta(days=1)).isoformat()},422)
        self.assertFalse(Sejour.objects.exists())

    def test_reception_peut_creer_client_sans_acces_fournisseurs(self):
        user=Utilisateur.objects.create(email='reception@test.local',nom='Réception',password_hash='unused')
        role,_=Role.objects.get_or_create(code='RECEPTIONNISTE',defaults={'libelle':'Réception'})
        _inserer_affectation(user.id,self.a.id,role.id)
        self.client.force_authenticate(user)
        self.post('hotel/clients',{'code':'H1','nom':'Nouveau client'})
        self.post('commercial/tiers',{'type':'fournisseur','code':'F1','nom':'Fournisseur'},403)

    def test_walkin_nom_libre_reutilise_nom_normalise(self):
        t=Tiers.objects.create(societe_id=self.a.id,code='H1',nom='Émile  Kwete',type='client')
        ch=Chambre.objects.create(societe_id=self.a.id,numero='1',tarif_nuit_usd=100)
        self.post('hotel/sejours',{'chambre_id':str(ch.id),'client_nom':'emile kwete',
            'date_arrivee':date.today().isoformat(),'date_depart_prevue':(date.today()+timedelta(days=1)).isoformat(),'arrivee_immediate':True})
        self.assertEqual(Tiers.objects.count(),1)
        self.assertEqual(Sejour.objects.get().tiers_id,t.id)

    def test_fiche_partagee_visible_et_reutilisable_sans_copie_locale(self):
        shared=Tiers.objects.create(societe_id=None,code='SHARED',nom='Client partagé',type='client')
        local=Tiers.objects.create(societe_id=self.b.id,code='LOCALB',nom='Client B',type='client')
        response=self.client.get(f'/api/hotel/clients?societe_id={self.a.id}').json()
        self.assertEqual([r['id'] for r in response],[str(shared.id)])
        self.assertIsNone(response[0]['societe_id'])
        self.post('hotel/clients',{'code':'SHARED','nom':'Copie'},409)
        self.post('commercial/tiers',{'type':'client','code':'AUTRE','nom':'Client partagé'},409)
        ch=Chambre.objects.create(societe_id=self.a.id,numero='1',tarif_nuit_usd=100)
        self.post('hotel/sejours',{'chambre_id':str(ch.id),'tiers_id':str(shared.id),'client_nom':shared.nom,
            'date_arrivee':date.today().isoformat(),'date_depart_prevue':(date.today()+timedelta(days=1)).isoformat(),'arrivee_immediate':True})
        self.assertEqual(Tiers.objects.count(),2)
        self.assertEqual(Sejour.objects.get().tiers_id,shared.id)

    def test_devis_refuse_client_prive_autre_societe_mais_accepte_partage(self):
        other=Tiers.objects.create(societe_id=self.b.id,code='B',nom='Client B',type='client')
        body={'tiers_id':str(other.id),'lignes':[{'designation':'Service','qte':1,'prix_unitaire':10,'taux_tva':0}]}
        self.post('ventes/devis',body,400)
        shared=Tiers.objects.create(societe_id=None,code='S',nom='Partagé',type='client')
        self.post('ventes/devis',{**body,'tiers_id':str(shared.id)})

    def test_facture_refuse_article_autre_societe_meme_sans_stock(self):
        t=Tiers.objects.create(societe_id=self.a.id,code='C',nom='Client A',type='client')
        article=Article.objects.create(societe_id=self.b.id,code='X',designation='Service B',gere_stock=False)
        self.post('commercial/factures',{'type':'vente','tiers_id':str(t.id),
            'lignes':[{'article_id':str(article.id),'designation':'Service','qte':1,'prix_unitaire':10,'taux_tva':0}]},400)
