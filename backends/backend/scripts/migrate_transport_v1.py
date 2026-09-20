"""Migration Transport & Intersociétés — tables flotte/courses/contrats/maintenance,
liaison des tiers aux sociétés du groupe et factures miroir.

Idempotent : re-exécutable sans danger.

Usage (depuis le dossier backend) :
    python -m scripts.migrate_transport_v1
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401 — enregistre les tables dans Base.metadata
from app.database import Base, engine

AJOUTS = {
    "tiers": [("societe_liee_id", "CHAR(32) REFERENCES societe(id)")],
    "facture": [("facture_liee_id", "CHAR(32) REFERENCES facture(id)")],
}


def main() -> None:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as con:
        for table, colonnes in AJOUTS.items():
            existantes = {c["name"] for c in insp.get_columns(table)}
            for nom, ddl in colonnes:
                if nom not in existantes:
                    con.execute(text(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}"))
                    print(f"  + {table}.{nom}")
    print("Migration Transport v1 terminee.")


if __name__ == "__main__":
    main()
