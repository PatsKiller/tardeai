"""LQ-20261107-377 — a failed intervention is closed once a later fix clears the component.

MEASURED 2026-11-07. /v3's Recent Changes feed (``/api/v2/health/activity``) showed two
"Execution pipeline failures" rows: ``claude_interventions`` 24558 (status fixed, written
14:06:46 ET) and 24557 (status failed, written 14:01:30 ET, detail "retry exit 0 but verify
failed: pipeline_still unrecovered=1 sla=0").  The failed row was honest when written — the
scorer's recovery run had not finished — and nothing ever revisited it once the finding left
the health snapshot.  Every one of the 484 ``failed`` health rows in the preceding seven days
had a later ``fixed`` row for the same component: the stale row is a class, not a record.

These tests pin (a) the predicate — supersede only on a LATER fixed row for the SAME
component, and only rows that are still open — (b) that ``resolved_at`` keeps the later fix's
time so the feed does not re-sort, (c) that a dry run writes nothing and an error never stops
the escalation pass, and (d) that the sweep runs BEFORE the empty-queue early return, which is
the only state the handler is in once the condition has cleared.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

COMPONENT = "health:execution_health:pipeline_failures"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rec():
    return _load("health_intervention_reconcile", "scripts/lib/health_intervention_reconcile.py")


@pytest.fixture(scope="module")
def esc():
    return _load("claude_escalation_handler", "scripts/claude_escalation_handler.py")


class _FakeCursor:
    def __init__(self, candidates=(), touched=None):
        self.candidates = list(candidates)
        self.touched = touched
        self.executed = []
        self.executed_many = []
        self.rowcount = -1
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._rows = self.candidates

    def executemany(self, sql, seq):
        self.executed_many.append((sql, list(seq)))
        self.rowcount = len(seq) if self.touched is None else self.touched

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _writes(cur):
    return [sql for sql, _ in cur.executed_many if "UPDATE claude_interventions" in sql]


# ── predicate ─────────────────────────────────────────────────────────────────


def test_no_connection_is_reported_not_raised(rec):
    out = rec.reconcile_superseded(None)
    assert out["error"] == "no_db"
    assert out["closed"] == 0


def test_candidate_predicate_needs_a_later_fixed_row_for_the_same_component(rec):
    sql = rec._CANDIDATES_SQL
    assert "f.status IN ('failed', 'investigating')" in sql
    assert "f.component LIKE 'health:%%'" in sql
    # the later fix, same component, strictly after — the positive evidence
    assert "s.component = f.component" in sql
    assert "s.status = 'fixed'" in sql
    assert "s.created_at > f.created_at" in sql
    # bounded by the feed's window and a batch cap
    assert "make_interval(hours => %s)" in sql
    assert "LIMIT %s" in sql


def test_supersede_keeps_the_later_fix_time_and_cannot_reclose_a_closed_row(rec):
    sql = rec._SUPERSEDE_SQL
    assert "status = 'superseded'" in sql
    # resolved_at is bound to the LATER fix's time, not now(): the row keeps its place
    # in the 7-day feed instead of jumping to the top as if it had just happened
    assert "resolved_at = %s" in sql
    assert "now()" not in sql
    # a row closed by another pass between SELECT and UPDATE is left alone
    assert "status IN ('failed', 'investigating')" in sql
    assert "superseded by a later verified remediation" in sql
    # the read-only shape check is the same expression, so it cannot drift from the write
    assert rec._SUPERSEDE_SOLUTION in rec._SELECT_SHAPE_SQL


# ── behaviour ─────────────────────────────────────────────────────────────────


def test_dry_run_lists_candidates_and_writes_nothing(rec):
    fixed_at = datetime(2026, 11, 7, 19, 6, 46, tzinfo=timezone.utc)
    cur = _FakeCursor(candidates=[(24557, COMPONENT, fixed_at)])
    conn = _FakeConn(cur)
    out = rec.reconcile_superseded(conn, dry_run=True)
    assert out == {
        "candidates": 1,
        "closed": 0,
        "ids": [24557],  # what a live pass would close
        "dry_run": True,
        "error": None,
    }
    assert _writes(cur) == []
    assert conn.commits == 1


def test_supersedes_the_row_with_the_later_fix_time(rec):
    fixed_at = datetime(2026, 11, 7, 19, 6, 46, tzinfo=timezone.utc)
    cur = _FakeCursor(candidates=[(24557, COMPONENT, fixed_at)])
    conn = _FakeConn(cur)
    out = rec.reconcile_superseded(conn)
    assert out["candidates"] == 1
    assert out["closed"] == 1
    assert out["ids"] == [24557]
    assert out["error"] is None
    ((sql, params),) = cur.executed_many
    assert sql is rec._SUPERSEDE_SQL
    assert params == [(fixed_at, 24557)]
    assert conn.commits == 1
    assert cur.closed


def test_a_row_closed_by_a_racing_pass_is_not_counted_closed(rec):
    fixed_at = datetime(2026, 11, 7, 19, 6, 46, tzinfo=timezone.utc)
    cur = _FakeCursor(candidates=[(24557, COMPONENT, fixed_at)], touched=0)
    conn = _FakeConn(cur)
    out = rec.reconcile_superseded(conn)
    assert out["candidates"] == 1
    assert out["closed"] == 0  # the WHERE guard refused it; nothing was written
    assert out["error"] is None


def test_nothing_to_do_writes_nothing(rec):
    cur = _FakeCursor(candidates=[])
    conn = _FakeConn(cur)
    out = rec.reconcile_superseded(conn)
    assert out["candidates"] == 0 and out["closed"] == 0
    assert _writes(cur) == []


def test_error_rolls_back_and_never_raises(rec):
    class _Boom(_FakeCursor):
        def execute(self, sql, params=None):
            raise RuntimeError("connection lost")

    cur = _Boom()
    conn = _FakeConn(cur)
    out = rec.reconcile_superseded(conn)
    assert out["error"].startswith("RuntimeError: connection lost")
    assert out["closed"] == 0
    assert conn.rollbacks == 1


# ── handler wiring: the sweep must not depend on a queued item ────────────────


def test_sweep_runs_before_the_empty_queue_exit(esc, tmp_path, monkeypatch):
    calls = []
    sentinel_conn = object()

    monkeypatch.setattr(esc, "_get_conn", lambda: sentinel_conn)
    monkeypatch.setattr(esc, "QUEUE_FILE", tmp_path / "claude_escalation_queue.json")
    monkeypatch.setattr(esc, "STALENESS_QUEUE_FILE", tmp_path / "claude_escalation_staleness_queue.json")

    import lib.health_intervention_reconcile as rec_mod

    def _fake(conn, **kwargs):
        calls.append((conn, kwargs))
        return {"candidates": 0, "closed": 0, "ids": [], "dry_run": kwargs.get("dry_run"), "error": None}

    monkeypatch.setattr(rec_mod, "reconcile_superseded", _fake)

    # Empty queue: process_queue returns before it would ever open a connection for a
    # queued item — the exact state that left row 24557 unreachable in production.
    esc.process_queue(dry_run=False, tier1_only=True)

    assert calls, "reconciliation sweep did not run on an empty queue"
    assert calls[0][0] is sentinel_conn
    assert calls[0][1].get("dry_run") is False


# ── the feed says out loud what "superseded" means ───────────────────────────


@pytest.fixture(scope="module")
def api():
    return _load("api_v2_lq377", "scripts/api_v2.py")


def _feed_row(status: str) -> dict:
    return {
        "component": COMPONENT,
        "status": status,
        "solution": "retry exit 0 but verify failed: pipeline_still unrecovered=1 sla=0",
        "diagnosis": "",
        "ts": "2026-11-07T19:01:30Z",
    }


def test_activity_feed_annotates_a_superseded_row(api, monkeypatch):
    row = _feed_row("superseded")

    def _fake_query(sql, params=None):
        return [row] if "claude_interventions" in sql else []

    monkeypatch.setattr(api, "_db_query", _fake_query)
    out = api._health_activity()
    item = out["activity"][0]
    assert item["action"] == "superseded"
    # the row keeps its own history but no longer reads as a live failure on its own
    assert "later remediation verified this component clear" in item["resolution"]
    assert "unrecovered=1" in item["detail"]


def test_activity_feed_leaves_a_fixed_row_unqualified(api, monkeypatch):
    def _fake_query(sql, params=None):
        return [_feed_row("fixed")] if "claude_interventions" in sql else []

    monkeypatch.setattr(api, "_db_query", _fake_query)
    out = api._health_activity()
    assert out["activity"][0]["resolution"] is None


# ── live-schema proof (read-only: SELECT + EXPLAIN, never an UPDATE) ─────────


@pytest.fixture(scope="module")
def live_conn():
    try:
        sys.path.insert(0, str(SCRIPTS))
        from db_adapter import _get_conn  # type: ignore

        conn = _get_conn()
    except Exception as exc:  # pragma: no cover — CI without a DB
        pytest.skip(f"no database: {exc}")
    if conn is None:  # pragma: no cover
        pytest.skip("no database connection")
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = on")
    cur.close()
    return conn


@pytest.mark.host_state("read-only SELECT against the live claude_interventions schema; writes nothing")
def test_candidate_query_runs_against_the_live_schema(rec, live_conn):
    out = rec.reconcile_superseded(live_conn, limit=1, dry_run=True)
    assert out["error"] is None, out["error"]
    assert isinstance(out["candidates"], int)


@pytest.mark.host_state("read-only SELECT of the UPDATE's SET expressions against the live schema; writes nothing")
def test_supersede_expressions_typecheck_against_the_live_schema(rec, live_conn):
    """EXPLAIN of an UPDATE needs UPDATE privilege, which this suite does not have.

    The read-only mirror selects the same assignment expressions over the same table,
    so a missing column or a text/varchar mismatch still fails here. Hermetic tests pin
    the write shape; this pins that the shape fits this database.
    """
    cur = live_conn.cursor()
    try:
        cur.execute(rec._SELECT_SHAPE_SQL, (24557,))
        cur.fetchall()
    finally:
        cur.close()
        live_conn.rollback()


def test_window_defaults_to_the_feed_window(rec):
    assert rec.DEFAULT_WINDOW_HOURS == 168  # /api/v2/health/activity lists 7 days
    assert rec.SUPERSEDED_STATUS == "superseded"
    # a default call reaches back exactly the feed window
    assert timedelta(hours=rec.DEFAULT_WINDOW_HOURS) == timedelta(days=7)
