"""
CIO Run Worker — Executes a specific CIO run by run_id.

Gate-B component. CIOWakeDispatcher owns wake lifecycle and creates runs.
CIORunWorker executes a supplied run_id — it does NOT poll wakes or create runs.

Advisory cycle:
  1. Open run projection from CIORunStore
  2. Determine current state (fresh QUEUED or resumed EVIDENCE_BUILD)
  3. If fresh: health check → evidence build
  4. Route specialists if needed → WAITING_FOR_SPECIALISTS (exit) or continue
  5. Hermes challenge if material → WAITING_FOR_HERMES (exit) or continue
  6. CIO synthesis (Alex, governed)
  7. Write actions → enqueue notifications
  8. Complete run
  9. On terminal: notify CIOWakeDispatcher to complete associated wake

Authority: advisory_only, no broker/risk/execution/2FA tools.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
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

RUN_BUDGETS: dict[str, dict[str, Any]] = {
    "daily_brief": {
        "name": "daily_brief",
        "max_provider_calls": 4,
        "max_cost_usd": 0.02,
        "max_specialist_calls": 2,
        "max_hermes_challenges": 1,
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

HERMES_MATERIALITY_THRESHOLD = 0.7


def resolve_run_budget(trigger_type: str) -> dict[str, Any]:
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
    """Executes a single CIO advisory cycle for a specific run_id.

    The run is created by CIOWakeDispatcher. The worker only executes —
    it never creates runs or polls wakes.
    """

    def __init__(
        self,
        *,
        run_store: Any = None,
        health_boundary: Any = None,
        action_ledger: Any = None,
        notification_outbox: Any = None,
        handoff_queue: Any = None,
        hermes_queue: Any = None,
        operator_profile: Any = None,
        mode: str = "shadow",
        synthesis_fn: Optional[Callable] = None,
        specialist_fn: Optional[Callable] = None,
        hermes_fn: Optional[Callable] = None,
    ):
        self.run_store = run_store
        self.health_boundary = health_boundary
        self.action_ledger = action_ledger
        self.notification_outbox = notification_outbox
        self.handoff_queue = handoff_queue
        self.hermes_queue = hermes_queue
        self.operator_profile = operator_profile
        self.mode = mode

        self._synthesis_fn = synthesis_fn
        self._specialist_fn = specialist_fn
        self._hermes_fn = hermes_fn

        self._run_id: Optional[str] = None
        self._call_count: int = 0
        self._cost_accrued: float = 0.0
        self._start_time: Optional[float] = None

    # ── Execute ────────────────────────────────────────────────────────────

    def execute(
        self,
        run_id: str,
        *,
        force_health_state: Optional[str] = None,
        force_snapshot: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute the CIO advisory cycle for a specific run_id.

        The run must already exist (created by CIOWakeDispatcher).
        Handles both fresh QUEUED runs and resumed EVIDENCE_BUILD runs.
        """
        self._start_time = time.time()
        self._call_count = 0
        self._cost_accrued = 0.0
        self._run_id = run_id

        # Load run projection
        if self.run_store is None:
            return {
                "run_id": run_id,
                "mode": self.mode,
                "status": "FAILED",
                "error": "No run_store available",
            }

        run = self.run_store.get_run(run_id)
        if run is None:
            return {
                "run_id": run_id,
                "mode": self.mode,
                "status": "FAILED",
                "error": f"Run not found: {run_id}",
            }

        current_status = run.get("status", "QUEUED")
        trigger_type = run.get("trigger_type", "SYSTEM")

        result: dict[str, Any] = {
            "run_id": run_id,
            "mode": self.mode,
            "resume": current_status not in ("QUEUED",),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "STARTED",
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
            budget = resolve_run_budget(trigger_type)
            result["budget_profile"] = budget.get("name", "default")

            # Step 1: Health check (fresh runs only)
            if current_status == "QUEUED":
                self.run_store.start(run_id, actor="cio_run_worker")
                health_result = self._check_health(force_health_state)
                if health_result["blocked"]:
                    result["status"] = "BLOCKED_BY_HEALTH"
                    result["blocked_by"] = "HEALTH_BOUNDARY"
                    try:
                        self.run_store.block(
                            run_id, f"HEALTH:{health_result['state']}",
                            actor="cio_run_worker",
                        )
                    except Exception:
                        pass
                    return result
                result["health_state"] = health_result["state"]
                result["health_decision_id"] = health_result.get("decision_id")

            # Step 2: Build financial snapshot (fresh runs after health, or resumed)
            if current_status in ("QUEUED", "EVIDENCE_BUILD"):
                snapshot_result = self._build_snapshot(force_snapshot)
                result["snapshot_id"] = snapshot_result.get("snapshot_id")
                result["snapshot_hash"] = snapshot_result.get("content_hash")

                if self.run_store and snapshot_result.get("snapshot_id"):
                    try:
                        self.run_store.evidence_built(
                            run_id,
                            snapshot_result["snapshot_id"],
                            actor="cio_run_worker",
                        )
                    except Exception:
                        pass
            else:
                snapshot_result = {}

            # Step 3: Route specialists if needed
            required_domains = run.get("required_domains", [])
            specialist_result = self._route_specialists(run_id, required_domains, snapshot_result)
            result["specialist_handoffs"] = specialist_result.get("handoff_ids", [])

            # Check if we need to wait for specialists
            if specialist_result.get("should_wait"):
                self.run_store.wait_for_specialists(
                    run_id,
                    specialist_result["handoff_ids"],
                    actor="cio_run_worker",
                )
                result["status"] = "WAITING_FOR_SPECIALISTS"
                return result

            # Step 4: Hermes challenge (material events only)
            hermes_result = self._maybe_challenge(run_id, run, snapshot_result)
            result["hermes_challenges"] = hermes_result.get("challenge_ids", [])

            if hermes_result.get("should_wait"):
                self.run_store.wait_for_hermes(
                    run_id,
                    hermes_result["challenge_ids"],
                    actor="cio_run_worker",
                )
                result["status"] = "WAITING_FOR_HERMES"
                return result

            # Step 5: Governed CIO synthesis (via Alex)
            synthesis_result = self._cio_synthesis(run, snapshot_result, specialist_result, hermes_result)
            result["synthesis_artifact_id"] = synthesis_result.get("artifact_id")

            # Step 6: Create/update CIO actions
            action_result = self._write_actions(synthesis_result)
            result["actions_created"] = action_result.get("action_ids", [])

            # Step 7: Enqueue shadow notifications
            notification_result = self._enqueue_notifications(action_result, synthesis_result)
            result["notifications_enqueued"] = notification_result.get("notification_ids", [])

            # Step 8: Complete the run
            if self.run_store:
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
            log.exception("CIO run worker failed for run %s", run_id)
            result["status"] = "FAILED"
            result["errors"].append(str(e))
            if self.run_store:
                try:
                    self.run_store.fail(run_id, str(e)[:200], actor="cio_run_worker")
                except Exception:
                    pass

        finally:
            elapsed = time.time() - (self._start_time or time.time())
            result["elapsed_seconds"] = round(elapsed, 2)
            result["provider_calls"] = self._call_count
            result["cost_accrued"] = round(self._cost_accrued, 6)
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

        return result

    # ── Step: Health Check ──────────────────────────────────────────────────

    def _check_health(self, force_state: Optional[str] = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": "UNKNOWN",
            "blocked": False,
            "decision_id": None,
        }

        if force_state is not None:
            result["state"] = force_state
            result["blocked"] = force_state in ("BLOCKED",)
            if not result["blocked"] and self.run_store and self._run_id:
                try:
                    self.run_store.health_checked(
                        self._run_id,
                        f"health-{uuid.uuid4().hex[:12]}",
                        actor="cio_run_worker",
                    )
                except Exception:
                    pass
            return result

        if self.health_boundary is None:
            result["blocked"] = False
            return result

        try:
            advisory_state = self.health_boundary.current_advisory_state()
            result["state"] = advisory_state
            result["blocked"] = advisory_state in ("BLOCKED",)
            result["decision_id"] = getattr(self.health_boundary, "latest_decision_id", lambda: None)()
        except Exception as e:
            log.warning("Health boundary check failed: %s", e)

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
        run_id: str,
        required_domains: list[str],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Route specialists. Returns should_wait=True if specialists need to complete."""
        handoff_ids: list[str] = []

        if not self.handoff_queue or not required_domains:
            return {"handoff_ids": handoff_ids, "should_wait": False, "artifacts": []}

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

        agent_task_types: dict[str, str] = {
            "maria": "cio_question",
            "steph": "allocation_review",
            "guardian": "risk_review",
            "ledger": "tax_account_review",
        }

        specialists_needed: set[str] = set()
        for domain in required_domains:
            spec = domain_specialists.get(domain)
            if spec:
                specialists_needed.add(spec)

        for spec in specialists_needed:
            try:
                task_type = agent_task_types.get(spec, "cio_question")
                handoff = {
                    "handoff_id": f"handoff-{spec}-{uuid.uuid4().hex[:8]}",
                    "from_agent": "alex",
                    "to_agent": spec,
                    "task_type": task_type,
                    "task_summary": f"CIO run {run_id}: review domains",
                    "parent_run_id": run_id,
                    "input_hash": hashlib.sha256(
                        f"{spec}:{','.join(required_domains)}".encode()
                    ).hexdigest(),
                    "priority": "NORMAL",
                }
                event = self.handoff_queue.enqueue(handoff, actor_id="cio_run_worker")
                hid = event.get("stream_id")
                if hid:
                    handoff_ids.append(hid)
                    if self.run_store:
                        self.run_store.record_specialist_request(
                            run_id, hid, actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Specialist enqueue failed for %s: %s", spec, e)

        should_wait = len(handoff_ids) > 0
        return {"handoff_ids": handoff_ids, "should_wait": should_wait, "artifacts": []}

    # ── Step: Hermes Challenge ──────────────────────────────────────────────

    def _maybe_challenge(
        self,
        run_id: str,
        run: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        challenge_ids: list[str] = []

        trigger_type = run.get("trigger_type", "")
        materiality = run.get("materiality", 0.0)

        should_challenge = (
            trigger_type in ("HEALTH_EVENT", "MATERIAL_EVENT")
            or materiality >= HERMES_MATERIALITY_THRESHOLD
        )

        if not should_challenge:
            return {"challenge_ids": [], "should_wait": False}

        if self.hermes_queue:
            try:
                event = self.hermes_queue.enqueue(
                    challenge_type="freshness_decay",
                    description=f"Material event for CIO run {run_id}",
                    source=f"cio_run:{run_id}",
                    priority="high" if materiality >= 0.8 else "normal",
                    evidence_refs=[snapshot.get("snapshot_id", "")],
                    actor_id="cio_run_worker",
                )
                cid = event.get("payload", {}).get("challenge_id") or event.get("stream_id")
                if cid:
                    challenge_ids.append(cid)
                    if self.run_store:
                        self.run_store.record_hermes_request(
                            run_id, cid, actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Hermes enqueue failed: %s", e)

        return {
            "challenge_ids": challenge_ids,
            "should_wait": len(challenge_ids) > 0,
        }

    # ── Step: CIO Synthesis ─────────────────────────────────────────────────

    def _cio_synthesis(
        self,
        run: dict[str, Any],
        snapshot: dict[str, Any],
        specialist_result: dict[str, Any],
        hermes_result: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = f"cio-synth-{uuid.uuid4().hex[:16]}"

        if self._synthesis_fn:
            result = self._synthesis_fn(
                run=run,
                snapshot=snapshot,
                specialist_result=specialist_result,
                hermes_result=hermes_result,
            )
            self._call_count += 1
            self._cost_accrued += 0.001
            if self.run_store and self._run_id:
                self.run_store.record_model_call(
                    self._run_id, f"synthesis-{artifact_id}", 0.001,
                    actor="cio_run_worker",
                )
            return {"artifact_id": artifact_id, "result": result, "mode": self.mode}

        synthesis = {
            "artifact_id": artifact_id,
            "mode": self.mode,
            "summary": f"CIO synthesis for run {self._run_id}",
            "recommendations": [],
            "confidence": 0.0,
            "requires_operator_review": True,
            "snapshot_ref": snapshot.get("snapshot_id"),
            "health_state": "UNKNOWN",
        }

        if self.run_store and self._run_id:
            try:
                self.run_store.record_model_call(
                    self._run_id, f"synthesis-{artifact_id}", 0.001,
                    actor="cio_run_worker",
                )
            except Exception:
                pass
            self._call_count += 1
            self._cost_accrued += 0.001

        return {"artifact_id": artifact_id, "result": synthesis, "mode": self.mode}

    # ── Step: Write Actions ─────────────────────────────────────────────────

    def _write_actions(self, synthesis_result: dict[str, Any]) -> dict[str, Any]:
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
                    if self.run_store:
                        self.run_store.transition(
                            self._run_id, "ACTION_WRITE",
                            action_id=aid, actor="cio_run_worker",
                        )
            except Exception as e:
                log.warning("Action write failed for rec %d: %s", i, e)

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
        notification_ids: list[str] = []

        if self.notification_outbox is None:
            return {"notification_ids": notification_ids}

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
                    if self.run_store:
                        try:
                            self.run_store.transition(
                                self._run_id, "NOTIFICATION_ENQUEUE",
                                notification_id=nid, actor="cio_run_worker",
                            )
                        except Exception:
                            pass
            except Exception as e:
                log.warning("Notification enqueue failed for action %s: %s", action_id, e)

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
