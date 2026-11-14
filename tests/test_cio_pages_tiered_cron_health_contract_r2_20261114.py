"""LQ-20261114 tiered cron r2: the cio-pages-product health contract and registry row match the tiered schedule.

Lead ruling 2026-11-14T08:22:09Z on REVIEW cc-deepseek-9 (C1, F2, F2b):

* C1  the registry row declares every tier in ``scheduler.schedules``, not only ``scheduler.cadence`` (= tier 1);
* F2  ``expected_cadence_hours`` is the slowest real interval, 0.5 h (off-hours and weekend */30);
* F2b the off-hours gap between builds is exactly 1800 s and a build lands ~22 s after its fire, so a failed
  threshold of 0.5 h read a healthy lane as stale for ~22 s every half hour. The threshold is 0.6 h: an on-time
  build at 1800 s + 25 s is fresh, and one missed */30 fire (2 x 1800 s) is still stale.

The age-vs-threshold decision is the repo's own (``self_heal_runbooks._pc_data_is_late``), not re-derived here.
Synthetic inputs only; no DB, no lane fired.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import cron_schedule
from scripts.lib import self_heal_runbooks as SHR
from scripts.lib.n8n_health_contracts import validate_contract
from scripts.lib.system_health_freshness import schedule_intent

ROOT = Path(__file__).resolve().parents[1]
LANE_ID = "cio-pages-product"
ET = ZoneInfo("America/New_York")
NOW = datetime(2031, 1, 8, 3, 0, tzinfo=timezone.utc)
BUILD_LAG_S = 25  # production builds land ~21-23 s after the fire (REVIEW cc-deepseek-9, 20/20 runs)


def _load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def _row() -> dict:
    rows = [r for r in _load("lane_registry.json")["lanes"] if r.get("lane_id") == LANE_ID]
    assert len(rows) == 1, rows
    return rows[0]


def _contract() -> dict:
    rows = [c for c in _load("n8n_health_contracts.json")["contracts"] if c.get("id") == LANE_ID]
    assert len(rows) == 1, rows
    return rows[0]


def _late(contract: dict, age_s: float) -> bool:
    late, _why = SHR._pc_data_is_late({}, {"data_age_s": age_s}, contract, NOW)
    return late


def _slowest_designed_gap_s() -> float:
    """Largest gap between consecutive fires over one synthetic non-DST week (Mon 2031-01-06 .. Mon 01-13 ET)."""
    start = datetime(2031, 1, 6, 0, 0, tzinfo=ET)
    end = start + timedelta(days=7)
    fires = sorted(
        {f.at.astimezone(timezone.utc) for e in _row()["dispatch"]["cron"]
         for f in cron_schedule.fires_between(e, start, end, "America/New_York")}
    )
    assert len(fires) > 1000, len(fires)
    return max((b - a).total_seconds() for a, b in zip(fires, fires[1:]))


def test_the_slowest_designed_gap_is_the_30_minute_off_hours_fire():
    assert _slowest_designed_gap_s() == 1800


def test_the_contract_validates_and_fails_after_the_gap_plus_a_build_lag_margin():
    c = _contract()
    assert validate_contract(c) == []
    b = c["baseline"]
    assert b["freshness_failed_after_h"] == 0.6
    assert b["freshness_failed_after_h"] > b["freshness_degraded_after_h"]
    gap = _slowest_designed_gap_s()
    assert gap + BUILD_LAG_S < b["freshness_failed_after_h"] * 3600 < 2 * gap


def test_an_on_time_off_hours_build_is_fresh_and_one_missed_fire_is_stale():
    c, gap = _contract(), _slowest_designed_gap_s()
    assert _late(c, gap + BUILD_LAG_S) is False, "1800 s + 25 s is an on-time */30 build"
    assert _late(c, 2 * gap) is True, "one missed */30 fire must read stale"


@pytest.mark.parametrize(("failed_h", "age_s", "late"), [(0.5, 1800 + BUILD_LAG_S, True), (1.0, 3600, False)])
def test_both_neighbouring_thresholds_misread_the_lane(failed_h, age_s, late):
    """0.5 h (the r1 value) calls an on-time build stale; 1.0 h misses a skipped fire."""
    c = copy.deepcopy(_contract())
    c["baseline"]["freshness_failed_after_h"] = failed_h
    assert _late(c, age_s) is late


def test_the_contract_text_no_longer_describes_the_shadow_stage_or_a_flat_tier():
    c = _contract()
    text = json.dumps([c["purpose"], c["failed"], c["baseline"]["freshness_rule"]])
    for gone in ("flat, no off-hours tier", "falls back to the in-server compute", "(not enabled)", "A shadow fire"):
        assert gone not in text, gone
    stale = next(f["text"] for f in c["failed"] if f["check"] == "stale")
    assert "14400" in stale and "unknown" in stale and "never computes" in stale
    # n8n_health_contracts counts any string holding the placeholder word "UNKNOWN" as an unfilled field, and a
    # canary lane with one is DRAFT_AT_LIVE_STAGE; the prose must say "unknown" in lower case.
    assert "UNKNOWN" not in json.dumps(c)
    assert "1800 s" in c["baseline"]["freshness_rule"] and "0.6 h" in c["baseline"]["freshness_rule"]


def test_the_row_declares_every_tier_and_the_slowest_cadence():
    r = _row()
    assert r["scheduler"]["schedules"] == r["dispatch"]["cron"]
    assert len(r["scheduler"]["schedules"]) == 8
    assert r["scheduler"]["cadence"] == r["dispatch"]["cron"][0]
    assert r["expected_cadence_hours"] == 0.5
    assert r["expected_cadence_hours"] * 3600 == _slowest_designed_gap_s()


def test_schedule_intent_reads_all_eight_tiers_not_only_the_first():
    report = schedule_intent({"schedule": "*/2 * * * *", "monitor_lane_ids": [LANE_ID]}, _load("lane_registry.json"))
    assert report["source_intent_status"] == "SOURCE_INTENT_ONLY", report
    assert report["source_intent"][0]["schedules"] == _row()["dispatch"]["cron"]
