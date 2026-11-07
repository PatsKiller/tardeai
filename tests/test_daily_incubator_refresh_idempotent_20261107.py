"""daily-incubator-refresh: a same-slot re-run is write-once, and a lost scan-refresh pass is not counted as
produced (LQ-20261107-128, 2026-11-07).

Two live failures of the 08:15 ET weekday slot on ``daily-incubator-refresh``:

* 2026-11-03 RUN_FAILED — ``psycopg2.OperationalError: SSL connection has been closed unexpectedly`` at
  ``conn.commit()``; fixed at 4972b9449 (ping + per-symbol commit) and served since. Not re-fixed here.
* 2026-11-05 RUN_TIMEOUT ``executor_lost`` — the executor process (and its child) died 4 min into the run; the
  reaper closed the row. The lane's ``dispatch.retry_policy`` is ``none`` and class ``ingest``, and no policy in
  ``config/n8n_retry_policies.json`` admits ``ingest``, so a lost executor is terminal: no second attempt.

A retry only becomes safe once a second run of the SAME slot cannot double-write. The scan-refresh pass holds
one transaction (so a killed run before its commit loses nothing), but a kill AFTER the commit re-ran the whole
pass under a retry: another ``incubator_events`` row per entry and a second ``days_active`` bump. These tests pin
the guard and the honest output accounting that make the retry safe.

Hermetic: fake connections only; no DB, no .env, no network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import daily_incubator_refresh as R  # noqa: E402


class FakeCursor:
    """Models the one behaviour the tests are about: whether the guarded UPDATE matches the row.

    ``conn.refreshed_today`` is the set of ``incubator_universe.id`` values whose ``last_seen_at`` is today. The
    real guard is in SQL (``AND (last_seen_at IS NULL OR last_seen_at < date_trunc('day', NOW()))``); this fake
    applies the same rule when the guard text is present and matches unconditionally without it, so the test
    fails on the old statement instead of passing because the fake was written to the new behaviour.
    """

    GUARD = "last_seen_at < date_trunc('day', NOW())"
    ACTIVE_COLS = [(c,) for c in ("id", "symbol", "strategy_id", "baseline_score", "latest_score", "best_score",
                                  "rvol_baseline", "rvol_latest", "gap_latest", "catalyst", "catalyst_verified",
                                  "days_active", "status")]
    SCAN_COLS = [(c,) for c in ("score", "rvol", "gap_pct", "catalyst", "catalyst_verified", "decision", "grade",
                                "run_type", "scanned_at")]

    def __init__(self, conn):
        self.conn = conn
        self.description = self.ACTIVE_COLS
        self.rowcount = -1
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        self.rowcount = -1
        if sql.strip() == "SELECT 1":                                              # _ping_ok
            self._rows = [(1,)]
            return
        if "SELECT id, symbol, strategy_id" in sql:                                # ACTIVE_INCUBATOR_QUERY
            self.description, self._rows = self.ACTIVE_COLS, list(self.conn.active)
            return
        if "SELECT s.score, s.rvol" in sql:                                        # LATEST_SCAN_QUERY
            self.description, self._rows = self.SCAN_COLS, [self.conn.scan]
            return
        if "UPDATE incubator_universe" in sql:
            inc_id = params[-1]
            if self.GUARD in sql and inc_id in self.conn.refreshed_today:
                self.rowcount = 0
                return
            self.conn.refreshed_today.add(inc_id)
            self.rowcount = 1
            return
        if "INSERT INTO incubator_events" in sql:
            self.conn.events.append(tuple(params))
            self.rowcount = 1
            return
        self.rowcount = 0                                                          # stale-catalyst lookup: none
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, active, scan):
        self.active = list(active)
        self.scan = tuple(scan)
        self.refreshed_today: set[int] = set()
        self.events: list[tuple] = []
        self.closed = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = 1


ACTIVE = [
    (1, "AAA", "strat-1", 40, 40, 40, 1.0, 1.0, 0.0, None, None, 3, "ACTIVE"),
    (2, "BBB", "strat-1", 50, 50, 50, 1.0, 1.0, 0.0, None, None, 4, "ACTIVE"),
]
SCAN = (55, 2.0, 1.5, "synthetic catalyst", True, "BUY", "A", "live", "2026-11-06T13:00:00+00:00")


def _apply(monkeypatch, conn):
    monkeypatch.setattr(R, "get_conn", lambda: conn)
    monkeypatch.setitem(sys.modules, "catalyst_enrichment", type(sys)("catalyst_enrichment"))
    sys.modules["catalyst_enrichment"].enrich_ticker = lambda sym: {}
    return R._run(argparse.Namespace(dry_run=False, apply=True))


def test_a_second_run_of_the_same_slot_writes_no_event_twice(monkeypatch, caplog):
    """The retry hazard: attempt 1 committed before the executor died, attempt 2 runs the whole pass again."""
    conn = FakeConn(ACTIVE, SCAN)

    first = _apply(monkeypatch, conn)
    assert len(conn.events) == 2 and conn.refreshed_today == {1, 2}

    second = _apply(monkeypatch, conn)
    assert len(conn.events) == 2, "a same-slot re-run must not write a second event for either symbol"
    assert first.get("already_refreshed") == 0 and second.get("already_refreshed") == 2
    out = R.lane_output(second)
    assert out["produced_count"] == 0
    assert out["skipped_reasons"] == {"no_scan_data": 0, "already_refreshed": 2}
    assert out["empty_reason"] == "already_refreshed"


def test_the_update_statement_carries_the_same_day_guard():
    """The fake mimics the guard only when the statement carries it; the statement must carry it."""
    assert "last_seen_at < date_trunc('day', NOW())" in R.UPDATE_INCUBATOR
    assert "days_active = days_active + 1" in R.UPDATE_INCUBATOR


def test_a_lost_scan_refresh_pass_is_not_counted_as_produced():
    """2026-10-16/11-03: the connection died before the scan-refresh commit, every row was rolled back, and the
    receipt still reported produced = processed - no_data. A run that lost its writes must say so."""
    out = R.lane_output({"processed": 1506, "no_data": 190, "scan_refresh_lost": 1506})
    assert out["produced_count"] == 0
    assert out["skipped_reasons"]["scan_refresh_lost"] == 1506
    assert out["empty_reason"] == "scan_refresh_lost"


def test_the_normal_run_still_reports_its_events():
    out = R.lane_output({"processed": 1506, "no_data": 190})
    assert out["produced_count"] == 1316
    assert out["skipped_reasons"] == {"no_scan_data": 190}
    assert out["empty_reason"] is None
