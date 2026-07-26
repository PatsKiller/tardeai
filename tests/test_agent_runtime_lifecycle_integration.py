"""In-memory integration tests: the governed runtime using persistence end to end.

When a RunPersistence adapter is injected, the persistence layer is the single
authoritative lifecycle state and ShadowRunJournal is not used.
"""

from __future__ import annotations

import itertools
import threading
from datetime import datetime, timedelta, timezone

import pytest

from scripts.agent_runtime.contracts import (
    AgentDefinition,
    BudgetPolicy,
    DeploymentState,
    Environment,
    RunEnvelope,
    ReviewVerdict,
    canonical_hash,
)
from scripts.agent_runtime.journal import ShadowRunJournal
from scripts.agent_runtime.persistence import IdempotencyConflictError, InMemoryPersistence, PersistenceError
from scripts.agent_runtime.runtime import MvlRuntime

_H = "a" * 64


class Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


def _pclock():
    c = itertools.count()
    return lambda: f"2026-07-25T03:00:{next(c):02d}.000000+00:00"


def _defn(deadline=3600, retrieval_required=True):
    return AgentDefinition(
        agent_id="alpha_agent", display_name="A", role="researcher", version="1.0", owner="o",
        allowed_job_types=("research",), allowed_tools=("kb.search",), retrieval_required=retrieval_required,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=5, max_cost_usd=1.0, deadline_seconds=deadline),
        deployment_state=DeploymentState.SHADOW, enabled=True)


def _runtime(tmp_path, *, persistence, clock=None, deadline=3600, retrieval_required=True):
    journal = ShadowRunJournal(str(tmp_path), Environment.SHADOW)
    retr = lambda run_id, query: [{"ref": "kb:1", "text": "x"}]
    model = lambda run_id, req: {"text": "analysis"}
    return MvlRuntime(_defn(deadline, retrieval_required), journal, retr, model,
                      clock=clock or (lambda: datetime(2026, 7, 25, tzinfo=timezone.utc)), persistence=persistence)


def _start(rt):
    return rt.start(job_type="research", objective="assess", input_payload={"a": 1}, validation_payload={"b": 2})


def _drive_to_review(rt, run_id):
    rt.retrieve(run_id, "levels")
    rt.reason(run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1}, cost_usd=0.2)
    return rt.create_artifact(run_id, artifact_type="analysis", payload={"finding": "x"},
                              prompt_version="p", provider_family="local", model="m")


# --------------------------------------------------------------------------- #
def test_full_lifecycle_persistence_authoritative(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    art = _drive_to_review(rt, env.run_id)
    rt.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt.complete(env.run_id)
    rt.record_score(env.run_id, art, "gamma_agent", {"quality": 0.5})  # permitted post-terminal
    st = rt.status(env.run_id)
    assert st["status"] == "COMPLETED"
    assert st["retrieval_count"] == 1 and st["model_calls"] == 1 and abs(st["cost_usd"] - 0.2) < 1e-9
    assert st["artifact"] and st["review"] and st["score"]
    assert list(rt.journal.list_run_ids()) == []  # journal never used as authority


def test_exact_durable_event_order(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    art = _drive_to_review(rt, env.run_id)
    rt.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt.complete(env.run_id)
    rt.record_score(env.run_id, art, "gamma_agent", {"quality": 0.5})
    order = [e.event_type for e in p.journal(env.run_id)]
    assert order == [
        "RUN_CREATED", "RETRIEVAL_STARTED", "RETRIEVAL_COMPLETED", "MODEL_STARTED",
        "MODEL_COMPLETED", "ARTIFACT_CREATED", "REVIEW_RECORDED", "RUN_COMPLETED", "SCORE_RECORDED",
    ]


def test_counters_costs_checkpoints_reconstruct(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    rt.reason(env.run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1}, cost_usd=0.3)
    rs = p.reconstruct(env.run_id)
    assert rs.retrieval_count == 1 and rs.model_calls == 1 and abs(rs.cost_usd - 0.3) < 1e-9
    assert rs.checkpoint == "model_complete" and rs.status == "REVIEW_REQUIRED"
    assert rs.retrieval_refs == ("kb:1",)


def test_tool_success_and_failure_reconstruct_durably(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    rt.invoke_tool(env.run_id, "kb.search", {"q": 1}, lambda a: {"r": 1})

    def boom(_):
        raise ValueError("tool blew up")

    with pytest.raises(ValueError):
        rt.invoke_tool(env.run_id, "kb.search", {"q": 2}, boom)
    types = [e.event_type for e in p.journal(env.run_id)]
    assert "TOOL_COMPLETED" in types and "TOOL_FAILED" in types
    assert rt.status(env.run_id)["tool_calls"] == 2


def test_persistence_failure_fails_closed_before_provider(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    calls = {"n": 0}
    rt.model_provider = lambda run_id, req: (calls.__setitem__("n", calls["n"] + 1), {"text": "x"})[1]

    def explode(*a, **k):
        raise PersistenceError("durable write failed")

    p.record_model_started = explode
    with pytest.raises(PersistenceError):
        rt.reason(env.run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1})
    assert calls["n"] == 0  # provider was never called — failed closed before the side effect


def test_no_divergence_between_status_and_reconstruction(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    _drive_to_review(rt, env.run_id)
    st = rt.status(env.run_id)
    rs = p.reconstruct(env.run_id)
    assert st["status"] == rs.status
    assert st["retrieval_count"] == rs.retrieval_count and st["model_calls"] == rs.model_calls
    assert st["checkpoint"] == rs.checkpoint and st["cost_usd"] == rs.cost_usd


def test_terminal_execution_cannot_resume_or_mutate(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    art = _drive_to_review(rt, env.run_id)
    rt.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt.complete(env.run_id)
    with pytest.raises(RuntimeError):  # terminal exec mutation blocked
        rt.create_artifact(env.run_id, artifact_type="analysis", payload={"finding": "late"},
                           prompt_version="p", provider_family="local", model="m")
    failed = _start(rt)
    rt.retrieve(failed.run_id, "levels")
    rt.fail(failed.run_id, "boom")
    with pytest.raises(RuntimeError):  # failed run cannot resume
        rt.resume(failed.run_id)


def test_deadline_exceeded_is_durably_recorded(tmp_path):
    clock = Clock(datetime(2026, 7, 25, tzinfo=timezone.utc))
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p, clock=clock, deadline=5)
    env = _start(rt)
    clock.advance(120)  # blow past the 5s deadline
    with pytest.raises(TimeoutError):
        rt.retrieve(env.run_id, "levels")
    rs = p.reconstruct(env.run_id)
    assert rs.status == "FAILED" and rs.failure_code == "DEADLINE_EXCEEDED"


def test_fresh_runtime_reconstructs_latest_checkpoint(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt1 = _runtime(tmp_path / "a", persistence=p)
    env = _start(rt1)
    rt1.retrieve(env.run_id, "levels")
    rt1.reason(env.run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1}, cost_usd=0.1)
    # a fresh runtime instance sharing the same persistence authority
    rt2 = _runtime(tmp_path / "b", persistence=p)
    st = rt2.status(env.run_id)
    assert st["status"] == "REVIEW_REQUIRED" and st["model_calls"] == 1 and st["checkpoint"] == "model_complete"
    art = rt2.create_artifact(env.run_id, artifact_type="analysis", payload={"finding": "x"},
                              prompt_version="p", provider_family="local", model="m")
    rt2.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt2.complete(env.run_id)
    assert p.reconstruct(env.run_id).status == "COMPLETED"


def test_journal_only_mode_remains_backward_compatible(tmp_path):
    rt = _runtime(tmp_path, persistence=None)
    env = _start(rt)
    art = _drive_to_review(rt, env.run_id)
    rt.record_review(env.run_id, art, "beta_agent", ReviewVerdict.PASS, [])
    rt.complete(env.run_id)
    assert rt.status(env.run_id)["status"] == "COMPLETED"
    assert env.run_id in list(rt.journal.list_run_ids())  # journal is the authority here


# --------------------------- tool pre-execution boundary ------------------ #
def test_tool_started_is_durable_before_executor_runs(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    seen = {}

    def executor(args):
        seen["types"] = [e.event_type for e in p.journal(env.run_id)]  # durable BEFORE the side effect
        return {"r": 1}

    rt.invoke_tool(env.run_id, "kb.search", {"q": 1}, executor)
    assert {"TOOL_PROPOSED", "TOOL_DECISION", "TOOL_STARTED"} <= set(seen["types"])
    assert "TOOL_COMPLETED" not in seen["types"]  # completion recorded only AFTER the executor


def test_prepare_persistence_failure_prevents_executor(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    calls = {"n": 0}

    def boom(*a, **k):
        raise PersistenceError("prepare failed")

    p.prepare_tool_call = boom
    with pytest.raises(PersistenceError):
        rt.invoke_tool(env.run_id, "kb.search", {"q": 1}, lambda a: (calls.__setitem__("n", calls["n"] + 1), {"r": 1})[1])
    assert calls["n"] == 0


def test_deny_never_invokes_executor_and_has_durable_denied_evidence(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    calls = {"n": 0}
    with pytest.raises(PermissionError):
        rt.invoke_tool(env.run_id, "not.allowlisted", {"q": 1}, lambda a: (calls.__setitem__("n", calls["n"] + 1), {"r": 1})[1])
    assert calls["n"] == 0
    types = [e.event_type for e in p.journal(env.run_id)]
    assert "TOOL_PROPOSED" in types and "TOOL_DECISION" in types and "TOOL_CANCELLED" in types
    assert "TOOL_STARTED" not in types
    assert p.reconstruct(env.run_id).tool_calls == 0  # denied call reserves no budget


def test_terminal_persistence_failure_leaves_reconstructable_in_flight(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path / "a", persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")

    def boom(*a, **k):
        raise PersistenceError("terminal write failed")

    p.finish_tool_call = boom
    with pytest.raises(PersistenceError):
        rt.invoke_tool(env.run_id, "kb.search", {"q": 1}, lambda a: {"r": 1})  # executor ran, terminal write failed
    types = [e.event_type for e in p.journal(env.run_id)]
    assert "TOOL_STARTED" in types                          # durable in-flight evidence
    assert "TOOL_COMPLETED" not in types and "TOOL_FAILED" not in types  # no fabricated completion
    assert p.reconstruct(env.run_id).tool_calls_ids == ()   # no terminal tool-call row
    # a fresh runtime/persistence instance reconstructs the in-flight call
    rt2 = _runtime(tmp_path / "b", persistence=p)
    assert rt2.status(env.run_id)["tool_calls"] == 1        # budget reserved, terminal not recorded
    assert p.reconstruct(env.run_id).tool_calls_ids == ()   # no terminal tool-call row exists


def test_finish_idempotent_and_conflict_and_requires_prepare(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path, persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    ah = canonical_hash({"q": 1})
    started = "2026-07-25T02:00:00.000000+00:00"
    prep = p.prepare_tool_call(env.run_id, agent_id="alpha_agent", tool_name="kb.search",
                               decision="ALLOW", decision_reason="ok", arguments_hash=ah, started_at=started)
    args = dict(run_id=env.run_id, tool_call_id=prep.tool_call_id, agent_id="alpha_agent", tool_name="kb.search",
                decision_reason="ok", arguments_hash=ah, started_at=started, completed_at=started)
    tid = p.finish_tool_call(result_hash=_H, terminal_state="completed", **args)
    assert p.finish_tool_call(result_hash=_H, terminal_state="completed", **args) == tid  # identical -> idempotent
    with pytest.raises(IdempotencyConflictError):
        p.finish_tool_call(result_hash="b" * 64, terminal_state="completed", **args)      # conflict -> fail closed
    with pytest.raises(PersistenceError):  # finish without a prepared lifecycle
        p.finish_tool_call(run_id=env.run_id, tool_call_id="deadbeef" * 8, agent_id="alpha_agent", tool_name="kb.search",
                           decision_reason="ok", arguments_hash=ah, result_hash=_H, started_at=started,
                           completed_at=started, terminal_state="completed")


def test_concurrent_preparation_cannot_exceed_budget(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    env = RunEnvelope(run_id="r_budget", agent_id="alpha_agent", agent_version="1.0", job_type="research",
                      environment=Environment.LAB, objective="assess", input_hash=_H, validation_hash=_H,
                      created_at="2026-07-25T02:00:00+00:00")
    p.create_run(env, BudgetPolicy(max_tool_calls=1))
    results: list[str] = []

    def worker(i):
        prep = p.prepare_tool_call("r_budget", agent_id="alpha_agent", tool_name=f"kb.search{i}",
                                   decision="ALLOW", decision_reason="ok", arguments_hash=_H,
                                   started_at=f"2026-07-25T02:00:1{i}+00:00")
        results.append(prep.decision)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ALLOW") == 1 and results.count("DENY") == 5
    assert p.reconstruct("r_budget").tool_calls == 1


# ------------------- run-control projection at runtime level --------------- #
def test_fresh_runtime_creates_artifact_with_persisted_retrieval_refs(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path / "a", persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    rt.reason(env.run_id, prompt_version="p", provider_family="local", model="m", request_payload={"q": 1}, cost_usd=0.2)
    # a fresh runtime reconstructs the run from persistence and must carry its retrieval refs
    rt2 = _runtime(tmp_path / "b", persistence=p)
    art = rt2.create_artifact(env.run_id, artifact_type="analysis", payload={"finding": "x"},
                              prompt_version="p", provider_family="local", model="m")
    assert art.retrieval_refs == ("kb:1",)


def test_status_and_reconstruction_agree_on_created_at(tmp_path):
    p = InMemoryPersistence(clock=_pclock())
    rt = _runtime(tmp_path / "a", persistence=p)
    env = _start(rt)
    rt.retrieve(env.run_id, "levels")
    rt2 = _runtime(tmp_path / "b", persistence=p)  # fresh instance, reconstructs from persistence
    assert rt2.status(env.run_id)["envelope"]["created_at"] == env.created_at
    assert p.reconstruct(env.run_id).created_at == env.created_at
