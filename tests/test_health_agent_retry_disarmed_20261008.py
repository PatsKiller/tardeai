"""2026-10-08: every retry_cmd in system_health_agent began with .venv/bin/python, absent from the served tree,
so every self-heal retry since the crons-to-CURRENT migration exited 127. The interpreter is now the agent's
own (sys.executable); the retry path stays DISARMED unless TRADEAI_HEALTH_AGENT_RETRY=1 because arming ~20
commands (some launch senders or daemons) is an operator decision."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "system_health_agent.py").read_text()
sys.path.insert(0, str(ROOT / "scripts"))


class _NoConn:
    closed = 1

    def cursor(self):
        raise RuntimeError("no db in tests")

    def rollback(self):
        pass


def test_disarmed_by_default_returns_false_and_runs_nothing(monkeypatch, tmp_path):
    import system_health_agent as agent
    monkeypatch.delenv("TRADEAI_HEALTH_AGENT_RETRY", raising=False)
    marker = tmp_path / "ran"
    comp = {"component": "disarm-test", "retry_cmd": f"touch {marker}"}
    agent._RETRY_DISARMED_LOGGED.discard("disarm-test")
    assert agent._attempt_retry(comp, _NoConn()) is False
    assert not marker.exists()
    assert "disarm-test" in agent._RETRY_DISARMED_LOGGED


def test_armed_rewrites_the_dev_venv_interpreter_to_the_running_one(monkeypatch, tmp_path):
    import system_health_agent as agent
    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "1")
    marker = tmp_path / "ran.txt"
    comp = {"component": "arm-test", "retry_cmd": f".venv/bin/python -c \"open('{marker}','w').write('x')\""}
    assert agent._attempt_retry(comp, _NoConn()) is True
    assert marker.read_text() == "x"      # ran under sys.executable, not a missing .venv


def test_every_dev_venv_retry_cmd_is_rewritten_before_execution():
    i = SRC.index("def _attempt_retry(")
    body = SRC[i:SRC.index("def _is_portfolio_market_hours")]
    assert 'cmd.startswith(".venv/bin/python")' in body and "sys.executable" in body
    assert body.index("TRADEAI_HEALTH_AGENT_RETRY") < body.index("retries_today = 0")
    tree = ast.parse(SRC)
    comps = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "MONITORED_COMPONENTS" for t in n.targets))
    dev = [c["component"] for c in comps if str(c.get("retry_cmd") or "").startswith(".venv/bin/python")]
    assert dev, "if no retry_cmd starts with .venv/bin/python any more, retire the rewrite"
