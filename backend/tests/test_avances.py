from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.avances import (
    compute_echeance, controle_equilibre, est_en_retard,
    beneficiaire_bloque, AvanceEnCours,
)

T0 = datetime(2026, 6, 22, 8, 0, 0)


def test_echeance_24h():
    assert compute_echeance(T0, 24) == datetime(2026, 6, 23, 8, 0, 0)


def test_echeance_2h():
    assert compute_echeance(T0, 2) == datetime(2026, 6, 22, 10, 0, 0)


def test_equilibre_conforme():
    r = controle_equilibre(100, [60, 40])
    assert r.conforme and r.ecart_usd == Decimal("0.00")
    assert not r.trop_percu and not r.complement_du


def test_trop_percu():
    # Avance 100, dépensé 70, rendu 30
    r = controle_equilibre(100, [70], solde_retourne_usd=30)
    assert r.conforme
    assert r.trop_percu
    assert r.solde_retourne_usd == Decimal("30.00")


def test_complement_du():
    # Avance 100, dépensé 130
    r = controle_equilibre(100, [130])
    assert r.complement_du
    assert r.ecart_usd == Decimal("-30.00")


def test_ecart_inexplique():
    # Avance 100, dépensé 80, rien rendu → écart 20 à expliquer
    r = controle_equilibre(100, [80])
    assert not r.conforme
    assert r.ecart_usd == Decimal("20.00")


def test_en_retard():
    av = AvanceEnCours(statut="a_justifier", echeance_justif=T0 + timedelta(hours=24))
    assert est_en_retard(av, T0 + timedelta(hours=25)) is True
    assert est_en_retard(av, T0 + timedelta(hours=1)) is False


def test_en_retard_mix_naif_aware():
    """L'échéance naïve (SQLite) comparée à un 'maintenant' aware ne doit pas planter."""
    from datetime import timezone
    naive = datetime(2026, 6, 22, 8, 0, 0)                       # sans fuseau (comme SQLite)
    aware_now = datetime(2026, 6, 22, 10, 0, 0, tzinfo=timezone.utc)
    av = AvanceEnCours(statut="a_justifier", echeance_justif=naive)
    assert est_en_retard(av, aware_now) is True                 # 10h > 8h
    aware_before = datetime(2026, 6, 22, 7, 0, 0, tzinfo=timezone.utc)
    assert est_en_retard(av, aware_before) is False


def test_justifiee_jamais_en_retard():
    av = AvanceEnCours(statut="justifiee", echeance_justif=T0)
    assert est_en_retard(av, T0 + timedelta(days=10)) is False


def test_blocage_avec_blocage_actif():
    assert beneficiaire_bloque(True, [], T0) is True


def test_blocage_avance_en_retard():
    av = AvanceEnCours(statut="a_justifier", echeance_justif=T0)
    assert beneficiaire_bloque(False, [av], T0 + timedelta(hours=1)) is True


def test_non_bloque():
    av = AvanceEnCours(statut="a_justifier", echeance_justif=T0 + timedelta(hours=24))
    assert beneficiaire_bloque(False, [av], T0 + timedelta(hours=1)) is False
