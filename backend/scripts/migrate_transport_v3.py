"""Migration Transport v3 — réception physique des PO intersociétés
(tables reception_inter / ligne_reception_inter). Idempotent.

Usage : python -m scripts.migrate_transport_v3
"""
from __future__ import annotations

from app import models          # noqa: F401
from app.database import Base, engine


def main() -> None:
    Base.metadata.create_all(engine)
    print("Migration Transport v3 terminee (reception_inter).")


if __name__ == "__main__":
    main()
