"""Migration Transport v5 — référence producteur sur les commandes clients.

Ajoute devis.reference_producteur. Idempotent.
Usage : python -m scripts.migrate_transport_v5
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401
from app.database import Base, engine


def main() -> None:
    insp = inspect(engine)
    existantes = {c["name"] for c in insp.get_columns("devis")}
    if "reference_producteur" not in existantes:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE devis ADD COLUMN reference_producteur VARCHAR"))
        print("  + devis.reference_producteur")
    Base.metadata.create_all(engine)
    print("Migration Transport v5 terminee.")


if __name__ == "__main__":
    main()
