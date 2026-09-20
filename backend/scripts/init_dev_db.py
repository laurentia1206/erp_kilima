"""Initialise la base de DÉVELOPPEMENT (SQLite) et la remplit de données démo.

Usage (depuis le dossier backend) :
    python -m scripts.init_dev_db

Recrée les tables (DROP + CREATE) puis amorce rôles, société PLANET, paliers,
comptes, caisse, bénéficiaire et utilisateurs de démonstration.
ATTENTION : efface les données existantes — réservé au développement.
"""
from __future__ import annotations

import sys

from app.database import Base, SessionLocal, engine
from scripts.seed_demo import seed_demo


def main() -> None:
    # GARDE-FOU : la base contient les donnees de test reelles de Laurent.
    # Toute reinitialisation exige une confirmation explicite.
    if "--je-confirme-effacer" not in sys.argv:
        print("REFUS : ce script EFFACE TOUTE la base (societes, agents, ecritures...).")
        print("Les donnees de test doivent etre conservees entre les sessions.")
        print("Pour reinitialiser malgre tout :")
        print("    python -m scripts.sauvegarde_db          (d'abord une sauvegarde !)")
        print("    python -m scripts.init_dev_db --je-confirme-effacer")
        sys.exit(1)
    print("[1/2] Recreation des tables...")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        ids = seed_demo(s)
    print("[2/2] Base de developpement prete.")
    print(f"  Societe PLANET : {ids['societe_id']}")
    print(f"  Caisse         : {ids['caisse_id']}")
    print(f"  Beneficiaire   : {ids['beneficiaire_id']}")
    print(f"  Mot de passe   : {ids['password']}")
    print("  Utilisateurs   :")
    for role, email in ids["users"].items():
        print(f"    - {email}  ({role})")


if __name__ == "__main__":
    main()
