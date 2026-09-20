"""Contrats de compatibilité conservés lors du découpage en applications."""
from collections import Counter
from importlib import import_module
import json
from pathlib import Path
import re

from django.apps import apps
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import SeparateDatabaseAndState
from django.test import SimpleTestCase
from django.urls import URLPattern, get_resolver, resolve

from core import models

CONTRACT = json.loads((Path(__file__).parent/'architecture_contract.json').read_text(encoding='utf-8'))


class ArchitectureTests(SimpleTestCase):
    def test_model_ownership_and_unchanged_tables(self):
        for name, expected in CONTRACT['models'].items():
            with self.subTest(model=name):
                model = apps.get_model(expected['app'], name)
                self.assertIs(getattr(models, name), model)
                self.assertEqual(model._meta.db_table, expected['table'])
                self.assertEqual(model.__module__, 'core.models' if expected['app']=='core' else f"apps.{expected['app']}.models")

    def test_api_routes_preserved_and_resolvable(self):
        def flatten(patterns, prefix=''):
            result=[]
            for pattern in patterns:
                path=prefix+str(pattern.pattern)
                if isinstance(pattern,URLPattern): result.append(path)
                else: result.extend(flatten(pattern.url_patterns,path))
            return result
        self.assertEqual(Counter(flatten(get_resolver().url_patterns)),Counter(CONTRACT['routes']))
        for route in CONTRACT['routes']:
            concrete=re.sub(r'<uuid:[^>]+>', '00000000-0000-0000-0000-000000000001',route)
            concrete=re.sub(r'<int:[^>]+>', '1',concrete)
            concrete=re.sub(r'<[^>]+>', 'exemple',concrete)
            self.assertIsNotNone(resolve('/'+concrete).func)

    def test_transition_has_no_database_operations(self):
        loader=MigrationLoader(None)
        migrations=[m for key,m in loader.disk_migrations.items() if key[1] in ('0001_adoption_modeles','0021_applications_metier')]
        self.assertEqual(len(migrations),12)
        for migration in migrations:
            for operation in migration.operations:
                self.assertIsInstance(operation,SeparateDatabaseAndState)
                self.assertEqual(operation.database_operations,[])

    def test_legacy_module_alias_keeps_the_same_service(self):
        for old,new in [('core.rh_finances','apps.rh.finances'),('core.comptabilite','apps.comptabilite.services'),('core.stock_lib','apps.stocks.services')]:
            self.assertIs(import_module(old),import_module(new))
