"""ANCHOR: LQ1446_BREACH_NO_FALSE_OUTPUT_20261109 — unreadable is not NO_OUTPUT.

LQ-20261107-1446. Nine signals the detector could not read were opened as NO_OUTPUT
P2 incidents. An unreadable signal is UNVERIFIABLE and is not an incident. Staleness
also flagged document-mentions-backfill 41 s past a 3× cadence deadline; the grace is
the lane SLA max_run (its timeout), not a fixed number of seconds.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import supervisor_breach_detector as det  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402

NOW = datetime(2026, 11, 9, 0, 26, 26, tzinfo=timezone.utc)


def _lane(**extra):
    lane = {
        "lane_id": "document-mentions-backfill",
        "state": "ACTIVE",
        "expected_cadence_hours": 1.0,
        "scheduler": {"kind": "n8n", "expression": "dispatcher", "cadence": "25 * * * *"},
        "output_signal": {
            "kind": "json_key",
            "path": "data/runtime/document-mentions-backfill_last.json",
            "key": "ok_at",
        },
    }
    lane.update(extra)
    return lane


def test_unreadable_signal_is_not_a_no_output_incident():
    diag: dict = {}
    rows = det.detect(
        lanes=[_lane()],
        sla_by_lane={"document-mentions-backfill": {"lane_id": "document-mentions-backfill", "max_run_s": 1500}},
        heartbeats={},
        observe=lambda sig: {"last_output_at": None, "readable": False, "detail": "bad json"},
        now=NOW,
        diagnostics=diag,
    )
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    entry = diag["unverifiable"]["document-mentions-backfill"]
    assert entry["class"] == "UNVERIFIABLE"
    assert entry["observed"]["readable"] is False


def test_forty_one_seconds_past_three_cadences_is_inside_the_run_timeout():
    """3 h + 41 s old, timeout/max_run 1500 s: not a miss. 3 h + timeout + 1 min is."""
    sla = {"document-mentions-backfill": {"lane_id": "document-mentions-backfill", "max_run_s": 1500}}
    barely = NOW - timedelta(hours=3, seconds=41)
    rows = det.detect(
        lanes=[_lane()],
        sla_by_lane=sla,
        heartbeats={},
        observe=lambda sig: {"last_output_at": barely.isoformat(), "readable": True},
        now=NOW,
        diagnostics={},
    )
    assert [r for r in rows if r["kind"] == "NO_OUTPUT"] == []
    late = NOW - timedelta(hours=3, seconds=1500 + 60)
    rows = det.detect(
        lanes=[_lane()],
        sla_by_lane=sla,
        heartbeats={},
        observe=lambda sig: {"last_output_at": late.isoformat(), "readable": True},
        now=NOW,
        diagnostics={},
    )
    assert [r["kind"] for r in rows] == ["NO_OUTPUT"]


def test_fanin_drops_an_unreadable_no_output_and_keeps_a_real_one(tmp_path):
    day = NOW.isoformat()
    rows = [
        {
            "state": "OPEN",
            "kind": "NO_OUTPUT",
            "lane_id": "hermes-pipeline-health",
            "detected_at": day,
            "authority": "READ_ONLY_ADVISORY",
            "evidence": {"note": "signal unreadable (UNVERIFIABLE, reported as NO_OUTPUT)"},
        },
        {
            "state": "OPEN",
            "kind": "NO_OUTPUT",
            "lane_id": "market-event-brief",
            "detected_at": day,
            "authority": "READ_ONLY_ADVISORY",
            "evidence": {"note": "never produced", "basis": "cadence:24h×3"},
        },
    ]
    path = tmp_path / "supervisor_breaches.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "supervisor_breach_detector_latest.json").write_text("{}", encoding="utf-8")
    found = fanin._breach_findings(tmp_path, NOW + timedelta(minutes=5))
    items = [f["item"] for f in found]
    assert items == ["market-event-brief:NO_OUTPUT"]
    assert found[0]["severity"] == "P2"
