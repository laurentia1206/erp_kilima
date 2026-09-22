"""Démarrage Docker : connexion PostgreSQL avec encodage des identifiants."""
import os
import sys
from urllib.parse import quote


def configure():
    if not os.environ.get("DATABASE_URL"):
        user = quote(os.environ["POSTGRES_USER"], safe="")
        password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
        database = quote(os.environ["POSTGRES_DB"], safe="")
        os.environ["DATABASE_URL"] = f"postgresql://{user}:{password}@db:5432/{database}"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kilima.settings")


if __name__ == "__main__":
    configure()
    os.execvp(sys.argv[1], sys.argv[1:])
