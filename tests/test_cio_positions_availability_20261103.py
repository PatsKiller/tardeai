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


def test_a_wrong_shaped_store_is_unreadable_not_empty(tmp_path):
    """cc2 second review (2026-11-03): valid JSON with the wrong shape is the third variant of the same lie.

    A document with no `holdings` member, or one whose `holdings` is not a list, is not an empty book — we could not
    read a position set out of it at all."""
    d = tmp_path / "data" / "portfolios" / "state"
    d.mkdir(parents=True)
    for name, body in (("no holdings key", '{"positions": [], "portfolio_totals": {}}'),
                       ("holdings is not a list", '{"holdings": "not a list"}'),
                       ("top level is an array", '[]'),
                       ("top level is a string", '"nope"'),
                       # claude-lead review (2026-11-05): a list of non-object rows is the same lie as a
                       # non-list, and `portfolio_for` would raise on it if it were handed through.
                       ("holdings holds non-object rows", '{"holdings": [1, "row"]}')):
        (d / "holdings.json").write_text(body, encoding="utf-8")
        gap = truth.resolve(tmp_path, NOW)["positions"]["gap"]
        assert "could not be read" in gap["reason"], (name, gap)


def test_caller_supplied_non_object_rows_and_none_are_unreadable_not_a_crash():
    """The `holdings` input path (tests/replay) bypasses `load_store`, so it must check the shape too.

    Before the guard, `inputs={"holdings": None}` reached `portfolio_for(None)` (AttributeError) and a list of
    non-object rows reached `row.get(...)` — a 500 on the Risk page, and the wrong sentence either way."""
    for supplied in (None, {"holdings": [1, "row"]}, [], "not a document"):
        positions = truth.resolve(root=".", now=NOW, inputs={"holdings": supplied, "do_now": None})["positions"]
        assert positions["rows"] == [], supplied
        assert "could not be read" in positions["gap"]["reason"], (supplied, positions["gap"])


def test_a_day_pl_gap_is_not_a_clock_gap():
    """claude-lead review (2026-11-05): `positions.day_pl_gap` used to be the PORTFOLIO's gap, which also carries
    holdings-value and clock reasons. A full day-change set over a document with no clock is AVAILABLE positions
    with a clock gap on the aggregate — it is not a day-P&L coverage gap, and saying so would assert a cause the
    positions section did not measure."""
    rows = [_row("ZZAA", day_change=1.0), _row("ZZBB", day_change=-2.0)]
    doc = truth.resolve(root=".", now=NOW,
                        inputs={"holdings": {"holdings": rows}, "do_now": None})  # readable shape, no clocks
    positions = doc["positions"]
    assert positions["gap"] is None, "a readable position set is available"
    assert "clock" in (doc["portfolio"]["gap"] or {}).get("reason", ""), (
        "the aggregate's own clock gap must still travel on the portfolio", doc["portfolio"]["gap"])
    assert positions["day_pl_gap"] is None, (
        "a clock gap is not a day-P&L coverage gap", positions["day_pl_gap"])


def test_a_readable_empty_list_is_the_only_no_positions_case(tmp_path):
    d = tmp_path / "data" / "portfolios" / "state"
    d.mkdir(parents=True)
    (d / "holdings.json").write_text('{"holdings": [], "portfolio_totals": {}}', encoding="utf-8")
    gap = truth.resolve(tmp_path, NOW)["positions"]["gap"]
    assert gap == {"reason": "no positions in the canonical holdings store"}, gap


def test_the_portfolio_keeps_its_own_partial_coverage_gap():
    doc = _resolve([_row("ZZAA", day_change=12.5), _row("ZZBB", 4, 25.0)])
    assert "day P&L partial" in (doc["portfolio"]["gap"] or {}).get("reason", ""), (
        "the aggregate's coverage gap must not be dropped to fix the positions section")
