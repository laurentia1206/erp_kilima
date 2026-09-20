"""Migration Transport v4 — confirmation des réceptions par le transporteur.

Ajoute reception_inter.statut / confirme_par / date_confirmation. Idempotent.
Usage : python -m scripts.migrate_transport_v4
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401
from app.database import Base, engine

AJOUTS = [
    ("statut", "VARCHAR DEFAULT 'confirmee'"),
    ("confirme_par", "CHAR(32) REFERENCES utilisateur(id)"),
    ("date_confirmation", "DATETIME"),
]


def main() -> None:
    insp = inspect(engine)
    existantes = {c["name"] for c in insp.get_columns("reception_inter")}
    with engine.begin() as con:
        for nom, ddl in AJOUTS:
            if nom not in existantes:
                con.execute(text(f"ALTER TABLE reception_inter ADD COLUMN {nom} {ddl}"))
                print(f"  + reception_inter.{nom}")
    Base.metadata.create_all(engine)
    print("Migration Transport v4 terminee.")


if __name__ == "__main__":
    main()
