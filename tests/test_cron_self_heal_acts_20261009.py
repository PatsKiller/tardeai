"""cron_self_heal acts on a healable lane (2026-10-09, n8n maturity B3.1).

Every live run prints `"acted": []`. That is CORRECT today: the six managed
lanes are in the crontab and fresh (hours old against cadence_h=80); the script
last acted 2026-09-21 06:00 (two STALE reruns, both ok). These tests prove it
still acts when a lane is healable, and pin the two defects found on the way:
  - `$PY` was hard-wired to <project>/.venv/bin/python, which does not exist in
    the served tree the health tick runs it from (every rerun -> 127; every
    re-add -> a crontab line with a dead interpreter);
  - a lane moved off cron (systemd / n8n / a step table) would have been
    re-added to the crontab and run twice.

Hermetic: tmp state/log/registry files; crontab, the rerun subprocess and the
Telegram notifier are all stubbed. Nothing touches the live crontab.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import cron_self_heal as csh

JOB = {
    "name": "demo_lane", "schedule_match": "demo_lane.py", "cadence_h": 80,
    "signal": ("log", "demo_lane.log"),
    "cron_line": "0 7 * * 1-5 cd $PROJ && $PY scripts/demo_lane.py --apply >> logs/demo_lane.log 2>&1",
    "remediate_cmd": "cd $PROJ && $PY scripts/demo_lane.py --apply",
}


class FakeShell:
    """Stands in for subprocess.run inside cron_self_heal: records every call."""

    def __init__(self, crontab: str = "") -> None:
        self.crontab = crontab
        self.calls: list = []
        self.installed: list[str] = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(cmd)
        if cmd == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.crontab, stderr="")
        if cmd == ["crontab", "-"]:
            self.installed.append(kwargs.get("input", ""))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")   # the rerun


@pytest.fixture
def heal_env(monkeypatch, tmp_path):
    notified: list[str] = []
    shell = FakeShell()
    registry = tmp_path / "lane_registry.json"
    registry.write_text(json.dumps({"lanes": []}))
    monkeypatch.setattr(csh, "REGISTRY", [dict(JOB)])
    monkeypatch.setattr(csh, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(csh, "LOG_FILE", tmp_path / "cron_self_heal.log")
    monkeypatch.setattr(csh, "LANE_REGISTRY", registry)
    monkeypatch.setattr(csh, "PROJECT_ROOT", tmp_path)          # no .venv here, like CURRENT
    monkeypatch.setattr(csh, "_notify", notified.append)
    monkeypatch.setattr(csh.subprocess, "run", shell)
    monkeypatch.setenv("PY", sys.executable)
    monkeypatch.delenv("TRADEAI_PY", raising=False)
    monkeypatch.setenv("PROJ", str(tmp_path))
    return shell, notified, registry, tmp_path


def _status(monkeypatch, *, scheduled: bool, age_h):
    monkeypatch.setattr(csh, "_crontab_lines",
                        lambda: ["0 7 * * 1-5 cd $PROJ && $PY scripts/demo_lane.py --apply"] if scheduled else [])
    monkeypatch.setattr(csh, "_log_age_h", lambda _f: age_h)


def test_stale_lane_is_rerun_with_an_interpreter_that_exists(heal_env, monkeypatch):
    shell, notified, _reg, _root = heal_env
    _status(monkeypatch, scheduled=True, age_h=200.0)
    out = csh.heal(dry=False)
    assert out["acted"] == ["demo_lane:re-ran remediate"]
    assert notified and "demo_lane STALE" in notified[0]
    rerun = [c for c in shell.calls if isinstance(c, str)]
    assert len(rerun) == 1 and sys.executable in rerun[0] and "$PY" not in rerun[0]
    assert ".venv/bin/python" not in rerun[0].replace(sys.executable, "")
    assert json.loads((_root / "state.json").read_text())["demo_lane"]["fails"] == 0


def test_dropped_cron_line_is_re_added_with_a_live_interpreter(heal_env, monkeypatch):
    shell, _notified, _reg, root = heal_env
    _status(monkeypatch, scheduled=False, age_h=1.0)
    out = csh.heal(dry=False)
    assert out["acted"] == ["demo_lane:re-added to crontab"]
    assert len(shell.installed) == 1
    line = shell.installed[0].strip().splitlines()[-1]
    assert "scripts/demo_lane.py --apply" in line and sys.executable in line and "$PY" not in line
    assert f"cd {root} " in line


def test_cooldown_stops_a_second_heal(heal_env, monkeypatch):
    _shell, _n, _reg, _root = heal_env
    _status(monkeypatch, scheduled=True, age_h=200.0)
    assert csh.heal(dry=False)["acted"]
    assert csh.heal(dry=False)["acted"] == []


def test_lane_scheduled_elsewhere_is_not_re_added(heal_env, monkeypatch):
    shell, _n, registry, _root = heal_env
    registry.write_text(json.dumps({"lanes": [{
        "lane_id": "demo-lane", "state": "ACTIVE",
        "scheduler": {"kind": "systemd", "match": "scripts/demo_lane.py"}}]}))
    _status(monkeypatch, scheduled=False, age_h=1.0)
    assert csh.heal(dry=False)["acted"] == []
    assert shell.installed == []
    _status(monkeypatch, scheduled=False, age_h=200.0)                 # still checked for staleness
    assert csh.heal(dry=False)["acted"] == ["demo_lane:re-ran remediate"]
    assert shell.installed == []


def test_superseded_and_retired_rows(tmp_path):
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps({"lanes": [
        {"lane_id": "a", "state": "RETIRED", "superseded_by": "health-tick",
         "scheduler": {"kind": "cron", "match": "a_lane.py"}},
        {"lane_id": "b", "state": "RETIRED", "scheduler": {"kind": "cron", "match": "b_lane.py"}},
        {"lane_id": "c", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "c_lane.py"}},
    ]}))
    assert csh._registry_scheduler("a_lane.py", reg)[0] == "elsewhere"
    assert csh._registry_scheduler("b_lane.py", reg)[0] == "retired"
    assert csh._registry_scheduler("c_lane.py", reg) is None
    assert csh._registry_scheduler("unknown.py", reg) is None


def test_an_active_cron_row_stops_the_scan(tmp_path):
    """Per the docstring an ACTIVE cron row means "crontab is truth": a later RETIRED
    row that shares the match (an old lane id for the same script) must not win."""
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps({"lanes": [
        {"lane_id": "now", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "same.py"}},
        {"lane_id": "old", "state": "RETIRED", "scheduler": {"kind": "cron", "match": "same.py"}},
    ]}))
    assert csh._registry_scheduler("same.py", reg) is None


def test_python_falls_back_to_a_real_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(csh, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("TRADEAI_PY", raising=False)
    monkeypatch.setenv("PY", str(tmp_path / "missing" / "python"))
    assert csh._python() == sys.executable
    assert Path(csh._python()).is_file()


def test_dry_run_reports_without_side_effects(heal_env, monkeypatch):
    shell, notified, _reg, root = heal_env
    _status(monkeypatch, scheduled=True, age_h=200.0)
    out = csh.heal(dry=True)
    assert out["acted"] == ["demo_lane:re-ran remediate"] and out["dry"] is True
    assert shell.calls == [] and notified == [] and not (root / "state.json").exists()
