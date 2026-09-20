"""Configuration du moteur Django actif ; les données et assets restent
dans backend/ pour préserver l'installation existante. Django gère le schéma.
Les variables du système ont priorité sur le fichier backend/.env.
"""
from __future__ import annotations

import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .environment import read_env, boolean, integer, directory, database

BASE_DIR = Path(__file__).resolve().parent.parent          # backend_django/
FASTAPI_DIR = BASE_DIR.parent / "backend"                   # backend/ (existant)


ENV_FILE = directory(os.environ.get("KILIMA_ENV_FILE", ".env"), FASTAPI_DIR)
if os.environ.get("KILIMA_ENV_FILE") and not ENV_FILE.is_file():
    raise ImproperlyConfigured("Le fichier désigné par KILIMA_ENV_FILE est introuvable.")
_ENV = {**read_env(ENV_FILE), **os.environ}

SECRET_KEY = _ENV.get("SECRET_KEY", "dev-cle-a-remplacer")
JWT_ALGORITHM = _ENV.get("ALGORITHM", "HS256")
APP_NAME = _ENV.get("APP_NAME", "ERP KILIMA HOLDINGS")
ENVIRONMENT = _ENV.get("ENVIRONMENT", "dev").lower()
PRODUCTION = ENVIRONMENT not in {"dev", "development", "test"}
DEBUG = boolean(_ENV, "DEBUG", not PRODUCTION)
ALLOWED_HOSTS = [h.strip() for h in _ENV.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
if PRODUCTION:
    if DEBUG:
        raise ImproperlyConfigured("DEBUG doit être désactivé en production.")
    if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("dev-", "remplacer-")):
        raise ImproperlyConfigured("Définissez une SECRET_KEY aléatoire d'au moins 50 caractères.")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS or not _ENV.get("ALLOWED_HOSTS"):
        raise ImproperlyConfigured("Définissez explicitement les ALLOWED_HOSTS de production, sans *.")
BACKUP_ON_STARTUP = boolean(_ENV, "BACKUP_ON_STARTUP", True)
BACKUP_DIR = directory(_ENV["BACKUP_DIR"], FASTAPI_DIR) if _ENV.get("BACKUP_DIR") else None
BACKUP_KEEP_COUNT = integer(_ENV, "BACKUP_KEEP_COUNT", 14, 1)
UPLOADS_DIR = directory(_ENV.get("UPLOADS_DIR", "uploads"), FASTAPI_DIR)
MAX_UPLOAD_MB = integer(_ENV, "MAX_UPLOAD_MB", 10, 1)
ACCESS_TOKEN_EXPIRE_MINUTES = integer(_ENV, "ACCESS_TOKEN_EXPIRE_MINUTES", 720, 1)
if JWT_ALGORITHM not in {"HS256", "HS384", "HS512"}:
    raise ImproperlyConfigured("ALGORITHM doit être HS256, HS384 ou HS512 (clé symétrique).")
SECURE_SSL_REDIRECT = boolean(_ENV, "SECURE_SSL_REDIRECT", PRODUCTION)
# À activer seulement derrière un proxy maîtrisé qui écrase cet en-tête.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if boolean(_ENV, "TRUST_PROXY_HTTPS") else None
SECURE_HSTS_SECONDS = integer(_ENV, "SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = boolean(_ENV, "SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = boolean(_ENV, "SECURE_HSTS_PRELOAD")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "core",
    "apps.approbations.apps.ApprobationsConfig",
    "apps.tresorerie.apps.TresorerieConfig",
    "apps.comptabilite.apps.ComptabiliteConfig",
    "apps.stocks.apps.StocksConfig",
    "apps.commercial.apps.CommercialConfig",
    "apps.hotel.apps.HotelConfig",
    "apps.transport.apps.TransportConfig",
    "apps.maintenance.apps.MaintenanceConfig",
    "apps.engins.apps.EnginsConfig",
    "apps.groupe.apps.GroupeConfig",
    "apps.rh.apps.RhConfig",
    "apps.pilotage.apps.PilotageConfig",
    "apps.editions.apps.EditionsConfig",
]

MIDDLEWARE = [
    "core.audit_context.AuditContextMiddleware",
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
DATABASES = {"default": database(_ENV, FASTAPI_DIR)}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated", "core.permissions.PermissionsModules"],
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
