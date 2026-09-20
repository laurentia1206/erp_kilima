"""Configuration du moteur Django actif ; les données et assets restent
dans backend/ pour préserver l'installation existante. Django gère le schéma.
Les variables du système ont priorité sur le fichier backend/.env.
"""
from __future__ import annotations

import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent          # backend_django/
FASTAPI_DIR = BASE_DIR.parent / "backend"                   # backend/ (existant)


def _lire_env(chemin: Path) -> dict:
    """Petit lecteur .env (pas de dépendance) — partage la config FastAPI."""
    out = {}
    if chemin.is_file():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                k, _, v = ligne.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_ENV = {**_lire_env(FASTAPI_DIR / ".env"), **os.environ}

SECRET_KEY = _ENV.get("SECRET_KEY", "dev-cle-a-remplacer")
JWT_ALGORITHM = _ENV.get("ALGORITHM", "HS256")
APP_NAME = _ENV.get("APP_NAME", "ERP KILIMA HOLDINGS")
ENVIRONMENT = _ENV.get("ENVIRONMENT", "dev").lower()
PRODUCTION = ENVIRONMENT not in {"dev", "development", "test"}
DEBUG = _ENV.get("DEBUG", "false" if PRODUCTION else "true").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in _ENV.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
if PRODUCTION:
    if DEBUG:
        raise ImproperlyConfigured("DEBUG doit être désactivé en production.")
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("dev-", "remplacer-")):
        raise ImproperlyConfigured("Définissez une SECRET_KEY aléatoire d'au moins 50 caractères.")
    if not _ENV.get("ALLOWED_HOSTS") or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Définissez explicitement les ALLOWED_HOSTS de production, sans *.")
BACKUP_ON_STARTUP = _ENV.get("BACKUP_ON_STARTUP", "true").lower() == "true"
ACCESS_TOKEN_EXPIRE_MINUTES = int(_ENV.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
SECURE_SSL_REDIRECT = _ENV.get("SECURE_SSL_REDIRECT", "true" if PRODUCTION else "false").lower() == "true"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kilima.urls"
WSGI_APPLICATION = "kilima.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]

# Base conservée à son emplacement historique.
# KILIMA_DB (variable d'environnement) permet de pointer une COPIE pour les
# tests d'écriture sans toucher aux données réelles.
_db_url = os.environ.get("KILIMA_DB") or _ENV.get("DATABASE_URL", "sqlite:///kilima_dev.db")
if _db_url.startswith("sqlite"):
    _db_path = _db_url.split("///")[-1]
    _db_file = Path(_db_path)
    if not _db_file.is_absolute():
        _db_file = FASTAPI_DIR / _db_file
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(_db_file)}}
else:
    # postgresql+psycopg://user:pwd@host/db → parsé pour Django
    from urllib.parse import urlparse
    u = urlparse(_db_url.replace("postgresql+psycopg", "postgresql"))
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"), "USER": u.username, "PASSWORD": u.password,
        "HOST": u.hostname or "localhost", "PORT": u.port or 5432,
    }}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "UNAUTHENTICATED_USER": None,
    # même format d'erreur que FastAPI : {"detail": "..."}
    "EXCEPTION_HANDLER": "core.auth.gestion_exceptions",
}

# (pas de django.contrib.staticfiles : le frontend backend/static est servi
#  par core.frontend_views avec les mêmes en-têtes no-cache que FastAPI)
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Lubumbashi"
# Dates naïves comme SQLAlchemy/SQLite (parité stricte des isoformat avec FastAPI)
USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
