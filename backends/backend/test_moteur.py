"""Banc d'essai du moteur d'écritures Django — s'exécute sur une COPIE de la
base (variable KILIMA_DB), jamais sur les données réelles.

    set KILIMA_DB=sqlite:///<copie> && python test_moteur.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

import django

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kilima.settings")
    assert os.environ.get("KILIMA_DB"), "KILIMA_DB obligatoire (copie de la base) !"
    django.setup()

    from core import comptabilite  # noqa: E402
    from core.models import Ecriture, LigneEcriture, Societe, Utilisateur  # noqa: E402

    soc = Societe.objects.filter(code="PLA").first()
    user = Utilisateur.objects.filter(email="dfi@kilima.cd").first()

    # état avant
    avant = Ecriture.objects.filter(societe_id=soc.id, numero__startswith="OD-").count()

    # 1. écriture équilibrée → doit passer, numéro séquencé dans le journal OD
    ecr = comptabilite.post_ecriture(
        soc.id, "OD", "Opérations diverses", "od", date.today(),
        "Test moteur Django — écart de caisse",
        [{"sens": "D", "compte": "658", "montant_usd": 12.5, "libelle": "Manquant test"},
         {"sens": "C", "compte": "571", "montant_usd": 12.5, "libelle": "Caisse test"}],
        "test_portage", "test", None, "TEST-DJANGO-001", user.id, statut="valide")
    lignes = list(LigneEcriture.objects.filter(ecriture_id=ecr.id).order_by("ordre"))
    print(f"1. Écriture créée : {ecr.numero} ({len(lignes)} lignes)")
    assert ecr.numero.startswith("OD-") and len(ecr.numero.split("-")[-1]) == 5
    assert lignes[0].sens == "D" and float(lignes[0].montant_usd) == 12.5
    assert lignes[0].devise_origine == "USD" and lignes[0].ordre == 0

    # 2. la ligne stockée a le même format que celles du moteur FastAPI (comparaison
    #    de la représentation SQLite d'une ligne existante vs la nouvelle)
    import sqlite3
    db_path = os.environ["KILIMA_DB"].split("///")[-1]
    con = sqlite3.connect(db_path)
    cols = [d[1] for d in con.execute("PRAGMA table_info(ligne_ecriture)")]
    ancienne = con.execute("SELECT * FROM ligne_ecriture WHERE ecriture_id != ? LIMIT 1",
                           (ecr.id.hex,)).fetchone()
    nouvelle = con.execute("SELECT * FROM ligne_ecriture WHERE ecriture_id = ? LIMIT 1",
                           (ecr.id.hex,)).fetchone()
    diff_null = [c for c, a, n in zip(cols, ancienne, nouvelle)
                 if (a is None) != (n is None) and c not in
                 ("tiers_id", "libelle_ligne", "lettrage_code", "montant_origine",
                  "taux_jour", "rapprochement_id")]
    print(f"2. Colonnes au même profil de nullité que FastAPI : {'OUI' if not diff_null else diff_null}")
    assert not diff_null

    # 3. écriture déséquilibrée → refus
    try:
        comptabilite.post_ecriture(
            soc.id, "OD", "Opérations diverses", "od", date.today(), "Déséquilibre",
            [{"sens": "D", "compte": "658", "montant_usd": 10.0},
             {"sens": "C", "compte": "571", "montant_usd": 9.0}],
            "test", "test", None, None, user.id)
        print("3. ERREUR : le déséquilibre est passé !")
        sys.exit(1)
    except Exception:
        print("3. Déséquilibre D≠C refusé : OUI")

    # 4. la balance reste équilibrée après l'insertion
    rows = con.execute("SELECT sens, SUM(montant_usd) FROM ligne_ecriture "
                       "WHERE societe_id = ? GROUP BY sens", (soc.id.hex,)).fetchall()
    tot = {s: round(m, 2) for s, m in rows}
    print(f"4. Balance société après insertion : D {tot.get('D')} / C {tot.get('C')} — "
          f"équilibrée : {tot.get('D') == tot.get('C')}")
    assert tot.get("D") == tot.get("C")

    # 5. numérotation : un 2e post dans le même journal incrémente de 1
    e2 = comptabilite.post_ecriture(
        soc.id, "OD", "Opérations diverses", "od", date.today(), "Seq test",
        [{"sens": "D", "compte": "658", "montant_usd": 1.0},
         {"sens": "C", "compte": "571", "montant_usd": 1.0}],
        "test", "test", None, None, user.id)
    n1, n2 = int(ecr.numero.split("-")[-1]), int(e2.numero.split("-")[-1])
    print(f"5. Séquence journal OD : {ecr.numero} → {e2.numero} (delta {n2 - n1})")
    assert n2 == n1 + 1

    print("\\nMOTEUR DJANGO VALIDE — 5/5 contrôles passés (sur copie de base).")


if __name__ == "__main__":
    main()
