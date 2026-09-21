"""Audit des nouvelles habilitations ; aucun droit attribué automatiquement."""
from django.db import migrations
from . import _audit_schema_v1 as schema

PLAN=[{'table': 'permission_module', 'module': 'core', 'fields': [{'name': 'id', 'type': 'UUIDField', 'private': False}, {'name': 'utilisateur_id', 'type': 'ForeignKey', 'private': False}, {'name': 'module', 'type': 'CharField', 'private': False}, {'name': 'consulter', 'type': 'BooleanField', 'private': False}, {'name': 'creer', 'type': 'BooleanField', 'private': False}, {'name': 'modifier', 'type': 'BooleanField', 'private': False}, {'name': 'supprimer', 'type': 'BooleanField', 'private': False}, {'name': 'executer', 'type': 'BooleanField', 'private': False}, {'name': 'exporter', 'type': 'BooleanField', 'private': False}], 'pk': 'id'}, {'table': 'super_administrateur', 'module': 'core', 'fields': [{'name': 'utilisateur_id', 'type': 'OneToOneField', 'private': False}, {'name': 'created_at', 'type': 'DateTimeField', 'private': False}, {'name': 'changer_mot_de_passe', 'type': 'BooleanField', 'private': False}], 'pk': 'utilisateur_id'}]


def installer(apps,editor):
    plan=PLAN
    for spec in plan:
        for sql in schema.statements(spec,plan,editor.connection.vendor): editor.execute(sql)
    apps.get_model('core','Role').objects.get_or_create(code='ADMIN_SYS',defaults={'libelle':'Administrateur système','niveau':0})


def retirer(apps,editor):
    for spec in PLAN:
        for name in schema.names(spec).values():
            editor.execute(f'DROP TRIGGER IF EXISTS {schema.quote(name)}'+('' if editor.connection.vendor=='sqlite' else ' ON '+schema.quote(spec['table'])))
            if editor.connection.vendor!='sqlite': editor.execute(f'DROP FUNCTION IF EXISTS {schema.quote(name)}()')


class Migration(migrations.Migration):
    dependencies=[('core','0024_permissions_systeme')]
    operations=[migrations.RunPython(installer,retirer)]
