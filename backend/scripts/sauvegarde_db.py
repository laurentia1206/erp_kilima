"""Sauvegarde / restauration de la base de développement (kilima_dev.db).

Une copie quotidienne est déjà faite automatiquement au démarrage du serveur
(backups/). Ce script permet en plus une sauvegarde manuelle horodatée avant
une opération risquée, et la restauration.

Usage (depuis le dossier backend) :
    python -m scripts.sauvegarde_db              # crée une sauvegarde horodatée
    python -m scripts.sauvegarde_db --lister     # liste les sauvegardes
    python -m scripts.sauvegarde_db --restaurer kilima_dev_20260723_181500.db
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "kilima_dev.db"
DOSSIER = BASE.parent / "backups"


def creer() -> None:
    if not BASE.exists():
        print("Aucune base kilima_dev.db a sauvegarder.")
        return
    DOSSIER.mkdir(exist_ok=True)
    cible = DOSSIER / f"kilima_dev_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(BASE, cible)
    print(f"Sauvegarde creee : {cible.name} ({cible.stat().st_size // 1024} Ko)")


def lister() -> None:
    if not DOSSIER.exists():
        print("Aucune sauvegarde.")
        return
    for f in sorted(DOSSIER.glob("kilima_dev_*.db")):
        print(f"  {f.name}  ({f.stat().st_size // 1024} Ko)")


def restaurer(nom: str) -> None:
    src = DOSSIER / nom
    if not src.exists():
        print(f"Introuvable : {src}")
        sys.exit(1)
    # on sauvegarde l'etat courant avant d'ecraser
    if BASE.exists():
        secours = DOSSIER / f"kilima_dev_avant_restauration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(BASE, secours)
        print(f"Etat courant mis de cote : {secours.name}")
    shutil.copy2(src, BASE)
    print(f"Base restauree depuis {nom}. Redemarrez le serveur.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        creer()
    elif args[0] == "--lister":
        lister()
    elif args[0] == "--restaurer" and len(args) > 1:
        restaurer(args[1])
    else:
        print(__doc__)
