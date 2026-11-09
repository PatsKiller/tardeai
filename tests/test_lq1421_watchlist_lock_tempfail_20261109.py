"""ANCHOR: lq1421_watchlist_lock_tempfail — LQ-20261107-1421.

hermes-coordinator research_curator hit Postgres lock_timeout while updating
watchlist_items (00:15 ET 2026-11-09; 14:38 Sun 2026-11-08) and exited 1, failing
the whole host-cron tick. Lock contention must retry in-process then exit
EX_TEMPFAIL (75); coordinator must treat 75 as soft-ok so the tick does not exit 1.
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
    ],
)
def test_pg_lock_error_detected(err):
    assert CURATOR._is_pg_lock_error(err) is True
    assert CURATOR._is_pg_lock_error(RuntimeError(err)) is True


def test_non_lock_error_not_tempfail():
    assert CURATOR._is_pg_lock_error("password authentication failed") is False
    assert CURATOR._is_pg_lock_error("division by zero") is False


def test_curator_main_retries_then_exits_75(monkeypatch):
    """Fail-before: uncaught lock → exit 1. Pass-after: 3 lock hits → exit 75."""
    calls = {"n": 0}

    def _boom(*, apply, force_deep=False):
        calls["n"] += 1
        raise Exception(
            'canceling statement due to lock timeout\n'
            'CONTEXT:  while updating tuple (455,5) in relation "watchlist_items"'
        )

    monkeypatch.setattr(CURATOR, "run_curator", _boom)
    monkeypatch.setattr(CURATOR.time, "sleep", lambda _s: None)
    rc = CURATOR.main([])
    assert rc == CURATOR.EX_TEMPFAIL == 75
    assert calls["n"] == CURATOR._LOCK_RETRIES == 3


def test_curator_main_recovers_after_transient_lock(monkeypatch):
    calls = {"n": 0}

    def _flaky(*, apply, force_deep=False):
        calls["n"] += 1
        if calls["n"] < 2:
            raise Exception("canceling statement due to lock timeout")
        return {"ok": True, "attempt": calls["n"]}

    monkeypatch.setattr(CURATOR, "run_curator", _flaky)
    monkeypatch.setattr(CURATOR.time, "sleep", lambda _s: None)
    printed = []

    def _print(*a, **k):
        printed.append(a[0] if a else "")

    monkeypatch.setattr("builtins.print", _print)
    rc = CURATOR.main([])
    assert rc == 0
    assert calls["n"] == 2
    assert any('"ok": true' in str(p).lower() or '"ok": True' in str(p) for p in printed) or any(
        "ok" in str(p) for p in printed
    )


def test_curator_main_non_lock_still_raises(monkeypatch):
    def _hard(*, apply, force_deep=False):
        raise RuntimeError("password authentication failed for user trade_ai")

    monkeypatch.setattr(CURATOR, "run_curator", _hard)
    with pytest.raises(RuntimeError, match="password authentication"):
        CURATOR.main([])


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
