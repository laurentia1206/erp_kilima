import io
from unittest.mock import patch
import bcrypt
from django.core.management import call_command, CommandError
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Utilisateur, Societe, Role, SuperAdministrateur, PermissionModule, AuditLog
from core.config_views import _inserer_affectation
from core.admin_views import configuration
from core.auth import creer_token
from core.permissions import ACTIONS
from apps.stocks.models import Article


class PermissionsSystemeTests(TestCase):
    def setUp(self):
        self.a=Societe.objects.create(code='PRA',nom='Société A')
        self.b=Societe.objects.create(code='PRB',nom='Société B')
        self.root=Utilisateur.objects.create(email='root@test.local',nom='Root',password_hash=bcrypt.hashpw(b'initial-password',bcrypt.gensalt(rounds=4)).decode())
        self.user=Utilisateur.objects.create(email='dfi@test.local',nom='DFI',password_hash='unused')
        self.super=SuperAdministrateur.objects.create(utilisateur=self.root)
        role,_=Role.objects.get_or_create(code='DFI',defaults={'libelle':'DFI'})
        _inserer_affectation(self.user.id,self.a.id,role.id)
        self.client=APIClient();self.client.force_authenticate(self.root)
        self.url=f'/api/systeme/utilisateurs/{self.user.id}'

    def save(self,**flags):
        rule={'module':'stocks',**{a:True for a in ACTIONS},**flags}
        return self.client.patch(self.url,{'revision':configuration(self.user)['revision'],'permissions':[rule]},format='json')

    def test_super_admin_manages_users_without_business_access(self):
        r=self.client.get('/api/societes');self.assertEqual(r.data,[])
        self.assertTrue(self.client.get('/api/auth/me').data['super_administrateur'])
        self.assertEqual(self.client.get(f'/api/stock/depots?societe_id={self.b.id}').status_code,403)
        self.assertEqual(self.client.get('/api/config/utilisateurs').status_code,200)
        self.assertEqual(self.client.get('/api/audit/journal?portee=global').status_code,200)
        self.assertEqual(self.client.get('/api/approbations').status_code,403)
        refs=self.client.get('/api/config/societes');self.assertEqual(refs.status_code,200)
        self.assertEqual(set(refs.data[0]),{'id','nom','code','actif'})
        self.assertEqual(self.client.post('/api/config/societes',{'code':'NEW','nom':'Interdite'},format='json').status_code,403)
        self.assertEqual(self.client.patch(f'/api/config/societes/{self.a.id}',{'nom':'Interdit'},format='json').status_code,403)
        self.assertEqual(self.client.delete(f'/api/config/societes/{self.a.id}').status_code,403)
        self.assertEqual(self.client.get('/api/config/paliers').status_code,403)
        self.assertEqual(self.client.get('/api/config/parametres').status_code,403)
        _inserer_affectation(self.root.id,self.a.id,Role.objects.get(code='DFI').id)
        self.assertEqual(self.client.get('/api/societes').data,[])
        self.assertEqual(self.client.get(f'/api/commercial/articles?societe_id={self.a.id}').status_code,403)

    def test_ordinary_admin_cannot_manage_global_permissions_or_reset_super(self):
        self.client.force_authenticate(self.user)
        for url in ['/api/systeme/utilisateurs',self.url]:self.assertEqual(self.client.get(url).status_code,403)
        for payload in [{'actif':False},{'actif':''},{'password':'replacement-password'},{'email':'takeover@test.local'}]:
            self.assertEqual(self.client.patch(f'/api/config/utilisateurs/{self.root.id}',payload,format='json').status_code,403)
        self.assertEqual(self.client.patch(self.url,{'permissions':[]},format='json').status_code,403)
        self.client.patch(f'/api/config/utilisateurs/{self.user.id}',{'super_administrateur':True},format='json')
        self.assertFalse(SuperAdministrateur.objects.filter(utilisateur=self.user).exists())

    def test_global_rules_apply_to_old_tokens_and_fake_company_parameters(self):
        token=creer_token(self.user.id)
        self.assertEqual(self.save(consulter=False).status_code,200)
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+token)
        for sid in (self.a.id,self.b.id):
            self.assertEqual(client.get(f'/api/commercial/articles?societe_id={sid}').status_code,403)
        self.assertEqual(client.get(f'/api/rh/organisation?societe_id={self.a.id}').status_code,200)
        self.assertTrue(AuditLog.objects.filter(action='ACCES_REFUSE').exists())

    def test_separate_create_edit_execute_delete_export_permissions(self):
        article=Article.objects.create(societe_id=self.a.id,code='P1',designation='Article')
        self.assertEqual(self.save(modifier=False,creer=False).status_code,200)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f'/api/commercial/articles?societe_id={self.a.id}').status_code,200)
        self.assertEqual(self.client.patch(f'/api/commercial/articles/{article.id}?societe_id={self.b.id}',{'designation':'Fraude'},format='json').status_code,403)
        self.assertEqual(self.client.post('/api/commercial/articles',{'societe_id':str(self.a.id),'code':'P2'},format='json').status_code,403)
        article.refresh_from_db();self.assertEqual(article.designation,'Article')
        PermissionModule.objects.create(utilisateur=self.user,module='editions',exporter=False)
        self.assertEqual(self.client.post('/api/editions/telecharger',{},format='json').status_code,403)
        PermissionModule.objects.create(utilisateur=self.user,module='approbations',executer=False)
        self.assertEqual(self.client.post('/api/requisitions/00000000-0000-0000-0000-000000000001/valider-demande',{},format='json').status_code,403)

    def test_permission_never_grants_company_or_business_role(self):
        self.assertEqual(self.save().status_code,200)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f'/api/stock/depots?societe_id={self.b.id}').status_code,403)

    def test_stale_revision_invalid_duplicate_modules_and_audit(self):
        old=configuration(self.user)['revision']
        self.assertEqual(self.save(modifier=False).status_code,200)
        r=self.client.patch(self.url,{'revision':old,'permissions':[]},format='json');self.assertEqual(r.status_code,400)
        self.assertFalse(PermissionModule.objects.get(utilisateur=self.user,module='stocks').modifier)
        rule={'module':'inconnu',**{a:True for a in ACTIONS}}
        r=self.client.patch(self.url,{'revision':configuration(self.user)['revision'],'permissions':[rule]},format='json');self.assertEqual(r.status_code,400)
        rule['module']='stocks'
        r=self.client.patch(self.url,{'revision':configuration(self.user)['revision'],'permissions':[rule,rule]},format='json');self.assertEqual(r.status_code,400)
        row=AuditLog.objects.filter(table_cible='permission_module').latest('id')
        self.assertEqual(row.utilisateur_id,self.root.id);self.assertEqual(row.nouvelle_valeur['modifier'],False)
        r=self.client.get('/api/audit/protection?portee=global');self.assertTrue(r.data['active'],r.data)

    def test_super_promotion_revocation_and_self_lockout(self):
        def status(u,grant):return self.client.post(f'/api/systeme/utilisateurs/{u.id}/statut',{'revision':configuration(u)['revision'],'super_administrateur':grant},format='json')
        self.assertEqual(status(self.root,False).status_code,400)
        self.assertEqual(self.client.patch(f'/api/config/utilisateurs/{self.root.id}',{'actif':False},format='json').status_code,400)
        self.assertEqual(status(self.user,True).status_code,200)
        self.assertEqual(self.save(consulter=False).status_code,400)
        self.assertEqual(status(self.user,False).status_code,200)
        self.user.actif=False;self.user.save()
        self.assertEqual(status(self.user,True).status_code,400)
        self.assertEqual(SuperAdministrateur.objects.count(),1)

    def test_first_password_change_required_and_secrets_not_logged(self):
        self.super.changer_mot_de_passe=True;self.super.save()
        self.assertEqual(self.client.get('/api/systeme/utilisateurs').status_code,403)
        self.assertEqual(self.client.get(f'/api/commercial/articles?societe_id={self.a.id}').status_code,403)
        self.assertTrue(self.client.get('/api/auth/me').data['changer_mot_de_passe'])
        self.assertEqual(self.client.post('/api/systeme/mot-de-passe',{'ancien':'wrong','nouveau':'new-strong-password'},format='json').status_code,400)
        self.assertEqual(self.client.post('/api/systeme/mot-de-passe',{'ancien':'initial-password','nouveau':'new-strong-password'},format='json').status_code,200)
        self.assertEqual(self.client.get('/api/systeme/utilisateurs').status_code,200)
        self.root.refresh_from_db();self.assertTrue(bcrypt.checkpw(b'new-strong-password',self.root.password_hash.encode()))
        logs=str(list(AuditLog.objects.values('ancienne_valeur','nouvelle_valeur')))
        self.assertNotIn('new-strong-password',logs);self.assertNotIn(self.root.password_hash,logs)

    def test_bootstrap_never_overwrites_existing_super(self):
        with self.assertRaises(CommandError):call_command('initialiser_super_admin',self.user.email,stdout=io.StringIO())
        self.assertFalse(SuperAdministrateur.objects.filter(utilisateur=self.user).exists())

    def test_password_rotation_invalidates_previous_super_session(self):
        old=creer_token(self.root.id,self.root.password_hash)
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+old)
        r=client.post('/api/systeme/mot-de-passe',{'ancien':'initial-password','nouveau':'rotated-password-123'},format='json')
        self.assertEqual(r.status_code,200)
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        client.credentials(HTTP_AUTHORIZATION='Bearer '+r.data['access_token'])
        self.assertEqual(client.get('/api/systeme/utilisateurs').status_code,200)

    def test_inactive_super_cannot_be_taken_over_by_ordinary_admin(self):
        self.root.actif=False;self.root.save()
        self.client.force_authenticate(self.user)
        r=self.client.patch(f'/api/config/utilisateurs/{self.root.id}',{'actif':True,'password':'takeover-password'},format='json')
        self.assertEqual(r.status_code,403)

    def test_super_audit_never_exposes_company_operations(self):
        article=Article.objects.create(societe_id=self.a.id,code='SECRET',designation='Business confidentiel')
        row=AuditLog.objects.filter(table_cible='article').latest('id')
        logs=self.client.get('/api/audit/journal?portee=global')
        self.assertTrue(all(r['table']!='article' for r in logs.data['resultats']))
        self.assertTrue(any(r['table']=='utilisateur_societe' for r in logs.data['resultats']))
        self.assertEqual(self.client.get(f'/api/audit/journal/{row.id}?portee=global').status_code,404)
        self.assertEqual(self.client.get(f'/api/audit/journal?societe_id={self.a.id}').status_code,403)
        self.assertEqual(self.client.get('/api/audit/export?portee=global&table=article').status_code,400)

    def test_every_business_route_refuses_super_admin(self):
        import re
        from django.urls import get_resolver,URLPattern
        def routes(patterns,prefix=''):
            for p in patterns:
                if isinstance(p,URLPattern):yield prefix+str(p.pattern),p.callback
                else:yield from routes(p.url_patterns,prefix+str(p.pattern))
        total=0
        for route,callback in routes(get_resolver().url_patterns):
            cls=getattr(callback,'cls',None)
            if not cls or not cls.__module__.startswith('apps.'):continue
            url='/'+re.sub(r'<uuid:[^>]+>','00000000-0000-0000-0000-000000000001',route)
            for verb in list(callback.actions):
                if verb in ('options','head'):continue
                with self.subTest(route=route,method=verb):
                    response=self.client.generic(verb.upper(),url,data=b'{}',content_type='application/json')
                    self.assertEqual(response.status_code,403)
                total+=1
        self.assertGreater(total,200)
