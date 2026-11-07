"""LQ-20261107-307: two health-tick monitors reported FINDINGS with exit 1, which health_tick reads as a crash.

health_tick.py (n8n maturity B3.1) treats rc 1 as an uncaught exception, so a monitor that ran cleanly and found
something must exit EXIT_FINDING (3) and declare ``finding_rc: [3]`` in config/health_tick_steps.json.
Measured in data/runtime/health_tick_history.jsonl 2026-11-01..07: pipeline-watchdog "crashed" 81 times (every
two hours, each one "repair unit not installed/loaded") and pipeline-freshness-monitor 25 times (two tables
stale), and each one marked tradeai-health-tick.service failed.

No DB, no network, no send: psycopg2 is a stub module and every collaborator is patched.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [p for p in (str(ROOT), str(ROOT / "scripts")) if p not in sys.path]

from scripts.lib.monitor_exit_codes import EXIT_FINDING, EXIT_PYTHON_CRASH  # noqa: E402


# ── pipeline_freshness_monitor ───────────────────────────────────────────────


@pytest.fixture()
def pfm(monkeypatch):
    sys.modules.pop("pipeline_freshness_monitor", None)
    mod = importlib.import_module("pipeline_freshness_monitor")
    observed = []
    fake_state = types.ModuleType("alert_condition_state")
    fake_state.observe = lambda key, state, alertable: observed.append(state) or {"notify": False, "action": "same"}
    monkeypatch.setitem(sys.modules, "alert_condition_state", fake_state)
    monkeypatch.setattr(sys, "argv", ["pipeline_freshness_monitor.py"])
    yield mod, observed
    sys.modules.pop("pipeline_freshness_monitor", None)


def test_a_stale_pipeline_is_a_finding_not_a_crash(pfm, monkeypatch):
    mod, observed = pfm
    stale = [{"name": "ticker_snapshot_daily", "age_days": 4.7, "threshold_days": 3.0, "surfaced": "x"}]
    monkeypatch.setattr(mod, "check", lambda: (stale, [], []))
    rc = mod.main()
    assert rc == EXIT_FINDING and rc != EXIT_PYTHON_CRASH
    assert observed == ["STALE:ticker_snapshot_daily|MISSING:none"]


def test_a_missing_pipeline_is_a_finding_too(pfm, monkeypatch):
    mod, _ = pfm
    missing = [{"name": "setup_advisory", "surfaced": "x", "reason": "empty_table", "detail": "d"}]
    monkeypatch.setattr(mod, "check", lambda: ([], missing, []))
    assert mod.main() == EXIT_FINDING


def test_all_fresh_is_ok(pfm, monkeypatch):
    mod, observed = pfm
    monkeypatch.setattr(mod, "check", lambda: ([], [], [{"name": "a", "age_days": 0.1}]))
    assert mod.main() == 0 and observed == ["FRESH"]


# ── pipeline_watchdog ────────────────────────────────────────────────────────


class _Conn:
    autocommit = False

    def close(self):
        pass


@pytest.fixture()
def wd(monkeypatch):
    fake_pg = types.ModuleType("psycopg2")
    fake_pg.connect = lambda **kw: _Conn()
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("pipeline_watchdog", None)
    mod = importlib.import_module("pipeline_watchdog")
    monkeypatch.setattr(mod, "check_pipeline_execution", lambda conn: [])
    monkeypatch.setattr(mod, "check_go_coverage", lambda conn: 0)
    monkeypatch.setattr(sys, "argv", ["pipeline_watchdog.py", "--no-telegram"])
    yield mod
    sys.modules.pop("pipeline_watchdog", None)


def _handoff(monkeypatch, result):
    from lib import pipeline_repair_handoff as handoff
    monkeypatch.setattr(handoff, "request_repair", lambda kind, **kw: dict(result))


def test_an_uninstalled_repair_unit_is_a_finding_not_a_crash(wd, monkeypatch):
    # The exact record the live watchdog logged at every even hour 2026-11-01..07.
    _handoff(monkeypatch, {"ok": False, "accepted": False, "recovered": False,
                           "unit": "tradeai-pipeline-repair@enrichment.service", "outcome": "FAILED",
                           "exit_code": 1, "error": "repair unit not installed/loaded; operator installation required"})
    rc = wd.main()
    assert rc == EXIT_FINDING and rc != EXIT_PYTHON_CRASH


def test_an_accepted_handoff_is_ok(wd, monkeypatch):
    _handoff(monkeypatch, {"ok": True, "accepted": True, "unit": "tradeai-pipeline-repair@enrichment.service",
                           "exit_code": 0})
    assert wd.main() == 0
