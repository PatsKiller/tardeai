"""2026-10-07: the first health-tick receipt showed system_health_agent --apply exiting 1 on every run.

Cause: the shared db_adapter connection was closed mid-run, `_attempt_retry`'s count SELECT raised, and the
retry log line then read an unbound `retries_today` (1,082 tracebacks in logs/system_health_agent.log).
Two components also pointed at jobs that no longer exist in that shape: the retired 08:05 aegis sender and
the telegram handler that became a systemd unit. Hermetic: no DB, no subprocess beyond `true`."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "scripts" / "system_health_agent.py"
SRC = SRC_PATH.read_text()
sys.path.insert(0, str(ROOT / "scripts"))


def _components():
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "MONITORED_COMPONENTS" for t in targets):
                return ast.literal_eval(node.value)
    raise AssertionError("MONITORED_COMPONENTS not found")


class _DeadConn:
    """A connection whose every operation raises, like psycopg2 after `connection already closed`."""
    closed = 1

    def cursor(self):
        raise RuntimeError("connection already closed")

    def rollback(self):
        raise RuntimeError("connection already closed")

    def commit(self):
        raise RuntimeError("connection already closed")


def test_a_dead_connection_does_not_crash_the_retry_path():
    import system_health_agent as agent
    comp = {"component": "unit-test", "retry_cmd": "true"}
    assert agent._attempt_retry(comp, _DeadConn()) is True   # `true` exits 0; the count query failing is logged, not fatal


def test_retries_today_is_bound_before_the_query_can_fail():
    i = SRC.index("def _attempt_retry(")
    body = SRC[i:SRC.index("def _is_portfolio_market_hours")]
    assert body.index("retries_today = 0") < body.index("cur.execute(")


def test_the_loop_refetches_a_closed_connection_before_each_component():
    i = SRC.index("for comp in MONITORED_COMPONENTS:")
    head = SRC[i:i + 900]
    assert 'getattr(conn, "closed", 0)' in head and "conn = _get_conn()" in head


def test_the_retired_aegis_sender_is_neither_checked_nor_retried():
    comp = next(c for c in _components() if c["component"] == "aegis_morning_brief")
    assert comp.get("retired") and not comp.get("retry_cmd")
    assert not any("aegis_morning_brief_delivery.py" in str(c.get("retry_cmd") or "") for c in _components())


def test_the_telegram_poller_is_monitored_but_never_relaunched():
    comp = next(c for c in _components() if c["component"] == "telegram_command_handler")
    assert not comp.get("retry_cmd"), "a second --poll process would duplicate getUpdates polling"
    assert comp["log_file"] == "telegram_callback_poller.log" and comp["critical"] is True
    assert not any("telegram_command_handler.py --poll" in str(c.get("retry_cmd") or "") for c in _components())


def test_logs_resolve_against_the_state_root_when_absent_from_the_code_tree(tmp_path, monkeypatch):
    import system_health_agent as agent
    state = tmp_path / "state"
    (state / "logs").mkdir(parents=True)
    (state / "logs" / "unit.log").write_text("x")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    assert agent._resolve_log("unit.log") == state / "logs" / "unit.log"
    # a log that exists in neither place still reports under the code tree (MISSING, not an exception)
    assert agent._resolve_log("never.log") == agent.PROJECT_ROOT / "logs" / "never.log"
    assert SRC.count("_resolve_log(log_file)") == 3, "all three freshness/validity readers share the resolver"
