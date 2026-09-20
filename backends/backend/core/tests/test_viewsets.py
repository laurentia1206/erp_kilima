"""Ressources DRF, fermeture des CRUD implicites et portée des données."""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import URLPattern, get_resolver, resolve
from rest_framework import serializers
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.viewsets import ModelViewSet

from core.config_views import _inserer_affectation
from core.models import Role, Societe, Tiers, Utilisateur
from core.viewsets import MetierModelViewSet
from apps.stocks.models import Article, Depot, StockDepot


class ViewSetStructureTests(SimpleTestCase):
    def test_resource_serializers_match_their_models(self):
        def flatten(patterns):
            for p in patterns:
                if isinstance(p, URLPattern): yield p
                else: yield from flatten(p.url_patterns)
        seen=set()
        for pattern in flatten(get_resolver().url_patterns):
            cls=getattr(pattern.callback,'cls',None)
            if not cls or not issubclass(cls,ModelViewSet) or cls in seen: continue
            seen.add(cls)
            with self.subTest(viewset=cls.__name__,module=cls.__module__):
                self.assertTrue(issubclass(cls.serializer_class,serializers.ModelSerializer))
                self.assertIs(cls.serializer_class.Meta.model,cls.queryset.model)
                self.assertNotIn('password_hash',cls.serializer_class().fields)
                self.assertNotIn('__all__',cls.serializer_class.Meta.fields)
                for action in cls.get_extra_actions():
                    self.assertTrue(action.mapping)
        self.assertGreater(len(seen),50)

    def test_inherited_crud_never_writes_or_reads_business_data(self):
        factory=APIRequestFactory()
        for verb,action in [('get','list'),('get','retrieve'),('post','create'),('put','update'),('patch','partial_update'),('delete','destroy')]:
            view=MetierModelViewSet.as_view({verb:action})
            request=factory.generic(verb.upper(),'/')
            force_authenticate(request,user=SimpleNamespace(is_authenticated=True))
            self.assertEqual(view(request).status_code,405)

    def test_resource_routes_share_the_same_viewset(self):
        collection=resolve('/api/stock/depots')
        detail=resolve('/api/stock/depots/00000000-0000-0000-0000-000000000001')
        self.assertIs(collection.func.cls,detail.func.cls)
        self.assertEqual(collection.func.actions['post'],'create')
        self.assertEqual(detail.func.actions,{'patch':'partial_update'})
        decision=resolve('/api/rh/paies/00000000-0000-0000-0000-000000000001/decision')
        action=getattr(decision.func.cls,decision.func.actions['post'])
        self.assertTrue(action.detail)
        self.assertEqual(dict(action.mapping),{'post':action.__name__})


class ViewSetResourceTests(TestCase):
    def setUp(self):
        self.a=Societe.objects.create(code='VSA',nom='Société A')
        self.b=Societe.objects.create(code='VSB',nom='Société B')
        self.user=Utilisateur.objects.create(email='viewsets@test.local',nom='Test',password_hash='unused')
        role=Role.objects.create(code='DFI',libelle='Direction financière')
        _inserer_affectation(self.user.id,self.a.id,role.id)
        self.client=APIClient();self.client.force_authenticate(self.user)

    def test_depot_crud_scope_and_stock_representation(self):
        r=self.client.post(f'/api/stock/depots?societe_id={self.a.id}',{'libelle':'Cuisine'},format='json')
        self.assertEqual(r.status_code,201,r.content)
        depot=Depot.objects.get(id=r.data['id'])
        article=Article.objects.create(societe_id=self.a.id,code='VS1',designation='Farine')
        StockDepot.objects.create(depot_id=depot.id,article_id=article.id,qte=Decimal('2.500'),valeur=Decimal('7.25'))
        response=self.client.get(f'/api/stock/depots?societe_id={self.a.id}')
        row=next(d for d in response.json() if d['id']==str(depot.id))
        self.assertEqual(row['nb_references'],1)
        self.assertEqual(row['valeur_stock_usd'],7.25)
        self.assertNotIn('created_by',row)
        r=self.client.patch(f'/api/stock/depots/{depot.id}',{'libelle':'Cuisine principale'},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.data['libelle'],'Cuisine principale')
        self.assertEqual(self.client.delete(f'/api/stock/depots/{depot.id}').status_code,405)
        self.assertEqual(self.client.get(f'/api/stock/depots?societe_id={self.b.id}').status_code,403)
        self.assertFalse(Depot.objects.filter(societe_id=self.b.id).exists())

    def test_catalogue_serializers_preserve_shared_tiers_and_numeric_types(self):
        for soc,code in [(self.a,'A'),(self.b,'B'),(None,'G')]:
            Tiers.objects.create(societe_id=soc.id if soc else None,type='client',code=code,nom=code)
        r=self.client.get(f'/api/commercial/tiers?societe_id={self.a.id}')
        self.assertEqual(r.status_code,200)
        self.assertEqual({t['code'] for t in r.json()},{'A','G'})
        self.assertTrue(all(isinstance(t['points_fidelite'],float) for t in r.json()))
        Article.objects.create(societe_id=self.a.id,code='A1',designation='Article',prix_vente=Decimal('12.50'),stock_qte=Decimal('3.000'),stock_valeur=Decimal('10.00'))
        r=self.client.get(f'/api/commercial/articles?societe_id={self.a.id}')
        row=r.json()[0]
        self.assertEqual(row['prix_vente'],12.5)
        self.assertEqual(row['cump'],3.33)
        self.assertEqual(self.client.get(f'/api/commercial/articles?societe_id={self.b.id}').status_code,403)
