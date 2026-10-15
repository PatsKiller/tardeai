"""hermes-pipeline-health: the send is split from the check (2026-10-14, canary wave 1b item 4).

COVERS = ["scripts/hermes_pipeline_health.py"]

The cron line (L578, crontab -l 2026-10-14, read-only) runs `hermes_pipeline_health.py --send`; the canary wave
excluded the lane because the live argv would need `--send` (forbidden token `send`; a sender on the dispatcher).
Evidence that the split costs nothing: `alert_dispatcher_unified` defines no `dispatch()` (only main() and private
helpers), so every cron `--send` raised AttributeError inside a bare `except: pass` and sent nothing. The findings
reach the operator through the alert_events (system_health) and escalation_queue rows, which the run writes with or
without --send. So the dispatcher argv (no --send) does the cron line's real work and is not a sender; the send stays
an optional, separately-recorded step (summary.send) that never decides the exit code.
Hermetic: fake db_adapter / dispatcher modules, TRADEAI_STATE_ROOT = tmp; nothing is sent.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import advisory_lane_guard as G  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

LANE = "hermes-pipeline-health"
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
ISSUES = ["promotion precision 428/2921 (15%) over 30d graded — promotion gates not filtering"]


def _load():
    key = "_tested_pipeline_health_send_split"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, ROOT / "scripts" / "hermes_pipeline_health.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(H, "check", lambda: list(ISSUES))
    monkeypatch.setattr(H.os, "popen", lambda cmd: io.StringIO("2026101412\n"))
    calls = []

    def _execute(sql, params=None, fetch=None):
        calls.append(" ".join(sql.split())[:40])
        return True

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=_execute))
    return tmp_path / "state", calls


def _receipt(state):
    return json.loads((state / "data" / "runtime" / f"{LANE}_last.json").read_text())


def test_the_unified_dispatcher_has_no_dispatch_function():
    """The evidence: `ad.dispatch(...)` cannot succeed against the real module, so cron --send never sent."""
    tree = ast.parse((ROOT / "scripts" / "alert_dispatcher_unified.py").read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    names |= {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "dispatch" not in names


def test_send_without_a_dispatch_function_is_recorded_not_swallowed(monkeypatch, env):
    state, calls = env
    monkeypatch.setitem(sys.modules, "alert_dispatcher_unified", types.SimpleNamespace())  # == the real module's API
    assert H.main(["--send"]) == 0
    rec = _receipt(state)
    assert rec["status"] == "ok" and rec["summary"]["send"] == "not_sent:AttributeError"
    assert [c.split(" (")[0] for c in calls] == ["INSERT INTO alert_events", "INSERT INTO escalation_queue"]


def test_the_dispatcher_argv_does_the_cron_lines_real_work_and_never_imports_the_sender(monkeypatch, env):
    state, calls = env
    monkeypatch.delitem(sys.modules, "alert_dispatcher_unified", raising=False)
    assert H.main(list(ALLOW[LANE]["command"][2:])) == 0
    assert "alert_dispatcher_unified" not in sys.modules
    rec = _receipt(state)
    assert rec["status"] == "ok" and "send" not in rec["summary"] and rec["summary"]["issues"] == 1
    assert [c.split(" (")[0] for c in calls] == ["INSERT INTO alert_events", "INSERT INTO escalation_queue"]


def test_a_working_send_is_recorded_and_never_decides_the_exit(monkeypatch, env):
    state, _ = env
    sent = []
    monkeypatch.setitem(sys.modules, "alert_dispatcher_unified",
                        types.SimpleNamespace(dispatch=lambda **kw: sent.append(kw)))
    assert H.main(["--send"]) == 0 and sent
    assert _receipt(state)["summary"]["send"] == "dispatched"


def test_allowlist_argv_carries_no_send_and_the_reach_is_not_a_sender():
    e = ALLOW[LANE]
    argv = [*e["command"], *(e["live_arg"] or [])]
    assert "--send" not in argv and LD.forbidden_text_hits(" ".join(argv)) == []
    rep = G.scan_entry(G.entry_script(e["command"]))
    assert not rep.is_sender and not rep.broker_modules and not rep.account_reads
