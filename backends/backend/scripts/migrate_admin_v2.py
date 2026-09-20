"""Migration Administration v2 — rôles personnalisés avec héritage de droits.

Ajoute role.herite_de. Idempotent.
Usage : python -m scripts.migrate_admin_v2
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401
from app.database import Base, engine


def main() -> None:
    insp = inspect(engine)
    existantes = {c["name"] for c in insp.get_columns("role")}
    if "herite_de" not in existantes:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE role ADD COLUMN herite_de VARCHAR"))
        print("  + role.herite_de")
    Base.metadata.create_all(engine)
    print("Migration Admin v2 terminee.")


if __name__ == "__main__":
    main()
