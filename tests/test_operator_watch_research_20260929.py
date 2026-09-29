"""Operator watchlist-and-research asks stay on the queue."""

import threading
import time

from scripts.lib.operator_watch_research import (
    annotate_operator_watch,
    external_slot,
    fetch_operator_research_owed,
    lookup_operator_watch,
    pin_operator_research,
    research_reserve_config,
)


def test_owed_query_returns_symbols_and_fails_soft():
    def query(sql, params):
        assert "watch_directives" in sql
        assert params[0] == ["openclaw", "operator"]
        return [{"symbol": "nflx"}, {"symbol": ""}, ("AMD",)]

    assert fetch_operator_research_owed(query) == {"NFLX", "AMD"}

    def boom(*_a, **_k):
        raise RuntimeError("db")

    assert fetch_operator_research_owed(boom) == set()


def test_owed_research_keeps_a_dollar_reserve_after_the_sweep_cap():
    def query(sql, params):
        assert params[-1] == "NFLX"
        assert "watch_directives" in sql
        return [{"symbol": "NFLX"}]

    cfg = {"daily_cost_cap_usd": 0.30, "daily_soft_cap": 600}
    bumped = research_reserve_config(cfg, "nflx", query=query)
    assert bumped["daily_cost_cap_usd"] == 0.35
    assert cfg["daily_cost_cap_usd"] == 0.30
    assert research_reserve_config(cfg, "NFLX", query=lambda *_a, **_k: []) is cfg
    assert research_reserve_config(cfg, "", query=query) is cfg

    def boom(*_a, **_k):
        raise RuntimeError("db")

    assert research_reserve_config(cfg, "NFLX", query=boom) is cfg


def test_held_reservation_reaches_the_deepseek_budget_check():
    from scripts.lib.deepseek_client import _held_reservation_id

    try:
        from lib.provider_cost.context import cost_attribution
    except ImportError:
        from scripts.lib.provider_cost.context import cost_attribution

    assert _held_reservation_id("7") == "7"
    assert _held_reservation_id(None) in (None, "")
    with cost_attribution(reservation_id="42"):
        assert _held_reservation_id(None) == "42"


def test_operator_watch_is_a_research_membership():
    assert annotate_operator_watch(["HELD"], True) == ["HELD", "WATCH"]
    assert annotate_operator_watch(["watchlist"], True) == ["watchlist"]
    assert annotate_operator_watch([], False) == []

    def query(sql, params):
        assert params[1] == "NFLX"
        return [{"hit": 1}]

    assert lookup_operator_watch("nflx", query) is True
    assert lookup_operator_watch("", query) is False


def test_owed_names_sort_first_and_a_missing_name_is_added():
    due = [
        {"symbol": "AAA", "tier": "T1-WATCH", "score": 90},
        {"symbol": "NFLX", "tier": "T3-COLD", "score": 1},
    ]
    pinned = pin_operator_research(due, {"NFLX", "MSFT"})
    assert [r["symbol"] for r in pinned[:2]] == ["NFLX", "MSFT"]
    assert pinned[1]["tier"] == "T1-WATCH"
    assert pinned[0]["operator_research_owed"] is True
    assert pinned[1]["operator_research_owed"] is True
    assert pinned[2]["symbol"] == "AAA"
    assert "operator_research_owed" not in pinned[2]


def test_reserve_does_not_spend_the_shared_budget():
    assert external_slot(owed=True, spent=50, budget=50, reserved_used=0) == "reserve"
    assert external_slot(owed=True, spent=50, budget=50, reserved_used=10) == "blocked"
    assert external_slot(owed=False, spent=3, budget=50, reserved_used=0) == "budget"
    assert external_slot(owed=False, spent=50, budget=50, reserved_used=0) == "blocked"


def test_directive_create_returns_while_promotion_is_still_running(monkeypatch):
    import directive_promotion as dp

    started = threading.Event()
    release = threading.Event()

    def slow(*_a, **_k):
        started.set()
        release.wait(2)
        return {"status": "PROMOTED", "registered": True}

    monkeypatch.setattr(dp, "promote_directive_lead", slow)
    t0 = time.perf_counter()
    res = dp.promote_directive_lead_bounded("NFLX", 1311, "directive:Watchlist", "operator", budget_s=0.15)
    elapsed = time.perf_counter() - t0
    assert res["status"] == "DEFERRED_TO_CRON"
    assert res["deferred"] is True
    assert elapsed < 0.8
    release.set()
    started.wait(1)


def test_directive_create_returns_a_fast_promotion(monkeypatch):
    import directive_promotion as dp

    monkeypatch.setattr(
        dp,
        "promote_directive_lead",
        lambda *_a, **_k: {"status": "PROMOTED", "registered": True},
    )
    res = dp.promote_directive_lead_bounded("NFLX", 7, "directive:Watchlist", "operator", budget_s=2)
    assert res["status"] == "PROMOTED"
    assert res.get("deferred") is not True
