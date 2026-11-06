"""UNKNOWN_DAY_CHANGE_RENDERS_AS_WORDS_20261105 — None must never read as flat or crash.

codex-cloud P2 on #2588, 2026-11-05:

    ``scripts/portfolio_loader.py:699`` — a parsed Fidelity fund row now carries
    ``day_change = None``.  If that row is among the 25 largest holdings,
    ``llm_context_engine.get_portfolio_context()`` formats it with ``:+.0f`` and the
    ``TypeError`` handler discards the WHOLE portfolio block, not just the unknown row.

The same class of defect exists on the remaining producer and render paths:

  * the Schwab/Fidelity CSV import (``portfolio_server._parse_csv_to_import``) has no
    day-change column, yet it seeded every non-cash row with 0.0 — a number the
    provenance check cannot tell from a measured zero;
  * the transaction reconstructor seeded 0.0 when the price cache had no preceding price;
  * consumers coerced ``None`` with ``or 0`` (morning brief, promo prompts, dashboards)
    or crashed on it.

These tests pin: unknown renders as the word ``unknown`` everywhere, a genuine measured
0.00 still renders as zero, and no producer invents a number it did not measure.
"""
from __future__ import annotations

import json
import math

import pytest

from scripts import llm_context_engine
from scripts.lib import day_change_display as dcd


# ── the shared renderer ───────────────────────────────────────────────────────

def test_the_renderer_never_turns_unknown_into_a_zero():
    assert dcd.format_day_change(None) == "unknown"
    assert dcd.format_day_change("not-a-number") == "unknown"
    assert dcd.format_day_change(float("nan")) == "unknown"
    assert dcd.format_day_change(float("inf")) == "unknown"
    assert dcd.format_day_change(float("-inf")) == "unknown"
    assert dcd.format_day_change(True) == "unknown"
    assert dcd.format_day_change_pct(None) == "unknown"


def test_the_renderer_keeps_a_measured_zero_as_zero():
    """Positive control: the fix separates unknown from zero; it does not reject zero."""
    assert dcd.format_day_change(0.0) == "$+0"
    assert dcd.format_day_change(-0.0) == "$+0"
    assert dcd.format_day_change_pct(0.0) == "+0.00%"
    assert dcd.format_day_change(1234.6) == "$+1,235"
    assert dcd.format_day_change(-12.5) == "$-12"
    assert dcd.format_day_change(0.0, currency="") == "+0"


# ── P2: the LLM portfolio context survives one unknown row ────────────────────

def _holding(sym, mv, day_change, pct=1.0):
    return {"symbol": sym, "market_value": mv, "portfolio_pct": pct,
            "day_change": day_change, "day_change_pct": day_change}


def _write_holdings(tmp_path, holdings):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "holdings.json").write_text(json.dumps({
        "portfolio_totals": {"total_value": sum(h["market_value"] for h in holdings)},
        "holdings": holdings,
    }), encoding="utf-8")


def test_portfolio_context_renders_unknown_without_losing_the_other_holdings(tmp_path, monkeypatch):
    holdings = [_holding(f"AAA{i}", 1000 - i, 0.0) for i in range(30)]
    holdings[3]["day_change"] = None            # inside the top 25
    holdings[3]["day_change_pct"] = None
    holdings[28]["day_change"] = None           # outside the top 25: must not be consulted
    _write_holdings(tmp_path, holdings)
    monkeypatch.setattr(llm_context_engine, "PROJECT_ROOT", tmp_path)

    ctx = llm_context_engine.get_portfolio_context()

    assert "Portfolio error" not in ctx, ctx
    assert "AAA3" in ctx, "the unknown row was dropped with the whole portfolio block"
    assert "AAA4" in ctx, "one unknown row must not discard the measured rows"
    assert "day=unknown" in ctx, ctx
    # positive control: a genuinely measured 0.00 is still zero
    assert "AAA0: $1,000 (1.0%) day=+0" in ctx, ctx


def test_portfolio_context_does_not_crash_when_portfolio_pct_is_unknown(tmp_path, monkeypatch):
    holdings = [_holding("AAA0", 1000, 0.0), _holding("AAA1", 900, 1.5)]
    holdings[1]["portfolio_pct"] = None
    _write_holdings(tmp_path, holdings)
    monkeypatch.setattr(llm_context_engine, "PROJECT_ROOT", tmp_path)

    ctx = llm_context_engine.get_portfolio_context()

    assert "Portfolio error" not in ctx, ctx
    assert "AAA1" in ctx, ctx


# ── producer paths: no seeded zero where nothing was measured ─────────────────

def test_csv_import_leaves_a_non_cash_day_change_unknown():
    from scripts.portfolio_server import _parse_csv_to_import
    from scripts.portfolio_repricer import _day_change_coverage

    csv_text = (
        "Positions as of 04/30/2026\n"
        "Symbol,Description,Quantity,Price,Market Value\n"
        "AAA,Alpha Corp,10,5.00,50.00\n"
        "CASH,Cash & Cash Investments,100,1.00,100.00\n"
    )
    parsed = _parse_csv_to_import({"csv_text": csv_text,
                                   "import_type": "schwab_positions",
                                   "filename": "roth.csv"})
    rows = {h["symbol"]: h for h in parsed["holdings"]}
    assert rows["AAA"]["day_change"] is None, "the CSV has no day-change column to measure"
    assert rows["AAA"]["day_change_pct"] is None
    # Cash is a genuinely measured zero: it is held at $1.00 and does not move.
    assert rows["CASH"]["day_change"] == 0.0
    assert rows["CASH"]["day_change_pct"] == 0.0
    coverage = _day_change_coverage(parsed["holdings"])
    assert coverage["day_change_unmeasured_rows"] == 1
    assert coverage["day_change_measured_rows"] == 1


def test_reconstructor_without_a_previous_price_leaves_the_change_unknown(tmp_path):
    from scripts.schwab_reconstructor import reconstruct_schwab_positions

    tx = tmp_path / "tx.csv"
    tx.write_text(
        "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n"
        "04/01/2026,Buy,AAA,Alpha Corp,10,5.00,0,-$50.00\n",
        encoding="utf-8",
    )
    holdings, summary = reconstruct_schwab_positions(
        str(tx), "schwab_roth", "Roth IRA", "IRA", {})   # empty price cache: no previous price
    row = holdings[0]
    assert row["day_change"] is None
    assert row["day_change_pct"] is None
    assert summary["day_change"] is None
    assert summary["day_change_pct"] is None


def test_reconstructor_with_a_previous_price_is_measured(tmp_path):
    from scripts.schwab_reconstructor import reconstruct_schwab_positions

    tx = tmp_path / "tx.csv"
    tx.write_text(
        "Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n"
        "04/01/2026,Buy,AAA,Alpha Corp,10,5.00,0,-$50.00\n",
        encoding="utf-8",
    )
    cache = {"AAA": {"2026-04-29": 4.0, "2026-04-30": 5.0}}
    holdings, summary = reconstruct_schwab_positions(
        str(tx), "schwab_roth", "Roth IRA", "IRA", cache)
    row = holdings[0]
    assert row["day_change"] == pytest.approx(10.0)     # (5.00 - 4.00) * 10 shares
    assert row["day_change_pct"] == pytest.approx(25.0)
    assert summary["day_change"] == pytest.approx(10.0)


# ── render paths: unknown is a word, never 0 and never a crash ───────────────

def test_morning_brief_says_unknown_instead_of_flat():
    from scripts.portfolio_live_monitor import _morning_brief

    portfolio = {"as_of": "2026-11-05",
                 "portfolio_totals": {"total_value": 100_000.0,
                                      "day_change": None,
                                      "day_change_pct": None},
                 "holdings": []}
    text = _morning_brief(portfolio, {}, None)
    assert "unknown" in text.lower(), text
    assert "$+0" not in text, text


def test_holdings_health_prompt_says_unknown_instead_of_crashing():
    from scripts.holdings_llm_refresh import build_holdings_prompt

    prompt = build_holdings_prompt(
        {"symbol": "AAA", "shares": 10, "market_value": 50.0, "price": 5.0,
         "day_change": None, "account": "roth"},
        news=[], social=[], agents=[], technical={},
    )
    assert "chg=unknown" in prompt, prompt


def test_cio_portfolio_line_says_unknown_when_the_change_is_unknown():
    from scripts.cio_commands import _portfolio_day_line

    assert _portfolio_day_line({"day_change_pct": None}) == "   Day: unknown"
    assert _portfolio_day_line({"day_change_pct": 1.25}) == "   Day: +1.2%"


def test_day_change_resolver_keeps_unknown_unknown():
    from scripts.lib.holding_day_change import resolve_holding_day_change

    chg, pct = resolve_holding_day_change(
        {"symbol": "AAA", "market_value": 1000.0, "day_change": None,
         "day_change_pct": None},
        market_value=1000.0, price=10.0, stale_price=10.0,
    )
    assert chg is None, "an unmeasured holding must not become a flat $0"
    assert pct is None


def test_day_change_resolver_keeps_a_measured_zero_zero():
    from scripts.lib.holding_day_change import resolve_holding_day_change

    chg, pct = resolve_holding_day_change(
        {"symbol": "AAA", "market_value": 1000.0, "day_change": 0.0,
         "day_change_pct": 0.0},
        market_value=1000.0, price=10.0, stale_price=10.0,
    )
    assert chg == 0.0
    assert pct == 0.0


# ── D51: the API boundary must not turn an unmeasured day into a confident $0 ──
#
# cc-deepseek-5 delta BLOCK at d7d894a1c: holding_day_change leaves an unmeasured day at
# ``None``, then api_v2 summed it with ``or 0`` — /overview emitted ``today_change: 0`` and
# the TODAY figure read $0 on a day nobody measured. These drive the real handlers through
# their module boundary; they read no live store (every input is injected).

_UNKNOWN_DAY_ROWS = [
    {"symbol": "AAA", "account": "schwab_taxable", "shares": 10.0,
     "market_value": 1000.0, "price": 100.0, "day_change": None, "day_change_pct": None},
    {"symbol": "BBB", "account": "schwab_taxable", "shares": 5.0,
     "market_value": 500.0, "price": 100.0, "day_change": None, "day_change_pct": None},
]


def _holdings_doc(rows, *, stored_day_change=0.0):
    return {
        "as_of": "2026-11-05",
        "holdings": [dict(r) for r in rows],
        "portfolio_totals": {
            "total_value": sum(r["market_value"] for r in rows),
            "day_change": stored_day_change,
        },
    }


def _patched_overview(monkeypatch, rows, *, snap_day_change=None, stored_day_change=0.0):
    """Run the real overview() with every store injected."""
    import api_v2
    from lib import canonical_observation as co
    from lib.data_broker import portfolio_snapshot

    doc = _holdings_doc(rows, stored_day_change=stored_day_change)
    total = doc["portfolio_totals"]["total_value"]

    def fake_observe(name, **kwargs):
        payload = doc if name == "holdings.json" else {}
        env = co.ObservationEnvelope(
            dataset=name, source_identity=name,
            freshness={"status": "fresh", "age_hours": 0.0, "threshold_hours": 24.0},
        )
        return payload, env

    monkeypatch.setattr(co, "observe_state_file", fake_observe)
    monkeypatch.setattr(portfolio_snapshot, "get_portfolio_snapshot", lambda **kwargs: {
        "totals": {"total_value": total, "day_change": snap_day_change,
                   "day_change_pct": None},
        "top_movers": [], "sector_allocation": [],
    })
    monkeypatch.setattr(api_v2, "_load_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(api_v2, "_db_query", lambda *args, **kwargs: {})
    return api_v2.overview()


def _patched_holdings(monkeypatch, rows, *, stored_day_change=0.0):
    """Run the real portfolio_holdings() with every store injected."""
    import api_v2

    doc = _holdings_doc(rows, stored_day_change=stored_day_change)

    def fake_load_json(path, *args, **kwargs):
        return doc if str(path).endswith("holdings.json") else {}

    monkeypatch.setattr(api_v2, "_load_json", fake_load_json)
    monkeypatch.setattr(
        api_v2, "_db_query",
        lambda *args, **kwargs: {} if kwargs.get("fetch") == "one" else [],
    )
    return api_v2.portfolio_holdings()


def test_live_portfolio_day_change_is_unknown_when_no_row_was_measured():
    import api_v2

    assert api_v2._live_portfolio_day_change(_UNKNOWN_DAY_ROWS) is None, (
        "an all-unknown book was reported as a flat $0")


def test_live_portfolio_day_change_keeps_a_measured_value():
    import api_v2

    rows = [{"symbol": "AAA", "shares": 10.0, "market_value": 1000.0, "price": 100.0,
             "day_change": 12.5, "day_change_pct": 1.25}]
    assert api_v2._live_portfolio_day_change(rows) == 12.5


def test_live_portfolio_day_change_keeps_a_measured_zero():
    """Positive control: separating unknown from zero does not reject zero."""
    import api_v2

    rows = [{"symbol": "AAA", "shares": 10.0, "market_value": 1000.0, "price": 100.0,
             "day_change": 0.0, "day_change_pct": 0.0}]
    assert api_v2._live_portfolio_day_change(rows) == 0.0


def test_overview_emits_null_today_change_for_an_all_unknown_book(monkeypatch):
    out = _patched_overview(monkeypatch, _UNKNOWN_DAY_ROWS)

    assert out["today_change"] is None, (
        f"/overview published {out['today_change']!r} for a day no row measured")
    assert out["today_pct"] is None
    assert out["today_pnl"]["total_change"] is None


def test_overview_keeps_a_measured_day_change(monkeypatch):
    rows = [{"symbol": "AAA", "account": "schwab_taxable", "shares": 10.0,
             "market_value": 1000.0, "price": 100.0,
             "day_change": 12.5, "day_change_pct": 1.25}]
    out = _patched_overview(monkeypatch, rows, snap_day_change=12.5)

    assert out["today_change"] == pytest.approx(12.5)
    assert out["today_pnl"]["total_change"] == pytest.approx(12.5)


def test_overview_keeps_a_measured_zero(monkeypatch):
    """Positive control: a genuinely measured flat day still renders as zero."""
    rows = [{"symbol": "AAA", "account": "schwab_taxable", "shares": 10.0,
             "market_value": 1000.0, "price": 100.0,
             "day_change": 0.0, "day_change_pct": 0.0}]
    out = _patched_overview(monkeypatch, rows, snap_day_change=0.0)

    assert out["today_change"] == 0.0


def test_holdings_emits_null_today_change_for_an_all_unknown_book(monkeypatch):
    out = _patched_holdings(monkeypatch, _UNKNOWN_DAY_ROWS)

    assert out["today_change"] is None, (
        f"/portfolio/holdings published {out['today_change']!r} for a day no row measured")
    assert all(row.get("day_change") is None for row in out["holdings"])


def test_holdings_keeps_a_measured_day_change(monkeypatch):
    rows = [{"symbol": "AAA", "account": "schwab_taxable", "shares": 10.0,
             "market_value": 1000.0, "price": 100.0,
             "day_change": 12.5, "day_change_pct": 1.25}]
    out = _patched_holdings(monkeypatch, rows)

    assert out["today_change"] == pytest.approx(12.5)


def test_the_rendered_brief_says_unknown_not_zero_for_an_unmeasured_day():
    from scripts.portfolio_live_monitor import _morning_brief

    brief = _morning_brief(
        {"as_of": "2026-11-05",
         "portfolio_totals": {"total_value": 1500.0, "day_change": None,
                              "day_change_pct": None},
         "holdings": _UNKNOWN_DAY_ROWS},
        {}, None,
    )

    assert "unknown" in brief.lower(), brief
    assert "$+0" not in brief and "Day: $0" not in brief, brief
