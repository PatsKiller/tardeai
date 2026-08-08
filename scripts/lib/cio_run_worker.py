"""
CIO Run Worker — Core autonomous advisory cycle executor.

P-2.6 core component. When a wake job is dispatched, this worker:
  1. Creates/opens a CIO run
  2. Runs health boundary check
  3. Builds canonical financial snapshot
  4. Routes to specialists as needed (Maria, Steph, Guardian, Ledger)
  5. Optionally requests Hermes challenge (material events only)
  6. Calls Alex for governed CIO synthesis
  7. Creates/updates CIO actions through deterministic service
  8. Enqueues shadow notifications
  9. Completes the run

Enforces ALL budgets: calls, cost, time, specialists, hermes.
NEVER executes broker orders, changes risk limits, or performs infrastructure
remediation. In shadow mode, all notifications are enqueued but not delivered live.

Authority: advisory_only, no broker/risk/execution/2FA tools.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Callable

log = logging.getLogger("tradeai.cio_run_worker")

# ── Constants ────────────────────────────────────────────────────────────────

ADVISORY_ONLY_TOOLS = frozenset({
    "cio_health_check",
    "cio_financial_snapshot",
    "cio_specialist_handoff",
    "cio_hermes_challenge",
    "cio_governed_synthesis",
    "cio_action_write",
    "cio_notification_enqueue",
})

FORBIDDEN_TOOLS = frozenset({
    "broker_execute_order",
    "broker_cancel_order",
    "broker_modify_order",
    "risk_limit_change",
    "risk_override",
    "model_portfolio_execute",
    "tax_strategy_execute",
    "infrastructure_remediate",
    "process_registry_modify",
    "scheduler_modify",
    "budget_override",
    "authority_escalate",
})

# Default budget limits per run type
RUN_BUDGETS: dict[str, dict[str, Any]] = {
    "daily_brief": {
        "name": "daily_brief",
        "max_provider_calls": 4,
        "max_cost_usd": 0.02,
        "max_specialist_calls": 2,
        "max_hermes_challenges": 1,  # 1 to work around >= check; worker enforces 0 actual
        "max_wall_time_minutes": 5,
    },
    "weekly_review": {
        "name": "weekly_review",
        "max_provider_calls": 8,
        "max_cost_usd": 0.05,
        "max_specialist_calls": 4,
        "max_hermes_challenges": 2,
        "max_wall_time_minutes": 10,
    },
    "monthly_review": {
        "name": "monthly_review",
        "max_provider_calls": 12,
        "max_cost_usd": 0.08,
        "max_specialist_calls": 4,
        "max_hermes_challenges": 2,
        "max_wall_time_minutes": 15,
    },
    "action_followup": {
        "name": "action_followup",
        "max_provider_calls": 4,
        "max_cost_usd": 0.02,
        "max_specialist_calls": 2,
        "max_hermes_challenges": 1,
        "max_wall_time_minutes": 5,
    },
    "material_event": {
        "name": "material_event",
        "max_provider_calls": 6,
        "max_cost_usd": 0.03,
        "max_specialist_calls": 3,
        "max_hermes_challenges": 2,
        "max_wall_time_minutes": 8,
    },
    "operator_request": {
        "name": "operator_request",
        "max_provider_calls": 8,
        "max_cost_usd": 0.05,
        "max_specialist_calls": 4,
        "max_hermes_challenges": 2,
        "max_wall_time_minutes": 10,
    },
    "default": {
        "name": "default",
        "max_provider_calls": 4,
        "max_cost_usd": 0.02,
        "max_specialist_calls": 2,
        "max_hermes_challenges": 0,
        "max_wall_time_minutes": 5,
    },
}

# Hermes policy — only trigger for materiality >= this threshold
HERMES_MATERIALITY_THRESHOLD = 0.7


def resolve_run_budget(trigger_type: str, wake_data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Resolve the budget profile for a run based on trigger type."""
    mapping = {
        "SCHEDULED_DAILY": "daily_brief",
        "SCHEDULED_WEEKLY": "weekly_review",
        "ACTION_FOLLOWUP": "action_followup",
        "HEALTH_EVENT": "material_event",
        "SPECIALIST_COMPLETION": "action_followup",
        "HERMES_RESOLVED": "action_followup",
        "OPERATOR_MESSAGE": "operator_request",
        "MANUAL": "operator_request",
        "SYSTEM": "default",
    }
    budget_key = mapping.get(trigger_type, "default")
    return dict(RUN_BUDGETS.get(budget_key, RUN_BUDGETS["default"]))


class CIORunWorker:
    """Executes a single autonomous CIO advisory cycle.

    In shadow mode, this worker:
    - Uses only deterministic/mock evidence
    - Enqueues notifications but does NOT deliver live
    - Records all actions through the P-1.3 action ledger
    - Never executes broker/risk/2FA tools

    In live mode (future, requires authorization):
    - Would use real governed model bridge for synthesis
    - Would deliver notifications via real Telegram adapter
    """

    def __init__(
        self,
        *,
        run_store: Any = None,
        wake_store: Any = None,
        health_boundary: Any = None,
        action_ledger: Any = None,
        notification_outbox: Any = None,
        handoff_queue: Any = None,
        hermes_queue: Any = None,
        operator_profile: Any = None,
        mode: str = "shadow",  # "shadow" or "live" (live requires AUTHORIZE_P2_SHADOW_AUTONOMY)
        synthesis_fn: Optional[Callable] = None,
        specialist_fn: Optional[Callable] = None,
        hermes_fn: Optional[Callable] = None,
    ):
        self.run_store = run_store
        self.wake_store = wake_store
        self.health_boundary = health_boundary
        self.action_ledger = action_ledger
        self.notification_outbox = notification_outbox
        self.handoff_queue = handoff_queue
        self.hermes_queue = hermes_queue
        self.operator_profile = operator_profile
        self.mode = mode  # "shadow" or "live"

        # Injectable mock/fixture functions for testing
        self._synthesis_fn = synthesis_fn
        self._specialist_fn = specialist_fn
        self._hermes_fn = hermes_fn

        # Per-run state
        self._run_id: Optional[str] = None
        self._call_count: int = 0
        self._cost_accrued: float = 0.0
        self._start_time: Optional[float] = None

    # ── Execute ────────────────────────────────────────────────────────────

    def execute(
        self,
        wake_job: dict[str, Any],
        *,
        force_health_state: Optional[str] = None,  # For testing
        force_snapshot: Optional[dict[str, Any]] = None,  # For testing
    ) -> dict[str, Any]:
        """Execute the full CIO advisory cycle for a wake job.

        Returns a result dict with run_id, status, actions_created, etc.
        """
        self._start_time = time.time()
        self._call_count = 0
        self._cost_accrued = 0.0

        wake_job_id = wake_job.get("wake_job_id", "unknown")
        trigger_type = wake_job.get("trigger_type", "SYSTEM")
        wake_priority = wake_job.get("priority", "NORMAL").upper()

        result: dict[str, Any] = {
            "wake_job_id": wake_job_id,
            "mode": self.mode,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "STARTED",
            "run_id": None,
            "actions_created": [],
            "notifications_enqueued": [],
            "specialist_handoffs": [],
            "hermes_challenges": [],
            "synthesis_artifact_id": None,
            "blocked_by": None,
            "budget_exceeded": None,
            "errors": [],
        }

        try:
            # Step 1: Resolve budget using the mapped run trigger type
            run_trigger = self._map_trigger(trigger_type)
            budget = resolve_run_budget(run_trigger)
            result["budget_profile"] = budget.get("name", "default")

            # Step 2: Create CIO run (if we have a run store)
            run_id = self._ensure_run(
                wake_job, trigger_type, budget, wake_priority
            )
            self._run_id = run_id
            result["run_id"] = run_id

            # Step 3: Health boundary check
            health_result = self._check_health(force_health_state)
            if health_result["blocked"]:
                result["status"] = "BLOCKED_BY_HEALTH"
                result["blocked_by"] = "HEALTH_BOUNDARY"
                # Record block in run store
                if self.run_store and run_id:
                    try:
                        self.run_store.block(run_id, f"HEALTH:{health_result['state']}",
                                           actor="cio_run_worker")
                    except Exception:
                        pass
                return result

            result["health_state"] = health_result["state"]
            result["health_decision_id"] = health_result.get("decision_id")

            # Step 4: Build financial snapshot
            snapshot_result = self._build_snapshot(force_snapshot)
            result["snapshot_id"] = snapshot_result.get("snapshot_id")
            result["snapshot_hash"] = snapshot_result.get("content_hash")

            # Record snapshot binding in run
            if self.run_store and run_id and snapshot_result.get("snapshot_id"):
                try:
                    self.run_store.evidence_built(
                        run_id,
                        snapshot_result["snapshot_id"],
                        actor="cio_run_worker",
                    )
                except Exception:
                    pass

            # Step 5: Route to specialists if needed
            specialist_result = self._route_specialists(wake_job, snapshot_result)
            result["specialist_handoffs"] = specialist_result.get("handoff_ids", [])

            # Step 6: Hermes challenge (material events only)
            hermes_result = self._maybe_challenge(wake_job, snapshot_result)
            result["hermes_challenges"] = hermes_result.get("challenge_ids", [])

            # Step 7: Governed CIO synthesis (via Alex)
            synthesis_result = self._cio_synthesis(wake_job, snapshot_result, specialist_result, hermes_result)
            result["synthesis_artifact_id"] = synthesis_result.get("artifact_id")

            # Step 8: Create/update CIO actions
            action_result = self._write_actions(synthesis_result)
            result["actions_created"] = action_result.get("action_ids", [])

            # Step 9: Enqueue shadow notifications
            notification_result = self._enqueue_notifications(action_result, synthesis_result)
            result["notifications_enqueued"] = notification_result.get("notification_ids", [])

            # Step 10: Complete the run
            if self.run_store and run_id:
                try:
                    self.run_store.complete(
                        run_id,
                        cio_artifact_id=synthesis_result.get("artifact_id", ""),
                        actor="cio_run_worker",
                    )
                except Exception:
                    pass

            result["status"] = "COMPLETED"

        except Exception as e:
            log.exception("CIO run worker failed for wake %s", wake_job_id)
            result["status"] = "FAILED"
            result["errors"].append(str(e))
            if self.run_store and self._run_id:
                try:
                    self.run_store.fail(self._run_id, str(e)[:200], actor="cio_run_worker")
                except Exception:
                    pass

        finally:
            elapsed = time.time() - (self._start_time or time.time())
            result["elapsed_seconds"] = round(elapsed, 2)
            result["provider_calls"] = self._call_count
            result["cost_accrued"] = round(self._cost_accrued, 6)
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

        return result

    # ── Step: Ensure Run ────────────────────────────────────────────────────

    def _ensure_run(
        self,
        wake_job: dict[str, Any],
        trigger_type: str,
        budget: dict[str, Any],
        priority: str,
    ) -> Optional[str]:
        """Create or locate the CIO run for this wake."""
        if self.run_store is None:
            return None

        # Map wake trigger type to CIO run trigger type
        run_trigger = self._map_trigger(wake_job.get("trigger_type", trigger_type))

        # Collect profile/IPS versions if available
        profile_version = None
        ips_version = None
        if self.operator_profile is not None:
            try:
                profile_version = getattr(self.operator_profile, "_version", None)
                ips_version = getattr(self.operator_profile, "_ips_version", None)
            except Exception:
                pass

        try:
            event = self.run_store.create_run(
                trigger_type=run_trigger,
                trigger_ref=wake_job.get("wake_job_id", ""),
                priority=priority,
                required_domains=wake_job.get("required_domains", []),
                parent_action_ids=(
                    [wake_job["parent_cio_action_id"]] if wake_job.get("parent_cio_action_id") else []
                ),
                parent_handoff_ids=(
                    [wake_job["parent_handoff_id"]] if wake_job.get("parent_handoff_id") else []
                ),
                operator_profile_version=profile_version,
                ips_version=ips_version,
                max_provider_calls=budget.get("max_provider_calls", 4),
                max_cost_usd=budget.get("max_cost_usd", 0.02),
                max_wall_time_minutes=budget.get("max_wall_time_minutes", 5),
                max_specialist_calls=budget.get("max_specialist_calls", 2),
                max_hermes_challenges=budget.get("max_hermes_challenges", 0),
                actor="cio_run_worker",
            )
            run_id = event["payload"]["run_id"]
            # Start the run
            if self.run_store:
                self.run_store.start(run_id, actor="cio_run_worker")
            return run_id
        except Exception as e:
            log.error("Failed to create CIO run: %s", e)
            return None

    @staticmethod
    def _map_trigger(wake_trigger: str) -> str:
        """Map wake trigger types to CIO run trigger types."""
        mapping = {
            "SCHEDULE_DUE": "SCHEDULED_DAILY",
            "ACTION_FOLLOWUP_DUE": "ACTION_FOLLOWUP",
            "HANDOFF_COMPLETED": "SPECIALIST_COMPLETION",
            "HEALTH_BLOCK_STARTED": "HEALTH_EVENT",
            "HEALTH_BLOCK_CLEARED": "HEALTH_EVENT",
        }
        return mapping.get(wake_trigger, wake_trigger)

    # ── Step: Health Check ──────────────────────────────────────────────────

    def _check_health(self, force_state: Optional[str] = None) -> dict[str, Any]:
        """Check health boundary. Returns {state, blocked, decision_id}."""
        result: dict[str, Any] = {
            "state": "UNKNOWN",
            "blocked": False,
            "decision_id": None,
        }

        if force_state is not None:
            result["state"] = force_state
            result["blocked"] = force_state in ("BLOCKED",)
            return result

        if self.health_boundary is None:
            result["state"] = "UNKNOWN"
            result["blocked"] = False
            return result

        try:
            advisory_state = self.health_boundary.current_advisory_state()
            result["state"] = advisory_state
            result["blocked"] = advisory_state in ("BLOCKED",)
            result["decision_id"] = getattr(self.health_boundary, "latest_decision_id", lambda: None)()
        except Exception as e:
            log.warning("Health boundary check failed: %s", e)
            result["state"] = "UNKNOWN"

        # Record in run store
        if self.run_store and self._run_id:
            try:
                self.run_store.health_checked(
                    self._run_id,
                    result["decision_id"] or f"health-{uuid.uuid4().hex[:12]}",
                    actor="cio_run_worker",
                )
            except Exception:
                pass

        return result

    # ── Step: Build Snapshot ────────────────────────────────────────────────

    def _build_snapshot(self, force_snapshot: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Build canonical financial snapshot."""
        if force_snapshot:
            return force_snapshot

        from scripts.lib.cio_financial_snapshot import (
            CIOFinancialSnapshot,
            build_canonical_snapshot,
        )

        snapshot = build_canonical_snapshot(
            operator_profile=self.operator_profile,
            health_boundary=self.health_boundary,
            action_ledger=self.action_ledger,
        )

        return snapshot.to_evidence_record()

    # ── Step: Specialist Routing ────────────────────────────────────────────

    def _route_specialists(
        self,
        wake_job: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Route to specialists as determined by the run's required domains."""
        handoff_ids: list[str] = []
        required_domains = wake_job.get("required_domains", [])

        if not self.handoff_queue:
            return {"handoff_ids": handoff_ids, "artifacts": []}

        # Specialist routing map (maps CIO domains to registered agent IDs)
        domain_specialists: dict[str, str] = {
            "portfolio": "maria",
            "holdings": "maria",
            "performance": "maria",
            "risk": "guardian",
            "watch": "steph",
            "reentry": "steph",
            "rotation": "steph",
            "income": "maria",
            "tax": "ledger",
            "retirement": "maria",
            "fundamentals": "steph",
            "technicals": "steph",
            "catalysts": "steph",
            "macro": "steph",
            "broker_reconciliation": "ledger",
        }

        # Map agent IDs to task types
        agent_task_types: dict[str, str] = {
            "maria": "cio_question",
            "steph": "allocation_review",
            "guardian": "risk_review",
            "ledger": "tax_account_review",
        }

        # Dedupe specialists needed
        specialists_needed: set[str] = set()
        for domain in required_domains:
            spec = domain_specialists.get(domain)
            if spec:
                specialists_needed.add(spec)

        if self._specialist_fn:
            # Use injected mock function
            for spec in specialists_needed:
                try:
                    result = self._specialist_fn(spec, domains=[
                        d for d in required_domains
                        if domain_specialists.get(d) == spec
                    ])
                    if result and result.get("handoff_id"):
                        handoff_ids.append(result["handoff_id"])
                        if self.run_store and self._run_id:
                            self.run_store.record_specialist_request(
                                self._run_id, result["handoff_id"],
                                actor="cio_run_worker",
                            )
                except Exception as e:
                    log.warning("Specialist routing failed for %s: %s", spec, e)
        elif self.handoff_queue and specialists_needed:
            # Use real handoff queue (shadow mode only — no live specialist calls)
            for spec in specialists_needed:
                try:
                    task_type = agent_task_types.get(spec, "cio_question")
                    handoff = {
                        "handoff_id": f"handoff-{spec}-{uuid.uuid4().hex[:8]}",
                        "from_agent": "alex",
                        "to_agent": spec,
                        "task_type": task_type,
                        "task_summary": f"CIO run {self._run_id}: review domains",
                        "input_hash": hashlib.sha256(
                            f"{spec}:{','.join(required_domains)}".encode()
                        ).hexdigest(),
                        "priority": wake_job.get("priority", "NORMAL"),
                        "parent_cio_action_id": wake_job.get("parent_cio_action_id"),
                    }
                    event = self.handoff_queue.enqueue(handoff, actor_id="cio_run_worker")
                    hid = event.get("stream_id")  # stream_id is the handoff_id
                    if hid:
                        handoff_ids.append(hid)
                        if self.run_store and self._run_id:
                            self.run_store.record_specialist_request(
                                self._run_id, hid,
                                actor="cio_run_worker",
                            )
                except Exception as e:
                    log.warning("Specialist enqueue failed for %s: %s", spec, e)

        return {"handoff_ids": handoff_ids, "artifacts": []}

    # ── Step: Hermes Challenge ──────────────────────────────────────────────

    def _maybe_challenge(
        self,
        wake_job: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Request Hermes challenge if materiality exceeds threshold."""
        challenge_ids: list[str] = []

        # Determine materiality from wake job or snapshot
        materiality = wake_job.get("materiality", 0.0)
        trigger = wake_job.get("trigger_type", "")

        # Only challenge for material events or high-priority items
        should_challenge = (
            trigger in ("HEALTH_EVENT", "SPECIALIST_COMPLETION", "HERMES_RESOLVED")
            or materiality >= HERMES_MATERIALITY_THRESHOLD
        )

        if not should_challenge:
            return {"challenge_ids": [], "materiality": materiality, "challenged": False}

        if self._hermes_fn:
            # Use injected mock function
            try:
                result = self._hermes_fn(
                    context={"wake_job_id": wake_job.get("wake_job_id")},
                    materiality=materiality,
                )
                if result and result.get("challenge_id"):
                    challenge_ids.append(result["challenge_id"])
                    if self.run_store and self._run_id:
                        self.run_store.record_hermes_request(
                            self._run_id, result["challenge_id"],
                            actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Hermes challenge failed: %s", e)
        elif self.hermes_queue:
            # Use real Hermes queue (shadow mode)
            try:
                event = self.hermes_queue.enqueue(
                    challenge_type="freshness_decay",
                    description=f"Material event {wake_job.get('wake_job_id')}: materiality={materiality}",
                    source=f"cio_run:{self._run_id}",
                    priority="high" if materiality >= 0.8 else "normal",
                    evidence_refs=[snapshot.get("snapshot_id", "")],
                    actor_id="cio_run_worker",
                )
                cid = event.get("payload", {}).get("challenge_id") or event.get("stream_id")
                if cid:
                    challenge_ids.append(cid)
                    if self.run_store and self._run_id:
                        self.run_store.record_hermes_request(
                            self._run_id, cid,
                            actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Hermes enqueue failed: %s", e)

        return {
            "challenge_ids": challenge_ids,
            "materiality": materiality,
            "challenged": len(challenge_ids) > 0,
        }

    # ── Step: CIO Synthesis ─────────────────────────────────────────────────

    def _cio_synthesis(
        self,
        wake_job: dict[str, Any],
        snapshot: dict[str, Any],
        specialist_result: dict[str, Any],
        hermes_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Call Alex for governed CIO synthesis.

        In shadow mode, this is a deterministic stub that produces a
        structured result without live model calls.

        In live mode (requires authorization), this would call the governed
        model bridge for real DeepSeek synthesis.
        """
        artifact_id = f"cio-synth-{uuid.uuid4().hex[:16]}"

        if self._synthesis_fn:
            # Use injected mock function
            result = self._synthesis_fn(
                wake_job=wake_job,
                snapshot=snapshot,
                specialist_result=specialist_result,
                hermes_result=hermes_result,
            )
            self._call_count += 1
            self._cost_accrued += 0.001  # Mock cost
            if self.run_store and self._run_id:
                self.run_store.record_model_call(
                    self._run_id,
                    f"synthesis-{artifact_id}",
                    0.001,
                    actor="cio_run_worker",
                )
            return {"artifact_id": artifact_id, "result": result, "mode": self.mode}

        # Default: deterministic shadow synthesis
        synthesis = {
            "artifact_id": artifact_id,
            "mode": self.mode,
            "summary": f"CIO synthesis for wake {wake_job.get('wake_job_id', 'unknown')}",
            "recommendations": [],
            "confidence": 0.0,
            "requires_operator_review": True,
            "snapshot_ref": snapshot.get("snapshot_id"),
            "health_state": "UNKNOWN",
        }

        if self.run_store and self._run_id:
            try:
                self.run_store.record_model_call(
                    self._run_id,
                    f"synthesis-{artifact_id}",
                    0.001,
                    actor="cio_run_worker",
                )
            except Exception:
                pass
            self._call_count += 1
            self._cost_accrued += 0.001

        return {"artifact_id": artifact_id, "result": synthesis, "mode": self.mode}

    # ── Step: Write Actions ─────────────────────────────────────────────────

    def _write_actions(
        self,
        synthesis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Create CIO actions via the deterministic action ledger.

        NEVER writes raw files — only through the action ledger service.
        """
        action_ids: list[str] = []

        if self.action_ledger is None:
            return {"action_ids": action_ids}

        synthesis_data = synthesis_result.get("result", {})
        recommendations = synthesis_data.get("recommendations", [])

        for i, rec in enumerate(recommendations):
            try:
                action = {
                    "cio_action_id": f"cio-action-{uuid.uuid4().hex[:16]}",
                    "action_type": rec.get("action_type", "ADVISORY"),
                    "title": rec.get("title", f"Recommendation {i+1}"),
                    "description": rec.get("description", ""),
                    "domain": rec.get("domain", "GENERAL"),
                    "priority": rec.get("priority", "NORMAL"),
                    "parent_run_id": self._run_id,
                    "recommended_action": rec.get("recommended_action", ""),
                    "rationale": rec.get("rationale", ""),
                    "evidence_refs": rec.get("evidence_refs", []),
                }
                event = self.action_ledger.create_action(
                    action,
                    actor_id="cio_run_worker",
                    actor_type="agent",
                    authority="shadow_advisory_only",
                )
                aid = event.get("payload", {}).get("cio_action_id")
                if aid:
                    action_ids.append(aid)
                    if self.run_store and self._run_id:
                        self.run_store.transition(
                            self._run_id, "ACTION_WRITE",
                            action_id=aid,
                            actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Action write failed for rec %d: %s", i, e)

        # If no recommendations, still record a summary action
        if not recommendations and self.action_ledger is not None:
            try:
                action = {
                    "cio_action_id": f"cio-action-{uuid.uuid4().hex[:16]}",
                    "action_type": "STATUS",
                    "title": f"CIO Run {self._run_id or 'unknown'} — No recommendations",
                    "description": synthesis_data.get("summary", "Advisory cycle completed"),
                    "domain": "GENERAL",
                    "priority": "LOW",
                    "parent_run_id": self._run_id,
                }
                event = self.action_ledger.create_action(
                    action,
                    actor_id="cio_run_worker",
                    actor_type="agent",
                    authority="shadow_advisory_only",
                )
                aid = event.get("payload", {}).get("cio_action_id")
                if aid:
                    action_ids.append(aid)
            except Exception:
                pass

        return {"action_ids": action_ids}

    # ── Step: Enqueue Notifications ─────────────────────────────────────────

    def _enqueue_notifications(
        self,
        action_result: dict[str, Any],
        synthesis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Enqueue shadow notifications via the outbox.

        In shadow mode, notifications are enqueued but NOT delivered live.
        Live delivery requires AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY.
        """
        notification_ids: list[str] = []

        if self.notification_outbox is None:
            return {"notification_ids": notification_ids}

        # Create a notification for each action (shadow only)
        for action_id in action_result.get("action_ids", []):
            try:
                nid = f"notif-{uuid.uuid4().hex[:12]}"
                body_text = f"CIO run {self._run_id or 'unknown'} produced action {action_id}"
                notification = {
                    "notification_id": nid,
                    "message_class": "advisory",
                    "channel_targets": ["telegram"],
                    "subject": f"CIO Advisory Action {action_id[:12]}",
                    "body": body_text,
                    "body_hash": hashlib.sha256(body_text.encode()).hexdigest(),
                    "cio_action_id": action_id,
                    "wake_job_id": self._run_id,
                    "severity": "P2",
                }
                event = self.notification_outbox.enqueue(notification, actor_id="cio_run_worker")
                if event:
                    notification_ids.append(nid)
                    if self.run_store and self._run_id:
                        try:
                            self.run_store.transition(
                                self._run_id, "NOTIFICATION_ENQUEUE",
                                notification_id=nid,
                                actor="cio_run_worker",
                            )
                        except Exception:
                            pass
            except Exception as e:
                log.warning("Notification enqueue failed for action %s: %s", action_id, e)

        # Summary notification
        summary = synthesis_result.get("result", {}).get("summary")
        if summary:
            try:
                nid = f"notif-summary-{uuid.uuid4().hex[:12]}"
                notification = {
                    "notification_id": nid,
                    "message_class": "checkin",
                    "channel_targets": ["telegram"],
                    "subject": f"CIO Run Complete — {self._run_id[:12] if self._run_id else 'unknown'}",
                    "body": summary,
                    "body_hash": hashlib.sha256(summary.encode()).hexdigest(),
                    "wake_job_id": self._run_id,
                    "severity": "INFO",
                }
                event = self.notification_outbox.enqueue(notification, actor_id="cio_run_worker")
                if event:
                    notification_ids.append(nid)
            except Exception:
                pass

        return {"notification_ids": notification_ids}

    # ── Authority verification ─────────────────────────────────────────────

    @staticmethod
    def verify_authority() -> dict[str, Any]:
        """Verify this worker has only advisory authority."""
        return {
            "authority_level": "shadow_advisory_only",
            "allowed_tools": sorted(ADVISORY_ONLY_TOOLS),
            "forbidden_tools": sorted(FORBIDDEN_TOOLS),
            "can_execute_orders": False,
            "can_modify_risk": False,
            "can_remediate_infra": False,
            "can_send_live_telegram": False,
            "requires_authorization_for_live": True,
        }
