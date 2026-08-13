"""Checkpoint 4a — closing the specialist→committee resume loop.

Proves that a resumed SPECIALIST_COMPLETION run convenes the advisory committee
from *real* completed specialist output (handoff queue projections), rather than
an empty artifact list. Zero provider calls, zero live side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.cio_specialist_artifacts import (
    extract_advisory_from_handoff,
    resolve_run_specialist_advisories,
)
from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue


# ═══════════════════════════════════════════════════════════════════════════════
# extract_advisory_from_handoff
# ═══════════════════════════════════════════════════════════════════════════════


def test_extract_advisory_full_envelope():
    handoff = {
        "current_status": "COMPLETED",
        "to_agent": "steph",
        "specialist_advisory": {
            "specialist_id": "steph",
            "position": "SUPPORT",
            "confidence": 0.8,
            "rationale": "drift toward target",
        },
    }
    out = extract_advisory_from_handoff(handoff)
    assert out["specialist_id"] == "steph"
    assert out["position"] == "SUPPORT"
    assert out["confidence"] == 0.8


def test_extract_advisory_legacy_fallback_neutral():
    handoff = {
        "current_status": "COMPLETED",
        "to_agent": "maria",
        "summary": "no explicit position persisted",
    }
    out = extract_advisory_from_handoff(handoff)
    assert out["specialist_id"] == "maria"
    assert out["position"] == "NEUTRAL"
    assert out["confidence"] == 0.5


def test_extract_advisory_non_completed_returns_none():
    assert extract_advisory_from_handoff({"current_status": "PENDING", "to_agent": "maria"}) is None
    assert extract_advisory_from_handoff(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_run_specialist_advisories
# ═══════════════════════════════════════════════════════════════════════════════


def _handoffs():
    return {
        "h1": {
            "current_status": "COMPLETED",
            "to_agent": "maria",
            "specialist_advisory": {"specialist_id": "maria", "position": "SUPPORT", "confidence": 0.7},
        },
        "h2": {
            "current_status": "COMPLETED",
            "to_agent": "steph",
            "specialist_advisory": {"specialist_id": "steph", "position": "SUPPORT", "confidence": 0.6},
        },
        "h3": {"current_status": "PENDING", "to_agent": "guardian"},
        "h4": {"current_status": "FAILED", "to_agent": "ledger"},
    }


def test_resolve_run_mixed_states():
    hs = _handoffs()
    run = {"specialist_requests": ["h1", "h2", "h3", "h4"], "parent_handoff_ids": []}
    resolved = resolve_run_specialist_advisories(run, lambda hid: hs.get(hid))
    assert [a["specialist_id"] for a in resolved["advisories"]] == ["maria", "steph"]
    assert resolved["completed_handoff_ids"] == ["h1", "h2"]
    assert resolved["pending_handoff_ids"] == ["h3"]
    # FAILED is terminal-non-contributing: covered, but not pending.
    assert resolved["covered_specialists"] == {"maria", "steph", "guardian", "ledger"}


def test_resolve_run_parent_handoff_ids_included():
    hs = _handoffs()
    run = {"specialist_requests": [], "parent_handoff_ids": ["h1"]}
    resolved = resolve_run_specialist_advisories(run, lambda hid: hs.get(hid))
    assert [a["specialist_id"] for a in resolved["advisories"]] == ["maria"]


def test_resolve_run_missing_handoff_keeps_pending():
    run = {"specialist_requests": ["ghost"], "parent_handoff_ids": []}
    resolved = resolve_run_specialist_advisories(run, lambda hid: None)
    assert resolved["advisories"] == []
    assert resolved["pending_handoff_ids"] == ["ghost"]


# ═══════════════════════════════════════════════════════════════════════════════
# Handoff queue round-trip: specialist_advisory is durable
# ═══════════════════════════════════════════════════════════════════════════════


def test_handoff_completion_persists_specialist_advisory(tmp_path, monkeypatch):
    from scripts.lib.cio_agent_handoff_queue import AGENT_REGISTRY

    # The live catalog keeps specialists NOT_READY (fail-closed), so handoffs to
    # them are BLOCKED and cannot be claimed. For this persistence canary, make
    # maria claimable so we can exercise the complete() -> projection round-trip.
    def _patched_registry():
        return {
            "alex": {"status": "REGISTERED", "role": "cio"},
            "maria": {"status": "AVAILABLE", "role": "research"},
        }

    monkeypatch.setattr(
        "scripts.lib.cio_agent_handoff_queue._build_agent_registry_from_catalog",
        _patched_registry,
    )
    monkeypatch.setattr(
        "scripts.lib.cio_agent_readiness.AgentReadinessRegistry.can_claim",
        lambda self, agent_id, claimed_at_catalog_hash=None: (True, "READY"),
    )
    AGENT_REGISTRY._loaded = False

    q = AgentHandoffQueue(event_store_path=tmp_path / "handoffs.jsonl")
    q.enqueue({
        "handoff_id": "h100",
        "from_agent": "alex",
        "parent_run_id": "run-100",
        "to_agent": "maria",
        "task_type": "cio_question",
        "task_summary": "review",
        "input_hash": "x",
        "max_budget_usd": 0,
    })
    q.claim("h100", "maria", "tok1")
    q.complete(
        "h100",
        {
            "artifact_id": "art-1",
            "artifact_hash": "hash-1",
            "specialist_advisory": {
                "specialist_id": "maria",
                "position": "SUPPORT",
                "confidence": 0.75,
                "rationale": "evidence-backed",
            },
        },
        "tok1",
        "maria",
    )
    h = q.get_handoff("h100")
    assert h["current_status"] == "COMPLETED"
    assert h["specialist_advisory"]["position"] == "SUPPORT"
    assert h["specialist_advisory"]["specialist_id"] == "maria"


# ═══════════════════════════════════════════════════════════════════════════════
# CIORunWorker._route_specialists consumes completed advisories
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeHandoffQueue:
    def __init__(self, projections=None):
        self.projections = projections or {}
        self.enqueued = []

    def get_handoff(self, handoff_id):
        return self.projections.get(handoff_id)

    def enqueue(self, handoff, actor_id=None):
        self.enqueued.append(handoff)
        return {"stream_id": handoff["handoff_id"]}


def test_route_specialists_consumes_completed_artifacts(tmp_path):
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker

    store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    store.initialize()

    fake = _FakeHandoffQueue({
        "h1": {
            "current_status": "COMPLETED",
            "to_agent": "maria",
            "specialist_advisory": {"specialist_id": "maria", "position": "SUPPORT", "confidence": 0.7},
        },
        "h2": {
            "current_status": "COMPLETED",
            "to_agent": "steph",
            "specialist_advisory": {"specialist_id": "steph", "position": "SUPPORT", "confidence": 0.6},
        },
    })

    worker = CIORunWorker(run_store=store, handoff_queue=fake)
    run = {
        "run_id": "run-1",
        "specialist_requests": ["h1", "h2"],
        "parent_handoff_ids": [],
        "required_domains": ["holdings", "watch"],
    }
    result = worker._route_specialists("run-1", run, ["holdings", "watch"], {})

    assert [a["specialist_id"] for a in result["artifacts"]] == ["maria", "steph"]
    # Both domains already covered → no re-route, no waiting.
    assert result["handoff_ids"] == []
    assert result["should_wait"] is False
    assert fake.enqueued == []


def test_route_specialists_still_routes_uncovered(tmp_path):
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker

    store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    store.initialize()

    fake = _FakeHandoffQueue()
    worker = CIORunWorker(run_store=store, handoff_queue=fake)
    run = {"run_id": "run-1", "specialist_requests": [], "parent_handoff_ids": [], "required_domains": ["holdings", "watch"]}
    result = worker._route_specialists("run-1", run, ["holdings", "watch"], {})

    assert result["artifacts"] == []
    assert result["should_wait"] is True
    assert len(result["handoff_ids"]) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-end: resumed run convenes committee from real output
# ═══════════════════════════════════════════════════════════════════════════════


def test_worker_resume_convenes_committee_from_real_output(tmp_path):
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_domain_registry import CIODomainRegistry
    from scripts.lib.cio_committee_synthesis import build_committee_synthesis_fn
    from scripts.lib.cio_investment_decision import POSITION_HOLD
    from scripts.lib.cio_evidence_ref import make_ref

    store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    store.initialize()
    created = store.create_run(
        trigger_type="SCHEDULED_DAILY",
        required_domains=["holdings", "watch"],
    )
    run_id = created["payload"]["run_id"]

    all_domains = CIODomainRegistry.load().domain_ids
    force_snapshot = {
        "snapshot_id": "snap-1",
        "content_hash": "abc123",
        "summary": "portfolio snapshot",
        "domain_states": {d: "AVAILABLE" for d in all_domains},
    }

    class FakeLedger:
        def __init__(self):
            self.actions = []

        def create_action(self, action, actor_id=None, actor_type=None, authority=None):
            self.actions.append(action)
            return {"payload": {"cio_action_id": action["cio_action_id"]}}

    class FakeOutbox:
        def __init__(self):
            self.notes = []

        def enqueue(self, note, actor_id=None):
            self.notes.append(note)
            return {"notification_id": note["notification_id"]}

    # Fake handoff queue: records enqueues, resolves completed projections.
    fake = _FakeHandoffQueue()

    ledger = FakeLedger()
    outbox = FakeOutbox()
    fn = build_committee_synthesis_fn(
        intended_position=POSITION_HOLD,
        quorum=2,
        evidence_refs=[make_ref(
            "holdings_detail", {"symbol": "SCHD"}, source="holdings.json",
            quality_state="AVAILABLE", symbol="SCHD",
        )],
        rationale_linked_to_evidence="Hold SCHD; committee convened from specialists.",
        conditions_to_change_view=["weight breaches fire"],
        symbols=["SCHD"],
    )

    worker = CIORunWorker(
        run_store=store,
        action_ledger=ledger,
        notification_outbox=outbox,
        handoff_queue=fake,
        synthesis_fn=fn,
    )

    # Phase 1: fresh run routes specialists and parks in WAITING_FOR_SPECIALISTS.
    first = worker.execute(run_id, force_health_state="HEALTHY", force_snapshot=force_snapshot)
    assert first["status"] == "WAITING_FOR_SPECIALISTS", first
    assert len(fake.enqueued) == 2

    # Simulate the specialists actually completing with real output.
    handoff_ids = [h["handoff_id"] for h in fake.enqueued]
    fake.projections = {
        handoff_ids[0]: {
            "current_status": "COMPLETED",
            "to_agent": "maria",
            "specialist_advisory": {"specialist_id": "maria", "position": "SUPPORT", "confidence": 0.7},
        },
        handoff_ids[1]: {
            "current_status": "COMPLETED",
            "to_agent": "steph",
            "specialist_advisory": {"specialist_id": "steph", "position": "SUPPORT", "confidence": 0.6},
        },
    }

    # Phase 2: a RESUME_RUN wake points the worker back at the same run; the
    # worker auto-resumes and convenes the committee from the resolved artifacts.
    second = worker.execute(run_id, force_snapshot=force_snapshot)
    assert second["status"] == "COMPLETED", second
    assert second["resume"] is True

    hold_actions = [a for a in ledger.actions if a.get("action_type") == "HOLD"]
    assert hold_actions, f"expected a HOLD action; got {[a.get('action_type') for a in ledger.actions]}"
    assert len(outbox.notes) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Event detector: HANDOFF_COMPLETED → RESUME_RUN linkage
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeWakeStore:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, payload, actor_id=None, actor_type=None, authority=None):
        self.enqueued.append(payload)
        return {"stream_id": payload["wake_job_id"]}

    def list_wakes(self, status=None, priority=None, limit=50):
        return []


class _FakeHandoffListQueue:
    def __init__(self, handoffs):
        self.handoffs = handoffs

    def list_handoffs(self, status=None):
        return [h for h in self.handoffs if status is None or h.get("current_status") == status]


def test_handoff_completion_creates_resume_wake():
    from scripts.lib.cio_event_detector import CIOEventDetector

    wake_store = _FakeWakeStore()
    queue = _FakeHandoffListQueue([
        {
            "handoff_id": "handoff-completed-001",
            "current_status": "COMPLETED",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_hash": "abc",
            "parent_run_id": "run-99",
            "parent_cio_action_id": None,
        }
    ])
    detector = CIOEventDetector(wake_store=wake_store, handoff_queue=queue)
    wakes = detector._check_handoff_completions(datetime.now(timezone.utc))

    assert len(wakes) == 1
    payload = wake_store.enqueued[0]
    assert payload["trigger_type"] == "HANDOFF_COMPLETED"
    assert payload["wake_intent"] == "RESUME_RUN"
    assert payload["target_run_id"] == "run-99"


def test_orphan_handoff_completion_falls_back_to_new_run():
    from scripts.lib.cio_event_detector import CIOEventDetector

    wake_store = _FakeWakeStore()
    queue = _FakeHandoffListQueue([
        {
            "handoff_id": "handoff-orphan-001",
            "current_status": "COMPLETED",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_hash": "abc",
            "parent_run_id": "",
            "parent_cio_action_id": None,
        }
    ])
    detector = CIOEventDetector(wake_store=wake_store, handoff_queue=queue)
    wakes = detector._check_handoff_completions(datetime.now(timezone.utc))

    assert len(wakes) == 1
    payload = wake_store.enqueued[0]
    assert payload["wake_intent"] == "NEW_RUN"
    assert payload["target_run_id"] is None
