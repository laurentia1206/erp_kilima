"""Contrôle Docker : disponibilité HTTP et connexion réelle à la base."""
import sys
import urllib.request

sys.path.insert(0, "/app/backend")
from entrypoint import configure

configure()
import django
django.setup()
from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1
with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
    assert response.status == 200
