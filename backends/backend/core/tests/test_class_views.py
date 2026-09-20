"""Contrat HTTP et sécurité de toutes les vues converties en classes."""
from importlib import import_module
import json
from pathlib import Path
import re
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSetMixin

CONTRACT = json.loads((Path(__file__).parent/'api_contract.json').read_text(encoding='utf-8'))


def concrete(route):
    route = re.sub(r'<uuid:[^>]+>', '00000000-0000-0000-0000-000000000001', route)
    route = re.sub(r'<int:[^>]+>', '1', route)
    return '/' + re.sub(r'<[^>]+>', 'exemple', route)


def dotted(cls):
    return cls.__module__ + '.' + cls.__qualname__


class ClassViewTests(SimpleTestCase):
    def test_routes_use_explicit_classes_and_keep_security_policies(self):
        for expected in CONTRACT:
            with self.subTest(route=expected['route']):
                match = resolve(concrete(expected['route']))
                self.assertEqual(match.route, expected['route'])
                cls = match.func.cls
                self.assertTrue(issubclass(cls, APIView))
                self.assertIs(getattr(import_module(cls.__module__), cls.__name__), cls)
                is_viewset = issubclass(cls, ViewSetMixin)
                self.assertTrue(cls.__name__.endswith('ViewSet' if is_viewset else 'View'))
                self.assertEqual(sorted(match.func.initkwargs.get('http_method_names', cls.http_method_names)), expected['methods'])
                for key, attribute in [('authentication','authentication_classes'), ('permissions','permission_classes'),
                                       ('parsers','parser_classes'), ('renderers','renderer_classes'), ('throttles','throttle_classes')]:
                    self.assertEqual([dotted(c) for c in getattr(cls, attribute)], expected[key])
                for method in expected['methods']:
                    if method != 'options':
                        self.assertIn(match.func.actions[method] if is_viewset else method, cls.__dict__)

    def test_options_and_forbidden_methods_cannot_execute_business_operations(self):
        factory = APIRequestFactory()
        user = SimpleNamespace(is_authenticated=True)
        for expected in CONTRACT:
            url = concrete(expected['route'])
            match = resolve(url)
            for verb in ('OPTIONS', 'TRACE', 'HEAD', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                if verb.lower() in expected['methods'] and verb != 'OPTIONS':
                    continue
                with self.subTest(route=expected['route'], method=verb):
                    request = factory.generic(verb, url)
                    force_authenticate(request, user=user)
                    response = match.func(request, **match.kwargs)
                    self.assertEqual(response.status_code, 200 if verb == 'OPTIONS' else 405)
                    self.assertEqual(sorted(m.strip().lower() for m in response['Allow'].split(',')), expected['methods'])
        # SimpleTestCase interdit toute requête SQL : aucun de ces appels ne touche aux données.

    def test_protected_routes_still_reject_anonymous_requests(self):
        factory = APIRequestFactory()
        for expected in CONTRACT:
            if not expected['permissions']:
                continue
            with self.subTest(route=expected['route']):
                url = concrete(expected['route'])
                match = resolve(url)
                response = match.func(factory.get(url), **match.kwargs)
                self.assertEqual(response.status_code, 401)
                self.assertIn('Bearer', response['WWW-Authenticate'])

    def test_public_login_and_health_remain_accessible(self):
        factory = APIRequestFactory()
        health = resolve('/api/health').func(factory.get('/api/health'))
        self.assertEqual(health.status_code, 200)
        # Validation du formulaire avant toute requête SQL et sans authentification.
        login = resolve('/api/auth/login').func(factory.post('/api/auth/login', {'username': [], 'password': ''}, format='json'))
        self.assertEqual(login.status_code, 400)
