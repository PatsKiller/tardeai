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


def test_conflict_severity_and_review_completion_require_causal_readback():
    row = {"security_guid": "g", "stance": "HOLD", "conviction": 60, "as_of": NOW.isoformat(),
           "conflicts": [
               {"field": "stance", "severity": "P2", "resolved": False, "values": [{"source": "cio_decisions", "value": "HOLD", "at": "2026-10-24"},
                 {"source": "watch_review", "value": "ADD", "at": "2026-10-23"}]},
               {"field": "held", "severity": "P1", "resolved": False, "values": [{"source": "holdings", "value": True, "at": "2026-10-24"},
                 {"source": "watch_review", "value": False, "at": "2026-10-23"}]}],
           "research": {"review_lifecycle": {"status": "ANSWERED_PENDING_CIO", "request_id": "r", "research_id": "research-1"}}}
    doc = {"prospects": [row]}
    result = truth.conflicts_for("g", projection=doc, now=NOW)
    assert [r["severity"] for r in result["conflicts"]] == ["P1", "P2"]
    assert result["review"]["state"] == "awaiting_decision"
    assert all(c["blocks_action"] for c in result["conflicts"])
    review = row["research"]["review_lifecycle"]
    review.update(status="CONFLICT_RESOLVED", new_stance="HOLD", conflict_resolved_at=NOW.isoformat(), evidence_refs=["thesis-1", "v2"])
    for c in row["conflicts"]:
        c["resolved"] = True
    assert truth.conflicts_for("g", projection=doc)["review"]["resolution_proven"] is False
    review["readback_verification"] = "CIO-owned linked publication and canonical record agree"
    result = truth.conflicts_for("g", projection=doc)
    assert result["review"]["state"] == "decided" and all(c["resolved"] for c in result["conflicts"])


def test_guid_batch_never_uses_a_ticker_match_as_identity():
    doc = {"prospects": [{"security_guid": "known", "symbol": "A", "stance": "HOLD", "conviction": 70}]}
    def identity(symbol, **kw):
        return {"security_guid": "known", "identity_status": "CONFIRMED" if symbol == "A" else "UNRESOLVED"}
    result = truth.stances_for_symbols(["A", "B"], projection=doc, identity_resolver=identity, now=NOW)
    assert result["A"]["stance"] == "HOLD"
    assert result["B"]["stance"] is None and result["B"]["gap"]


def test_status_scorecard_and_observability_share_evaluations(tmp_path):
    status = {"as_of": NOW.isoformat(), "evaluations": [
        {"id": "hermes_research", "title": "Hermes", "status": "working", "verdict": "36 completions",
         "metrics": [{"label": "DeepSeek ok 24h", "value": 36}]}],
        "summary": {"working": 1, "degraded": 0, "blocked": 0, "dark": 0}}
    sc = truth.scorecard_payload(canonical_status=status, root=tmp_path, now=NOW)
    ob = truth.observability_payload(canonical_status=status, root=tmp_path, now=NOW)
    row = next(r for r in ob["scorecards"] if r["name"] == "Hermes / Research")
    assert row["status"] == sc["tiles"][0]["status"].upper() == "WORKING"
    assert row["metrics"] == sc["tiles"][0]["metrics"]


def test_header_holdings_risk_have_identical_totals_count_quote_and_stop_state(tmp_path, holdings):
    doc = truth.resolve(tmp_path, NOW, inputs={"holdings": holdings, "companies": {}, "policy": {}, "cio_status": {},
            "broker_stops": [{"account": "schwab_roth", "symbol": "SPCX", "status": "pending_activation", "stop_price": 90}],
            "approvals": [{"kind": "paper", "count": 3}], "paper_stats": {"closed": 10, "wins": 5}})
    header = truth.overview_payload({"periods": {"1D": {"change": 123}}}, document=doc)
    book = truth.holdings_payload({"holdings": [{"symbol": "SPCX", "account": "schwab_roth", "price": 777}]}, document=doc)
    risk = truth.risk_payload(document=doc)
    assert header["position_count"] == book["position_count"] == risk["position_count"] == 3
    assert header["portfolio_value"] == book["total_value"] == 3699
    assert header["today_change"] == header["periods"]["1D"]["change"] == book["today_change"] == -57
    a = next(r for r in book["holdings"] if r["symbol"] == "SPCX" and r["account_id"] == "schwab_roth_ira")
    b = next(r for r in risk["positions"] if r["symbol"] == "SPCX" and r["account_id"] == "schwab_roth_ira")
    assert a["price"] == b["price"] == 100
    assert a["stop_state"] == b["stop_state"] == "pending_activation"


def test_basis_does_not_present_partial_lots_as_complete_profit():
    p = {"symbol": "AMANX", "shares": 100, "price": 50.72, "market_value": 5072,
         "cost_basis": 1229.8, "basis_partial": True}
    assert truth.basis_for(p)["unrealized_pl_pct"] is None
    p["cost_basis_broker"] = 5072
    result = truth.basis_for(p)
    assert result["cost_basis_usd"] == 5072 and result["unrealized_pl_usd"] == 0
    assert result["conflicts"]


def test_sale_proceeds_are_never_realized_profit_without_full_fifo_basis():
    event = {"symbol": "NAVN", "account": "schwab_rollover", "shares_sold": 100,
             "sold_at": "2026-10-23T15:00:00-04:00", "proceeds_usd": 13009.73, "realized_pnl": 13009.73}
    assert truth.realized_for_sale(event, round_trips=[])["realized_pnl"] is None
    rows = [{"symbol": "NAVN", "account": "schwab_rollover_ira", "qty": 100, "entry_price": 100,
             "net_pnl": 3009.73, "exit_time": event["sold_at"]}]
    result = truth.realized_for_sale(event, round_trips=rows)
    assert result["realized_pnl"] == 3009.73 and result["cost_basis_usd"] == 10000
    rows[0]["qty"] = 50
    assert truth.realized_for_sale(event, round_trips=rows)["realized_pnl"] is None


def test_execution_display_uses_flags_without_changing_authority():
    payload = {"live_unlocked": False, "armed_for_execution": True, "execution_model": "ENABLED"}
    result = truth.execution_status(payload)
    assert result["execution_display_status"] == "locked" and result["armed_for_execution"] is False
    assert "ENABLED" not in result["execution_model"]
    assert payload["armed_for_execution"] is True


def test_empty_named_tree_never_creates_store_directories(tmp_path):
    before = list(tmp_path.rglob("*"))
    doc = truth.resolve(tmp_path, NOW)
    assert doc["positions"]["loss_at_stop_usd"] is None
    assert doc["stops"]["active_count"] is None
    assert list(tmp_path.rglob("*")) == before


def test_engine_inputs_use_oldest_material_time_and_reject_naive_time(holdings, tmp_path):
    row = {"security_guid": "g", "symbol": "SPCX", "stance": "ADD", "conviction": 70,
           "as_of": NOW.isoformat(), "evidence_at": NOW.isoformat(), "conviction_components": {
               "thesis": {"value": 70, "weight": 0.5, "source": "thesis", "evidence_at": "2026-09-01T12:00:00Z"},
               "quote": {"value": 80, "weight": 0.5, "source": "quote", "evidence_at": NOW.isoformat()}}}
    for p in holdings["holdings"]:
        if p["symbol"] == "SPCX":
            p["security_guid"] = "g"
    doc = truth.resolve(tmp_path, NOW, inputs={"holdings": holdings, "companies": {}, "cio_status": {}, "policy": {}, "broker_stops": []})
    result = truth.security_inputs_for("g", document=doc, projection={"prospects": [row]}, now=NOW)
    assert result["canonical"]["as_of"] == "2026-09-01T12:00:00+00:00"
    assert result["context"]["held"] is True
    row["conviction_components"]["thesis"]["evidence_at"] = "2026-09-01T12:00:00"
    result = truth.security_inputs_for("g", document=doc, projection={"prospects": [row]}, now=NOW)
    assert result["canonical"]["as_of"] is None and result["gap"]


def test_unified_approval_projection_is_never_added_to_legacy_counts():
    unified = {"total": 7, "by_type": {"grant": 3, "trade": 4}, "source": "operator queue",
               "as_of": NOW.isoformat(), "stale": False, "gap": None}
    result = truth.approvals_for(projection=unified, rows=[{"kind": "paper", "count": 38}], now=NOW)
    assert result == unified
    assert result is not unified


def test_financial_queue_items_keep_source_ids_and_explicit_refs_only():
    def query(sql, params=None, **kw):
        assert sql.lstrip().startswith("SELECT")
        if "FROM action_queue" in sql:
            return [{"id": 1, "recommendation_id": "rec-1", "symbol": "SPCX", "status": "pending"}]
        if "FROM paper_trade_proposals" in sql:
            return [{"id": 1, "symbol": "SPCX", "account": "alpaca_paper", "status": "PENDING"}]
        return []
    result = truth.financial_queue_items(db_query=query, now=NOW)
    assert result["complete"]
    assert {r["key"] for r in result["items"]} == {"action_queue:1", "paper_trade_proposals:1"}
    assert result["items"][0]["source_refs"][1] == {"source": "recommendation_registry", "id": "rec-1"}
    assert result["items"][1]["kind"] == "paper"
    assert all(r["can_decide"] is False for r in result["items"])
    assert truth.financial_queue_items(now=NOW)["complete"] is False


def test_financial_queue_truncation_is_a_gap_not_a_total():
    result = truth.financial_queue_items(now=NOW, limit=1,
        db_query=lambda sql, params=None, **kw: [{"id": 1}, {"id": 2}])
    assert result["complete"] is False and len(result["gaps"]) == 4


def test_projection_does_not_redate_positions_with_quote_clock(holdings, tmp_path):
    holdings["positions_built_at"] = "2026-10-23T19:00:00-04:00"
    doc = truth.resolve(tmp_path, NOW, inputs={"holdings": holdings, "companies": {}, "cio_status": {}, "policy": {}, "broker_stops": []})
    risk = truth.risk_payload(document=doc)
    header = truth.overview_payload({"pricing": {"canonical_total_value": 999}, "today_pnl": {"total_change": 999}}, document=doc)
    assert risk["positions_as_of"] == holdings["positions_built_at"]
    assert header["pricing"]["canonical_total_value"] == header["portfolio_value"]
    assert header["today_pnl"]["total_change"] == header["today_change"]
