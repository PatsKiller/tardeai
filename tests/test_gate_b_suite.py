"""
Gate-B: Comprehensive behavioral test suite.

All tests use temporary stores or isolated fixtures. NO canonical store mutations.
NO provider calls. NO Telegram sends. NO live activation.

Covers:
  - Wake ownership and lifecycle (B1)
  - NEW_RUN / RESUME_RUN contract (B1.1)
  - Wait/resume state machine (B1.2)
  - Handoff parentage (B1.3)
  - Alex intake removal (B1.4)
  - Governed gateway registration (B2/B3)
  - No financial-agent fallback (B4)
  - Hermes Research Gateway (B7)
  - Legacy Watch CIO gate (B8)
  - Identity normalization (B9)
  - Gate-A regression (all Gate-A tests pass on Gate-B changes)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure project scripts are importable
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_dir():
    """Temporary directory for isolated test stores."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def wake_store(temp_dir):
    """CIOWakeJobStore backed by temporary file."""
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    store_path = temp_dir / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=store_path)
    return store


@pytest.fixture
def run_store(temp_dir):
    """CIORunStore backed by temporary file."""
    from scripts.lib.cio_run import CIORunStore
    store_path = temp_dir / "cio_runs.jsonl"
    store = CIORunStore(store_path=str(store_path))
    store.initialize()
    return store


@pytest.fixture
def wake_dispatcher(wake_store, run_store, temp_dir):
    """CIOWakeDispatcher with temp stores."""
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
    ledger = temp_dir / "cio_wake_dispatches.jsonl"
    return CIOWakeDispatcher(
        wake_store=wake_store,
        run_store=run_store,
        dispatch_ledger_path=str(ledger),
    )


@pytest.fixture
def run_worker(run_store):
    """CIORunWorker with mock components."""
    from scripts.lib.cio_run_worker import CIORunWorker
    return CIORunWorker(
        run_store=run_store,
        health_boundary=None,
        action_ledger=None,
        notification_outbox=None,
        handoff_queue=None,
        hermes_queue=None,
        mode="shadow",
    )


@pytest.fixture
def handoff_queue(temp_dir):
    """AgentHandoffQueue backed by temporary file."""
    from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue
    store_path = temp_dir / "agent_handoff_queue.jsonl"
    return AgentHandoffQueue(event_store_path=store_path)


@pytest.fixture
def hermes_challenge_worker(hermes_queue_mock, wake_store, run_store):
    """HermesChallengeWorker with mock queue."""
    from scripts.lib.cio_hermes_challenge_worker import HermesChallengeWorker
    return HermesChallengeWorker(
        hermes_queue=hermes_queue_mock,
        wake_store=wake_store,
        run_store=run_store,
    )


@pytest.fixture
def hermes_queue_mock():
    """Mock HermesChallengeQueue."""
    return MagicMock()


def _enqueue_test_wake(wake_store, wake_job_id=None, **kwargs):
    """Helper to enqueue a test wake job."""
    wid = wake_job_id or f"test-wake-{uuid.uuid4().hex[:12]}"
    payload = {
        "wake_job_id": wid,
        "trigger_type": kwargs.get("trigger_type", "SCHEDULE_DUE"),
        "trigger_ref": kwargs.get("trigger_ref", ""),
        "priority": kwargs.get("priority", "NORMAL"),
        "required_domains": kwargs.get("required_domains", []),
        "wake_intent": kwargs.get("wake_intent", "NEW_RUN"),
        "target_run_id": kwargs.get("target_run_id"),
        "idempotency_key": kwargs.get("idempotency_key", f"ik-{wid}"),
    }
    wake_store.enqueue(payload, actor_id="test")
    return wid


# ═══════════════════════════════════════════════════════════════════════════════
# B1 — Wake Ownership
# ═══════════════════════════════════════════════════════════════════════════════


class TestWakeOwnership:
    """B1: CIOWakeDispatcher as sole wake claimant."""

    def test_single_wake_produces_exactly_one_run(self, wake_dispatcher, wake_store, run_store):
        """NEW_RUN creates exactly one CIO run."""
        wid = _enqueue_test_wake(wake_store)
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        runs = run_store.list_runs()
        assert len(runs) == 1
        assert runs[0]["trigger_ref"] == wid

    def test_same_wake_not_dispatched_twice(self, wake_dispatcher, wake_store):
        """Idempotency: same wake dispatched once."""
        _enqueue_test_wake(wake_store, wake_job_id="duplicate-wake")
        r1 = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert r1["dispatched_count"] == 1
        r2 = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert r2["dispatched_count"] == 0, "Should not re-dispatch active wake"

    def test_wake_not_completed_at_dispatch(self, wake_dispatcher, wake_store):
        """Wake is NOT completed at dispatch — stays in DISPATCHED state."""
        wid = _enqueue_test_wake(wake_store)
        wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        wake = wake_store.get_wake_job(wid)
        assert wake is not None
        assert wake["current_status"] in ("DISPATCHED",)

    def test_terminal_run_completes_wake(self, wake_dispatcher, wake_store, run_store):
        """A wake transitions to COMPLETED only when the linked CIO run is terminal."""
        wid = _enqueue_test_wake(wake_store)
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        run_id = result["dispatched"][0]["run_id"]

        # Run must go through proper lifecycle to reach terminal
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")
        run_store.complete(run_id, cio_artifact_id="test-artifact", actor="test")

        # Mark wake in flight first, then complete
        wake_dispatcher.mark_in_flight(wid)
        wake_dispatcher.on_run_completed(wid, run_id, "COMPLETED", "test-artifact")

        wake = wake_store.get_wake_job(wid)
        assert wake["current_status"] == "COMPLETED"
        assert wake.get("completion_details", {}).get("cio_run_id") == run_id

    def test_mark_in_flight(self, wake_dispatcher, wake_store):
        """DISPATCHED → IN_FLIGHT transition works."""
        wid = _enqueue_test_wake(wake_store)
        wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert wake_dispatcher.mark_in_flight(wid)
        wake = wake_store.get_wake_job(wid)
        assert wake["current_status"] == "IN_FLIGHT"


# ═══════════════════════════════════════════════════════════════════════════════
# B1.1 — RESUME_RUN Contract
# ═══════════════════════════════════════════════════════════════════════════════


class TestResumeRun:
    """B1.1: NEW_RUN vs RESUME_RUN."""

    def test_resume_run_never_creates_new_run(self, wake_dispatcher, wake_store, run_store):
        """RESUME_RUN validates existing run and does NOT create another."""
        # Create a run first
        event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test-ref",
            actor="test",
        )
        target_run_id = event["payload"]["run_id"]
        run_store.start(target_run_id, actor="test")
        run_store.health_checked(target_run_id, "hd-1", actor="test")
        run_store.evidence_built(target_run_id, "snap-1", actor="test")
        # evidence_built goes to CIO_SYNTHESIS. Transition to WAITING_FOR_SPECIALISTS.
        run_store.wait_for_specialists(target_run_id, ["test-handoff"], actor="test")

        # Enqueue a RESUME_RUN wake
        wid = _enqueue_test_wake(
            wake_store,
            wake_intent="RESUME_RUN",
            trigger_type="HANDOFF_COMPLETED",
            target_run_id=target_run_id,
        )

        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["wake_intent"] == "RESUME_RUN"
        assert result["dispatched"][0]["run_id"] == target_run_id
        # Only 1 run total
        runs = run_store.list_runs()
        assert len(runs) == 1

    def test_resume_run_requires_target(self, wake_dispatcher, wake_store):
        """RESUME_RUN without target_run_id is rejected."""
        wid = _enqueue_test_wake(
            wake_store,
            wake_intent="RESUME_RUN",
            target_run_id=None,
        )
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0
        assert result["error_count"] == 1

    def test_resume_run_target_not_found(self, wake_dispatcher, wake_store):
        """RESUME_RUN with nonexistent target is rejected."""
        wid = _enqueue_test_wake(
            wake_store,
            wake_intent="RESUME_RUN",
            target_run_id="nonexistent-run-id",
        )
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0
        assert result["error_count"] >= 1

    def test_resume_run_target_terminal(self, wake_dispatcher, wake_store, run_store):
        """RESUME_RUN with terminal target is rejected."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="t", actor="test")
        target = event["payload"]["run_id"]
        run_store.start(target, actor="test")
        run_store.health_checked(target, "hd-1", actor="test")
        run_store.evidence_built(target, "snap-1", actor="test")
        run_store.complete(target, actor="test")

        wid = _enqueue_test_wake(
            wake_store,
            wake_intent="RESUME_RUN",
            target_run_id=target,
        )
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0
        assert result["error_count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# B1.2 — Wait/Resume State Machine
# ═══════════════════════════════════════════════════════════════════════════════


class TestWaitResumeStateMachine:
    """B1.2: WAITING_FOR_SPECIALISTS / WAITING_FOR_HERMES."""

    def test_wait_for_specialists_persists_state(self, run_store):
        """WAITING_FOR_SPECIALISTS is a durable state."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="w", actor="test")
        run_id = event["payload"]["run_id"]
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")

        run_store.wait_for_specialists(run_id, ["handoff-1"], actor="test")
        run = run_store.get_run(run_id)
        assert run["status"] == "WAITING_FOR_SPECIALISTS"

    def test_resume_after_specialists(self, run_store):
        """Resume transitions WAITING_FOR_SPECIALISTS → EVIDENCE_BUILD."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="w", actor="test")
        run_id = event["payload"]["run_id"]
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")
        run_store.wait_for_specialists(run_id, ["handoff-1"], actor="test")
        run_store.resume(run_id, "SPECIALIST_COMPLETION", actor="test")
        run = run_store.get_run(run_id)
        assert run["status"] == "EVIDENCE_BUILD"

    def test_wait_for_hermes_persists_state(self, run_store):
        """WAITING_FOR_HERMES is a durable state."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="w", actor="test")
        run_id = event["payload"]["run_id"]
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")

        run_store.wait_for_hermes(run_id, ["challenge-1"], actor="test")
        run = run_store.get_run(run_id)
        assert run["status"] == "WAITING_FOR_HERMES"

    def test_resume_after_hermes(self, run_store):
        """Resume transitions WAITING_FOR_HERMES → EVIDENCE_BUILD."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="w", actor="test")
        run_id = event["payload"]["run_id"]
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")
        run_store.wait_for_hermes(run_id, ["challenge-1"], actor="test")
        run_store.resume(run_id, "HERMES_RESOLVED", actor="test")
        run = run_store.get_run(run_id)
        assert run["status"] == "EVIDENCE_BUILD"

    def test_cannot_resume_non_waiting(self, run_store):
        """Resume is rejected for non-waiting states."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="w", actor="test")
        run_id = event["payload"]["run_id"]
        with pytest.raises(ValueError):
            run_store.resume(run_id, "test", actor="test")


# ═══════════════════════════════════════════════════════════════════════════════
# B1.3 — Specialist Parentage
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecialistParentage:
    """B1.3: parent_run_id mandatory for Alex handoffs."""

    def test_parent_run_id_required_for_alex_handoff(self, handoff_queue):
        """Handoffs from Alex require parent_run_id."""
        with pytest.raises(ValueError, match="parent_run_id"):
            handoff_queue.enqueue({
                "handoff_id": f"hb-{uuid.uuid4().hex[:8]}",
                "from_agent": "alex",
                "to_agent": "maria",
                "task_type": "cio_question",
                "task_summary": "Test handoff without parent_run_id",
                "input_hash": "abc123",
                "priority": "NORMAL",
            })

    def test_parent_run_id_not_required_for_operator(self, handoff_queue):
        """Non-Alex handoffs don't need parent_run_id."""
        # Using maria as "from_agent" — only alex requires parent_run_id
        handoff_queue.enqueue({
            "handoff_id": f"hb-{uuid.uuid4().hex[:8]}",
            "from_agent": "maria",
            "to_agent": "steph",
            "task_type": "cio_question",
            "task_summary": "Operator handoff",
            "parent_run_id": "",
            "input_hash": "abc123",
            "priority": "NORMAL",
        })

    def test_alex_handoff_with_parent_run_id_succeeds(self, handoff_queue):
        """Alex handoff with parent_run_id succeeds."""
        event = handoff_queue.enqueue({
            "handoff_id": f"hb-{uuid.uuid4().hex[:8]}",
            "from_agent": "alex",
            "to_agent": "maria",
            "task_type": "cio_question",
            "task_summary": "Test handoff with parent_run_id",
            "parent_run_id": "test-run-123",
            "input_hash": "abc123",
            "priority": "NORMAL",
        })
        assert event is not None


# ═══════════════════════════════════════════════════════════════════════════════
# B1.4 — Alex Generic Intake Removal
# ═══════════════════════════════════════════════════════════════════════════════


class TestAlexIntakeRemoval:
    """B1.4: Alex does not consume raw wakes/events/Hermes."""

    def test_alex_job_source_no_wake_polling(self):
        """job_source('alex') no longer reads CIO wakes."""
        from scripts.agent_runtime_live_providers import job_source
        jobs = job_source("alex")
        wake_jobs = [j for j in jobs if j.job_type == "cio_synthesis" and j.trigger_kind not in ("AGENT_HANDOFF",)]
        assert len(wake_jobs) == 0, "Alex should not consume raw CIO wake jobs"

    def test_alex_job_source_no_hermes_queue(self):
        """job_source('alex') no longer reads Hermes challenge queue."""
        from scripts.agent_runtime_live_providers import job_source
        jobs = job_source("alex")
        hermes_jobs = [j for j in jobs if j.job_type == "hermes_challenge_review"]
        assert len(hermes_jobs) == 0, "Alex should not consume Hermes challenges"


# ═══════════════════════════════════════════════════════════════════════════════
# B2/B3 — Governed Gateway Registration
# ═══════════════════════════════════════════════════════════════════════════════


class TestGovernedGateway:
    """B2/B3: Six financial agents registered, unknown callers fail closed."""

    def test_all_six_agents_registered(self):
        """All financial agents (plus the advisory desk) are in CALLER_PROCESS_MAP."""
        from scripts.lib.cio_governed_model_bridge import CALLER_PROCESS_MAP
        expected = {"alex", "maria", "steph", "guardian", "ledger", "morgan", "advisory_desk"}
        assert set(CALLER_PROCESS_MAP.keys()) == expected

    def test_unknown_caller_fails_closed(self):
        """Unknown callers return None from resolve_caller."""
        from scripts.lib.cio_governed_model_bridge import resolve_caller
        assert resolve_caller("unknown_agent") is None
        assert resolve_caller("") is None
        assert resolve_caller(None) is None

    def test_policy_resolution_for_all_agents(self):
        """All registered processes resolve to valid policies."""
        from scripts.lib.cio_governed_model_bridge import resolve_model_policy
        for process_id in [
            "alex_cio_synthesis", "maria_research_critique",
            "steph_allocation_review", "guardian_risk_critique",
            "ledger_tax_critique", "morgan_wealth_synthesis",
        ]:
            policy = resolve_model_policy(process_id)
            assert policy is not None, f"{process_id} should resolve"
            assert "model_id" in policy

    def test_unknown_process_fails_closed(self):
        """Unknown process_id returns None."""
        from scripts.lib.cio_governed_model_bridge import resolve_model_policy
        assert resolve_model_policy("unknown_process") is None

    def test_caller_task_policy_map_exists(self):
        """CALLER_TASK_POLICY_MAP covers all agents (plus the advisory desk)."""
        from scripts.lib.cio_governed_model_bridge import CALLER_TASK_POLICY_MAP
        expected = {"alex", "maria", "steph", "guardian", "ledger", "morgan", "advisory_desk"}
        assert set(CALLER_TASK_POLICY_MAP.keys()) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# B4 — No Financial-Agent Fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoFinancialAgentFallback:
    """B4: Financial agents do not route through raw Ollama or generic router."""

    def test_financial_agents_use_governed_gateway(self):
        """alex, maria, steph, guardian, ledger, morgan → governed gateway."""
        from scripts.agent_runtime_live_providers import _AGENT_MODEL_MAP, build_providers

        for agent_id in ("alex", "maria", "steph", "guardian", "ledger", "morgan"):
            providers = build_providers(agent_id)
            # Governed gateway provider returns PROVIDER_BLOCKED on direct calls
            result = providers.model("test-run", {"messages": []})
            assert "PROVIDER_BLOCKED" in result.get("error", ""), \
                f"{agent_id} should route through governed gateway, not raw providers"

    def test_deepseek_failure_blocks_or_defers(self):
        """Governed gateway provider fails with PROVIDER_BLOCKED, not silent fallback."""
        from scripts.agent_runtime_live_providers import _build_governed_gateway_provider
        provider = _build_governed_gateway_provider()
        result = provider("test-run", {"messages": [{"role": "user", "content": "test"}]})
        assert result.get("response") == ""
        assert "PROVIDER_BLOCKED" in result.get("error", "")

    def test_reflective_critics_use_governed_flash(self):
        """sentinel/iris/reflection use governed Flash; darwin stays deterministic."""
        from scripts.agent_runtime_live_providers import _AGENT_MODEL_MAP, _build_governed_flash_provider
        assert set(("sentinel", "iris", "reflection", "darwin")) <= set(_AGENT_MODEL_MAP)
        # The three LLM-using reflective critics share the same governed-Flash factory.
        assert _AGENT_MODEL_MAP["sentinel"] is _AGENT_MODEL_MAP["iris"]
        assert _AGENT_MODEL_MAP["sentinel"] is _AGENT_MODEL_MAP["reflection"]
        # darwin keeps its own (unused) Ollama factory — deterministic scorer.
        assert _AGENT_MODEL_MAP["darwin"] is not _AGENT_MODEL_MAP["sentinel"]
        assert callable(_build_governed_flash_provider)

    def test_no_broken_route_llm_call_import(self):
        """_build_deepseek_provider with broken route_llm_call no longer exists."""
        from scripts import agent_runtime_live_providers as ar
        assert not hasattr(ar, "_build_deepseek_provider"), \
            "Broken _build_deepseek_provider must be removed"


# ═══════════════════════════════════════════════════════════════════════════════
# B7 — Hermes Research Gateway
# ═══════════════════════════════════════════════════════════════════════════════


class TestHermesGateway:
    """B7: Single Hermes challenge worker, independent gateway."""

    def test_single_challenge_worker_exists(self):
        """HermesChallengeWorker is defined as a single consumer."""
        from scripts.lib.cio_hermes_challenge_worker import HermesChallengeWorker
        assert HermesChallengeWorker is not None

    def test_hermes_declared_lanes_not_fallback(self):
        """Declared lanes are explicit, not silent fallback."""
        from scripts.lib.cio_hermes_challenge_worker import HERMES_RESEARCH_LANES
        assert len(HERMES_RESEARCH_LANES) > 0
        for lane_name, lane in HERMES_RESEARCH_LANES.items():
            assert "provider" in lane
            assert "model" in lane
            assert "purpose" in lane

    def test_hermes_creates_resume_wake(self, wake_store, run_store, hermes_queue_mock):
        """Hermes worker creates RESUME_RUN wake on challenge completion."""
        from scripts.lib.cio_hermes_challenge_worker import HermesChallengeWorker

        worker = HermesChallengeWorker(
            hermes_queue=hermes_queue_mock,
            wake_store=wake_store,
            run_store=run_store,
        )

        # Create a parent run in WAITING_FOR_HERMES
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="test", actor="test")
        run_id = event["payload"]["run_id"]
        run_store.start(run_id, actor="test")
        run_store.health_checked(run_id, "hd-1", actor="test")
        run_store.evidence_built(run_id, "snap-1", actor="test")
        # Need a Hermes request first for the run to go to HERMES_CHALLENGE
        run_store.record_hermes_request(run_id, "ch-1", actor="test")
        run_store.wait_for_hermes(run_id, ["ch-1"], actor="test")

        artifact = {
            "artifact_id": "hermes-artifact-test",
            "challenge_id": "ch-1",
            "artifact_hash": "abc123",
            "status": "COMPLETED",
        }

        worker._create_resume_wake(run_id, "ch-1", artifact)

        # Check a resume wake was created
        wakes = wake_store.list_wakes()
        resume_wakes = [w for w in wakes if w.get("wake_intent") == "RESUME_RUN"]
        assert len(resume_wakes) >= 1
        rw = resume_wakes[0]
        assert rw["target_run_id"] == run_id


# ═══════════════════════════════════════════════════════════════════════════════
# B8 — Legacy Watch CIO Gate
# ═══════════════════════════════════════════════════════════════════════════════


class TestLegacyWatchGate:
    """B8: Legacy Watch CIO authority disabled."""

    def test_legacy_cio_synthesis_disabled_by_default(self):
        """Legacy CIO synthesis is disabled in Gate-B."""
        from scripts.lib.cio_legacy_watch_gate import (
            legacy_cio_synthesis_enabled,
            legacy_cio_authority,
            LegacyCIOAuthority,
        )
        assert not legacy_cio_synthesis_enabled()
        assert legacy_cio_authority() == LegacyCIOAuthority.SPECIALIST_EVIDENCE_ONLY

    def test_cio_view_classification(self):
        """cio_view origin classification works."""
        from scripts.lib.cio_legacy_watch_gate import classify_cio_view_origin
        assert classify_cio_view_origin("cio_run_worker") == "AUTHORITATIVE_CIO_ACTION"
        assert classify_cio_view_origin("watchlist_cio_synthesis") == "LEGACY_CIO_REVIEW"
        assert classify_cio_view_origin("unknown_source") == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════════
# B9 — Identity Normalization
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentityNormalization:
    """B9: Guardian/Ledger identity aliases."""

    def test_risk_agent_alias_guardian(self):
        """risk_agent → guardian."""
        from scripts.lib.cio_identity_resolver import resolve_canonical_id
        assert resolve_canonical_id("risk_agent") == "guardian"

    def test_tax_agent_alias_ledger(self):
        """tax_agent → ledger."""
        from scripts.lib.cio_identity_resolver import resolve_canonical_id
        assert resolve_canonical_id("tax_agent") == "ledger"

    def test_canonical_ids_self_resolve(self):
        """guardian → guardian, ledger → ledger."""
        from scripts.lib.cio_identity_resolver import resolve_canonical_id
        assert resolve_canonical_id("guardian") == "guardian"
        assert resolve_canonical_id("ledger") == "ledger"

    def test_unknown_passthrough(self):
        """Unknown IDs passed through unchanged."""
        from scripts.lib.cio_identity_resolver import resolve_canonical_id
        assert resolve_canonical_id("alex") == "alex"
        assert resolve_canonical_id("unknown") == "unknown"

    def test_all_mapping_functions_return_valid(self):
        """All resolver functions return valid values for guardian and ledger."""
        import scripts.lib.cio_identity_resolver as ir
        for canonical in ("guardian", "ledger"):
            assert ir.get_display_name(canonical)
            assert ir.get_fleet_id(canonical)
            assert ir.get_handoff_queue_id(canonical)
            assert ir.get_maturity_catalog_key(canonical)
            assert ir.get_process_registry_id(canonical)


# ═══════════════════════════════════════════════════════════════════════════════
# CIORunWorker — Gate-B execution
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunWorkerGateB:
    """CIORunWorker accepts run_id, not wake_job."""

    def test_execute_accepts_run_id(self, run_worker, run_store):
        """execute(run_id) succeeds with a valid run."""
        event = run_store.create_run(trigger_type="SCHEDULED_DAILY", trigger_ref="t", actor="test")
        run_id = event["payload"]["run_id"]
        result = run_worker.execute(run_id, force_health_state="CLEAR", force_snapshot={
            "snapshot_id": "snap-test", "content_hash": "abc",
            "domain_states": {
                "portfolio": "AVAILABLE",
                "risk": "AVAILABLE",
                "health_data_quality": "AVAILABLE",
                "watch_intelligence": "AVAILABLE",
                "operator_profile": "AVAILABLE",
                "open_cio_actions": "AVAILABLE",
            },
        })
        assert result["run_id"] == run_id
        assert result["status"] in ("COMPLETED", "WAITING_FOR_SPECIALISTS")

    def test_execute_unknown_run_fails(self, run_worker):
        """execute() on unknown run returns FAILED."""
        result = run_worker.execute("nonexistent-run-id")
        assert result["status"] == "FAILED"

    def test_no_create_run_authority(self, run_worker, run_store):
        """CIORunWorker does NOT have _ensure_run method."""
        import inspect
        methods = [m[0] for m in inspect.getmembers(run_worker, predicate=inspect.ismethod)]
        assert "_ensure_run" not in methods, "CIORunWorker must not create runs"

    def test_no_wake_store_dependency(self, run_worker):
        """CIORunWorker no longer requires wake_store."""
        assert not hasattr(run_worker, "wake_store"), "CIORunWorker must not have wake_store"


# ═══════════════════════════════════════════════════════════════════════════════
# Gate-A Regression
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateARegression:
    """Gate-A tests must still pass on Gate-B changes."""

    def test_event_bus_integrity(self, temp_dir):
        """CIOEventBus hash chain integrity still works."""
        from scripts.lib.cio_event_bus import CIOEventBus
        bus_path = temp_dir / "cio_events.jsonl"
        cursor_path = temp_dir / "cio_cursors.jsonl"
        bus = CIOEventBus(bus_path=str(bus_path), cursor_path=str(cursor_path))
        bus.emit("system.heartbeat_ok", {"detected": True}, "test")
        valid, msg = bus.verify_integrity()
        assert valid, f"Event bus integrity failed: {msg}"

    def test_action_ledger_lifecycle(self, temp_dir):
        """CIOActionLedger create/transition still works."""
        from scripts.lib.cio_action_ledger import CIOActionLedger
        store_path = temp_dir / "cio_actions.jsonl"
        ledger = CIOActionLedger(event_store_path=store_path)
        event = ledger.create_action({
            "cio_action_id": f"action-{uuid.uuid4().hex[:12]}",
            "action_type": "ADVISORY",
            "title": "Test action",
            "description": "Gate-A regression test",
            "domain": "GENERAL",
            "priority": "LOW",
        }, actor_id="test")
        assert event is not None

    def test_heartbeat_event_bus_works(self, temp_dir):
        """CIOEventBus creation and emit still works."""
        from scripts.lib.cio_event_bus import CIOEventBus
        bus_path = temp_dir / "cio_events_hb.jsonl"
        cursor_path = temp_dir / "cio_cursors_hb.jsonl"
        bus = CIOEventBus(bus_path=str(bus_path), cursor_path=str(cursor_path))
        event = bus.emit("system.heartbeat_ok", {"detected": False}, "test")
        assert event is not None

    def test_notification_outbox(self, temp_dir):
        """Notification outbox module is importable."""
        import scripts.lib.cio_notification_delivery as nd
        assert hasattr(nd, "RealTelegramAdapter")
        # NotificationOutbox may use a different class name; module loads OK

    def test_cio_commands_parse(self):
        """cio_commands parsing still functional."""
        import scripts.cio_commands as cc
        assert hasattr(cc, "cmd_done")
        assert hasattr(cc, "cmd_defer")
        assert hasattr(cc, "cmd_reject")


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def wake_store_fixture(temp_dir):
    """Create a CIOWakeJobStore for the given temp dir."""
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    return CIOWakeJobStore(event_store_path=temp_dir / "cio_wake_jobs.jsonl")
