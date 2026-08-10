"""
CIO Wake Backlog Policy — Deterministic pre-filter for accumulated PENDING wakes.

Applied BEFORE poll_and_dispatch() by any recurring dispatcher entry-point.
When the dispatcher activates after downtime (or on first run), PENDING wakes
may have accumulated for hours. This policy classifies each PENDING wake and
disposes of invalid ones before the dispatcher claims them.

Classifications:
  DISPATCH              — wake is still valid and should be dispatched
  EXPIRE                — wake is past its effective window or max backlog age
  CANCEL_AS_SUPERSEDED  — a newer wake for the same purpose supersedes this one
  ALREADY_SATISFIED     — a linked CIO run already exists and reached terminal

All decisions are deterministic. No model calls, no operator prompts.
Wakes are NEVER deleted. Dispositions are recorded as durable events in the
event-sourced wake store.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from scripts.lib.cio_run import TERMINAL_STATUSES

log = logging.getLogger("tradeai.cio_wake_backlog_policy")


class CIOWakeBacklogPolicy:
    """Deterministic policy for handling accumulated PENDING wakes before
    dispatcher activation.

    Required classifications per wake:
      DISPATCH            — wake is still valid and should be dispatched
      EXPIRE              — wake is past its effective window
      CANCEL_AS_SUPERSEDED — a newer wake for the same purpose supersedes this one
      ALREADY_SATISFIED   — a linked CIO run already exists and reached terminal

    All decisions must be deterministic — no model calls, no operator prompts.
    Wakes are NEVER deleted. Dispositions are recorded as durable events.
    """

    # Bounded lookback: do not consider wakes older than this
    MAX_BACKLOG_AGE_HOURS = 24

    # Effective windows per trigger type
    EFFECTIVE_WINDOWS: dict[str, int] = {
        "SCHEDULE_DUE": 4,           # hours — scheduled briefs expire
        "HEALTH_BLOCK_STARTED": 2,   # hours — health events are time-sensitive
        "HEALTH_BLOCK_CLEARED": 2,
        "ACTION_FOLLOWUP_DUE": 8,
        "HANDOFF_COMPLETED": 12,
        "HERMES_CHALLENGE_RESOLVED": 6,
    }

    # Semantically idempotent trigger types (only one per period)
    SEMANTIC_SINGLETON_TYPES: frozenset[str] = frozenset({"SCHEDULE_DUE"})

    def __init__(self):
        pass

    def classify(
        self,
        wake: dict[str, Any],
        all_pending_wakes: Optional[list[dict[str, Any]]] = None,
        run_store: Any = None,
    ) -> str:
        """Classify a single PENDING wake.

        Returns one of: DISPATCH, EXPIRE, CANCEL_AS_SUPERSEDED, ALREADY_SATISFIED
        """
        trigger_type = wake.get("trigger_type", "")
        created_at_str = wake.get("created_at", "")
        wake_job_id = wake.get("wake_job_id", "")

        # 1. Effective window expiry
        if trigger_type in self.EFFECTIVE_WINDOWS:
            effective_hours = self.EFFECTIVE_WINDOWS[trigger_type]
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    expiry_time = created_at + timedelta(hours=effective_hours)
                    if datetime.now(timezone.utc) > expiry_time:
                        return "EXPIRE"
                except (ValueError, TypeError):
                    pass

        # 2. Superseded check (semantic singletons)
        if trigger_type in self.SEMANTIC_SINGLETON_TYPES and all_pending_wakes:
            this_created_at = None
            try:
                this_created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError):
                pass

            if this_created_at is not None:
                for other in all_pending_wakes:
                    other_wid = other.get("wake_job_id", "")
                    if other_wid == wake_job_id:
                        continue
                    if other.get("trigger_type") != trigger_type:
                        continue
                    other_created_str = other.get("created_at", "")
                    if not other_created_str:
                        continue
                    try:
                        other_created_at = datetime.fromisoformat(other_created_str)
                    except (ValueError, TypeError):
                        continue
                    if other_created_at > this_created_at:
                        return "CANCEL_AS_SUPERSEDED"

        # 3. Already satisfied (linked run terminal)
        linked_run_id = wake.get("linked_run_id")
        if linked_run_id and run_store is not None:
            try:
                run = run_store.get_run(linked_run_id)
                if run is not None and run.get("status") in TERMINAL_STATUSES:
                    return "ALREADY_SATISFIED"
            except Exception:
                pass

        # 4. Max backlog age (hard safety cutoff)
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                cutoff = created_at + timedelta(hours=self.MAX_BACKLOG_AGE_HOURS)
                if datetime.now(timezone.utc) > cutoff:
                    return "EXPIRE"
            except (ValueError, TypeError):
                pass

        # 5. Default: valid for dispatch
        return "DISPATCH"

    def apply(
        self,
        wake_store: Any,
        run_store: Any = None,
        max_dispatches: int = 5,
    ) -> dict[str, Any]:
        """Apply backlog policy to all PENDING wakes.

        Returns dict with dispatched/expired/superseded/satisfied counts and IDs.
        """
        all_pending = wake_store.list_wakes(status="PENDING", limit=100)

        results: dict[str, Any] = {
            "dispatched": [],
            "expired": [],
            "superseded": [],
            "satisfied": [],
            "dispatched_count": 0,
            "expired_count": 0,
            "superseded_count": 0,
            "satisfied_count": 0,
        }

        # Build dispatch list first — classify all, then apply dispositions
        dispatch_list: list[str] = []

        for wake in all_pending:
            wake_job_id = wake.get("wake_job_id", "")
            trigger_type = wake.get("trigger_type", "UNKNOWN")

            classification = self.classify(
                wake,
                all_pending_wakes=all_pending,
                run_store=run_store,
            )

            if classification == "EXPIRE":
                reason = f"BACKLOG_EXPIRED:trigger={trigger_type}"
                try:
                    wake_store.expire(wake_job_id, reason=reason, actor_id="cio_backlog_policy")
                    results["expired"].append({
                        "wake_job_id": wake_job_id,
                        "reason": reason,
                    })
                    results["expired_count"] += 1
                except ValueError as e:
                    log.warning("Could not expire wake %s: %s", wake_job_id, e)

            elif classification == "CANCEL_AS_SUPERSEDED":
                reason = f"BACKLOG_SUPERSEDED:trigger={trigger_type}"
                try:
                    wake_store.cancel(wake_job_id, reason=reason, actor_id="cio_backlog_policy")
                    results["superseded"].append({
                        "wake_job_id": wake_job_id,
                        "reason": reason,
                    })
                    results["superseded_count"] += 1
                except ValueError as e:
                    log.warning("Could not cancel wake %s: %s", wake_job_id, e)

            elif classification == "ALREADY_SATISFIED":
                reason = f"BACKLOG_ALREADY_SATISFIED:trigger={trigger_type}"
                try:
                    wake_store.complete(
                        wake_job_id,
                        completion_payload={"backlog_reason": reason},
                        actor_id="cio_backlog_policy",
                    )
                    results["satisfied"].append({
                        "wake_job_id": wake_job_id,
                        "reason": reason,
                    })
                    results["satisfied_count"] += 1
                except ValueError as e:
                    log.warning("Could not complete satisfied wake %s: %s", wake_job_id, e)

            elif classification == "DISPATCH":
                dispatch_list.append(wake_job_id)
                if len(dispatch_list) <= max_dispatches:
                    results["dispatched"].append({
                        "wake_job_id": wake_job_id,
                    })

        results["dispatched_count"] = len(results["dispatched"])

        return results
