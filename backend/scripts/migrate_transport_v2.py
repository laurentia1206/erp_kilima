"""Migration Transport v2 — flux PO intersociété & réquisitions multiples.

- commande : destination, transporteur_societe_id, devis_lie_id
- devis    : commande_origine_id
- course   : commande_origine_id + camion_id devient NULLABLE (statut « demande »)
  → la table est reconstruite (SQLite ne sait pas relâcher un NOT NULL)
- course_requisition : nouvelle table ; reprend les liens course.requisition_id existants

Idempotent : re-exécutable sans danger.
Usage : python -m scripts.migrate_transport_v2
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app import models          # noqa: F401
from app.database import Base, engine

AJOUTS = {
    "commande": [("destination", "VARCHAR"),
                 ("transporteur_societe_id", "CHAR(32) REFERENCES societe(id)"),
                 ("devis_lie_id", "CHAR(32) REFERENCES devis(id)")],
    "devis": [("commande_origine_id", "CHAR(32) REFERENCES commande(id)")],
    "course": [("commande_origine_id", "CHAR(32) REFERENCES commande(id)")],
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

        # course.camion_id → NULLABLE : reconstruction de la table si nécessaire
        col = next(c for c in inspect(engine).get_columns("course") if c["name"] == "camion_id")
        if not col["nullable"]:
            con.execute(text("PRAGMA foreign_keys=OFF"))
            con.execute(text("ALTER TABLE course RENAME TO course_ancienne"))
            models.Course.__table__.create(con)
            cols = [c["name"] for c in inspect(engine).get_columns("course_ancienne")]
            communes = ", ".join(c for c in cols
                                 if c in {x.name for x in models.Course.__table__.columns})
            con.execute(text(f"INSERT INTO course ({communes}) SELECT {communes} FROM course_ancienne"))
            con.execute(text("DROP TABLE course_ancienne"))
            con.execute(text("PRAGMA foreign_keys=ON"))
            print("  ~ course reconstruite (camion_id nullable)")

    Base.metadata.create_all(engine)   # course_requisition

    # Reprise des liens réquisition existants dans la table d'association
    with engine.begin() as con:
        rows = con.execute(text(
            "SELECT id, requisition_id FROM course WHERE requisition_id IS NOT NULL")).all()
        for cid, rid in rows:
            deja = con.execute(text(
                "SELECT 1 FROM course_requisition WHERE course_id=:c AND requisition_id=:r"),
                {"c": cid, "r": rid}).first()
            if not deja:
                import uuid as _uuid
                con.execute(text(
                    "INSERT INTO course_requisition (id, course_id, requisition_id) "
                    "VALUES (:i, :c, :r)"), {"i": _uuid.uuid4().hex, "c": cid, "r": rid})
                print(f"  + lien course↔réquisition repris")
    print("Migration Transport v2 terminee.")


if __name__ == "__main__":
    main()
