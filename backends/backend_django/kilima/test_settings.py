"""Tests Django isolés : aucune lecture/écriture dans la base de travail."""
import os

os.environ["KILIMA_DB"] = "sqlite:///:memory:"
os.environ["BACKUP_ON_STARTUP"] = "false"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECURE_SSL_REDIRECT"] = "false"

from .settings import *  # noqa: F403,E402

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
BACKUP_ON_STARTUP = False
