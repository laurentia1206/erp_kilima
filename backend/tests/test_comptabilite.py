import pytest

from app.domain.comptabilite import LigneCompta, est_equilibree, totaux, assert_equilibree


def test_equilibree():
    lignes = [LigneCompta("D", "409", 100), LigneCompta("C", "571", 100)]
    assert est_equilibree(lignes)
    assert totaux(lignes) == (100, 100)


def test_desequilibree():
    lignes = [LigneCompta("D", "409", 100), LigneCompta("C", "571", 90)]
    assert not est_equilibree(lignes)
    with pytest.raises(ValueError):
        assert_equilibree(lignes)


def test_sans_credit():
    assert not est_equilibree([LigneCompta("D", "409", 100)])


def test_multi_lignes():
    # Justification : D charges 70 + D charges 30 / C avance 100
    lignes = [LigneCompta("D", "605", 70), LigneCompta("D", "615", 30), LigneCompta("C", "409", 100)]
    assert est_equilibree(lignes)
