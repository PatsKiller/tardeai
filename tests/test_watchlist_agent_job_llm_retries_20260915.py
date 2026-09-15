"""2026-09-15: capped / circuit-open / input-limit agent jobs are deferred and retried, not failed."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text(encoding="utf-8")


def _ns():
    tree = ast.parse(SRC)
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "LLM_RETRY_POLICY" for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name in {"classify_llm_failure", "requeue_deferred_llm_retries"})]
    mod = ast.Module(body=keep, type_ignores=[])
    ns: dict = {}
    exec(compile(mod, "retry_policy", "exec"), ns)
    return ns


def test_cost_cap_is_retryable_with_two_hour_delay():
    r = _ns()["classify_llm_failure"]("LLM error: COST_CAP_EXCEEDED: global cap", "")
    assert r == {"retry": True, "tag": "cost_cap", "delay_minutes": 120, "attempt": 1}


def test_circuit_open_retries_after_twenty_minutes():
    r = _ns()["classify_llm_failure"]("LLM error: CIRCUIT_OPEN: agent", "note [retry:circuit_open#1]")
    assert r["retry"] is True and r["delay_minutes"] == 20 and r["attempt"] == 2


def test_ceiling_stops_retrying():
    f = _ns()["classify_llm_failure"]
    note = " [retry:cost_cap#1] [retry:cost_cap#2] [retry:cost_cap#3]"
    assert f("LLM error: COST_CAP_EXCEEDED: global cap", note)["retry"] is False
    assert f("LLM error: INPUT_LIMIT_EXCEEDED: prompt 9000", " [retry:input_limit#1]")["retry"] is False


def test_other_errors_still_fail():
    f = _ns()["classify_llm_failure"]
    assert f("LLM error: provider 500", "")["retry"] is False
    assert f("", "")["retry"] is False and f(None, None)["tag"] is None


def test_requeue_sql_matches_every_retry_tag_and_delay():
    class Cur:
        sql = None
        def execute(self, sql, params=None):
            Cur.sql = sql
        def fetchall(self):
            return [(1,)]
    assert _ns()["requeue_deferred_llm_retries"](Cur()) == [(1,)]
    for tag, minutes in (("cost_cap", 120), ("circuit_open", 20), ("input_limit", 360)):
        assert f"[retry:{tag}#" in Cur.sql and f"{minutes} minutes" in Cur.sql
    assert "status='deferred'" in Cur.sql and "status='queued'" in Cur.sql


def test_failure_branch_defers_before_marking_failed_and_requeue_runs_each_pass():
    i_retry = SRC.index("retry = classify_llm_failure(raw, job.get(\"note\"))")
    i_failed = SRC.index("if not raw or raw.startswith(\"LLM error\"):\n            cur.execute(\"UPDATE watchlist_agent_jobs SET status='failed'")
    assert i_retry < i_failed
    assert "retried = requeue_deferred_llm_retries(cur)" in SRC
