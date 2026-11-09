"""LQ-20261107-1556: a dispatched lane's success is the n8n ledger's RUN_DONE row, not a journal line.

The false P1 INC-261109-ysqqrk (2026-11-09): cron_outage_watchdog read only the wrapper journal and the
lane's JSON receipt, but event-detector is executed by the n8n dispatcher, which records a run in the
coordination ledger and never writes a wrapper-journal completion. The ledger holds RUN_DONE live exit 0
at 12:00Z (07:00 ET) and 14:02Z (09:02 ET) that day. Failure first, then the fix, then the ledger read
proven bounded and fail-toward-alerting. Synthetic registry and a synthetic ledger created by the real
schema migration; the host state root is never touched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import cron_outage_watchdog as watchdog  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

#: Monday 2026-11-09 09:30 ET: two fires from today's 07:00/09:00 expression are already elapsed.
NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
FIRE_SCHEDULE = "0 7,9,12,16,20 * * 1-5"


def _lane(lane_id: str = "event-detector", *, state: str = "ACTIVE", dispatch: dict | None = None) -> dict:
    row = {
        "lane_id": lane_id,
        "state": state,
        "expected_cadence_hours": 59.0,
        # No market_day_gate.sh token: the synthetic lane needs no injected trading calendar.
        "scheduler": {"kind": "cron", "expression": FIRE_SCHEDULE, "match": "scripts/event_detector.py",
                      "command_text": "cd $PROJ && $PY scripts/event_detector.py"},
        "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}_last.json"},
    }
    if dispatch is not None:
        row["dispatch"] = dispatch
    return row


@pytest.fixture
def state_root(tmp_path, monkeypatch):
    """A clean state root: empty wrapper journal and one stale JSON receipt (Nov 8, the observed one)."""
    monkeypatch.delenv("TRADEAI_N8N_COORDINATION_LEDGER", raising=False)
    root = tmp_path / "state"
    (root / "logs").mkdir(parents=True)
    (root / "logs/safe_flock_events.jsonl").write_text("")
    (root / "data/runtime").mkdir(parents=True)
    (root / "data/runtime/event-detector_last.json").write_text(
        json.dumps({"schema": "LaneRunReceipt@v1", "status": "ok", "ok_at": "2026-11-08T08:33:00Z"}))
    return root


def _make_ledger(root: Path, rows: list[tuple]) -> Path:
    """Create the ledger with the real migrations, then insert (run_id, lane, mode, state, requested_at,
    finished_at, exit_code) rows. The migration is the production one, so the reader is tested against the
    real column set and indexes rather than a hand-built table."""
    path = root / "data/governance/n8n_coordination_ledger.sqlite"
    ledger = CoordinationLedger(path)  # creates parent, WAL, _migrate + _migrate_dispatch_v2
    ledger.close()
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at, exit_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()
    return path


def _collect(registry, state_root):
    return watchdog.collect({"lanes": registry}, state_root, NOW)


def _grade(registry, state_root, successes=None):
    if successes is None:
        successes = _collect(registry, state_root)["successes"]
    report = watchdog.evaluate({"lanes": registry}, [], successes, now=NOW)
    return next(row for row in report["rows"] if row["lane_id"] == "event-detector")


def test_ledger_run_done_is_what_flips_missed_runs_to_ok(state_root):
    """Fail-before the fix: cron-only evidence grades MISSED_RUNS for a lane the ledger shows succeeded twice."""
    registry = [_lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})]
    _make_ledger(state_root, [
        ("run-0700", "event-detector", "live", "RUN_DONE", "2026-11-09T12:00:04.399455+00:00",
         "2026-11-09T12:00:29.032183+00:00", 0),
        ("run-0902", "event-detector", "live", "RUN_DONE", "2026-11-09T14:00:06.568274+00:00",
         "2026-11-09T14:02:18.867546+00:00", 0),
    ])

    # The pre-fix reader: cron evidence only. Two elapsed fires after the last cron success => MISSED_RUNS.
    cron_only = {"event-detector": [{"at": "2026-11-08T08:33:00Z", "validated_success": True, "source": "ok_at"}]}
    before = _grade(registry, state_root, successes=cron_only)
    assert before["status"] == "MISSED_RUNS", before
    assert before["missed_fires"] == 2, before

    successes = _collect(registry, state_root)["successes"]
    after = _grade(registry, state_root, successes=successes)
    assert after["status"] == "OK", after
    assert after["missed_fires"] == 0
    # The last success is the ledger's finish instant of the 09:00 fire, not the receipt mtime, not the fire time.
    assert after["last_success_at"] == "2026-11-09T14:02:18.867546Z"
    sources = {entry["source"] for entry in successes["event-detector"]}
    assert "n8n_ledger:RUN_DONE" in sources


def test_only_live_run_done_exit_zero_rows_count(state_root):
    registry = [_lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})]
    _make_ledger(state_root, [
        ("dry", "event-detector", "dry_run", "RUN_DONE", "2026-11-09T12:00:04+00:00", "2026-11-09T12:00:09+00:00", 0),
        ("failed", "event-detector", "live", "RUN_FAILED", "2026-11-09T12:00:04+00:00", "2026-11-09T12:00:09+00:00", 1),
        ("exit1", "event-detector", "live", "RUN_DONE", "2026-11-09T12:00:04+00:00", "2026-11-09T12:00:09+00:00", 1),
        ("skipped", "event-detector", "live", "RUN_SKIPPED_LOCK", "2026-11-09T12:00:04+00:00",
         "2026-11-09T12:00:09+00:00", 0),
    ])
    successes = _collect(registry, state_root)["successes"]
    # Only the stale cron receipt remains: no ledger row is a success unless it is live RUN_DONE exit 0.
    assert [entry["source"] for entry in successes["event-detector"]] == ["ok_at"]
    assert _grade(registry, state_root, successes=successes)["status"] == "MISSED_RUNS"


def test_future_and_unregistered_and_paused_rows_are_not_success(state_root):
    registry = [
        _lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE}),
        _lane("paused-lane", state="PAUSED", dispatch={"mode": "live", "cron": FIRE_SCHEDULE}),
    ]
    future = (NOW + timedelta(hours=1)).isoformat()
    _make_ledger(state_root, [
        ("future", "event-detector", "live", "RUN_DONE", future, future, 0),
        ("unregistered", "not-in-registry", "live", "RUN_DONE", "2026-11-09T12:00:04+00:00",
         "2026-11-09T12:00:09+00:00", 0),
        ("paused", "paused-lane", "live", "RUN_DONE", "2026-11-09T12:00:04+00:00",
         "2026-11-09T12:00:09+00:00", 0),
    ])
    successes = _collect(registry, state_root)["successes"]
    assert [entry["source"] for entry in successes["event-detector"]] == ["ok_at"]  # a future row is never evidence
    assert "paused-lane" not in successes  # a paused lane is not evaluated, so not credited either


def test_rows_older_than_the_cadence_window_are_not_read(state_root):
    """The window is two elapsed opportunities plus slack; an older success is not evidence for today."""
    registry = [_lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})]
    stale = (NOW - timedelta(hours=2 * 59.0 + 1 + 1)).isoformat()
    _make_ledger(state_root, [
        ("ancient", "event-detector", "live", "RUN_DONE", stale, stale, 0),
    ])
    assert watchdog.n8n_successes({"lanes": registry}, state_root, NOW) == ({}, [])


def test_absent_ledger_leaves_cron_evidence_exactly_as_it_was(state_root):
    registry = [_lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})]
    snapshot = _collect(registry, state_root)
    assert snapshot["successes"]["event-detector"][0]["source"] == "ok_at"
    assert "n8n_ledger_unavailable" not in snapshot["collection_gaps"]


def test_unreadable_ledger_is_a_collection_gap_and_never_health(state_root):
    """A present-but-corrupt ledger must not excuse the lane: the gap is reported and the grade stays MISSED."""
    registry = [_lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})]
    path = state_root / "data/governance/n8n_coordination_ledger.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database")
    successes, gaps = watchdog.n8n_successes({"lanes": registry}, state_root, NOW)
    assert successes == {}
    assert gaps == ["n8n_ledger_unavailable"]
    snapshot = _collect(registry, state_root)
    assert "n8n_ledger_unavailable" in snapshot["collection_gaps"]
    assert _grade(registry, state_root, successes=snapshot["successes"])["status"] == "MISSED_RUNS"


def test_lane_without_a_dispatch_block_ignores_the_ledger(state_root):
    """Only a dispatched lane's success lives in the ledger; a cron lane keeps its receipt/journal evidence."""
    registry = [_lane()]
    _make_ledger(state_root, [
        ("run-0902", "event-detector", "live", "RUN_DONE", "2026-11-09T14:00:06+00:00",
         "2026-11-09T14:02:18+00:00", 0),
    ])
    successes = _collect(registry, state_root)["successes"]
    assert [entry["source"] for entry in successes["event-detector"]] == ["ok_at"]


def test_malformed_cadence_widens_the_read_instead_of_crashing(state_root):
    """A bad registry value must not take the monitor down; the window falls back to the 24 h floor."""
    lane = _lane(dispatch={"mode": "live", "cron": FIRE_SCHEDULE})
    lane["expected_cadence_hours"] = "not-a-number"
    _make_ledger(state_root, [
        ("run-0902", "event-detector", "live", "RUN_DONE", "2026-11-09T14:00:06+00:00",
         "2026-11-09T14:02:18+00:00", 0),
    ])
    successes, gaps = watchdog.n8n_successes({"lanes": [lane]}, state_root, NOW)
    assert gaps == []
    assert successes["event-detector"][0]["at"] == "2026-11-09T14:02:18Z"
