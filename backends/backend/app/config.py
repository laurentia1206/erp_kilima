"""Configuration de l'application (variables d'environnement / .env)."""
from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dossier `backend/` — sert d'ancrage pour .env et la base SQLite de dev,
# afin que le serveur démarre depuis n'importe quel répertoire courant.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ERP KILIMA HOLDINGS"
    environment: str = "dev"

    # Base de données (PostgreSQL en prod ; SQLite en dev via .env)
    database_url: str = "postgresql+psycopg://kilima:kilima@localhost:5432/kilima_erp"

    # Sécurité / JWT
    secret_key: str = "CHANGER-EN-PRODUCTION"
    access_token_expire_minutes: int = 8 * 60
    algorithm: str = "HS256"

    @model_validator(mode="after")
    def _resolve_sqlite_path(self):
        """Rend un chemin SQLite relatif absolu (ancré sur backend/)."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            p = Path(self.database_url[len(prefix):])
            if not p.is_absolute():
                self.database_url = prefix + str((BACKEND_DIR / p).resolve())
        return self


settings = Settings()
