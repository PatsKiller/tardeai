"""2026-10-08: every retry_cmd in system_health_agent began with .venv/bin/python, absent from the served tree,
so every self-heal retry since the crons-to-CURRENT migration exited 127. The interpreter is now the agent's
own (sys.executable); the retry path stays DISARMED unless TRADEAI_HEALTH_AGENT_RETRY=1 because arming ~20
commands (some launch senders or daemons) is an operator decision."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "system_health_agent.py").read_text()
sys.path.insert(0, str(ROOT / "scripts"))


class _NoConn:
    closed = 1

    def cursor(self):
        raise RuntimeError("no db in tests")

    def rollback(self):
        pass


@pytest.fixture
def retry_process(monkeypatch, tmp_path):
    """A strict child-result seam; this fixture never launches a process."""
    import system_health_agent as agent

    code_root = tmp_path / "source"
    code_root.mkdir()
    monkeypatch.setattr(agent, "PROJECT_ROOT", code_root)
    state = {"expected": None, "marker": None, "calls": [], "events": [], "unexpected": []}

    def refuse(*args, **kwargs):
        state["unexpected"].append("unexpected command")
        raise AssertionError("retry fixture forbids external commands")

    class CompletedChild:
        returncode = 0

        def communicate(self, *, timeout):
            assert 0 < timeout <= 300
            # Controlled completion artifact, not proof of interpreter execution.
            state["marker"].write_text("x", encoding="utf-8")
            return "fixture child completed", ""

    def popen(command, **kwargs):
        expected_kwargs = {
            "shell": True,
            "stdout": agent.subprocess.PIPE,
            "stderr": agent.subprocess.PIPE,
            "text": True,
            "cwd": str(code_root),
            "start_new_session": True,
        }
        if state["expected"] is None or command != state["expected"] or kwargs != expected_kwargs:
            return refuse()
        state["calls"].append(command)
        return CompletedChild()

    def event(conn, component, event_type, severity, message, *, action=None, success=None):
        state["events"].append((component, event_type, severity, action, success))

    monkeypatch.setattr(agent.subprocess, "Popen", popen)
    monkeypatch.setattr(agent.subprocess, "run", refuse)
    monkeypatch.setattr(agent.os, "system", refuse)
    monkeypatch.setattr(agent, "_log_event", event)
    yield state
    assert not state["unexpected"], state["unexpected"]


def test_disarmed_by_default_returns_false_and_runs_nothing(monkeypatch, tmp_path, retry_process):
    import system_health_agent as agent

    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)
    marker = tmp_path / "ran"
    comp = {"component": "disarm-test", "retry_cmd": f"touch {marker}"}
    agent._RETRY_DISARMED_LOGGED.discard("disarm-test")
    assert agent._attempt_retry(comp, _NoConn()) is False
    assert not marker.exists()
    assert "disarm-test" in agent._RETRY_DISARMED_LOGGED
    assert not retry_process["calls"] and not retry_process["events"]


def test_armed_rewrites_the_dev_venv_interpreter_to_the_running_one(monkeypatch, tmp_path, retry_process):
    import system_health_agent as agent

    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "1")
    marker = tmp_path / "ran.txt"
    comp = {"component": "arm-test", "retry_cmd": f".venv/bin/python -c \"open('{marker}','w').write('x')\""}
    expected = f"{sys.executable} -c \"open('{marker}','w').write('x')\""
    retry_process.update(expected=expected, marker=marker)
    # Arming does not create a known budget when DB history is unavailable.
    assert agent._attempt_retry(comp, _NoConn()) is False
    assert not marker.exists() and retry_process["calls"] == []
    assert retry_process["events"] == [("arm-test", "RETRY_BUDGET_HELD", "WARN", None, False)]


def test_known_fixture_budget_preserves_the_running_interpreter(monkeypatch, tmp_path, retry_process):
    import system_health_agent as agent

    class KnownConn:
        def cursor(self):
            return self

        def execute(self, *args):
            pass

        def fetchone(self):
            return (0,)

        def commit(self):
            pass

    state = tmp_path / "fixture-state"
    (state / "data/runtime").mkdir(parents=True)
    (state / "data/runtime/health_retry_attempts.jsonl").write_text("")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setattr(agent, "_health_retry_history", lambda path, now: path.read_text())
    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "1")
    marker = tmp_path / "known-ran.txt"
    cmd = f".venv/bin/python -c \"open('{marker}','w').write('x')\""
    expected = cmd.replace(".venv/bin/python", sys.executable, 1)
    retry_process.update(expected=expected, marker=marker)
    assert agent._attempt_retry({"component": "known-arm-test", "retry_cmd": cmd}, KnownConn()) is True
    assert marker.read_text() == "x"  # fake completion; never business-output proof
    assert retry_process["calls"] == [expected]
    assert retry_process["events"] == [("known-arm-test", "RETRY", "INFO", expected[:100], True)]


def test_every_dev_venv_retry_cmd_is_rewritten_before_execution():
    i = SRC.index("def _attempt_retry(")
    body = SRC[i : SRC.index("def _is_portfolio_market_hours")]
    assert 'cmd.startswith(".venv/bin/python")' in body and "sys.executable" in body
    assert body.index("TRADEAI_HEALTH_AGENT_RETRY") < body.index("retries_today = 0")
    tree = ast.parse(SRC)
    comps = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MONITORED_COMPONENTS" for t in n.targets)
    )
    dev = [c["component"] for c in comps if str(c.get("retry_cmd") or "").startswith(".venv/bin/python")]
    assert dev, "if no retry_cmd starts with .venv/bin/python any more, retire the rewrite"
