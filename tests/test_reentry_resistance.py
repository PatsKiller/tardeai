from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lib.reentry_resistance as reentry_resistance
from lib.reentry_resistance import CACHE_KEY, compute_resistance, refresh_resistance_cache


def _no_holdings(monkeypatch):
    """The resistance universe now includes live holdings so the Portfolio table has a
    level to show. That reads holdings.json, so pin it empty to keep these cases about
    the exit/mandate scope rather than whatever is held today."""
    monkeypatch.setattr(reentry_resistance, "_holdings_symbols", set)


def series(values):
    start = dt.date(2026, 1, 1)
    return [(start + dt.timedelta(days=index), float(value)) for index, value in enumerate(values)]


def test_active_breakout_counts_only_closed_sessions_held_above():
    base = [100 + index * 0.1 for index in range(30)]
    prior_resistance = max(base[-20:])
    breakout = prior_resistance * 1.02
    values = base + [breakout, breakout * 1.01, breakout * 1.005]

    result = compute_resistance(series(values))

    assert result["state"] == "ABOVE"
    assert result["hold_days"] == 3
    assert result["hold_start"] == series(values)[-3][0].isoformat()
    assert result["resistance"] == round(prior_resistance, 4)
    assert result["distance_pct"] > 0


def test_latest_close_below_prior_resistance_is_not_a_hold():
    values = [100 + index for index in range(25)] + [120, 119, 118]

    result = compute_resistance(series(values))

    assert result["state"] in ("BELOW", "TESTING")
    assert result["hold_days"] == 0
    assert result["hold_start"] is None


def test_insufficient_history_is_unavailable_not_zero():
    result = compute_resistance(series([100, 101, 102]))

    assert result["state"] == "UNAVAILABLE"
    assert result["hold_days"] is None
    assert result["resistance"] is None


class FakeExecute:
    def __init__(self):
        self.saved = None
        self.start = dt.date(2026, 1, 1)

    def __call__(self, sql, params=(), fetch=None):
        normalized = " ".join(sql.split()).lower()
        if "select value from ui_prefs" in normalized:
            return {"value": {}}
        if "select distinct upper(symbol)" in normalized:
            return [{"symbol": "SCHG"}, {"symbol": "SCHD"}]
        if "from ticker_prices" in normalized:
            symbol = params[0]
            step = 0.8 if symbol == "SCHG" else 0.2
            return [
                {"price_date": self.start + dt.timedelta(days=index), "close_price": 100 + index * step}
                for index in range(90)
            ]
        if "insert into ui_prefs" in normalized:
            assert params[0] == CACHE_KEY
            self.saved = json.loads(params[1])
            return None
        raise AssertionError(f"unexpected SQL: {normalized}")


def test_refresh_persists_symbol_map_with_auditable_method(monkeypatch):
    _no_holdings(monkeypatch)
    ex = FakeExecute()

    payload = refresh_resistance_cache(ex)

    assert payload["symbol_count"] == 2
    assert set(payload["symbols"]) == {"SCHG", "SCHD"}
    assert ex.saved == payload
    # The method statement is auditable at the payload root rather than repeated on
    # every row — identical text on ~490 symbols was ~110 kB on a payload five desks
    # fetch. Rows must therefore NOT carry it, or the duplication silently returns.
    assert "closed-session hold only" in payload["method"]
    assert "closed-session break only" in payload["support_method"]
    assert payload["tolerance_pct"] == 0.5
    assert not any("method" in row for row in payload["symbols"].values())


def test_holdings_join_the_resistance_universe(tmp_path):
    """A held symbol needs a closed-session level for the Portfolio table. Cash sweeps
    and delisted CUSIP placeholders have no tradable series, so they must not enter."""
    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps({"holdings": [
        {"symbol": "SCHD"},
        {"symbol": "jepi"},
        {"symbol": "CASH", "is_cash": True},
        {"symbol": "44984F807"},
        {"symbol": ""},
    ]}))

    assert reentry_resistance._holdings_symbols(holdings) == {"SCHD", "JEPI"}
    # A missing or unreadable snapshot degrades to empty, never raises into the cron.
    assert reentry_resistance._holdings_symbols(tmp_path / "absent.json") == set()


def _walk(start: float, steps: list[float]) -> list[tuple[dt.date, float]]:
    """Daily closes from a start price and a list of per-session returns."""
    day = dt.date(2026, 1, 5)
    out, price = [], start
    for step in steps:
        price *= 1 + step
        out.append((day, round(price, 4)))
        day += dt.timedelta(days=1)
    return out


def test_scrub_drops_corrupt_bars_not_real_moves():
    """ticker_prices held NVDA closes of 0.66/0.18/0.05 between ~200 closes.

    Support is the minimum of a trailing window, so those bars became a five-cent
    "support level". The scrubber has to remove them while leaving an ordinary
    session alone — otherwise it would quietly rewrite real price history.
    """
    series = _walk(200.0, [0.0] * 60)
    corrupted = list(series)
    corrupted[30] = (corrupted[30][0], 0.66)
    corrupted[31] = (corrupted[31][0], 0.18)
    corrupted[32] = (corrupted[32][0], 0.05)

    cleaned, dropped = reentry_resistance.scrub_series(corrupted)

    assert len(dropped) == 3
    assert all(close > 100 for _, close in cleaned)
    # A clean series must survive untouched — no silent rewriting of real history.
    assert reentry_resistance.scrub_series(series) == (series, [])


def test_scrub_keeps_a_sustained_decline():
    """A real collapse is not a corrupt tick: the rolling median follows it down."""
    series = _walk(100.0, [0.0] * 20 + [-0.08] * 25)

    cleaned, dropped = reentry_resistance.scrub_series(series)

    assert dropped == []
    assert cleaned == series


def test_rsi_matches_wilder_and_brackets_trend():
    """Wilder RSI over the same closed-session series the levels already read."""
    assert reentry_resistance.compute_rsi(_walk(50.0, [0.01] * 40))["rsi"] > 90
    assert reentry_resistance.compute_rsi(_walk(50.0, [-0.01] * 40))["rsi"] < 10
    # Too little history is UNAVAILABLE, never a fabricated midpoint.
    assert reentry_resistance.compute_rsi(_walk(50.0, [0.01] * 5))["rsi"] is None


def test_rsi_suppressed_on_unadjusted_split_but_not_on_a_coverage_hole():
    """DJTU jumped +869% in a session; AMD simply has 28 days missing.

    The first is an unadjusted corporate action that drives RSI to an extreme; the
    second is absent data, where the bars either side are not a one-day move. Only
    the former may suppress the number.
    """
    split = _walk(10.0, [0.0] * 30)
    split = split[:20] + [(day, close * 9) for day, close in split[20:]]
    assert reentry_resistance.compute_rsi(split)["rsi"] is None
    assert "unadjusted price gap" in reentry_resistance.compute_rsi(split)["rsi_reason"]

    hole = _walk(10.0, [0.0] * 20)
    tail = [(day + dt.timedelta(days=28), close * 1.5) for day, close in _walk(10.0, [0.0] * 20)]
    assert reentry_resistance.compute_rsi(hole + tail)["rsi"] is not None
