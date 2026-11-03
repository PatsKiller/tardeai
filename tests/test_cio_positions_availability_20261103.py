"""The CIO positions read path answers "are the positions available?" — not "is the day P&L complete?".

Operator list item 3 (2026-11-03): the Home Do-now source `cio_positions` and the page said "Current CIO positions
unavailable" while the canonical store held 26 priced positions. `cio_truth.resolve()` copied the PORTFOLIO's gap —
which on this payload reads "day P&L partial: 26 holding row(s) without a day change ... excluded" — into
`positions.gap`, and every consumer of `positions.gap` (Home's `answered` flag, the Risk desk) reads it as
"positions are missing". A partial day change is a fact about the P&L, not about availability.

These tests pin the separation: `positions.gap` answers availability; `positions.day_pl_gap` carries the coverage
fact; the portfolio keeps its own gap. Fixtures only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)


def _doc(rows):
    return {"last_repriced": "2026-11-03 10:42:01 ET", "generated_at": "2026-11-03 10:42:01 ET",
            "positions_built_at": "2026-11-03 10:40:00 ET", "reprice_source": "finviz_live", "holdings": rows}


def _row(symbol, shares=10, price=50.0, **kw):
    base = {"symbol": symbol, "account": "fixture_taxable", "shares": shares, "price": price,
            "market_value": round(shares * price, 2), "cost_basis": round(shares * price, 2)}
    base.update(kw)
    return base


def _resolve(rows):
    return truth.resolve(root=".", now=NOW, inputs={"holdings": _doc(rows), "do_now": None})


def test_positions_are_available_even_when_the_day_change_is_partial():
    # Two priced positions, neither carrying a day change: value and counts are known, TODAY is not.
    # One row carries a day change and one does not: TODAY is partial, the position set is complete.
    doc = _resolve([_row("ZZAA", day_change=12.5), _row("ZZBB", 4, 25.0)])
    positions = doc["positions"]
    assert len(positions["rows"]) == 2
    assert positions["gap"] is None, "a partial day P&L must not make the positions look unavailable"
    assert "day P&L partial" in (positions["day_pl_gap"] or {}).get("reason", ""), "the coverage fact still travels"
    assert positions["day_pl_gap"] == doc["portfolio"]["gap"]
    assert positions["stale"] is False


def test_an_empty_store_still_reports_positions_unavailable():
    positions = _resolve([])["positions"]
    assert positions["rows"] == []
    assert positions["gap"] == {"reason": "no positions in the canonical holdings store"}
    assert positions["day_pl_gap"] is None or isinstance(positions["day_pl_gap"], dict)


def test_an_unreadable_store_says_it_could_not_be_read(tmp_path):
    """cc3 BLOCK F1 (2026-11-03): a 0-byte or missing store says "no positions", which is the wrong sentence for the
    exact incident this item is about — the file could not be READ. Risk renders this reason verbatim."""
    d = tmp_path / "data" / "portfolios" / "state"
    d.mkdir(parents=True)
    (d / "holdings.json").write_text("", encoding="utf-8")          # the 2026-11-03 0-byte incident
    positions = truth.resolve(tmp_path, NOW)["positions"]
    assert positions["rows"] == []
    assert "could not be read" in positions["gap"]["reason"], positions["gap"]


def test_a_missing_store_says_it_could_not_be_read(tmp_path):
    positions = truth.resolve(tmp_path, NOW)["positions"]
    assert "could not be read" in positions["gap"]["reason"], positions["gap"]


def test_the_portfolio_keeps_its_own_partial_coverage_gap():
    doc = _resolve([_row("ZZAA", day_change=12.5), _row("ZZBB", 4, 25.0)])
    assert "day P&L partial" in (doc["portfolio"]["gap"] or {}).get("reason", ""), (
        "the aggregate's coverage gap must not be dropped to fix the positions section")
