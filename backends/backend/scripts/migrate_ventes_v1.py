"""Migration module Ventes (devis → commande → livraison → facture → règlement).

Crée les tables devis / ligne_devis / livraison / ligne_livraison et la colonne
facture.devis_id. Idempotent : re-exécutable sans danger.

Usage (depuis le dossier backend) :
    python -m scripts.migrate_ventes_v1
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401 — enregistre les tables dans Base.metadata
from app.database import Base, engine

AJOUTS = {
    "facture": [("devis_id", "CHAR(32) REFERENCES devis(id)")],
}


def main() -> None:
    # Nouvelles tables d'abord (create_all ignore l'existant)
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as con:
        for table, colonnes in AJOUTS.items():
            existantes = {c["name"] for c in insp.get_columns(table)}
            for nom, ddl in colonnes:
                if nom not in existantes:
                    con.execute(text(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}"))
                    print(f"  + {table}.{nom}")
    print("Migration Ventes v1 terminee.")


if __name__ == "__main__":
    main()
