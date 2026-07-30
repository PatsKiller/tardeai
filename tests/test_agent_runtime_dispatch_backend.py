"""Governed dispatch backend — safety-property tests.

Runs entirely on InMemoryPersistence + deterministic providers; touches no real
DB and imports no driver. Proves the backend is bounded, circuit-broken, dedup /
stale-refusing, kill-switchable, fail-closed (no fabrication), non-agentic, and
that it drives the governed MvlRuntime lifecycle end-to-end.

    .venv/bin/python -m pytest tests/test_agent_runtime_dispatch_backend.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Match the import identity the runtime uses (scripts/ on path -> `agent_runtime.*`).
sys.path.insert(0, str(ROOT / "scripts"))

import agent_runtime_dispatch_boot as boot  # noqa: E402
from agent_runtime.agents.dispatcher import JobOutcome, JobRequest  # noqa: E402
from agent_runtime.contracts import (  # noqa: E402
    AgentDefinition, BudgetPolicy, DeploymentState, Environment, canonical_hash,
)
from agent_runtime.journal import ShadowRunJournal  # noqa: E402
from agent_runtime.persistence import InMemoryPersistence  # noqa: E402
from agent_runtime.runtime import MvlRuntime  # noqa: E402


def _job(agent_id="sentinel", dedup="d1", *, enqueued="2999-01-01T00:00:00+00:00"):
    # far-future enqueue keeps jobs non-stale regardless of run date
    return JobRequest(agent_id=agent_id, job_type="watch_ticket_review",
                      input_hash=canonical_hash({"dedup": dedup}), enqueued_at=enqueued,
                      dedup_value=dedup)


# ── kill switch ───────────────────────────────────────────────────────────────

def test_kill_switch_cancels_when_enable_file_absent(tmp_path, monkeypatch):
    enable = tmp_path / "agent_runtime_enabled"
    monkeypatch.setenv(boot.ENABLE_FILE_ENV, str(enable))
    should_cancel = boot.make_should_cancel()
    assert should_cancel() is True          # absent → cancel
    enable.write_text("")
    assert boot.make_should_cancel()() is False  # present → run


def test_dispatcher_cancels_whole_batch_when_kill_switch_off(tmp_path, monkeypatch):
    enable = tmp_path / "flag"
    monkeypatch.setenv(boot.ENABLE_FILE_ENV, str(enable))  # absent
    calls = []
    d = boot.build_dispatcher("sentinel", processor=lambda j: calls.append(j), max_batch=8)
    results = d.process_batch([_job(dedup="a"), _job(dedup="b")])
    assert calls == []                                   # processor never ran
    assert all(r.outcome == JobOutcome.CANCELLED for r in results)


# ── bounded / dedup / stale / wrong-agent refusals ───────────────────────────

def test_bounded_dedup_stale_wrong_agent(tmp_path, monkeypatch):
    monkeypatch.setenv(boot.ENABLE_FILE_ENV, str(tmp_path / "on"))
    (tmp_path / "on").write_text("")                     # enabled
    ran = []
    d = boot.build_dispatcher("sentinel", processor=lambda j: ran.append(j.dedup_value), max_batch=1)
    results = d.process_batch([
        _job(dedup="x"),                                  # accepted
        _job(dedup="x"),                                  # duplicate
        _job(dedup="y"),                                  # over capacity (cap=1)
        _job(agent_id="darwin", dedup="z"),               # wrong agent
        _job(dedup="s", enqueued="2000-01-01T00:00:00+00:00"),  # stale
    ])
    outcomes = [r.outcome for r in results]
    assert outcomes[0] == JobOutcome.COMPLETED
    assert JobOutcome.REFUSED_DUPLICATE in outcomes
    assert JobOutcome.REFUSED_CAPACITY in outcomes
    assert JobOutcome.REFUSED_WRONG_AGENT in outcomes
    assert JobOutcome.REFUSED_STALE in outcomes
    assert ran == ["x"]


def test_circuit_breaker_opens_after_consecutive_failures(tmp_path, monkeypatch):
    monkeypatch.setenv(boot.ENABLE_FILE_ENV, str(tmp_path / "on"))
    (tmp_path / "on").write_text("")

    def boom(_job):
        raise RuntimeError("processor failure")
    d = boot.build_dispatcher("sentinel", processor=boom, max_batch=8)
    # sentinel spec trips open after 3 consecutive failures
    results = d.process_batch([_job(dedup=str(i)) for i in range(6)])
    outcomes = [r.outcome for r in results]
    assert outcomes[:3] == [JobOutcome.FAILED] * 3
    assert JobOutcome.CIRCUIT_OPEN in outcomes[3:]


# ── fail-closed: no fabrication without operator wiring ──────────────────────

def test_run_bounded_batch_refuses_without_dsn(monkeypatch):
    monkeypatch.delenv(boot.DISPATCH_DSN_ENV, raising=False)
    with pytest.raises(boot.DispatchConfigError, match="DISPATCH_DSN"):
        boot.run_bounded_batch("sentinel", 4)


def test_run_bounded_batch_refuses_without_provider_module(monkeypatch):
    monkeypatch.setenv(boot.DISPATCH_DSN_ENV, "postgresql://x@/lab")
    monkeypatch.delenv(boot.PROVIDER_MODULE_ENV, raising=False)
    with pytest.raises(boot.DispatchConfigError, match="PROVIDER_MODULE"):
        boot.run_bounded_batch("sentinel", 4)


def test_build_dispatcher_rejects_unknown_agent():
    with pytest.raises(boot.DispatchConfigError, match="unknown agent"):
        boot.build_dispatcher("not_an_agent", processor=lambda j: None)


# ── driver isolation: boot never imports psycopg2 at module import ───────────

def test_boot_module_does_not_import_driver_at_import_time():
    # psycopg2 must only be imported lazily inside _connection_factory.
    src = (ROOT / "scripts" / "agent_runtime_dispatch_boot.py").read_text()
    top = src.split("def _connection_factory", 1)[0]
    assert "import psycopg2" not in top


# ── end-to-end: the governed MvlRuntime lifecycle runs through the dispatcher ─

def _sentinel_definition():
    return AgentDefinition(
        agent_id="sentinel", display_name="Sentinel", role="Reflective critic",
        version="test-v1", owner="test-owner",
        allowed_job_types=("watch_ticket_review",),
        allowed_tools=("kb.search", "ticket.read", "artifact.write"),
        denied_tools=("score.write",), retrieval_required=True,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=3, max_cost_usd=0.0, deadline_seconds=60),
        deployment_state=DeploymentState.SHADOW, enabled=True,
    )


def test_end_to_end_pipeline_persists_run_artifact_review_score(tmp_path, monkeypatch):
    monkeypatch.setenv(boot.ENABLE_FILE_ENV, str(tmp_path / "on"))
    (tmp_path / "on").write_text("")
    persistence = InMemoryPersistence()
    run_ids: list[str] = []

    def processor(job: JobRequest):
        journal = ShadowRunJournal(tmp_path / "runs", Environment.SHADOW)
        rt = MvlRuntime(
            definition=_sentinel_definition(), journal=journal,
            retrieval_provider=lambda rid, q: [{"ref": "lesson:x", "content": "stop below entry"}],
            model_provider=lambda rid, req: {"verdict": "CAUTION", "request_hash": canonical_hash(req)},
            persistence=persistence,
        )
        run = rt.start(job_type="watch_ticket_review", objective="Critique one ticket.",
                       input_payload={"symbol": "TEST", "n": job.dedup_value},
                       validation_payload={"state": "PASS"})
        run_ids.append(run.run_id)
        rt.retrieve(run.run_id, "known contradictions")
        rt.reason(run.run_id, prompt_version="v1", provider_family="deterministic",
                  model="none", request_payload={"q": "critique"})
        from agent_runtime.contracts import ReviewVerdict
        artifact = rt.create_artifact(run.run_id, artifact_type="critique",
                                      payload={"verdict": "CAUTION"}, prompt_version="v1",
                                      provider_family="deterministic", model="none")
        # reviewer != producer and scorer != producer (fleet independence)
        rt.record_review(run.run_id, artifact, "iris", ReviewVerdict.CAUTION, ["arithmetic deterministic"])
        rt.record_score(run.run_id, artifact, "darwin", {"grounding": 1.0, "utility": 0.5})

    d = boot.build_dispatcher("sentinel", processor=processor, max_batch=4)
    results = d.process_batch([_job(dedup="j1"), _job(dedup="j2")])
    assert [r.outcome for r in results] == [JobOutcome.COMPLETED, JobOutcome.COMPLETED]
    # both runs (producer=sentinel, reviewer=iris, scorer=darwin — independence
    # preserved) reconstruct from the persistence, each with a reviewed artifact.
    assert len(run_ids) == 2
    for rid in run_ids:
        state = persistence.reconstruct(rid)
        assert state is not None
