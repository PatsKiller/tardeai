#!/usr/bin/env python3
"""discovery_health as a first-class outcome-bus section (URDL Stage 4, Part G).

Pure/monkeypatched — no DB required. Covers: section field contract, graceful
stale/missing/corrupt handling (the bus build must never crash on discovery
problems), pause-state propagation, defensive DB extras, and the build_bus
wiring in hermes_outcome_feedback_agent.

    .venv/bin/python -m pytest tests/test_hermes_outcome_bus_discovery_health.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_outcome_feedback_agent as agent  # noqa: E402
from lib.hermes_outcome_bus import bus as bus_mod  # noqa: E402

SPEC_FIELDS = {
    "generated_at", "candidates_total", "new_7d", "by_type", "by_status",
    "duplicate_rate_7d", "false_ticker_rate_7d", "approval_rate",
    "promotions_7d", "feedback_counts", "do_no_harm", "top_sources",
    "top_trends", "noisy_sources", "recurring_duplicate_clusters",
    "paused", "pause_reason",
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_feed(tmp_path: Path, generated_at: str, **overrides) -> Path:
    latest = {
        "generated_at": generated_at, "candidates_total": 7, "new_7d": 5,
        "duplicate_rate_7d": 0.12, "false_ticker_rate_7d": 0.05,
        "approval_rate": 0.5, "promotions_7d": 2,
        "degraded": [], "recommendation": "steady",
    }
    latest.update(overrides)
    p = tmp_path / "hermes_discovery_outcome_feed.json"
    p.write_text(json.dumps({"version": "discovery-outcome-feed-v1",
                             "section": "discovery_health",
                             "latest": latest, "history": [latest]}))
    return p


def _write_card(tmp_path: Path, generated_at: str,
                recommendation: str = "steady",
                degraded=None, reasons=None) -> Path:
    card = {
        "version": "discovery-scorecard-v2",
        "generated_at": generated_at,
        "totals": {"candidates": 7},
        "by_status": {"DISCOVERED": 4, "READY_FOR_REVIEW": 3},
        "by_type": {"TOPIC_CANDIDATE": 5, "TREND_CANDIDATE": 2},
        "intake": {"new_candidates_7d": 5},
        "decisions": {"approval_rate": 0.5},
        "promotions": {"promotions_7d": 2},
        "feedback": {"approved": 3, "rejected": 1},
        "windows": {"last_7d": {"duplicate_rate": 0.12,
                                "false_ticker_rate": 0.05}},
        "do_no_harm": {"recommendation": recommendation,
                       "degraded": degraded or [],
                       "reasons": reasons or []},
    }
    p = tmp_path / "hermes_discovery_scorecard.json"
    p.write_text(json.dumps(card))
    return p


def _write_schedule(tmp_path: Path, **overrides) -> Path:
    cfg = {"enabled": True, "paused": False, "pause_reason": None,
           "do_no_harm_pause_respected": True}
    cfg.update(overrides)
    p = tmp_path / "hermes_discovery_schedule.json"
    p.write_text(json.dumps(cfg))
    return p


@pytest.fixture
def schedule_cfg(tmp_path, monkeypatch):
    p = _write_schedule(tmp_path)
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCHEDULE_CONFIG_PATH", p)
    return p


# ── field contract + freshness ───────────────────────────────────────────────

def test_fresh_section_has_all_spec_fields(tmp_path, schedule_cfg):
    now = datetime.now(timezone.utc)
    feed = _write_feed(tmp_path, _iso(now - timedelta(hours=1)))
    card = _write_card(tmp_path, _iso(now - timedelta(hours=1)))
    s = bus_mod.build_discovery_health_section(feed, card, now=now)

    assert s["status"] == "ok"
    missing = SPEC_FIELDS - set(s)
    assert not missing, f"discovery_health missing spec fields: {sorted(missing)}"
    assert s["candidates_total"] == 7 and s["new_7d"] == 5
    assert s["by_type"] == {"TOPIC_CANDIDATE": 5, "TREND_CANDIDATE": 2}
    assert s["by_status"] == {"DISCOVERED": 4, "READY_FOR_REVIEW": 3}
    assert s["duplicate_rate_7d"] == 0.12 and s["false_ticker_rate_7d"] == 0.05
    assert s["approval_rate"] == 0.5 and s["promotions_7d"] == 2
    assert s["feedback_counts"] == {"approved": 3, "rejected": 1}
    assert s["do_no_harm"] == {"recommendation": "steady", "degraded": [],
                               "reasons": []}
    assert s["paused"] is False and s["pause_reason"] is None
    assert "advisory" in s["advisory_note"]


def test_stale_feed_marks_section_stale_but_keeps_data(tmp_path, schedule_cfg):
    now = datetime.now(timezone.utc)
    feed = _write_feed(tmp_path, _iso(now - timedelta(hours=72)))
    card = _write_card(tmp_path, _iso(now - timedelta(hours=72)))
    s = bus_mod.build_discovery_health_section(feed, card, now=now)
    assert s["status"] == "stale"
    assert s["age_hours"] > bus_mod.DISCOVERY_STALE_HOURS
    assert s["candidates_total"] == 7  # data still surfaced, just flagged stale


def test_missing_files_yield_missing_status_not_crash(tmp_path, schedule_cfg):
    s = bus_mod.build_discovery_health_section(tmp_path / "nope_feed.json",
                                               tmp_path / "nope_card.json")
    assert s["status"] == "missing"
    assert "note" in s


def test_corrupt_files_yield_missing_status_not_crash(tmp_path, schedule_cfg):
    feed = tmp_path / "feed.json"
    card = tmp_path / "card.json"
    feed.write_text("{not json!!!")
    card.write_text("[]")  # readable but wrong shape
    s = bus_mod.build_discovery_health_section(feed, card)
    assert s["status"] == "missing"


def test_scorecard_only_still_builds_section(tmp_path, schedule_cfg):
    """Feed absent but scorecard fresh → data from the scorecard, status ok."""
    now = datetime.now(timezone.utc)
    card = _write_card(tmp_path, _iso(now - timedelta(hours=2)))
    s = bus_mod.build_discovery_health_section(tmp_path / "nofeed.json", card,
                                               now=now)
    assert s["status"] == "ok"
    assert s["candidates_total"] == 7
    assert s["duplicate_rate_7d"] == 0.12  # from windows.last_7d fallback


# ── pause-state propagation ──────────────────────────────────────────────────

def test_config_pause_propagates(tmp_path, monkeypatch):
    p = _write_schedule(tmp_path, paused=True, pause_reason="operator hold")
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCHEDULE_CONFIG_PATH", p)
    now = datetime.now(timezone.utc)
    s = bus_mod.build_discovery_health_section(
        _write_feed(tmp_path, _iso(now)), _write_card(tmp_path, _iso(now)), now=now)
    assert s["paused"] is True and s["pause_reason"] == "operator hold"


def test_do_no_harm_pause_propagates(tmp_path, schedule_cfg):
    now = datetime.now(timezone.utc)
    feed = _write_feed(tmp_path, _iso(now), recommendation="pause",
                       degraded=["duplicate_rate", "candidate_volume"])
    card = _write_card(tmp_path, _iso(now), recommendation="pause",
                       degraded=["duplicate_rate", "candidate_volume"],
                       reasons=["duplicate rate 40% vs prior 10%"])
    s = bus_mod.build_discovery_health_section(feed, card, now=now)
    assert s["paused"] is True
    assert "do_no_harm" in (s["pause_reason"] or "")
    assert s["do_no_harm"]["recommendation"] == "pause"
    assert s["do_no_harm"]["degraded"] == ["duplicate_rate", "candidate_volume"]
    assert s["do_no_harm"]["reasons"] == ["duplicate rate 40% vs prior 10%"]


def test_do_no_harm_pause_not_respected_when_config_says_so(tmp_path, monkeypatch):
    p = _write_schedule(tmp_path, do_no_harm_pause_respected=False)
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCHEDULE_CONFIG_PATH", p)
    now = datetime.now(timezone.utc)
    s = bus_mod.build_discovery_health_section(
        _write_feed(tmp_path, _iso(now), recommendation="pause"),
        _write_card(tmp_path, _iso(now), recommendation="pause"), now=now)
    assert s["paused"] is False


# ── DB extras are strictly best-effort ───────────────────────────────────────

class _BadCur:
    def execute(self, *a, **k):
        raise RuntimeError("no database for you")

    @property
    def connection(self):
        raise RuntimeError("no connection either")


def test_extras_never_crash_without_db():
    assert agent.fetch_discovery_health_extras(_BadCur()) == {}
    assert agent.fetch_discovery_health_extras(None) == {}


def test_build_discovery_health_survives_dead_cursor(tmp_path, schedule_cfg,
                                                     monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(bus_mod, "DISCOVERY_FEED_PATH",
                        _write_feed(tmp_path, _iso(now)))
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCORECARD_PATH",
                        _write_card(tmp_path, _iso(now)))
    s = agent.build_discovery_health(_BadCur())
    assert s["status"] == "ok"
    assert s["top_sources"] == []  # extras degraded silently to defaults


# ── build_bus wiring: discovery_health is a first-class bus section ──────────

def test_build_bus_includes_discovery_health_section(tmp_path, schedule_cfg,
                                                     monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(bus_mod, "DISCOVERY_FEED_PATH",
                        _write_feed(tmp_path, _iso(now)))
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCORECARD_PATH",
                        _write_card(tmp_path, _iso(now)))

    monkeypatch.setattr(agent, "fetch_global_metrics", lambda cur, cfg: {})
    monkeypatch.setattr(agent, "fetch_by_symbol", lambda cur, cfg: {})
    monkeypatch.setattr(agent, "fetch_by_tag", lambda cur, cfg: {})
    monkeypatch.setattr(agent, "fetch_stop_quality", lambda cur, cfg: {})
    monkeypatch.setattr(agent, "fetch_resource_efficiency",
                        lambda cur, cfg, g: {})
    monkeypatch.setattr(agent, "load_outcome_bus_trend", lambda days=14: {})
    monkeypatch.setattr(agent, "evaluate_alerts", lambda shell, trend, cfg: {})
    monkeypatch.setattr(agent, "enrich_alerts", lambda alerts, shell, cfg: {})
    monkeypatch.setattr(agent, "build_maturity_status",
                        lambda shell, trend, alerts, cfg: {})
    monkeypatch.setattr(agent, "read_outcome_bus", lambda path=None: None)
    monkeypatch.setattr(agent, "enrich_bus_traceability",
                        lambda bus, trend=None, prior_bus=None: bus)

    bus = agent.build_bus(cur=None, cfg={}, run_id="test_dh")

    dh = bus.get("discovery_health")
    assert isinstance(dh, dict), "discovery_health must be a first-class section"
    assert dh["status"] == "ok"
    assert dh["candidates_total"] == 7
    missing = SPEC_FIELDS - set(dh)
    assert not missing, f"bus discovery_health missing fields: {sorted(missing)}"
    # bus stays advisory: the section carries no action/feedback entries
    assert "feedback_to_governor" not in dh and "actions" not in dh


def test_build_bus_survives_missing_discovery_files(tmp_path, schedule_cfg,
                                                    monkeypatch):
    monkeypatch.setattr(bus_mod, "DISCOVERY_FEED_PATH", tmp_path / "gone.json")
    monkeypatch.setattr(bus_mod, "DISCOVERY_SCORECARD_PATH",
                        tmp_path / "gone2.json")
    s = agent.build_discovery_health(None)
    assert s["status"] == "missing"  # never crashes the nightly bus build


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
