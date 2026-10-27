"""Régénère les déclencheurs d'audit de `requisition_ligne` : la colonne
`facture_id` (paiement sur justificatif adossé à une facture fournisseur)
a été ajoutée et les triggers figent leur plan de colonnes. Le spec
`requisition` accompagne `requisition_ligne` pour la résolution de sa
société."""
from django.db import migrations
from . import _audit_schema_v1 as schema

_REQUISITION = {'table': 'requisition', 'module': 'approbations', 'fields': [{'name': 'id', 'type': 'UUIDField', 'private': False}, {'name': 'numero', 'type': 'CharField', 'private': False}, {'name': 'societe_id', 'type': 'UUIDField', 'private': False}, {'name': 'site_id', 'type': 'UUIDField', 'private': False}, {'name': 'initiateur_id', 'type': 'UUIDField', 'private': False}, {'name': 'date_requisition', 'type': 'DateField', 'private': False}, {'name': 'objet', 'type': 'TextField', 'private': False}, {'name': 'justification', 'type': 'TextField', 'private': False}, {'name': 'mode_decaissement', 'type': 'CharField', 'private': False}, {'name': 'nature', 'type': 'CharField', 'private': False}, {'name': 'priorite', 'type': 'CharField', 'private': False}, {'name': 'devise', 'type': 'CharField', 'private': False}, {'name': 'taux_jour', 'type': 'DecimalField', 'private': False}, {'name': 'montant_total', 'type': 'DecimalField', 'private': False}, {'name': 'montant_total_usd', 'type': 'DecimalField', 'private': False}, {'name': 'statut', 'type': 'CharField', 'private': False}, {'name': 'created_at', 'type': 'DateTimeField', 'private': False}], 'pk': 'id'}
PLAN_NOUVEAU = [_REQUISITION, {'table': 'requisition_ligne', 'module': 'approbations', 'fields': [{'name': 'id', 'type': 'UUIDField', 'private': False}, {'name': 'requisition_id', 'type': 'UUIDField', 'private': False}, {'name': 'ordre', 'type': 'IntegerField', 'private': False}, {'name': 'compte_impute', 'type': 'CharField', 'private': False}, {'name': 'facture_id', 'type': 'UUIDField', 'private': False}, {'name': 'code_article', 'type': 'CharField', 'private': False}, {'name': 'description', 'type': 'TextField', 'private': False}, {'name': 'unite', 'type': 'CharField', 'private': False}, {'name': 'quantite', 'type': 'DecimalField', 'private': False}, {'name': 'prix_unitaire', 'type': 'DecimalField', 'private': False}, {'name': 'montant', 'type': 'DecimalField', 'private': False}, {'name': 'devise', 'type': 'CharField', 'private': False}, {'name': 'montant_usd', 'type': 'DecimalField', 'private': False}], 'pk': 'id'}]
PLAN_ANCIEN = [_REQUISITION, {'table': 'requisition_ligne', 'module': 'approbations', 'fields': [{'name': 'id', 'type': 'UUIDField', 'private': False}, {'name': 'requisition_id', 'type': 'UUIDField', 'private': False}, {'name': 'ordre', 'type': 'IntegerField', 'private': False}, {'name': 'compte_impute', 'type': 'CharField', 'private': False}, {'name': 'code_article', 'type': 'CharField', 'private': False}, {'name': 'description', 'type': 'TextField', 'private': False}, {'name': 'unite', 'type': 'CharField', 'private': False}, {'name': 'quantite', 'type': 'DecimalField', 'private': False}, {'name': 'prix_unitaire', 'type': 'DecimalField', 'private': False}, {'name': 'montant', 'type': 'DecimalField', 'private': False}, {'name': 'devise', 'type': 'CharField', 'private': False}, {'name': 'montant_usd', 'type': 'DecimalField', 'private': False}], 'pk': 'id'}]


CIBLES = ('requisition_ligne',)


def _remplacer(editor, plan):
    for spec in plan:
        if spec['table'] not in CIBLES:
            continue
        for name in schema.names(spec).values():
            editor.execute(f'DROP TRIGGER IF EXISTS {schema.quote(name)}'
                           + ('' if editor.connection.vendor == 'sqlite'
                              else ' ON ' + schema.quote(spec['table'])))
            if editor.connection.vendor != 'sqlite':
                editor.execute(f'DROP FUNCTION IF EXISTS {schema.quote(name)}()')
        for sql in schema.statements(spec, plan, editor.connection.vendor):
            editor.execute(sql)


def installer(apps, editor):
    _remplacer(editor, PLAN_NOUVEAU)


def retirer(apps, editor):
    _remplacer(editor, PLAN_ANCIEN)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0028_audit_tiers_lignes'),
        ('approbations', '0002_requisitionligne_facture_id'),
    ]
    operations = [migrations.RunPython(installer, retirer)]
