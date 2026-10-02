"""Advisory dependency clocks: independent producer clocks, derived lag list.

Pure-function tests over frozen rows; no desk build, DB, LLM, or broker.
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.api_v3_advisory import (  # noqa: E402
    DEPENDENCY_LANES,
    RUN_NOW_REFRESHES,
    _dependency_clock,
    _dependency_refresh,
)

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
SYNTH = "2026-10-02T15:50:00+00:00"
EXPECTED = {
    "advisory_synthesis", "technicals", "prices", "watch_intelligence", "reentry",
    "analyst_data", "research", "hermes_research", "durable_memory",
}


def _row(*, quote_as_of: str = "2026-10-02T15:55:00+00:00") -> dict:
    return {
        "watch_intelligence": {
            "quote": {"price_as_of": quote_as_of},
            "technicals": {"rsi": {"value": 30}},  # no technicals clock on the row
            "reviews": {"maria": {"completed_at": "2026-10-01T20:06:00+00:00"}, "cio": {"status": "NOT_RUN"}},
        },
        "decision_context": {"research_delta": {"evidence_as_of": "2026-10-02T14:00:00+00:00"}},
        "expand": {
            "analyst": {"target": 120.0, "target_as_of": "2026-09-30"},
            "evidence_items": [
                {"type": "technicals", "source": "indicator_snapshot", "as_of": "2026-10-02T15:45:14"},
                {"type": "external_research", "source": "hermes_external_research", "as_of": "2026-10-02 09:14:11"},
                {"type": "agent_opinion", "source": "watchlist_agent_results", "as_of": "2026-10-02 08:00:00"},
            ],
        },
    }


def _ts() -> dict:
    return {
        "synthesis": SYNTH,
        "reentry": "2026-10-02T15:45:00+00:00",
        "memory": "2026-10-02T14:15:50+00:00",
    }


TECH_PRODUCER = {
    "source_as_of": "2026-10-02T05:50:42-04:00",  # indicator_cache_refresh 05:45 ET run
    "producer": "indicator_cache_refresh (indicator_confluence_cache)",
    "source_ref": "db:indicator_confluence_cache.computed_at",
}


def _clocks(**kw):
    kw.setdefault("price_clock", {"as_of": "2026-10-02 11:58:00 ET", "clock_field": "last_repriced", "reprice_source": "finviz_live"})
    kw.setdefault("producer_clocks", {"technicals": TECH_PRODUCER})
    return _dependency_clock([_row()], _ts(), now=NOW, **kw)


def test_every_clock_has_contract_fields():
    clocks = _clocks()
    assert set(clocks) == EXPECTED
    for name, c in clocks.items():
        for key in ("name", "source_as_of", "producer", "source_ref", "age_seconds",
                    "freshness", "stale_after_seconds", "refreshed_by_run_now",
                    "next_scheduled_run", "next_scheduled_run_reason"):
            assert key in c, (name, key)
        assert c["freshness"] in {"FRESH", "STALE", "UNKNOWN"}
        assert isinstance(c["stale_after_seconds"], int) and c["stale_after_seconds"] > 0


def test_mixed_freshness_synthesis_fresh_technicals_stale():
    producer = dict(TECH_PRODUCER, source_as_of="2026-09-30T09:45:00+00:00")
    clocks = _clocks(producer_clocks={"technicals": producer})
    assert clocks["advisory_synthesis"]["freshness"] == "FRESH"
    assert clocks["technicals"]["freshness"] == "STALE"
    assert clocks["technicals"]["source_as_of"] == "2026-09-30T09:45:00+00:00"
    refresh = _dependency_refresh(clocks, {"state": "ok", "finished_at": SYNTH})
    assert refresh["status"] == "DEPENDENCIES_NOT_ALL_REFRESHED"
    assert refresh["all_dependencies_at_or_after_synthesis"] is False
    assert "technicals" in refresh["stale"]
    lags = [o["lag_seconds"] for o in refresh["older_than_synthesis"]]
    assert lags == sorted(lags, reverse=True)  # largest lag first
    labels = {o["name"]: o["label"] for o in refresh["older_than_synthesis"]}
    assert labels["technicals"] == "technicals 2d older than synthesis"


def test_price_tick_does_not_refresh_technicals():
    before = _clocks()
    tick = _dependency_clock(
        [_row(quote_as_of="2026-10-02T15:59:59+00:00")], _ts(), now=NOW,
        price_clock={"as_of": "2026-10-02 11:59:59 ET", "clock_field": "last_repriced"},
        producer_clocks={"technicals": TECH_PRODUCER},
    )
    assert tick["prices"]["source_as_of"] == "2026-10-02 11:59:59 ET"
    assert tick["prices"]["source_as_of"] != before["prices"]["source_as_of"]
    assert tick["technicals"]["source_as_of"] == before["technicals"]["source_as_of"]
    assert tick["technicals"]["age_seconds"] == before["technicals"]["age_seconds"]


def test_quote_and_snapshot_projection_time_never_feed_technicals():
    clocks = _dependency_clock([_row()], _ts(), now=NOW)  # no producer clock supplied
    assert clocks["technicals"]["source_as_of"] is None
    assert clocks["technicals"]["freshness"] == "UNKNOWN"
    # Prices still fall back to the watch quote — on their own clock.
    assert clocks["prices"]["source_as_of"] == "2026-10-02T15:55:00+00:00"


def test_derived_lag_label_minutes():
    producer = dict(TECH_PRODUCER, source_as_of="2026-10-02T15:08:00+00:00")
    refresh = _dependency_refresh(_clocks(producer_clocks={"technicals": producer}))
    labels = {o["name"]: o["label"] for o in refresh["older_than_synthesis"]}
    assert labels["technicals"] == "technicals 42m older than synthesis"
    assert "prices" not in labels  # 11:58 ET is after the 15:50Z synthesis
    assert refresh["summary"].count("older than synthesis") == len(labels)


def test_only_synthesis_is_refreshed_by_run_now():
    clocks = _clocks()
    assert {n for n, c in clocks.items() if c["refreshed_by_run_now"]} == {"advisory_synthesis"}
    refresh = _dependency_refresh(clocks)
    assert set(refresh["not_refreshed_by_run_now"]) == EXPECTED - {"advisory_synthesis"}


def test_run_now_audit_matches_execute_run_code_path():
    """If run-now starts refreshing a producer, RUN_NOW_REFRESHES must change."""
    from lib import advisory_desk_schedule as sched

    src = inspect.getsource(sched._execute_run)
    assert "build_advisory_desk(force=True" in src
    assert "enrich_advisory_with_opinions(" in src
    for producer in ("indicator", "reprice", "quote_refresh", "reentry", "hermes", "analyst", "memory", "watch"):
        assert producer not in src, producer
    assert RUN_NOW_REFRESHES == {name: name == "advisory_synthesis" for name in EXPECTED}


def test_watch_intelligence_and_hermes_are_independent_clocks():
    clocks = _clocks()
    assert clocks["watch_intelligence"]["source_as_of"] == "2026-10-01T20:06:00+00:00"
    # Evidence clocks are DB wall time in America/New_York (offset truncated).
    assert clocks["hermes_research"]["source_as_of"] == "2026-10-02T13:14:11+00:00"
    assert clocks["research"]["source_as_of"] == "2026-10-02T14:00:00+00:00"
    assert clocks["reentry"]["source_as_of"] == "2026-10-02T15:45:00+00:00"


def test_targetless_analyst_block_is_not_an_analyst_clock():
    row = _row()
    row["expand"]["analyst"] = {"target": None, "target_as_of": "2026-10-02"}
    clocks = _dependency_clock([row], _ts(), now=NOW)
    assert clocks["analyst_data"]["source_as_of"] is None
    assert clocks["analyst_data"]["freshness"] == "UNKNOWN"


def test_unknown_clock_listed_and_status_not_all_refreshed():
    clocks = _dependency_clock([], {"synthesis": SYNTH}, now=NOW)
    refresh = _dependency_refresh(clocks)
    assert refresh["status"] == "DEPENDENCIES_NOT_ALL_REFRESHED"
    assert set(refresh["unknown_clock"]) == EXPECTED - {"advisory_synthesis"}
    assert _dependency_refresh(_dependency_clock([], {}, now=NOW))["status"] == "SYNTHESIS_CLOCK_UNKNOWN"


def test_next_run_passthrough_and_undeclared_reason():
    next_runs = {
        "advisory_synthesis": {"next_run_at": "2026-10-05T13:15:00+00:00", "lane_id": "tradeai-advisory-shadow-session.timer"},
        "reentry": {"next_run_at": None, "reason": "no lane_registry entry declares this producer"},
    }
    clocks = _clocks(next_runs=next_runs)
    assert clocks["advisory_synthesis"]["next_scheduled_run"] == "2026-10-05T13:15:00+00:00"
    assert clocks["reentry"]["next_scheduled_run"] is None
    assert clocks["reentry"]["next_scheduled_run_reason"]
    assert DEPENDENCY_LANES["reentry"] == ()
    assert set(DEPENDENCY_LANES) == EXPECTED - {"advisory_synthesis"}


def test_stale_synthesis_reported_independently():
    old = (NOW - timedelta(days=40)).isoformat()
    clocks = _dependency_clock([_row()], {"synthesis": old}, now=NOW, producer_clocks={"technicals": TECH_PRODUCER})
    assert clocks["advisory_synthesis"]["freshness"] == "STALE"
    assert clocks["technicals"]["freshness"] == "FRESH"
