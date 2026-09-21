"""Application core — démarrage : sauvegarde quotidienne de la base.

Filet de sécurité repris du main.py FastAPI : copie quotidienne de la base
SQLite au premier démarrage du jour (backups/kilima_dev_AAAAMMJJ.db, 14
conservées). Les données de test de Laurent ne doivent JAMAIS être perdues.
"""
from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from .audit_context import install
        install()
        try:
            from pathlib import Path

            from django.conf import settings
            from .backups import sauvegarder_sqlite

            if not settings.BACKUP_ON_STARTUP:
                return

            db = settings.DATABASES["default"]
            if "sqlite" not in db["ENGINE"]:
                return
            db_path = Path(db["NAME"])
            if not db_path.exists():
                return
            cible = sauvegarder_sqlite(db_path, settings.BACKUP_DIR)
            dossier = cible.parent
            anciennes = sorted(dossier.glob(f"{db_path.stem}_*.db"))
            for vieille in anciennes[:-settings.BACKUP_KEEP_COUNT]:
                vieille.unlink(missing_ok=True)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Échec de la sauvegarde quotidienne de la base.")
