"""ANCHOR: lq1421_watchlist_lock_tempfail — LQ-20261107-1421.

hermes-coordinator research_curator hit Postgres lock_timeout while updating
watchlist_items (00:15 ET 2026-11-09; 14:38 Sun 2026-11-08) and exited 1, failing
the whole host-cron tick. Lock contention must retry in-process then exit
EX_TEMPFAIL (75); coordinator must treat 75 as soft-ok so the tick does not exit 1.

REWORK (grok-b): before attempt 2, rollback+close the curator connection and drop
the traceback; retry only the scalp watchlist txn (think-tank + prospect staging
stay outside the loop).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


CURATOR = _load("lq1421_curator", "scripts/hermes_research_curator.py")
COORD = _load("lq1421_coord", "scripts/hermes_coordinator.py")

_LOCK_MSG = (
    'psycopg2.errors.LockNotAvailable: canceling statement due to lock timeout\n'
    'CONTEXT:  while updating tuple (455,5) in relation "watchlist_items"'
)


def test_ex_tempfail_constant_is_75():
    assert CURATOR.EX_TEMPFAIL == 75
    assert COORD.EX_TEMPFAIL == 75


@pytest.mark.parametrize(
    "err",
    [
        'canceling statement due to lock timeout\nCONTEXT:  while updating tuple (746,6) in relation "watchlist_items"',
        "ERROR:  canceling statement due to lock timeout",
        "deadlock detected",
        "could not obtain lock on row in relation",
        "lock_not_available",
        _LOCK_MSG,
    ],
)
def test_pg_lock_error_detected(err):
    assert CURATOR._is_pg_lock_error(err) is True
    assert CURATOR._is_pg_lock_error(RuntimeError(err)) is True


def test_non_lock_error_not_tempfail():
    assert CURATOR._is_pg_lock_error("password authentication failed") is False
    assert CURATOR._is_pg_lock_error("division by zero") is False


def test_curator_main_lock_exits_75(monkeypatch):
    """Exhausted lock from run_curator → exit 75 (not 1)."""

    def _boom(*, apply, force_deep=False):
        raise Exception(_LOCK_MSG)

    monkeypatch.setattr(CURATOR, "run_curator", _boom)
    rc = CURATOR.main([])
    assert rc == CURATOR.EX_TEMPFAIL == 75


def test_curator_main_non_lock_still_raises(monkeypatch):
    def _hard(*, apply, force_deep=False):
        raise RuntimeError("password authentication failed for user trade_ai")

    monkeypatch.setattr(CURATOR, "run_curator", _hard)
    with pytest.raises(RuntimeError, match="password authentication"):
        CURATOR.main([])


def test_scalp_retry_rollbacks_and_closes_before_attempt_2(monkeypatch):
    """REWORK: lock inside the opened connection → rollback+close before reconnect."""
    import sys

    conn1 = MagicMock(name="conn1")
    conn2 = MagicMock(name="conn2")
    reconnects = {"n": 0}

    def _connect():
        reconnects["n"] += 1
        return conn2

    monkeypatch.setattr(CURATOR, "_db_connect", _connect)
    monkeypatch.setattr(CURATOR.time, "sleep", lambda _s: None)

    calls = {"n": 0, "conns": []}

    def _scalp(conn, signals, *, apply, max_mine, max_stage):
        calls["n"] += 1
        calls["conns"].append(conn)
        if calls["n"] == 1:
            raise Exception(_LOCK_MSG)
        return {"mined": 1, "incubator": {"staged": 1}}

    sys.modules["momentum_scalp_lead_miner"] = SimpleNamespace(
        run_scalp_lead_pipeline=_scalp
    )

    out, final_conn = CURATOR._run_scalp_with_lock_retry(
        conn1, {}, apply=True, max_mine=24, max_stage=8
    )
    assert out["mined"] == 1
    assert calls["n"] == 2
    assert calls["conns"] == [conn1, conn2]
    assert final_conn is conn2
    # Attempt 1's connection must be released before attempt 2 opens a new one.
    assert conn1.rollback.call_count == 1
    assert conn1.close.call_count == 1
    assert reconnects["n"] == 1


def test_scalp_retry_exhausted_raises_clean_lock(monkeypatch):
    import sys

    conn = MagicMock(name="conn")
    reopened = []

    def _connect():
        c = MagicMock(name=f"reconnect{len(reopened)}")
        reopened.append(c)
        return c

    monkeypatch.setattr(CURATOR, "_db_connect", _connect)
    monkeypatch.setattr(CURATOR.time, "sleep", lambda _s: None)

    def _always_lock(conn, signals, *, apply, max_mine, max_stage):
        raise Exception(_LOCK_MSG)

    sys.modules["momentum_scalp_lead_miner"] = SimpleNamespace(
        run_scalp_lead_pipeline=_always_lock
    )

    with pytest.raises(Exception, match="lock timeout") as ei:
        CURATOR._run_scalp_with_lock_retry(conn, {}, apply=True, max_mine=1, max_stage=1)
    # Fresh exception via _drop_traceback + `raise ... from None` (no cause chain).
    assert ei.value.__cause__ is None
    assert ei.value.__suppress_context__ is True
    assert conn.rollback.call_count == 1
    assert conn.close.call_count == 1
    # Attempts 2 and 3 each open a fresh conn, then roll it back+close on failure.
    assert len(reopened) == CURATOR._LOCK_RETRIES - 1
    for c in reopened:
        assert c.rollback.call_count == 1
        assert c.close.call_count == 1


def test_run_curator_does_not_rerun_think_tank_or_staging_on_scalp_lock(monkeypatch):
    """REWORK: think-tank + prospect staging stay outside the scalp retry loop."""
    counts = {"tank": 0, "mine": 0, "stage": 0, "scalp": 0}
    conn_a = MagicMock(name="conn_a")
    conn_b = MagicMock(name="conn_b")
    conns = iter([conn_a, conn_b])
    monkeypatch.setattr(CURATOR, "_db_connect", lambda: next(conns))
    monkeypatch.setattr(CURATOR.time, "sleep", lambda _s: None)
    monkeypatch.setattr(CURATOR, "_env", lambda: None)

    def _tank(**kwargs):
        counts["tank"] += 1
        return {"signals": {"rs_rsi": {}}}

    def _mine(conn, signals, max_prospects=12):
        counts["mine"] += 1
        return [{"symbol": "AAA", "thesis": "t", "strength": 1, "source": "s"}]

    def _stage(conn, prospects, *, apply, max_stage):
        counts["stage"] += 1
        return {"staged": 1, "skipped": 0, "detail": []}

    def _scalp(conn, signals, *, apply, max_mine, max_stage):
        counts["scalp"] += 1
        if counts["scalp"] == 1:
            raise Exception(_LOCK_MSG)
        return {"mined": 0, "incubator": {"staged": 0}}

    import sys

    sys.modules["hermes_think_tank"] = SimpleNamespace(run_think_tank=_tank)
    sys.modules["think_tank_prospect_discovery"] = SimpleNamespace(
        mine_signal_prospects=_mine,
        stage_signal_prospects=_stage,
        run_intel_discovery=lambda **k: {"added": 0},
        _run_script=lambda *a, **k: {"ok": True, "result": {}},
    )
    sys.modules["momentum_scalp_lead_miner"] = SimpleNamespace(
        run_scalp_lead_pipeline=_scalp
    )
    sys.modules["sector_research_universe"] = SimpleNamespace(
        run_sector_universe=lambda *a, **k: {}
    )
    sys.modules["research_critique_pipeline"] = SimpleNamespace(
        run_critique_pipeline=lambda *a, **k: {}
    )
    monkeypatch.setattr(CURATOR, "_log_consciousness", lambda *a, **k: {"attention": []})

    report = CURATOR.run_curator(apply=False, force_deep=False)
    assert counts == {"tank": 1, "mine": 1, "stage": 1, "scalp": 2}
    assert report["prospect_pipeline"]["signal_staging"]["staged"] == 1
    conn_a.rollback.assert_called()
    conn_a.close.assert_called()


def test_coordinator_run_script_tempfail_is_soft_ok(monkeypatch):
    """Child exit 75 must not mark the agent failed (tick would exit 1)."""
    COORD.PY = "/usr/bin/python3"

    def _run(*a, **k):
        return SimpleNamespace(returncode=75, stdout="", stderr="EX_TEMPFAIL: lock")

    monkeypatch.setattr(subprocess, "run", _run)
    out = COORD.run_script("research_curator", ["scripts/hermes_research_curator.py", "--apply"])
    assert out["exit"] == 75
    assert out["tempfail"] is True
    assert out["ok"] is True


def test_coordinator_run_script_exit_1_still_hard(monkeypatch):
    COORD.PY = "/usr/bin/python3"

    def _run(*a, **k):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", _run)
    out = COORD.run_script("research_curator", ["scripts/hermes_research_curator.py", "--apply"])
    assert out["exit"] == 1
    assert out.get("tempfail") is False
    assert out["ok"] is False
