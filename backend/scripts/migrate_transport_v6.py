"""Migration Transport v6 — unité d'emballage des courses (sacs, fûts, tonnes…).

Ajoute course.unite. Idempotent.
Usage : python -m scripts.migrate_transport_v6
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401
from app.database import Base, engine


def main() -> None:
    insp = inspect(engine)
    if "unite" not in {c["name"] for c in insp.get_columns("course")}:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE course ADD COLUMN unite VARCHAR DEFAULT 'tonnes'"))
        print("  + course.unite")
    Base.metadata.create_all(engine)
    print("Migration Transport v6 terminee.")


if __name__ == "__main__":
    main()
