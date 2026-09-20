"""Contrats de configuration sans réseau ni base de travail."""
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from kilima.environment import boolean, database, integer, read_env


class EnvironmentTests(SimpleTestCase):
    def test_bom_quotes_and_special_characters_remain_literal(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('\ufeff# commentaire\nSECRET_KEY="a#b=c$HOME"\nBLANK=\n', encoding="utf-8")
            self.assertEqual(read_env(path), {"SECRET_KEY": "a#b=c$HOME", "BLANK": ""})
            path.write_text('SECRET_KEY="secret-non-ferme', encoding="utf-8")
            with self.assertRaises(ImproperlyConfigured) as error:
                read_env(path)
            self.assertNotIn("secret-non-ferme", str(error.exception))

    def test_invalid_booleans_and_numbers_fail_explicitly(self):
        self.assertTrue(boolean({"DEBUG": "true"}, "DEBUG"))
        self.assertFalse(boolean({"DEBUG": "0"}, "DEBUG"))
        for action in [lambda: boolean({"DEBUG": "fales"}, "DEBUG"),
                       lambda: integer({"AGE": "zero"}, "AGE", 1),
                       lambda: integer({"AGE": "0"}, "AGE", 1, 1)]:
            with self.assertRaises(ImproperlyConfigured):
                action()

    def test_sqlite_path_and_override_do_not_depend_on_working_directory(self):
        base = Path(__file__).resolve().parent
        db = database({"DATABASE_URL": "sqlite:///../recette.db"}, base)
        self.assertEqual(db["NAME"], str((base / "../recette.db").resolve()))
        db = database({"DATABASE_URL": "invalid", "KILIMA_DB": "sqlite:///:memory:"}, base)
        self.assertEqual(db["NAME"], ":memory:")

    def test_postgres_decodes_credentials_and_applies_ssl(self):
        db = database({"DATABASE_URL": "postgresql+psycopg://agent:p%40ss%23%3A@db.example:5433/kilima?sslmode=require",
                       "DB_SSLMODE": "verify-full", "DB_SSLROOTCERT": "ca.crt"}, Path.cwd())
        self.assertEqual(db["PASSWORD"], "p@ss#:")
        self.assertEqual(db["PORT"], 5433)
        self.assertEqual(db["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(db["OPTIONS"]["sslrootcert"], str(Path.cwd() / "ca.crt"))

    def test_bad_database_urls_fail_without_leaking_credentials(self):
        for url in ["mysql://agent:secret@db/kilima", "postgresql://agent:secret@db:bad/kilima",
                    "postgresql://agent:secret@db/kilima?unknown=1", "sqlite:///"]:
            with self.assertRaises(ImproperlyConfigured) as error:
                database({"DATABASE_URL": url}, Path.cwd())
            self.assertNotIn("secret", str(error.exception))

    def load_settings(self, env):
        spec = importlib.util.find_spec("kilima.settings")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, env, clear=True):
            spec.loader.exec_module(module)
        return module

    def test_system_environment_overrides_selected_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("ENVIRONMENT=dev\nDATABASE_URL=sqlite:///file.db\nMAX_UPLOAD_MB=25\n", encoding="utf-8")
            settings = self.load_settings({"KILIMA_ENV_FILE": str(path), "KILIMA_DB": "sqlite:///:memory:", "MAX_UPLOAD_MB": "12"})
            self.assertEqual(settings.DATABASES["default"]["NAME"], ":memory:")
            self.assertEqual(settings.MAX_UPLOAD_MB, 12)
            self.assertIsNone(settings.SECURE_PROXY_SSL_HEADER)

    def test_production_guards_and_explicit_proxy_trust(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("", encoding="utf-8")
            env = {"KILIMA_ENV_FILE": str(path), "ENVIRONMENT": "production",
                   "SECRET_KEY": "s" * 64, "ALLOWED_HOSTS": "erp.example", "DATABASE_URL": "sqlite:///:memory:"}
            settings = self.load_settings(env)
            self.assertFalse(settings.DEBUG)
            self.assertTrue(settings.SECURE_SSL_REDIRECT)
            trusted = self.load_settings({**env, "TRUST_PROXY_HTTPS": "true"})
            self.assertEqual(trusted.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
            for invalid in [{"DEBUG": "true"}, {"SECRET_KEY": "dev-key"}, {"ALLOWED_HOSTS": " , "}, {"ALLOWED_HOSTS": "*"}]:
                with self.assertRaises(ImproperlyConfigured):
                    self.load_settings({**env, **invalid})
            with self.assertRaises(ImproperlyConfigured):
                self.load_settings({"KILIMA_ENV_FILE": str(path.with_name("missing.env"))})
