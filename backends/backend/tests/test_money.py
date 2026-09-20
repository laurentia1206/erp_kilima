from decimal import Decimal

import pytest

from app.domain.money import to_usd, from_usd, quantize


def test_usd_inchange():
    assert to_usd("USD", 150) == Decimal("150.00")


def test_cdf_vers_usd():
    # 1 USD = 2800 CDF ; 280000 CDF = 100 USD
    assert to_usd("CDF", 280000, taux_usd=2800) == Decimal("100.00")


def test_usd_vers_cdf():
    assert from_usd("CDF", 100, taux_usd=2800) == Decimal("280000.00")


def test_cdf_sans_taux_erreur():
    with pytest.raises(ValueError):
        to_usd("CDF", 1000)


def test_taux_nul_erreur():
    with pytest.raises(ValueError):
        to_usd("CDF", 1000, taux_usd=0)


def test_arrondi_commercial():
    assert quantize("10.005") == Decimal("10.01")


def test_devise_inconnue():
    with pytest.raises(ValueError):
        to_usd("EUR", 10)
