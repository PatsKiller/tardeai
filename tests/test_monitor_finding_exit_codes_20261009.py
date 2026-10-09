"""Monitors that report a FINDING by exit code use EXIT_FINDING (3), never 1.

n8n maturity B3.1 (2026-10-09, review of PR #1600): health_tick declared
`finding_rc: [1]` for these three steps, but 1 is also CPython's exit for an
uncaught exception and for sys.exit("fatal ..."), so a crash was recorded as a
finding whenever its stderr did not end in a recognisable exception line. The
monitors now exit 3 for a finding and the table declares `finding_rc: [3]`.

Hermetic: every probe, DB read and alert is stubbed.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from scripts.lib import monitor_exit_codes as codes
from scripts.lib import pipeline_liveness

ROOT = Path(__file__).resolve().parents[1]


def test_finding_code_is_distinct_from_success_and_python_crash():
    assert codes.EXIT_FINDING not in (codes.EXIT_OK, codes.EXIT_PYTHON_CRASH)
    assert codes.EXIT_FINDING == 3


def test_live_table_declares_the_shared_finding_code():
    from scripts import health_tick as ht
    table = ht.load_table(ROOT / "config" / "health_tick_steps.json")
    declared = {s["step_id"]: s.get("finding_rc") for s in table["steps"] if s.get("finding_rc")}
    assert declared == {"system-health-agent": [codes.EXIT_FINDING],
                        "moomoo-opend-health": [codes.EXIT_FINDING],
                        "pipeline-liveness-report": [codes.EXIT_FINDING]}


# ── pipeline_liveness_report --fail-on-finding ──────────────────────────────

def _liveness(monkeypatch, findings):
    from scripts import pipeline_liveness_report as mod
    report = types.SimpleNamespace(to_dict=lambda: {"lanes": [], "findings": findings})
    monkeypatch.setattr(mod, "default_lanes", lambda: [])
    monkeypatch.setattr(mod, "evaluate", lambda lanes: report)
    return mod


@pytest.mark.parametrize("status", ["STARVED", "NO_ELIGIBLE_INPUT", "UNKNOWN"])
def test_liveness_fail_on_finding_exits_finding_code(monkeypatch, status):
    mod = _liveness(monkeypatch, [{"lane": "x", "status": getattr(pipeline_liveness, status)}])
    monkeypatch.setattr(sys, "argv", ["pipeline_liveness_report.py", "--json", "--fail-on-finding"])
    assert mod.main() == codes.EXIT_FINDING


def test_liveness_without_findings_or_flag_exits_zero(monkeypatch):
    mod = _liveness(monkeypatch, [])
    monkeypatch.setattr(sys, "argv", ["pipeline_liveness_report.py", "--json", "--fail-on-finding"])
    assert mod.main() == 0
    mod = _liveness(monkeypatch, [{"lane": "x", "status": "STARVED"}])
    monkeypatch.setattr(sys, "argv", ["pipeline_liveness_report.py", "--json"])
    assert mod.main() == 0


# ── moomoo opend_health ─────────────────────────────────────────────────────

@pytest.fixture
def opend(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))
    try:
        import opend_health as mod
    finally:
        sys.path.remove(str(ROOT / "scripts" / "moomoo"))
    monkeypatch.setattr(mod, "STATE", tmp_path / "opend.json")
    monkeypatch.setattr(mod, "_bump", lambda ok: 0 if ok else 1)
    monkeypatch.setattr(mod, "_unit_active", lambda: (True, "active"))
    monkeypatch.setattr(sys, "argv", ["opend_health.py"])
    return mod


def test_opend_down_is_a_finding_not_a_crash_code(opend, monkeypatch):
    monkeypatch.setattr(opend, "_port_open", lambda: False)
    assert opend.main() == codes.EXIT_FINDING
    assert json.loads(opend.STATE.read_text())["ok"] is False


def test_opend_up_exits_zero(opend, monkeypatch):
    monkeypatch.setattr(opend, "_port_open", lambda: True)
    monkeypatch.setattr(opend, "_quote_ok", lambda: (True, "snapshot ok"))
    assert opend.main() == 0


# ── system_health_agent ─────────────────────────────────────────────────────

@pytest.fixture
def agent(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import system_health_agent as mod
    return mod


def _report(status):
    return {"summary": {"ok": 0, "stale": 0, "missing": 0, "failed": 1, "locked": 0,
                        "retried": 0, "escalated": 0},
            "checks": [{"name": "c", "critical": True, "status": status}]}


def test_agent_critical_down_exits_finding_code(agent, monkeypatch):
    monkeypatch.setattr(agent, "run_health_check", lambda **kw: _report("STALE"))
    monkeypatch.setattr(sys, "argv", ["system_health_agent.py", "--apply"])
    with pytest.raises(SystemExit) as exc:
        agent.main()
    assert exc.value.code == codes.EXIT_FINDING


def test_agent_all_ok_or_dry_run_does_not_exit_nonzero(agent, monkeypatch):
    monkeypatch.setattr(agent, "run_health_check", lambda **kw: _report("OK"))
    monkeypatch.setattr(sys, "argv", ["system_health_agent.py", "--apply"])
    agent.main()
    monkeypatch.setattr(agent, "run_health_check", lambda **kw: _report("STALE"))
    monkeypatch.setattr(sys, "argv", ["system_health_agent.py"])   # dry run
    agent.main()
