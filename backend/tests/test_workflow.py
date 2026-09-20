from decimal import Decimal

import pytest

from app.domain.workflow import (
    Approbateur, Palier, resolve_palier, roles_requis, est_pleinement_approuve,
)

# Grille réelle du groupe (sortie de fonds)
PALIERS = [
    Palier(Decimal("0"), Decimal("1000"), (Approbateur("DFI", "seul"),), "≤1000"),
    Palier(Decimal("1000.01"), Decimal("10000"),
           (Approbateur("DFI"), Approbateur("DG"), Approbateur("ADMIN"), Approbateur("PRESIDENT")),
           "1001-10000"),
    Palier(Decimal("10000.01"), None, (Approbateur("PRESIDENT", "seul"),), ">10000"),
]


def test_palier_bas():
    p = resolve_palier(500, PALIERS)
    assert p.libelle == "≤1000"
    assert roles_requis(p) == ["DFI"]


def test_palier_borne_1000():
    assert resolve_palier(1000, PALIERS).libelle == "≤1000"


def test_palier_median():
    p = resolve_palier(5000, PALIERS)
    assert set(roles_requis(p)) == {"DFI", "DG", "ADMIN", "PRESIDENT"}


def test_palier_haut():
    p = resolve_palier(25000, PALIERS)
    assert roles_requis(p) == ["PRESIDENT"]


def test_aucun_palier():
    with pytest.raises(ValueError):
        resolve_palier(-5, PALIERS)


def test_dfi_seul_valide():
    p = resolve_palier(800, PALIERS)
    assert est_pleinement_approuve(p, {"DFI": "valide"}) is True


def test_conjoint_incomplet():
    p = resolve_palier(5000, PALIERS)
    assert est_pleinement_approuve(p, {"DFI": "valide", "DG": "valide"}) is False


def test_conjoint_complet():
    p = resolve_palier(5000, PALIERS)
    appro = {"DFI": "valide", "DG": "valide", "ADMIN": "valide", "PRESIDENT": "valide"}
    assert est_pleinement_approuve(p, appro) is True


def test_rejet_bloque():
    p = resolve_palier(5000, PALIERS)
    appro = {"DFI": "valide", "DG": "valide", "ADMIN": "rejete", "PRESIDENT": "valide"}
    assert est_pleinement_approuve(p, appro) is False


def test_president_seul():
    p = resolve_palier(25000, PALIERS)
    assert est_pleinement_approuve(p, {"PRESIDENT": "valide"}) is True
