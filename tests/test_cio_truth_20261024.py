"""W1 read-only CIO truth: strict identity, consistent facts and visible gaps."""
from datetime import datetime, timezone
import json

import pytest

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)


def test_stance_is_guid_bound_and_preserves_lower_level_conflicts():
    doc = {"source": {"kind": "store"}, "prospects": [
        {"security_guid": "guid-spcx", "symbol": "SPCX", "stance": "ADD", "conviction": 73.3,
         "revision": 2, "as_of": NOW.isoformat(), "stale": False,
         "conflicts": [{"source": "decision_engine", "stance": "TRIM"}]},
        {"security_guid": "other-guid", "symbol": "SPCX", "stance": "SELL", "conviction": 10},
    ]}
    result = truth.stance_for("guid-spcx", projection=doc, now=NOW)
    assert (result["stance"], result["conviction"]) == ("ADD", 73.3)
    assert result["conflicts"][0]["source_b"]["value"] == "TRIM"
    assert result["conflicts"][0]["resolved"] is False
    result["conflicts"].clear()
    assert len(doc["prospects"][0]["conflicts"]) == 1
    missing = truth.stance_for("SPCX", projection=doc, now=NOW)
    assert missing["stance"] is None and missing["gap"]


def test_stance_uses_latest_version_and_keeps_expiry():
    doc = {"prospects": [
        {"security_guid": "g", "stance": "ADD", "conviction": 80, "revision": 1, "as_of": "2026-10-22"},
        {"security_guid": "g", "stance": "HOLD", "conviction": 60, "revision": 2, "as_of": "2026-10-23", "stale": True},
    ]}
    result = truth.stance_for("g", projection=doc, now=NOW)
    assert result["stance"] == "HOLD" and result["stale"] is True


def test_empty_guid_never_reads_a_store(monkeypatch):
    from scripts.lib.data_broker import cio_prospect
    monkeypatch.setattr(cio_prospect, "get_prospects", lambda **kw: (_ for _ in ()).throw(AssertionError("read")))
    assert truth.stance_for("", now=NOW)["gap"]


@pytest.fixture
def holdings():
    return {"last_repriced": NOW.isoformat(), "portfolio_totals": {"total_value": 999999, "day_change": 900},
            "holdings": [
                {"symbol": "SPCX", "account": "schwab_roth", "shares": 10, "market_value": 1000,
                 "price": 100, "day_change": -20, "as_of": NOW.isoformat()},
                {"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 20, "market_value": 2000,
                 "price": 100, "day_change": -40, "as_of": NOW.isoformat()},
                {"symbol": "EDGE", "account": "schwab_roth", "shares": 1, "market_value": 100,
                 "price": 100, "day_change": 1, "as_of": NOW.isoformat()},
                {"symbol": "SMALL", "account": "schwab_roth", "shares": 1, "market_value": 99,
                 "price": 99, "day_change": 2, "as_of": NOW.isoformat()},
                {"symbol": "123456789", "account": "schwab_roth", "shares": 0, "market_value": 0, "day_change": 0},
                {"symbol": "CASH", "account": "schwab_roth", "shares": 500, "market_value": 500, "is_cash": True},
            ]}


def test_holdings_are_one_value_clock_with_aliases_and_explicit_count(holdings):
    result = truth.portfolio_for(holdings, now=NOW)
    assert result["total_usd"] == 3699 and result["cash_usd"] == 500
    assert result["day_pl_usd"] == -57 and result["day_pl_pct"] < 0
    assert result["position_count"] == 3  # account+symbol; $100 boundary included
    assert result["position_counts"]["excluded_cusip_zero"] == 1
    assert result["position_counts"]["below_100"] == 1
    assert sum(r["total_usd"] for r in result["accounts"]) == result["total_usd"]
    assert sum(r["day_pl_usd"] for r in result["accounts"]) == result["day_pl_usd"]
    assert result["accounts"][1]["account_id"] == "schwab_roth_ira"
    assert holdings["holdings"][0].get("account_id") is None


def test_missing_holdings_or_day_value_is_unknown(holdings):
    assert truth.portfolio_for({}, now=NOW)["total_usd"] is None
    del holdings["holdings"][0]["day_change"]
    result = truth.portfolio_for(holdings, now=NOW)
    assert result["day_pl_usd"] is None and result["gap"]


@pytest.mark.parametrize("status,state,protected", [
    ("WORKING", "active", True), ("pending_activation", "pending_activation", False),
    ("FILLED", "filled", False), ("CANCELED", "none", False), (None, "unknown", False),
])
def test_stop_state_is_independent_of_stop_price(status, state, protected):
    rows = [{"account": "schwab_roth", "symbol": "SPCX", "stop_price": 90, "status": status,
             "captured_at": NOW.isoformat(), "order_id": "fixture-order"}]
    stop = truth.stop_for("schwab_roth_ira", "SPCX", broker_rows=rows, now=NOW)
    assert stop["stop_state"] == state and stop["broker_protected"] is protected
    assert truth.stop_for("schwab_rollover_ira", "SPCX", broker_rows=rows, now=NOW)["stop_price"] is None


def test_planned_stop_is_no_evidence_of_resting_protection():
    planned = {"SPCX:schwab_roth": {"account": "schwab_roth", "stop": 88, "set_date": "2026-10-24"}}
    stop = truth.stop_for("schwab_roth_ira", "SPCX", planned=planned, now=NOW)
    assert (stop["stop_source"], stop["stop_price"], stop["broker_protected"]) == ("planned", 88, False)


def test_filled_latest_order_never_resurrects_older_working_observation():
    rows = [{"account": "schwab_roth", "symbol": "SPCX", "order_id": "x", "stop_price": 90,
             "status": status, "captured_at": at} for status, at in
            [("WORKING", "2026-10-23T20:00Z"), ("FILLED", "2026-10-24T20:00Z")]]
    stop = truth.stop_for("schwab_roth", "SPCX", broker_rows=rows, now=NOW)
    assert stop["stop_state"] == "filled" and stop["broker_protected"] is False


def test_typed_counts_and_paper_denominator_are_complete():
    counts = truth.approvals_for(rows=[{"kind": "paper", "count": 38}, {"kind": "broker", "count": 2}], now=NOW)
    assert counts["total"] == 40 and counts["by_type"]["paper"] == 38
    assert truth.approvals_for(now=NOW)["total"] is None
    paper = truth.paper_win_rate(stats={"closed": 157, "wins": 77}, now=NOW)
    assert paper["win_rate_pct"] == 49.0 and paper["closed"] == 157
    assert truth.paper_win_rate(stats={"closed": 0, "wins": 0}, now=NOW)["win_rate_pct"] is None


def test_cash_waterfall_excludes_earmark_and_never_defaults_policy(holdings):
    result = truth.capital_for(truth.portfolio_for(holdings, now=NOW),
        plan={"cash_posture": {"reserve_usd": 100}, "capital_sources": {
            "earmarked_redeploy_usd": 300, "total_prospective_raise_usd": 50}}, now=NOW)
    assert result["investable_usd"] == 100 and result["prospective_raise_usd"] == 50
    assert result["policy_max_pct"] is None and result["gap"]


def test_resolve_private_tree_has_one_account_stop_and_value_model(tmp_path, holdings):
    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps(holdings))
    before = (state / "holdings.json").read_bytes()
    result = truth.resolve(tmp_path, NOW, inputs={"companies": {}, "policy": {}, "broker_stops": [
        {"account": "schwab_roth_ira", "symbol": "SPCX", "stop_price": 90,
         "status": "pending_activation", "captured_at": NOW.isoformat()}]})
    assert result["portfolio"]["total_usd"] == 3699
    spcx = [r for r in result["positions"]["rows"] if r["symbol"] == "SPCX"]
    assert spcx[0]["stop_state"] == "pending_activation" and spcx[1]["stop_state"] == "none"
    assert result["stops"]["pending_count"] == 1 and result["stops"]["active_count"] == 0
    assert result["regime"]["label"] is None and result["regime"]["gap"]
    assert before == (state / "holdings.json").read_bytes()
    assert sorted(p.name for p in state.iterdir()) == ["holdings.json"]


def test_portfolio_broker_uses_same_aggregate_instead_of_repricing(tmp_path, holdings, monkeypatch):
    from scripts.lib.data_broker import portfolio_snapshot as snapshot
    monkeypatch.setattr(snapshot, "STATE_DIR", tmp_path)
    (tmp_path / "holdings.json").write_text(json.dumps(holdings))
    # A conflicting quote may not change the canonical holdings valuation clock.
    (tmp_path / "finviz_quote_cache.json").write_text(json.dumps({"SPCX": {"price": 777, "day_change_pct": 12}}))
    result = snapshot.build_portfolio_snapshot()
    shared = truth.portfolio_for(holdings, now=NOW)
    assert result["totals"]["total_value"] == shared["total_usd"]
    assert result["totals"]["day_change"] == shared["day_pl_usd"]
    assert result["totals"]["total_cash"] == shared["cash_usd"]
    assert result["source"]["active_position_count"] == shared["position_count"]
