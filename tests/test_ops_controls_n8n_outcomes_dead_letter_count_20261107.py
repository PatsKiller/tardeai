"""ANCHOR: OPS_CONTROLS_N8N_OUTCOMES_DEAD_LETTER_COUNT_20261107 — the count is the count, not the page size.

LQ-20261107-148. The Ops Controls n8n tab prints "· N open dead letter(s)" from
``LaneLedger.dead_letters_open``, and ``read_ledger`` computed that number with the same query it used to
find the *newest* dead letter::

    SELECT dead_at, last_state, last_reason FROM dead_letters WHERE lane_id=? AND released_at IS NULL
    ORDER BY dead_at DESC LIMIT 20

so ``len(rows)`` is the row limit (``LIMIT 20``) or the number of dead letters, whichever is smaller. The
lane ``n8n-research-intake-consumer`` held **113** unreleased dead letters on 2026-11-07 — the tail of the
2026-10-23 ``safe_flock`` cron outage (docs/ops/incidents/INCIDENT_20261023_SAFE_FLOCK_CRON_OUTAGE.md) —
and the site said **20**:

    read_ledger(...)['n8n-research-intake-consumer'].dead_letters_open  ->  20
    SELECT count(*) FROM dead_letters WHERE lane_id='n8n-research-intake-consumer'
        AND released_at IS NULL                                         -> 113

A page size standing in for a count is the same defect class as a sentinel zero standing in for missing
data: the reader cannot tell "20" from "at least 20", and the operator cannot size the debt. The number
displayed must be the number of open dead letters, and the newest-row example (``dead_letter_last``) keeps
its own bounded query.

Hermetic: a fixture sqlite ledger with the production schema subset, no host, no network.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib import ops_controls_n8n_outcomes as NO

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
  requested_by TEXT, caller_id TEXT, requested_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, exit_code INTEGER,
  duration_s REAL, receipt_json TEXT, slot_key TEXT, attempt INTEGER, parent_run_id TEXT, class TEXT,
  priority INTEGER, worker_id TEXT, pid INTEGER, heartbeat_at TEXT, verdict TEXT);
CREATE INDEX runs_state_requested_at ON runs (state, requested_at);
CREATE INDEX runs_lane_state ON runs (lane_id, state);
CREATE TABLE run_outcomes (run_id TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT, status TEXT NOT NULL,
  run_state TEXT NOT NULL, exit_code INTEGER, receipt_path TEXT, duration_s REAL, effect_key TEXT, reason TEXT,
  attempt INTEGER, finished_at TEXT, recorded_at TEXT NOT NULL);
CREATE INDEX run_outcomes_lane ON run_outcomes (lane_id, recorded_at);
CREATE TABLE dead_letters (slot_key TEXT PRIMARY KEY, lane_id TEXT NOT NULL, mode TEXT, slot_local TEXT,
  attempts INTEGER, last_run_id TEXT, last_state TEXT, last_reason TEXT, verdict TEXT, dead_at TEXT NOT NULL,
  released_at TEXT, released_by TEXT, release_note TEXT, class TEXT, max_attempts INTEGER, policy TEXT);
CREATE INDEX dead_letters_lane ON dead_letters (lane_id, dead_at);
CREATE TABLE breakers (lane_id TEXT PRIMARY KEY, opened_at TEXT, consecutive INTEGER, released_at TEXT,
  released_by TEXT);
"""

LANE = "n8n-research-intake-consumer"


@pytest.fixture()
def led(tmp_path: Path):
    path = tmp_path / "ledger.sqlite"
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.commit()
    c.close()

    class Led:
        def __init__(self, p: Path) -> None:
            self.path = p

        def dead(self, lane: str, at: datetime, *, released_at: datetime | None = None, n: int = 1) -> None:
            con = sqlite3.connect(self.path)
            for i in range(n):
                con.execute(
                    "INSERT INTO dead_letters (slot_key, lane_id, mode, attempts, last_state, last_reason,"
                    " dead_at, released_at, class, max_attempts, policy) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"{lane}-{at.isoformat()}-{i}",
                        lane,
                        "live",
                        1,
                        "RUN_FAILED",
                        "exit_1",
                        (at + timedelta(seconds=i)).isoformat(),
                        released_at.isoformat() if released_at else None,
                        "report",
                        1,
                        "unresolved",
                    ),
                )
            con.commit()
            con.close()

        def run_ok(self, lane: str, at: datetime) -> None:
            rec = '{"output_signal_mtime_before": 100.0, "output_signal_mtime_after": 200.0}'
            con = sqlite3.connect(self.path)
            con.execute(
                "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at, exit_code, receipt_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"d:{lane}:{at.isoformat()}", lane, "live", "RUN_DONE", at.isoformat(), at.isoformat(), 0, rec),
            )
            con.execute(
                "INSERT INTO run_outcomes (run_id, lane_id, mode, status, run_state, exit_code, finished_at,"
                " recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"d:{lane}:{at.isoformat()}", lane, "live", "success", "RUN_DONE", 0,
                 at.isoformat(), at.isoformat()),
            )
            con.commit()
            con.close()

    return Led(path)


def test_a_lane_beyond_the_page_size_reports_its_real_count(led):
    """113 open dead letters are 113, not the LIMIT 20 the newest-row query happens to return."""
    led.dead(LANE, NOW - timedelta(days=14), n=113)
    L = NO.read_ledger(led.path, [LANE], NOW)[LANE]
    assert L.dead_letters_open == 113


def test_the_newest_dead_letter_is_still_reported(led):
    """The bound that the count no longer uses still picks the newest row, not an arbitrary one."""
    led.dead(LANE, NOW - timedelta(days=14), n=25)
    L = NO.read_ledger(led.path, [LANE], NOW)[LANE]
    assert L.dead_letter_last["reason"] == "exit_1"
    assert L.dead_letter_last["at"].startswith("2026-10-24T18:00:24")


def test_released_dead_letters_are_not_open(led):
    led.dead(LANE, NOW - timedelta(days=14), n=5)
    led.dead(LANE, NOW - timedelta(days=13), released_at=NOW - timedelta(days=1), n=40)
    L = NO.read_ledger(led.path, [LANE], NOW)[LANE]
    assert L.dead_letters_open == 5


def test_another_lane_s_dead_letters_are_not_this_lane_s(led):
    led.dead(LANE, NOW - timedelta(days=14), n=7)
    led.dead("some-other-lane", NOW - timedelta(days=14), n=50)
    out = NO.read_ledger(led.path, [LANE, "some-other-lane"], NOW)
    assert out[LANE].dead_letters_open == 7
    assert out["some-other-lane"].dead_letters_open == 50


def test_a_lane_with_none_says_zero_not_unknown(led):
    led.run_ok(LANE, NOW - timedelta(hours=1))
    L = NO.read_ledger(led.path, [LANE], NOW)[LANE]
    assert L.dead_letters_open == 0
    assert L.dead_letter_last is None


def test_the_count_does_not_scan_dead_letters(led):
    """The count is still an indexed lookup on (lane_id, dead_at), never a full-table scan."""
    led.dead(LANE, NOW - timedelta(days=14), n=30)
    con = sqlite3.connect(led.path)
    plan = " | ".join(
        r[-1]
        for r in con.execute(
            "EXPLAIN QUERY PLAN SELECT count(*) FROM dead_letters WHERE lane_id=? AND released_at IS NULL",
            (LANE,),
        )
    )
    con.close()
    assert not any(p.strip() == "SCAN dead_letters" for p in plan.split("|")), plan


def test_the_site_prints_the_number_the_ledger_holds(led):
    """The Ops Controls serializer carries the count through unchanged."""
    led.dead(LANE, NOW - timedelta(days=14), n=113)
    row = {"lane_id": LANE, "state": "ACTIVE", "scheduler": {"kind": "cron", "stage": "shadow",
                                                             "match": f"scripts/{LANE}.py",
                                                             "expression": "*/15 * * * *",
                                                             "command_text": f"$PY scripts/{LANE}.py"},
           "dispatch": {"mode": "live", "cron": ["*/15 * * * *"], "tz": "America/New_York", "class": "report"}}
    L = NO.read_ledger(led.path, [LANE], NOW)[LANE]
    pub = NO.lane_outcome(row, L, "live", NOW)
    assert pub["dead_letters_open"] == 113
