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
        port = parsed.port
    except ValueError:
        raise ImproperlyConfigured("DATABASE_URL : adresse ou port invalide.") from None
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg", "mysql"}:
        raise ImproperlyConfigured("DATABASE_URL doit utiliser SQLite, PostgreSQL ou MySQL.")
    if port == 0:
        raise ImproperlyConfigured("DATABASE_URL : le port doit être compris entre 1 et 65535.")
    if not parsed.path.lstrip("/") or not parsed.hostname or not parsed.username or parsed.fragment:
        raise ImproperlyConfigured("DATABASE_URL : précisez utilisateur, serveur et base ; encodez les caractères réservés.")
    options = dict(parse_qsl(parsed.query))
    if parsed.scheme == "mysql":
        if options:
            raise ImproperlyConfigured("MySQL : utilisez les variables DB_MYSQL_* pour les options, sans paramètres dans DATABASE_URL.")
        sslmode = env.get("DB_MYSQL_SSL_MODE", "REQUIRED").upper()
        if sslmode not in {"DISABLED", "PREFERRED", "REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"}:
            raise ImproperlyConfigured("DB_MYSQL_SSL_MODE : mode SSL MySQL invalide.")
        ssl = {option: str(directory(env[key], base))
               for key, option in [("DB_MYSQL_SSL_CA", "ca"), ("DB_MYSQL_SSL_CERT", "cert"), ("DB_MYSQL_SSL_KEY", "key")]
               if env.get(key)}
        if sslmode in {"VERIFY_CA", "VERIFY_IDENTITY"} and not ssl.get("ca"):
            raise ImproperlyConfigured("DB_MYSQL_SSL_CA est requis pour vérifier le certificat du serveur.")
        if bool(ssl.get("cert")) != bool(ssl.get("key")):
            raise ImproperlyConfigured("DB_MYSQL_SSL_CERT et DB_MYSQL_SSL_KEY doivent être renseignés ensemble.")
        if ssl and sslmode == "DISABLED":
            raise ImproperlyConfigured("MySQL : les certificats SSL sont incompatibles avec le mode DISABLED.")
        options = {"charset": "utf8mb4", "sql_mode": "STRICT_TRANS_TABLES",
                   "isolation_level": "read committed", "ssl_mode": sslmode,
                   "connect_timeout": integer(env, "DB_TIMEOUT_SECONDS", 20, 1)}
        if ssl:
            options["ssl"] = ssl
        return {"ENGINE": "django.db.backends.mysql",
                "NAME": unquote(parsed.path.lstrip("/")), "USER": unquote(parsed.username),
                "PASSWORD": unquote(parsed.password or ""), "HOST": parsed.hostname, "PORT": port or 3306,
                "CONN_MAX_AGE": integer(env, "DB_CONN_MAX_AGE", 60),
                "CONN_HEALTH_CHECKS": True, "OPTIONS": options}
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
            "PASSWORD": unquote(parsed.password or ""), "HOST": parsed.hostname, "PORT": port or 5432,
            "CONN_MAX_AGE": integer(env, "DB_CONN_MAX_AGE", 60),
            "CONN_HEALTH_CHECKS": True, "OPTIONS": options}
