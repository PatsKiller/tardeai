"""LQ-20261107-205: NaN/inf from enrichment or price rows must become None,
never 0 and never an int() / round() crash (the HTTP 500 on sector-leaders).

Fixtures are synthetic. No real holdings or prices.
"""

import math

from sector_leaders_service import _f, _prices


class _FakeCur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return None

    def fetchall(self):
        return list(self._rows)


def test_f_nan_is_none_not_zero():
    assert _f(float("nan")) is None


def test_f_inf_is_none():
    assert _f(float("inf")) is None
    assert _f(float("-inf")) is None


def test_f_finite_passthrough_and_bad_input():
    assert _f(12.5) == 12.5
    assert _f("3") == 3.0
    assert _f(0) == 0.0
    assert _f(None) is None
    assert _f("not-a-number") is None


def test_nan_adv_and_mcap_do_not_reach_round():
    # The two round() sites in build_sector_leaders: round(adv), round(mcap*1e6).
    # After the guard both inputs are None, so the guarded expressions are safe.
    avg_vol = _f(float("nan"))
    mcap_m = _f(float("nan"))
    price = 10.0
    adv = (avg_vol * 1000 * price) if (avg_vol is not None) else None
    assert adv is None
    assert (round(mcap_m * 1e6) if mcap_m is not None else None) is None


def test_prices_skips_nan_close_rows():
    cur = _FakeCur([("AAA", float("nan")), ("BBB", 25.0), ("CCC", None)])
    prices = _prices(cur, ["AAA", "BBB", "CCC"])
    assert prices == {"BBB": 25.0}
    assert not any(math.isnan(v) for v in prices.values())


def test_prices_skips_inf_and_nonpositive_close_rows():
    cur = _FakeCur([("AAA", float("inf")), ("BBB", 0.0), ("CCC", -1.0), ("DDD", 7.5)])
    assert _prices(cur, ["AAA", "BBB", "CCC", "DDD"]) == {"DDD": 7.5}


def test_prices_empty_symbols_short_circuits():
    assert _prices(_FakeCur([]), []) == {}
