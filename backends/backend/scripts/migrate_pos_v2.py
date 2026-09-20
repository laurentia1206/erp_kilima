"""Migration POS v2 — à exécuter UNE FOIS sur une base existante.

Ajoute les colonnes remises/fidélité/avoirs et la table paiement_facture
sans toucher aux données. Idempotent : re-exécutable sans danger.

Usage (depuis le dossier backend) :
    python -m scripts.migrate_pos_v2
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401 — enregistre les tables dans Base.metadata
from app.database import Base, engine

AJOUTS = {
    "tiers": [("points_fidelite", "NUMERIC(18,2) DEFAULT 0")],
    "facture": [
        ("remise_totale", "NUMERIC(18,2) DEFAULT 0"),
        ("note", "VARCHAR"),
        ("origine_id", "CHAR(32) REFERENCES facture(id)"),
        ("pos_recu_usd", "NUMERIC(18,2)"),
        ("pos_monnaie_usd", "NUMERIC(18,2)"),
    ],
    "ligne_facture": [
        ("remise_pct", "NUMERIC(6,2) DEFAULT 0"),
        ("origine_ligne_id", "CHAR(32) REFERENCES ligne_facture(id)"),
    ],
}


def main() -> None:
    insp = inspect(engine)
    with engine.begin() as con:
        for table, colonnes in AJOUTS.items():
            existantes = {c["name"] for c in insp.get_columns(table)}
            for nom, ddl in colonnes:
                if nom not in existantes:
                    con.execute(text(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}"))
                    print(f"  + {table}.{nom}")
    # Nouvelles tables (paiement_facture…) : create_all ignore l'existant
    Base.metadata.create_all(engine)
    print("Migration POS v2 terminee.")


if __name__ == "__main__":
    main()
