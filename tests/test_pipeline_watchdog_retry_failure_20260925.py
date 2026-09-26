"""pipeline_watchdog: a retry that RAISES is handled like a failed retry (refresh of PR #140).

Before: a subprocess timeout inside the retry logged a bare ERROR every cycle (flooding the
execution_health log_errors check), left the pipeline_runs row stuck 'running', and never
escalated at MAX_RETRIES. Now both failure shapes go through one path.

Runs without psycopg2 or a rendered .env (CI installs only pytest + pyyaml).
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def wd(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("pipeline_watchdog", None)
    mod = importlib.import_module("pipeline_watchdog")
    yield mod
    sys.modules.pop("pipeline_watchdog", None)


class _Cur:
    def __init__(self, retries_today):
        self._n = retries_today

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return (self._n,)


class _Conn:
    def __init__(self, retries_today):
        self._n = retries_today

    def cursor(self):
        return _Cur(self._n)


def _wire(monkeypatch, wd, *, run_ok=True, raise_exc=None, returncode=0):
    calls = {"run_fail": [], "run_complete": [], "actions": [], "telegram": []}
    reg = types.ModuleType("pipeline_registry")
    reg.run_start = lambda script, **k: 42
    reg.run_complete = lambda rid: calls["run_complete"].append(rid)
    reg.run_fail = lambda rid, msg: calls["run_fail"].append((rid, msg))
    monkeypatch.setitem(sys.modules, "pipeline_registry", reg)

    def fake_run(*a, **k):
        if raise_exc is not None:
            raise raise_exc
        return types.SimpleNamespace(returncode=returncode, stderr="boom stderr")

    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    monkeypatch.setattr(wd, "log_action", lambda conn, *a: calls["actions"].append(a))
    monkeypatch.setattr(wd, "was_alerted_recently", lambda conn, target: False)
    monkeypatch.setattr(wd, "send_telegram", lambda msg, urgent=False: calls["telegram"].append(msg))
    return calls


ISSUE = {"script": "demo_job", "critical": True, "command": "true", "issue": "overdue"}


def test_timeout_marks_run_failed_records_action_and_does_not_log_error(wd, monkeypatch, caplog):
    calls = _wire(monkeypatch, wd, raise_exc=subprocess.TimeoutExpired("true", 300))
    with caplog.at_level(logging.WARNING, logger=wd.log.name):
        wd.handle_pipeline_issues(_Conn(0), [dict(ISSUE)])
    assert calls["run_fail"] and calls["run_fail"][0][0] == 42
    assert calls["actions"] and calls["actions"][0][0] == "retry" and calls["actions"][0][3] is False
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert calls["telegram"] == []  # first failure does not escalate


def test_timeout_at_max_retries_escalates_once(wd, monkeypatch):
    calls = _wire(monkeypatch, wd, raise_exc=subprocess.TimeoutExpired("true", 300))
    wd.handle_pipeline_issues(_Conn(wd.MAX_RETRIES - 1), [dict(ISSUE)])
    assert len(calls["telegram"]) == 1 and "demo_job" in calls["telegram"][0]
    assert ("alert", "demo_job", "max_retries", True, "") in calls["actions"]


def test_nonzero_exit_still_takes_the_same_failure_path(wd, monkeypatch):
    calls = _wire(monkeypatch, wd, returncode=2)
    wd.handle_pipeline_issues(_Conn(wd.MAX_RETRIES - 1), [dict(ISSUE)])
    assert calls["run_fail"] == [(42, "boom stderr")]
    assert len(calls["telegram"]) == 1


def test_success_is_unchanged(wd, monkeypatch):
    calls = _wire(monkeypatch, wd, returncode=0)
    wd.handle_pipeline_issues(_Conn(0), [dict(ISSUE)])
    assert calls["run_complete"] == [42] and calls["run_fail"] == [] and calls["telegram"] == []


def test_registry_import_failure_still_escalates(wd, monkeypatch):
    """If pipeline_registry itself can't be imported, rid/run_fail are None — must not NameError."""
    calls = _wire(monkeypatch, wd)
    monkeypatch.setitem(sys.modules, "pipeline_registry", None)  # import raises ImportError
    wd.handle_pipeline_issues(_Conn(wd.MAX_RETRIES - 1), [dict(ISSUE)])
    assert calls["run_fail"] == []
    assert len(calls["telegram"]) == 1
