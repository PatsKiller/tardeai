"""Checkpoint 3 — Autonomous CIO orchestration lifecycle canaries.

Proves, with zero provider calls and zero live side effects, that the converged
CIO lifecycle satisfies:

  * exactly one CIO parent run per semantic event (no duplicate runs)
  * no duplicate operator notification (fail-closed outbox)

Each of the 10 required canaries is exercised against the real lifecycle
components (CIOWakeJobStore, CIORunStore, CIOWakeDispatcher, CIOActionLedger,
CIOOutcomeStore, NotificationOutbox, semantic event dedupe, materiality gate)
using isolated temp-path stores.

Financial authority: READ_ONLY_ADVISORY. No broker/order/stop/2FA writes.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────


class _FakeGoalStore:
    """Hermetic goal store: no candidates, no disk writes."""

    def list_due_or_idle_goals(self, limit=10):
        return []

    def goals_for_event_types(self, types, limit=10):
        return []

    def get_context_for_agent(self, agent_id):
        return {"open_goals": [], "thesis_snippets": [], "desk_thesis": {}}

    def record_wake(self, *a, **k):
        pass


def _make_wake_payload(wake_job_id, trigger_ref="ev_1"):
    return {
        "wake_job_id": wake_job_id,
        "trigger_type": "EVENT_BUS",
        "trigger_ref": trigger_ref,
        "trigger_hash": hashlib.sha256(trigger_ref.encode()).hexdigest()[:16],
        "reason_codes": ["EVENT_BUS", "PORTFOLIO_MATERIAL_CHANGE"],
        "required_domains": ["portfolio"],
        "wake_intent": "NEW_RUN",
        "idempotency_key": wake_job_id,
    }


def _note(nid, *, dedupe_key=None, idempotency_key=None):
    body = "trim SCHD by $5k to fund JEPI"
    n = {
        "notification_id": nid,
        "message_class": "advisory",
        "channel_targets": ["telegram"],
        "subject": "CIO call",
        "body": body,
        "body_hash": hashlib.sha256(body.encode()).hexdigest(),
    }
    if dedupe_key is not None:
        n["dedupe_key"] = dedupe_key
    if idempotency_key is not None:
        n["idempotency_key"] = idempotency_key
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Canary 1 — material holding change produces exactly one semantic event
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_material_holding_change_detected_and_deduped():
    from scripts.cio_heartbeat import detect_changes
    from scripts.lib.cio_semantic_event_key import (
        SemanticEventDeduplicator,
        compute_semantic_event_key,
    )

    prev = {"domains": {"portfolio": {"state": "AVAILABLE", "data": {"total_value": 100.0}}}}
    cur = {"domains": {"portfolio": {"state": "AVAILABLE", "data": {"total_value": 105.0}}}}
    changes = detect_changes(cur, prev)
    port_changes = [
        c for c in changes
        if c.get("domain") == "portfolio" and c.get("change_type") == "DATA_CHANGED"
    ]
    assert port_changes, "material portfolio change must be detected"

    # The same business event published twice collapses to ONE semantic key.
    aggregate = {"domain": "portfolio", "change": "DATA_CHANGED"}
    key = compute_semantic_event_key("portfolio.material_change", aggregate)
    dedup = SemanticEventDeduplicator()
    assert dedup.check_and_mark(key) is True
    assert dedup.check_and_mark(key) is False  # duplicate suppressed


# ─────────────────────────────────────────────────────────────────────────────
# Canary 2/3/5 — cash above band, concentration breach, defensive/rotation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "situation_type,expected",
    [
        ("S5_CASH_DEPLOYMENT", True),
        ("S6_CONCENTRATION_OR_DISPOSITION", True),
        ("S8_DEFENSIVE_REGIME", True),  # defensive regime is material (portfolio posture)
        ("S4_SECTOR_ROTATION", False),  # rotation is a forward-loop signal, not a notify
        ("S7_WATCH_PROMOTION", False),  # watch promotion is forwarded, not a CIO notify
        ("S2_STOP_GAP", False),  # routine card
    ],
)
def test_canary_materiality_gate(situation_type, expected):
    from scripts.lib.cio_plan_enrichment import is_material_plan

    plan = {"situation_type": situation_type, "fire_reasons": []}
    assert is_material_plan(plan) is expected


def test_canary_no_change_event_suppressed():
    from scripts.lib.cio_plan_enrichment import is_material_source

    policy = {
        "material_sources": ["situation.raised", "OPERATOR_MESSAGE"],
        "non_material_sources": ["system.heartbeat_ok"],
    }
    assert is_material_source("system.heartbeat_ok", policy) is False
    assert is_material_source("situation.raised", policy) is True
    assert is_material_source("OPERATOR_MESSAGE", policy) is True


# ─────────────────────────────────────────────────────────────────────────────
# Canary 4 — watch promotion candidate creates an advisory plan (forward loop)
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_watch_promotion_produces_plan(tmp_path):
    from scripts.lib.cio_plans import CIOPlanStore
    from scripts.lib.cio_situation_detector import VALID_SITUATION_TYPES

    assert "S7_WATCH_PROMOTION" in VALID_SITUATION_TYPES
    store = CIOPlanStore(
        event_path=tmp_path / "plans.jsonl",
        projection_path=tmp_path / "plans_projection.json",
    )
    plan = store.create_plan(
        situation_type="S7_WATCH_PROMOTION",
        symbols=["PLTR"],
        title="Watch promotion: PLTR ready for research",
        summary="Watch item meets research threshold",
        options=[{"id": "research", "label": "Commission research"}],
        recommendation="Promote PLTR to research queue",
        revisit_at=(datetime.now(timezone.utc)).isoformat(),
        owner_agent="alex",
    )
    assert plan["status"] == "draft"
    assert "PLTR" in plan["symbols"]
    assert plan["authority"] == "READ_ONLY_ADVISORY"
    # Dedup: same type+symbol within window returns the existing open plan.
    dup = store.find_recent_dedup("S7_WATCH_PROMOTION", ["PLTR"], within_hours=6.0)
    assert dup is not None
    assert dup["plan_id"] == plan["plan_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Canary 6 — specialist handoff required, then resume (no duplicate run)
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_specialist_handoff_and_resume(tmp_path):
    from scripts.lib.cio_run import CIORunStore

    run_store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    run_store.initialize()
    ev = run_store.create_run(trigger_type="SYSTEM", trigger_ref="ev_handoff", priority="NORMAL")
    run_id = ev["payload"]["run_id"]

    run_store.start(run_id)
    run_store.health_checked(run_id, "hd_1")
    run_store.record_specialist_request(run_id, "handoff_maria_1")
    run_store.wait_for_specialists(run_id, ["handoff_maria_1"])

    run = run_store.get_run(run_id)
    assert run["status"] == "WAITING_FOR_SPECIALISTS"
    assert "handoff_maria_1" in run["specialist_requests"]

    # Resume reopens the SAME run (parent run resumes, not a new run).
    run_store.resume(run_id, "specialist completed")
    assert run_store.get_run(run_id)["status"] == "EVIDENCE_BUILD"
    assert len(run_store.list_runs()) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Canary 7 — provider blocked: budget gate fails closed, no silent fallback
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_provider_blocked_budget_fails_closed(tmp_path):
    from scripts.lib.cio_run import CIORunStore

    run_store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    run_store.initialize()
    ev = run_store.create_run(
        trigger_type="SYSTEM", trigger_ref="ev_blocked", max_provider_calls=1,
    )
    run_id = ev["payload"]["run_id"]

    run_store.record_model_call(run_id, "call_1", 0.001)  # within budget
    with pytest.raises(ValueError) as exc:
        run_store.record_model_call(run_id, "call_2", 0.001)  # exceeds budget
    assert "provider_calls" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# Canary 8 — restart/replay recovery: stale lease released, chain intact
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_restart_replay_recovers_expired_lease(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    wake_store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    wake_store.enqueue(_make_wake_payload("wake_recover", "ev_recover"))
    wake_store.claim("wake_recover", "token_1", lease_seconds=0)

    assert wake_store.get_wake_job("wake_recover")["current_status"] == "CLAIMED"
    recovered = wake_store.recover_expired_leases(stale_seconds=0)
    assert "wake_recover" in recovered
    assert wake_store.get_wake_job("wake_recover")["current_status"] == "PENDING"

    integrity = wake_store.verify_integrity()
    assert integrity["valid"], integrity


def test_canary_restart_replay_run_resume_after_crash(tmp_path):
    from scripts.lib.cio_run import CIORunStore

    run_store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    run_store.initialize()
    ev = run_store.create_run(trigger_type="SYSTEM", trigger_ref="ev_resume")
    run_id = ev["payload"]["run_id"]
    run_store.start(run_id)
    run_store.health_checked(run_id, "hd_1")
    run_store.record_specialist_request(run_id, "handoff_1")
    run_store.wait_for_specialists(run_id, ["handoff_1"])

    # Simulate crash: reopen the store from disk; state is reconstructed.
    run_store2 = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    run_store2.initialize()
    assert run_store2.get_run(run_id)["status"] == "WAITING_FOR_SPECIALISTS"
    run_store2.resume(run_id, "replay resume")
    assert run_store2.get_run(run_id)["status"] == "EVIDENCE_BUILD"
    ok, msg = run_store2.verify_integrity()
    assert ok, msg


# ─────────────────────────────────────────────────────────────────────────────
# Canary 9 — operator defer creates an explicit future condition
# ─────────────────────────────────────────────────────────────────────────────


def test_canary_operator_defer_with_future_trigger(tmp_path):
    from scripts.lib.cio_action_ledger import CIOActionLedger
    from scripts.lib.cio_outcome_store import CIOOutcomeStore

    ledger = CIOActionLedger(event_store_path=tmp_path / "actions.jsonl")
    ledger.create_action(
        {
            "cio_action_id": "action_defer_1",
            "title": "Trim SCHD",
            "followup_condition": "revisit after next CPI print",
            "next_check_at": (datetime.now(timezone.utc)).isoformat(),
            "operator_decision_required": True,
        },
        actor_id="alex",
    )
    ledger.transition_action(
        "action_defer_1", "CIO_ACTION_DEFERRED", {"reason": "operator wants to wait"},
        actor_id="alex",
    )
    action = ledger.get_action("action_defer_1")
    assert action["current_status"] == "DEFERRED"
    # The explicit future condition is durable on the action — not a forgotten note.
    assert "CPI" in action.get("followup_condition", "")
    assert action.get("next_check_at")

    # The follow-up wake trigger maps to a dedicated ACTION_FOLLOWUP run.
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
    assert (
        CIOWakeDispatcher._map_wake_to_run_trigger("ACTION_FOLLOWUP_DUE")
        == "ACTION_FOLLOWUP"
    )

    # Durable operator disposition is recorded independently (never forgotten).
    outcomes = CIOOutcomeStore(store_path=str(tmp_path / "outcomes.jsonl"))
    outcomes.record_outcome(
        cio_action_id="action_defer_1",
        operator_disposition="DEFERRED",
        outcome_status="UNKNOWN",
        actor="operator",
    )
    got = outcomes.get_outcomes("action_defer_1")
    assert got and got[-1]["payload"]["operator_disposition"] == "DEFERRED"


# ─────────────────────────────────────────────────────────────────────────────
# Invariant A — exactly one CIO parent run per semantic event
# ─────────────────────────────────────────────────────────────────────────────


def test_invariant_exactly_one_run_per_semantic_event(tmp_path):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    wake_store = CIOWakeJobStore(event_store_path=tmp_path / "wakes.jsonl")
    run_store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    run_store.initialize()

    disp = CIOWakeDispatcher(
        wake_store=wake_store,
        run_store=run_store,
        dispatch_ledger_path=str(tmp_path / "dispatch.jsonl"),
        goal_store=_FakeGoalStore(),
        readiness_registry=None,
    )

    # One semantic event → one wake (idempotency key collapses re-enqueue).
    payload = _make_wake_payload("wake_event_1", "ev_semantic_1")
    wake_store.enqueue(payload)
    wake_store.enqueue(payload)  # duplicate idempotency_key → no second wake
    assert len(wake_store.list_wakes()) == 1

    # First dispatch creates exactly one run.
    r1 = disp.poll_and_dispatch(max_dispatches=5)
    assert r1["dispatched_count"] == 1, r1
    assert len(run_store.list_runs()) == 1

    # Second dispatch does NOT create a second run (wake no longer PENDING).
    r2 = disp.poll_and_dispatch(max_dispatches=5)
    assert r2["dispatched_count"] == 0, r2
    assert len(run_store.list_runs()) == 1

    run = run_store.list_runs()[0]
    assert run["trigger_ref"] == "wake_event_1"


# ─────────────────────────────────────────────────────────────────────────────
# Invariant B — no duplicate operator notification (fail-closed outbox)
# ─────────────────────────────────────────────────────────────────────────────


def test_invariant_no_duplicate_notification(tmp_path):
    from scripts.lib.cio_notification_outbox import NotificationOutbox

    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")

    # Same semantic source re-enqueued collapses to one notification.
    e1 = outbox.enqueue(_note("n_1", dedupe_key="action:trim_schd"), actor_id="alex")
    e2 = outbox.enqueue(_note("n_1", dedupe_key="action:trim_schd"), actor_id="alex")
    assert e1["event_id"] == e2["event_id"]
    assert len(outbox.list_notifications()) == 1

    # Forbidden execution classes are rejected (fail-closed).
    bad = _note("n_bad", dedupe_key="action:execute")
    bad["message_class"] = "execute_trade"
    with pytest.raises(ValueError):
        outbox.enqueue(bad, actor_id="alex")


def test_invariant_notification_delivery_fail_closed_no_credentials():
    from scripts.lib.cio_notification_delivery import RealTelegramAdapter

    adapter = RealTelegramAdapter(bot_token=None, chat_id=None)
    assert adapter.is_live is False
    result = adapter.send({"notification_id": "n", "body": "hi", "subject": "s"})
    assert result["delivered"] is False
    assert result["error"] == "DELIVERY_BLOCKED_CREDENTIALS"
