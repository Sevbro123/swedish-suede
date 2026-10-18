import numpy as np
import pytest

from nhlmodel.odds.vig import american_to_decimal, american_to_implied, devig, overround, profit_per_unit


@pytest.mark.parametrize(
    "ml,dec",
    [(-110, 1 + 100 / 110), (100, 2.0), (-100, 2.0), (150, 2.5), (-200, 1.5)],
)
def test_american_to_decimal(ml, dec):
    assert american_to_decimal(ml) == pytest.approx(dec)


def test_implied_probability_known_values():
    assert american_to_implied(-150) == pytest.approx(0.6)
    assert american_to_implied(130) == pytest.approx(100 / 230)


def test_rejects_invalid_american_odds():
    with pytest.raises(ValueError):
        american_to_decimal(50)


def test_overround_standard_minus110_pair():
    # -110/-110: each side 110/210, total 1.047619 -> 4.76% margin
    assert overround(-110, -110) == pytest.approx(220 / 210 - 1)


def test_devig_symmetric_market_is_fifty_fifty():
    assert devig(-110, -110) == pytest.approx(0.5)
    assert devig(-110, -110, method="power") == pytest.approx(0.5)


@pytest.mark.parametrize("method", ["multiplicative", "power"])
def test_devig_probabilities_sum_to_one(method):
    h = np.array([-150, -250, 120, -105])
    a = np.array([130, 210, -140, -115])
    ph, pa = devig(h, a, method=method), devig(a, h, method=method)
    assert np.allclose(ph + pa, 1.0)
    assert np.all((ph > 0) & (ph < 1))


def test_multiplicative_devig_value():
    ph, pa = 0.6, 100 / 230
    assert devig(-150, 130) == pytest.approx(ph / (ph + pa))


def test_power_method_shades_longshot_more_than_multiplicative():
    # Power removes proportionally more margin from the longshot, so the favourite's fair prob is higher.
    assert devig(-250, 210, method="power") > devig(-250, 210)


def test_no_vig_market_is_unchanged():
    # +100/-100 has zero overround; both methods return the raw implied prob.
    assert overround(100, -100) == pytest.approx(0.0)
    assert devig(100, -100, method="power") == pytest.approx(0.5)


def test_profit_per_unit():
    assert profit_per_unit([-150, 130, 130], [True, True, False]) == pytest.approx([100 / 150, 1.3, -1.0])


def test_zero_edge_bets_lose_the_vig_in_expectation():
    # Fair prob from a -110/-110 market is 0.5; betting one side at -110 has EV = 0.5*(100/110) - 0.5 < 0.
    ev = 0.5 * (100 / 110) - 0.5
    assert ev == pytest.approx(-0.04545, abs=1e-4)
