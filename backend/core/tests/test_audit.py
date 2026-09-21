from datetime import date
from decimal import Decimal
import io
import json
import uuid
from unittest.mock import patch

import bcrypt
from django.db import connection, transaction, DatabaseError
from django.test import TestCase
from rest_framework.test import APIClient
from openpyxl import load_workbook

from core.models import AuditLog, Societe, Role, Utilisateur, Tiers, UtilisateurSociete
from core.config_views import _inserer_affectation
from core.audit_schema import names, build_plan
from core.audit_context import current
from django.apps import apps
from apps.stocks.models import Article
from apps.rh.models import RHAgent, RHContrat


class AuditTests(TestCase):
    def setUp(self):
        self.a=Societe.objects.create(code='AUA',nom='Audit A')
        self.b=Societe.objects.create(code='AUB',nom='Audit B')
        self.password='audit-test-only'
        self.user=Utilisateur.objects.create(email='audit@test.local',nom='DFI audit',password_hash=bcrypt.hashpw(self.password.encode(),bcrypt.gensalt(rounds=4)).decode())
        self.admin=Utilisateur.objects.create(email='admin-audit@test.local',nom='Admin',password_hash='secret-hash-not-for-audit')
        for user,code in [(self.user,'DFI'),(self.admin,'ADMIN_SYS')]:
            role,_=Role.objects.get_or_create(code=code,defaults={'libelle':code})
            _inserer_affectation(user.id,self.a.id,role.id)
        self.client=APIClient();self.client.force_authenticate(self.user)
        self.url=f'/api/audit/journal?societe_id={self.a.id}'

    def article(self,soc=None,**extra):
        return Article.objects.create(societe_id=(soc or self.a).id,code=uuid.uuid4().hex[:10],designation='Article audit',**extra)

    def test_request_actor_ip_before_after_and_correlation(self):
        a=self.article(prix_vente=Decimal('12.00'))
        response=self.client.patch(f'/api/commercial/articles/{a.id}',{'prix_vente':15},format='json',REMOTE_ADDR='192.0.2.44',HTTP_X_FORWARDED_FOR='203.0.113.9',HTTP_X_REQUEST_ID='invented')
        self.assertEqual(response.status_code,200,response.content)
        row=AuditLog.objects.filter(table_cible='article',enregistrement_id=a.id.hex,action='UPDATE').latest('id')
        self.assertEqual(row.utilisateur_id,self.user.id)
        self.assertEqual(row.societe_id,self.a.id)
        self.assertEqual(row.adresse_ip,'192.0.2.44')
        self.assertEqual(row.ancienne_valeur['prix_vente'],12)
        self.assertEqual(row.nouvelle_valeur['prix_vente'],15)
        self.assertEqual(row.champs_modifies,['prix_vente'])
        self.assertEqual(str(row.requete_id),response['X-Request-ID'])
        self.assertEqual(row.methode,'PATCH')
        self.assertIsNone(current.get())

    def test_bulk_update_raw_sql_delete_and_noop(self):
        a=self.article();b=self.article()
        start=AuditLog.objects.count()
        Article.objects.filter(id__in=[a.id,b.id]).update(prix_vente=12)
        self.assertEqual(AuditLog.objects.count()-start,2)
        Article.objects.filter(id__in=[a.id,b.id]).update(prix_vente=12)
        self.assertEqual(AuditLog.objects.count()-start,2)
        with connection.cursor() as cursor:cursor.execute('UPDATE article SET prix_vente=%s WHERE id=%s',[13,a.id.hex])
        a.delete()
        deleted=AuditLog.objects.filter(table_cible='article',action='DELETE').latest('id')
        self.assertEqual(deleted.ancienne_valeur['prix_vente'],13)
        self.assertEqual(deleted.societe_id,self.a.id)
        self.assertEqual(deleted.origine,'systeme')

    def test_changes_and_logs_roll_back_together(self):
        a=self.article();before=AuditLog.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Article.objects.filter(pk=a.pk).update(prix_vente=99)
                raise RuntimeError('Annulation')
        a.refresh_from_db();self.assertEqual(a.prix_vente,0)
        self.assertEqual(AuditLog.objects.count(),before)

    def test_audit_failure_prevents_untraceable_change(self):
        a=self.article();connection.connection.create_function('kilima_audit',1,lambda k:(_ for _ in ()).throw(RuntimeError('indisponible')))
        try:
            with self.assertRaises(DatabaseError),transaction.atomic():
                Article.objects.filter(pk=a.pk).update(prix_vente=44)
        finally:
            from core.audit_context import register_connection
            register_connection(connection=connection)
        a.refresh_from_db();self.assertEqual(a.prix_vente,0)

    def test_raw_assignment_has_company_and_user_reference(self):
        row=AuditLog.objects.filter(table_cible='utilisateur_societe',action='INSERT').latest('id')
        self.assertEqual(row.societe_id,self.a.id)
        self.assertEqual(row.nouvelle_valeur['utilisateur_id'],self.admin.id.hex)

    def test_immutable_orm_sql_and_replace(self):
        row=AuditLog.objects.first()
        for operation in (lambda:AuditLog.objects.filter(id=row.id).update(action='FAUX'),lambda:row.delete(),lambda:AuditLog.objects.all().delete()):
            with self.assertRaises(ValueError):operation()
        row.action='FAUX'
        with self.assertRaises(ValueError):row.save()
        for sql in ['UPDATE audit_log SET action=\'FAUX\' WHERE id=%s','DELETE FROM audit_log WHERE id=%s']:
            with self.assertRaises(DatabaseError),transaction.atomic():
                with connection.cursor() as cursor:cursor.execute(sql,[row.id])
        with self.assertRaises(DatabaseError),transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('INSERT OR REPLACE INTO audit_log SELECT * FROM audit_log WHERE id=%s',[row.id])
        self.assertNotEqual(AuditLog.objects.get(id=row.id).action,'FAUX')

    def test_login_success_failure_disabled_and_unknown_account(self):
        client=APIClient()
        for name,password,status in [(self.user.email,self.password,200),(self.user.email,'wrong-password',401),('unknown@test.local','wrong-password',401)]:
            r=client.post('/api/auth/login',{'username':name,'password':password},format='json',REMOTE_ADDR='192.0.2.55')
            self.assertEqual(r.status_code,status)
        self.user.actif=False;self.user.save()
        r=client.post('/api/auth/login',{'username':self.user.email,'password':self.password},format='json')
        self.assertEqual(r.status_code,403)
        logs=AuditLog.objects.filter(categorie='securite')
        self.assertEqual(logs.filter(action='CONNEXION_REUSSIE').count(),1)
        self.assertEqual(logs.filter(action='CONNEXION_ECHEC').count(),3)
        self.assertEqual(logs.filter(action='CONNEXION_ECHEC',societe_id=self.a.id).count(),2)
        content=json.dumps(list(logs.values('ancienne_valeur','nouvelle_valeur')),default=str)
        for secret in [self.password,'wrong-password','unknown@test.local',self.user.password_hash]:self.assertNotIn(secret,content)

    def test_private_hr_fields_and_passwords_are_masked(self):
        agent=RHAgent.objects.create(societe=self.a,matricule='A1',nom='Personne privée',nom_normalise='personne privee',date_engagement=date.today(),created_by=self.user.id,updated_by=self.user.id)
        contract=RHContrat.objects.create(societe=self.a,agent=agent,reference='C1',type_contrat='CDI',debut=date.today(),salaire=1234,base_salaire='net',devise='USD',created_by=self.user.id,updated_by=self.user.id)
        row=AuditLog.objects.filter(table_cible='core_rhcontrat',enregistrement_id=contract.id.hex).latest('id')
        self.assertEqual(row.nouvelle_valeur['salaire'],'[masqué]')
        userlog=AuditLog.objects.filter(table_cible='utilisateur',enregistrement_id=self.user.id.hex).first()
        self.assertEqual(userlog.nouvelle_valeur['password_hash'],'[masqué]')
        self.assertNotIn(self.user.password_hash,json.dumps(userlog.nouvelle_valeur))

    def test_scope_permissions_shared_and_detail(self):
        a=self.article();b=self.article(self.b)
        Tiers.objects.create(code='SHARED',nom='Partagé',type='client')
        foreign=AuditLog.objects.filter(table_cible='article',enregistrement_id=b.id.hex).latest('id')
        r=self.client.get(self.url);self.assertEqual(r.status_code,200)
        self.assertEqual(r['Cache-Control'],'no-store')
        self.assertNotIn(foreign.id,[x['id'] for x in r.data['resultats']])
        self.assertEqual(self.client.get(f'/api/audit/journal/{foreign.id}?societe_id={self.a.id}').status_code,404)
        self.assertEqual(self.client.get(f'/api/audit/journal?societe_id={self.b.id}').status_code,403)
        self.assertEqual(self.client.get('/api/audit/journal?portee=global').status_code,403)
        r=self.client.get(self.url+'&portee=partage');self.assertTrue(any(x['table']=='tiers' for x in r.data['resultats']))
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/audit/journal?portee=global').status_code,200)
        ordinary=Utilisateur.objects.create(email='ordinary@test.local',nom='Agent',password_hash='unused')
        role,_=Role.objects.get_or_create(code='COMPTABLE',defaults={'libelle':'Comptable'})
        _inserer_affectation(ordinary.id,self.a.id,role.id);self.client.force_authenticate(ordinary)
        self.assertEqual(self.client.get(self.url).status_code,403)

    def test_filters_pagination_dates_and_read_only(self):
        for n in range(55):self.article()
        r=self.client.get(self.url+'&table=article');self.assertEqual(len(r.data['resultats']),50)
        bound=r.data['borne'];self.article()
        r2=self.client.get(self.url+f'&table=article&page=2&borne={bound}')
        self.assertEqual(len(r2.data['resultats']),5)
        self.assertEqual(r2.data['total'],55)
        for query in ['&du=not-a-date','&du=2026-10-01&au=2026-01-01','&page=-1','&utilisateur_id=bad']:
            self.assertEqual(self.client.get(self.url+query).status_code,400)
        self.assertEqual(self.client.delete(self.url).status_code,405)

    def test_server_exports_and_export_trace(self):
        a=self.article();Article.objects.filter(id=a.id).update(designation='=1+2')
        url=f'/api/audit/export?societe_id={self.a.id}&table=article'
        r=self.client.get(url+'&format_export=xlsx');self.assertEqual(r.status_code,200,r.content[:100])
        book=load_workbook(io.BytesIO(r.content));self.assertEqual(book.active['A1'].value,self.a.nom)
        self.assertFalse(any(c.data_type=='f' for row in book.active for c in row))
        r=self.client.get(url+'&format_export=pdf');self.assertEqual(r.status_code,200,r.content[:100]);self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(AuditLog.objects.filter(action='EXPORT_AUDIT',societe_id=self.a.id).count(),2)
        self.assertEqual(self.client.get(f'/api/audit/export?societe_id={self.b.id}').status_code,403)
        self.assertEqual(self.client.get(url+'&format_export=csv').status_code,400)

    def test_missing_or_modified_trigger_is_detected(self):
        url=f'/api/audit/protection?societe_id={self.a.id}'
        r=self.client.get(url);self.assertTrue(r.data['active'],r.data)
        spec=next(x for x in build_plan(apps) if x['table']=='article');name=names(spec)['UPDATE']
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP TRIGGER "'+name+'"')
                cursor.execute('CREATE TRIGGER "'+name+'" AFTER UPDATE ON article BEGIN SELECT 1; END')
            r=self.client.get(url);self.assertFalse(r.data['active']);self.assertIn(name,r.data['modifies'])
            transaction.set_rollback(True)
        self.assertTrue(self.client.get(url).data['active'])
