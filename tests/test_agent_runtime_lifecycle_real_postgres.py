"""Gated real-LAB end-to-end runtime→persistence integration (TCP 5433, PGPASSFILE).

Skipped everywhere except the operator host proof (AGENTIC_REAL_LAB=1). Drives the
governed MvlRuntime with the authoritative PostgreSQL adapter through the full
lifecycle. Never contacts production port 5432.
"""

from __future__ import annotations

import itertools
import os
from datetime import datetime, timezone

import pytest

psycopg2 = pytest.importorskip("psycopg2")

pytestmark = pytest.mark.skipif(os.getenv("AGENTIC_REAL_LAB") != "1", reason="real LAB runtime integration runs only under the host proof")

from scripts.agent_runtime.contracts import (  # noqa: E402
    AgentDefinition,
    BudgetPolicy,
    DeploymentState,
    Environment,
    ReviewVerdict,
)
from scripts.agent_runtime.journal import ShadowRunJournal  # noqa: E402
from scripts.agent_runtime.persistence import PostgresPersistence  # noqa: E402
from scripts.agent_runtime.runtime import MvlRuntime  # noqa: E402

_LAB_HOST = os.getenv("AGENTIC_LAB_HOST", "127.0.0.1")
_LAB_DB = os.getenv("AGENTIC_LAB_DB", "trade_ai_agentic_lab")
_LAB_ROLE = os.getenv("AGENTIC_LAB_ROLE", "agentic_runtime_lab_rw")
_c = itertools.count()


def _factory():
    conn = psycopg2.connect(host=_LAB_HOST, port=5433, dbname=_LAB_DB, user=_LAB_ROLE,
                            options="-c search_path=agentic_runtime")
    conn.autocommit = False
    return conn


def _pgclock():
    return lambda: f"2026-07-25T04:00:{next(_c):02d}.000000+00:00"


def _runtime(tmp_path):
    defn = AgentDefinition(
        agent_id="alpha_agent", display_name="A", role="researcher", version="1.0", owner="o",
        allowed_job_types=("research",), allowed_tools=("kb.search",), retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=5, max_cost_usd=1.0, deadline_seconds=3600),
        deployment_state=DeploymentState.SHADOW, enabled=True)
    journal = ShadowRunJournal(str(tmp_path), Environment.SHADOW)
    return MvlRuntime(defn, journal,
                      retrieval_provider=lambda run_id, q: [{"ref": "kb:1", "text": "x"}],
                      model_provider=lambda run_id, req: {"text": "analysis"},
                      clock=lambda: datetime(2026, 7, 25, tzinfo=timezone.utc),
                      persistence=PostgresPersistence(_factory, clock=_pgclock()))


def test_real_end_to_end_runtime_lifecycle(tmp_path):
    rt = _runtime(tmp_path)
    env = rt.start(job_type="research", objective="assess", input_payload={"a": next(_c)}, validation_payload={"b": 2})
    rt.retrieve(env.run_id, "levels")

    # The executor reads the durable journal mid-execution: TOOL_PROPOSED -> TOOL_DECISION ->
    # TOOL_STARTED must already be committed to PostgreSQL before any external side effect runs,
    # and no terminal TOOL_COMPLETED may exist yet.
    def executor(args):
        live = [e.event_type for e in rt.persistence.journal(env.run_id)]
        tail = live[live.index("TOOL_PROPOSED"):]
        assert tail[:3] == ["TOOL_PROPOSED", "TOOL_DECISION", "TOOL_STARTED"]
        assert "TOOL_COMPLETED" not in live
        return {"r": 1}

    rt.invoke_tool(env.run_id, "kb.search", {"q": 1}, executor)
    rt.reason(env.run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1}, cost_usd=0.2)
    art = rt.create_artifact(env.run_id, artifact_type="analysis", payload={"finding": "x"},
                             prompt_version="p", provider_family="local", model="m")
    rt.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt.complete(env.run_id)
    rt.record_score(env.run_id, art, "gamma_agent", {"quality": 0.5})  # post-terminal

    st = rt.status(env.run_id)
    assert st["status"] == "COMPLETED"
    assert st["retrieval_count"] == 1 and st["model_calls"] == 1 and st["tool_calls"] == 1
    assert st["artifact"] and st["review"] and st["score"]

    # a fresh runtime instance reconstructs the same authoritative state from PostgreSQL
    fresh = _runtime(tmp_path)
    assert fresh.status(env.run_id)["status"] == "COMPLETED"
    order = [e.event_type for e in fresh.persistence.journal(env.run_id)]
    for stage in ("RUN_CREATED", "RETRIEVAL_COMPLETED", "MODEL_COMPLETED", "ARTIFACT_CREATED",
                  "REVIEW_RECORDED", "RUN_COMPLETED", "SCORE_RECORDED", "TOOL_COMPLETED"):
        assert stage in order
