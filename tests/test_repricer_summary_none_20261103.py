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


# ── the WIRING (cc-deepseek-3's ordering analysis on new main, 2026-11-05T13:40Z) ─────────────────
# The helpers above can be perfect and the fix still not happen: main() has to call them. On main
# 1af9d5baf the Before/After lines are raw f-strings again, so a rebuilt document raises TypeError
# and exits 1 — the crash is still the first thing that happens. These two tests drive the real CLI
# path, because a helper-level suite stays green with the wiring reverted (measured: 5 passed).

import contextlib
import json

import pytest


def _state(tmp_path, **totals):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    doc = {
        "holdings": [{"symbol": "SPCX", "account": "ACCT_A", "shares": 300, "price": 174.0}],
        "portfolio_totals": {"total_value": 1_000_000, "day_change": None, **totals},
    }
    (state / "holdings.json").write_text(json.dumps(doc), encoding="utf-8")
    return state, state / "holdings.json"


def _no_lock(monkeypatch):
    """Keep the test hermetic: the shared holdings lock is a process-wide flock, not the property here."""
    from scripts.lib import holdings_write_lock as hl
    monkeypatch.setattr(hl, "holdings_write_lock", lambda: contextlib.nullcontext())


def test_the_cli_prints_unknown_and_refuses_a_degraded_document(tmp_path, monkeypatch, capsys):
    """The hazard case: totals on file, no account summaries, day_change null.

    Before the wiring the CLI died with TypeError before the guard could speak. Now the operator line
    prints `Day: unknown`, the refusal names its reason, the exit code is 3, and the bytes on disk are
    still the ones that were there — the guard provides explicitly what the crash provided by accident.
    """
    import portfolio_repricer as pr

    _no_lock(monkeypatch)
    state, target = _state(tmp_path)
    before = target.read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        pr.main([state])

    out = capsys.readouterr().out
    assert exit_info.value.code == 3, "a refused pass must exit 3"
    assert "Before: $1,000,000 | Day: unknown" in out, f"the safe summary line was not used: {out!r}"
    assert "REFUSED: no account summaries" in out, f"the refusal did not name its reason: {out!r}"
    assert target.read_bytes() == before, "a refused CLI pass must leave holdings.json byte-identical"


def test_the_cli_prints_the_computed_day_change_after_a_successful_reprice(tmp_path, monkeypatch, capsys):
    """The healthy case: the PRIOR day_change is unknown, the computed one is printed and written.

    `unknown` is a statement about the value on file, not about the pass — this is the assertion that
    keeps the two meanings apart in the operator's log.
    """
    import portfolio_repricer as pr

    _no_lock(monkeypatch)
    state, target = _state(tmp_path, total_value=1_000)

    def fake_reprice(portfolio, state_dir, stats=None):
        # ``stats`` is the caller-owned run summary main() hands to the lane run receipt (2026-11-07).
        out = json.loads(json.dumps(portfolio))
        out["portfolio_totals"]["day_change"] = 10.0
        if stats is not None:
            stats["holdings"] = len(out.get("holdings") or [])
        return out

    monkeypatch.setattr(pr, "reprice_portfolio", fake_reprice)
    pr.main([state])                       # no SystemExit on a healthy pass

    out = capsys.readouterr().out
    assert "Before: $1,000 | Day: unknown" in out, f"the prior value is not shown as unknown: {out!r}"
    assert "After: $1,000 | Day: $+10" in out, f"the computed value is not shown: {out!r}"
    assert json.loads(target.read_text())["portfolio_totals"]["day_change"] == 10.0
