"""Market Risk Engine exposure + risk budget (DSN-20261031-market-risk-engine P2-T8, P2-T9). Synthetic book only:
made-up tickers ETF_A / STOCK_B / DEF_C and round numbers; no real positions, amounts or account labels."""

from datetime import datetime, timezone

import pytest

from scripts.lib.market_risk import exposure as ex
from scripts.lib.market_risk import risk_budget as rb
from scripts.lib.market_risk.contract import assert_no_behavior_fields

NOW = datetime(2026, 10, 29, 22, 15, tzinfo=timezone.utc)  # Thu 18:15 ET
BUDGET = rb.load_budget()
A1, A2 = ex.opaque_account("account-one"), ex.opaque_account("account-two")

PROFILES = {
    "ETF_A": {"sector": "Technology", "name": "Large-cap growth ETF"},
    "STOCK_B": {"sector": "Communication Services", "name": "single stock"},
    "DEF_C": {"sector": "Utilities", "name": "utility"},
}


def _book():
    return [
        {"symbol": "ETF_A", "account_key": A1, "market_value": 600.0, "mark": 36.0},
        {"symbol": "STOCK_B", "account_key": A1, "market_value": 300.0, "mark": 140.0},
        {"symbol": "DEF_C", "account_key": A2, "market_value": 50.0, "mark": 50.0},
        {"symbol": "CASH", "account_key": A2, "market_value": 50.0, "is_cash": True},
    ]


def _ctx(**over):
    positions = over.pop("positions", None) or _book()
    kw = dict(
        profiles=PROFILES,
        etf_lookthrough=None,
        stops=[
            {"symbol": "ETF_A", "level": 34.5},  # 4.2% below
            {"symbol": "STOCK_B", "level": 132.0},  # 5.7% below
            {"symbol": "DEF_C", "level": 40.0},  # 20% below
        ],
        earnings={"STOCK_B": "2026-11-05"},  # 5 sessions after Thu 10-29
        entries=[{"symbol": "STOCK_B", "opened_at": "2026-10-25"}],  # 4 days old
        now=NOW,
        policy=BUDGET,
    )
    kw.update(over)
    return ex.build_portfolio_context(positions, **kw)


def test_plan_example_shape_is_vulnerable_and_lifts_orange_to_red():
    ctx = _ctx()
    assert ctx.vulnerability is not None and ctx.vulnerability >= 70, ctx.note
    up = ex.proposed_uplift("ORANGE", ctx, BUDGET)
    assert up and up["to"] == "RED" and up["reason"] == "vulnerability"
    syms = {d["symbol"] for d in ctx.drivers}
    assert {"ETF_A", "STOCK_B"} <= syms
    b = {(r["scope"], r["budget"]) for r in ctx.budget_breaches}
    assert ("book", "growth_style_pct") in b and ("book", "recent_entry_in_event_window_pct") in b
    assert "ETF look-through UNKNOWN" in ctx.note


def test_blue_none_green_never_uplift_and_red_has_no_higher_tier():
    ctx = _ctx()
    for t in ("BLUE", "NONE", "GREEN", "RED"):
        assert ex.proposed_uplift(t, ctx, BUDGET) is None


def test_yellow_needs_80_but_budget_uplift_ratio_still_lifts_one_tier():
    ctx = _ctx()
    up = ex.proposed_uplift("YELLOW", ctx, BUDGET)
    assert up and up["to"] == "ORANGE"  # vulnerability >= 80, or a budget at 1.25x
    sectors = {"U_1": "Utilities", "S_2": "Consumer Staples", "H_3": "Healthcare", "E_4": "Energy"}
    calm = ex.build_portfolio_context(
        [{"symbol": s, "account_key": A2, "market_value": 25.0, "mark": 10.0} for s in sectors],
        profiles={s: {"sector": v} for s, v in sectors.items()},
        etf_lookthrough=None,
        stops=[{"symbol": s, "level": 8.0} for s in sectors],  # 20% below: not near
        earnings={},
        entries=[],
        now=NOW,
        policy=BUDGET,
    )
    assert calm.vulnerability < 20 and not calm.budget_breaches, calm  # sector 25% of a 30% limit only
    assert ex.proposed_uplift("YELLOW", calm, BUDGET) is None


def test_outputs_carry_no_behaviour_fields_and_no_account_labels():
    ctx = _ctx()
    payload = {"drivers": list(ctx.drivers), "budget_breaches": list(ctx.budget_breaches), "note": ctx.note}
    assert_no_behavior_fields(payload)
    text = repr(payload)
    assert "account-one" not in text and "34.5" not in text and "132.0" not in text  # no stop levels out
    for d in ctx.drivers:
        assert set(d) <= {"symbol", "reason", "stop_distance_pct"}


def test_unknown_inputs_are_none_not_zero():
    ctx = _ctx(stops=None, earnings=None, entries=None)
    assert "stops unknown" in ctx.note and "earnings calendar unknown" in ctx.note
    m = rb.measure(
        _book(),
        profiles=PROFILES,
        etf_lookthrough=None,
        stops=None,
        earnings=None,
        entries=None,
        event_symbols=None,
        today=NOW.date(),
        budget=BUDGET,
    )
    for k in ("unprotected_pct", "earnings_exposure_48h_pct", "event_cluster_exposure_pct", "single_theme_pct"):
        assert m["actual"][k] is None


def test_lookthrough_counts_ai_and_earnings_through_the_etf():
    look = {"ETF_A": {"MSFT": 0.12, "GOOGL": 0.08, "OTHER": 0.8}}
    m = rb.measure(
        _book(),
        profiles=PROFILES,
        etf_lookthrough=look,
        stops=[],
        earnings={"GOOGL": "2026-10-30"},
        entries=[],
        event_symbols=[],
        today=NOW.date(),
        budget=BUDGET,
    )
    assert m["actual"]["ai_basket_pct"] == pytest.approx(12.0)  # 600 * 0.20 of 1000
    assert m["actual"]["earnings_exposure_48h_pct"] == pytest.approx(4.8)


def test_load_inputs_with_reader_unavailable_is_unknown():
    def boom():
        raise OSError("store missing")

    ctx = ex.context_from_production(now=NOW, budget=BUDGET, store_loader=boom)
    assert ctx.vulnerability is None and "unknown" in ctx.note
    ctx = ex.context_from_production(now=NOW, budget=BUDGET, store_loader=lambda: {})
    assert ctx.vulnerability is None


def test_load_inputs_normalizes_and_hides_accounts():
    doc = {
        "as_of": "2026-10-29T20:00:00Z",
        "holdings": [
            {"symbol": "etf_a", "account": "account-one", "market_value": 600, "shares": 10, "canonical_mark": 60},
            {"symbol": "STOCK_B", "account": "account-one", "market_value": "bad"},
        ],
    }
    inp = ex.load_inputs(
        now=NOW,
        store_loader=lambda: doc,
        stops_loader=lambda now: [],
        profiles_loader=lambda syms: ({"ETF_A": {"sector": "Technology"}}, None),
    )
    assert inp["available"] and [p["symbol"] for p in inp["positions"]] == ["ETF_A"]
    assert inp["positions"][0]["account_key"].startswith("acct-") and "account-one" not in repr(inp)


def test_sessions_until_weekdays():
    d = NOW.date()  # Thursday
    assert rb.sessions_until("2026-10-29", d) == 0
    assert rb.sessions_until("2026-10-30", d) == 1
    assert rb.sessions_until("2026-11-02", d) == 2  # weekend skipped
    assert rb.sessions_until("2026-10-28", d) is None
