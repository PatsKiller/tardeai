"""The repricer's pre-reprice summary must tolerate missing/corrupt totals.

Observed 2026-11-03 at `CURRENT/logs/portfolio_repricer_intraday.log` (11:00:03 ET run):

    print(f"Before: ${portfolio['portfolio_totals']['total_value']:,.0f} | "
          f"Day: ${portfolio['portfolio_totals']['day_change']:+,.0f}")
    TypeError: unsupported format string passed to NoneType.__format__

The holdings rebuild had written `portfolio_totals.day_change = null`, so every */15 run died
*before* `reprice_portfolio` ran and before any write -- the writer did not tolerate a missing
value (spec item C). The fix formats a missing/non-finite total as `unknown` and keeps going.
"""
from __future__ import annotations

from scripts.portfolio_repricer import _fetch_data_broker_quotes, _summary_amount, _summary_line


def test_missing_or_corrupt_totals_format_as_unknown():
    assert _summary_amount(None) == "unknown"
    assert _summary_amount("") == "unknown"
    assert _summary_amount("not-a-number") == "unknown"
    assert _summary_amount(float("nan")) == "unknown"
    assert _summary_amount(float("inf")) == "unknown"
    assert _summary_amount(float("-inf")) == "unknown"


def test_real_totals_keep_their_existing_shape():
    assert _summary_amount(1_252_051.05) == "$1,252,051"
    assert _summary_amount(847_552.75) == "$847,553"
    assert _summary_amount(-12.5, signed=True) == "$-12"
    assert _summary_amount(1234.6, signed=True) == "$+1,235"


def test_summary_line_survives_the_rebuilt_document():
    rebuilt = {"portfolio_totals": {"total_value": 1_252_051.05, "day_change": None}}
    assert _summary_line("Before", rebuilt) == "Before: $1,252,051 | Day: unknown"
    assert _summary_line("After", rebuilt) == "After: $1,252,051 | Day: unknown"
    assert _summary_line("Before", {}) == "Before: unknown | Day: unknown"
    assert _summary_line("Before", {"portfolio_totals": None}) == "Before: unknown | Day: unknown"


# ── data-broker quote supplement (operator dispatch ruling: Alpaca via the broker) ──────────────

def test_broker_quotes_map_into_the_reprice_shape():
    def reader(symbols):
        assert symbols == ["nvda", "V"]
        return {
            "NVDA": {"price": 207.35, "chg_pct": 2.5, "as_of": "2026-11-03T15:40:00Z",
                     "source": "data_broker.market_quotes:alpaca"},
            "V": {"price": None, "chg_pct": 1.0},
        }

    out = _fetch_data_broker_quotes(["nvda", "V"], None, batch_reader=reader)
    assert set(out) == {"NVDA"}  # the None price is skipped, not guessed
    rec = out["NVDA"]
    assert rec["price"] == 207.35
    assert rec["change_pct"] == 2.5
    assert rec["prev_close"] == round(207.35 / 1.025, 4)
    assert rec["source"].startswith("data_broker")


def test_broker_quotes_skip_non_positive_and_survive_a_failing_reader():
    assert _fetch_data_broker_quotes(["X"], None, batch_reader=lambda s: {"X": {"price": 0}}) == {}
    assert _fetch_data_broker_quotes(["X"], None, batch_reader=lambda s: {"X": {"price": -3}}) == {}
    assert _fetch_data_broker_quotes([], None) == {}

    def boom(symbols):
        raise RuntimeError("broker down")

    assert _fetch_data_broker_quotes(["X"], None, batch_reader=boom) == {}
