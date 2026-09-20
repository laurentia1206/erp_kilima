"""Lecture et validation de la configuration, sans connexion à la base."""
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured


def read_env(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ImproperlyConfigured(f"Fichier d'environnement : ligne {number} sans signe =.")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ImproperlyConfigured(f"Fichier d'environnement : guillemets incomplets à la ligne {number}.")
            value = value[1:-1]
        values[key] = value
    return values


def boolean(env, key, default=False):
    value = env.get(key, str(default)).lower().strip()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ImproperlyConfigured(f"{key} doit valoir true ou false.")
    return value in {"true", "1", "yes"}


def integer(env, key, default, minimum=0):
    try:
        value = int(env.get(key, default))
    except (TypeError, ValueError):
        raise ImproperlyConfigured(f"{key} doit être un nombre entier.") from None
    if value < minimum:
        raise ImproperlyConfigured(f"{key} doit être supérieur ou égal à {minimum}.")
    return value


def directory(value, base):
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def database(env, base):
    url = env.get("KILIMA_DB") or env.get("DATABASE_URL", "sqlite:///kilima_dev.db")
    if url.startswith("sqlite:///"):
        name = url[len("sqlite:///"):]
        if not name:
            raise ImproperlyConfigured("DATABASE_URL : chemin SQLite manquant.")
        return {"ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:" if name == ":memory:" else str(directory(name, base)),
                "OPTIONS": {"timeout": integer(env, "DB_TIMEOUT_SECONDS", 20, 1)}}
    try:
        parsed = urlsplit(url)
        port = parsed.port or 5432
    except ValueError:
        raise ImproperlyConfigured("DATABASE_URL : adresse ou port invalide.") from None
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg"}:
        raise ImproperlyConfigured("DATABASE_URL doit utiliser SQLite ou PostgreSQL.")
    if not parsed.path.lstrip("/") or not parsed.hostname or not parsed.username or parsed.fragment:
        raise ImproperlyConfigured("DATABASE_URL : précisez utilisateur, serveur et base ; encodez les caractères réservés.")
    options = dict(parse_qsl(parsed.query))
    if set(options) - {"sslmode", "sslrootcert", "connect_timeout"}:
        raise ImproperlyConfigured("DATABASE_URL : seuls sslmode, sslrootcert et connect_timeout sont acceptés en options.")
    sslmode = env.get("DB_SSLMODE") or options.get("sslmode", "prefer")
    if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ImproperlyConfigured("DB_SSLMODE : mode SSL PostgreSQL invalide.")
    options["sslmode"] = sslmode
    options["connect_timeout"] = integer(
        {"timeout": env.get("DB_TIMEOUT_SECONDS", options.get("connect_timeout", 20))}, "timeout", 20, 1)
    if env.get("DB_SSLROOTCERT"):
        options["sslrootcert"] = str(directory(env["DB_SSLROOTCERT"], base))
    return {"ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")), "USER": unquote(parsed.username),
            "PASSWORD": unquote(parsed.password or ""), "HOST": parsed.hostname, "PORT": port,
            "CONN_MAX_AGE": integer(env, "DB_CONN_MAX_AGE", 60),
            "CONN_HEALTH_CHECKS": True, "OPTIONS": options}
