"""
CIO Wake Dispatcher — Sole durable wake claimant for CIO advisory cycles.

Gate-B component. The dispatcher is the ONLY component that reads PENDING wakes,
claims them, and creates CIO runs. CIORunWorker receives run_id — it does not
poll wakes or create runs.

Wake lifecycle:
  PENDING → CLAIMED (lease) → DISPATCHED (linked_run_id) → IN_FLIGHT → COMPLETED

COMPLETED only after the linked CIO run reaches a terminal state.
Dispatch is NOT completion of the CIO case.

Two wake intents:
  NEW_RUN:    dispatcher creates exactly one CIO run
  RESUME_RUN: target_run_id required; dispatcher validates existing run,
              does NOT create a run; CIORunWorker resumes target_run_id
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_wake_jobs import CIOWakeJobStore, ACTIVE

log = logging.getLogger("tradeai.cio_wake_dispatcher")

# ── Dispatch idempotency store path ─────────────────────────────────────────
DISPATCH_LEDGER_PATH = "data/cio/cio_wake_dispatches.jsonl"

# ── Default lease duration for claimed wakes ────────────────────────────────
DEFAULT_LEASE_SECONDS = 300  # 5 minutes
DEFAULT_STALE_LEASE_MULTIPLIER = 2  # 2x lease before auto-recover


class CIOWakeDispatcher:
    """Sole wake claimant and CIO run creator.

    Responsibilities:
    - Poll CIOWakeJobStore for PENDING wakes
    - Claim with lease
    - Semantic idempotency (wake_job_id + intent)
    - Wake → run linkage (NEW_RUN creates run; RESUME_RUN validates existing)
    - Dispatch record
    - Recovery of expired claims
    - Do NOT mark wakes complete at dispatch

    CIORunWorker executes run_id. CIOWakeDispatcher owns wake lifecycle.
    """

    def __init__(
        self,
        wake_store: Optional[CIOWakeJobStore] = None,
        run_store: Any = None,
        dispatch_ledger_path: str = DISPATCH_LEDGER_PATH,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ):
        self.wake_store = wake_store or CIOWakeJobStore()
        self.run_store = run_store  # CIORunStore, injected
        self.lease_seconds = lease_seconds
        self.dispatch_ledger_path = Path(dispatch_ledger_path)
        self.dispatch_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._dispatched: set[str] = set()
        self._load_dispatch_ledger()

    def _load_dispatch_ledger(self):
        """Load dispatched wake IDs from the dispatch ledger."""
        if not self.dispatch_ledger_path.exists():
            return
        try:
            with open(self.dispatch_ledger_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        entry = json.loads(stripped)
                        wid = entry.get("wake_job_id")
                        if wid:
                            self._dispatched.add(wid)
                    except Exception:
                        continue
        except Exception:
            pass

    def _record_dispatch(self, wake_job_id: str, run_id: str, intent: str):
        """Record a dispatch in the ledger for idempotency."""
        entry = json.dumps({
            "wake_job_id": wake_job_id,
            "run_id": run_id,
            "wake_intent": intent,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True) + "\n"
        try:
            with open(self.dispatch_ledger_path, "a") as f:
                f.write(entry)
                f.flush()
        except Exception:
            pass
        self._dispatched.add(wake_job_id)

    def _semantic_idempotency_key(self, wake: dict[str, Any]) -> str:
        """Compute a semantic idempotency key from wake identity + intent."""
        wake_id = wake.get("wake_job_id", "")
        intent = wake.get("wake_intent", "NEW_RUN")
        target = wake.get("target_run_id", "")
        raw = f"{wake_id}:{intent}:{target}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Dispatch ────────────────────────────────────────────────────────────

    def poll_and_dispatch(self, max_dispatches: int = 5) -> dict[str, Any]:
        """Poll for pending wakes and dispatch up to max_dispatches runs.

        Does NOT mark wakes complete. Wake completion is linked to
        terminal run state via on_run_completed().
        """
        # Recover expired leases first
        recovered = self.wake_store.recover_expired_leases(
            stale_seconds=self.lease_seconds * DEFAULT_STALE_LEASE_MULTIPLIER
        )
        if recovered:
            log.info("Recovered %d expired wake leases: %s", len(recovered), recovered)

        wakes = self.wake_store.list_wakes(status="PENDING", limit=max_dispatches)

        dispatched: list[dict[str, str]] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for wake in wakes:
            wake_job_id = wake.get("wake_job_id", "")

            # Idempotency: skip already-dispatched wakes
            if wake_job_id in self._dispatched:
                skipped.append(wake_job_id)
                continue

            # Safety: skip if already active
            current = self.wake_store.get_wake_job(wake_job_id)
            if current and current.get("current_status") in ACTIVE:
                self._dispatched.add(wake_job_id)
                skipped.append(wake_job_id)
                continue

            # Determine wake intent
            wake_intent = wake.get("wake_intent", "NEW_RUN")
            target_run_id = wake.get("target_run_id")

            # ── RESUME_RUN validation ──────────────────────────────────
            if wake_intent == "RESUME_RUN":
                if not target_run_id:
                    errors.append({
                        "wake_job_id": wake_job_id,
                        "error": "RESUME_RUN requires target_run_id",
                    })
                    skipped.append(wake_job_id)
                    continue

                if self.run_store is not None:
                    existing_run = self.run_store.get_run(target_run_id)
                    if existing_run is None:
                        errors.append({
                            "wake_job_id": wake_job_id,
                            "error": f"RESUME_RUN target {target_run_id} not found",
                        })
                        skipped.append(wake_job_id)
                        continue
                    if existing_run.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "EXPIRED"):
                        errors.append({
                            "wake_job_id": wake_job_id,
                            "error": f"RESUME_RUN target {target_run_id} is terminal: {existing_run['status']}",
                        })
                        skipped.append(wake_job_id)
                        continue

            # ── Claim with lease ───────────────────────────────────────
            claim_token = str(uuid.uuid4())
            try:
                self.wake_store.claim(
                    wake_job_id, claim_token,
                    lease_seconds=self.lease_seconds,
                    actor_id="cio_wake_dispatcher",
                )
            except ValueError as e:
                log.warning("Could not claim wake %s: %s", wake_job_id, e)
                skipped.append(wake_job_id)
                continue

            # ── Wake intent normalization ────────────────────────────────
            # Only three valid paths:
            #   1. NEW_RUN        → create exactly one CIO run
            #   2. RESUME_RUN     → link to existing run (target_run_id required)
            #   3. Recognized legacy intent → explicitly normalized to NEW_RUN
            # Unknown/malformed intents → fail closed (no run created)
            #
            # This is the explicit compatibility map.  Do NOT use a
            # catch-all "anything else = NEW_RUN" — unknown intent
            # produces durable invalid-intent disposition.
            LEGACY_INTENT_NORMALIZATION: dict[str, str] = {
                # Schedule-purpose intents (used by schedule producers)
                # preserved as run_purpose; normalized to NEW_RUN operation
                "SCHEDULED_CIO_BRIEF": "NEW_RUN",
                "HEALTH_EVENT": "NEW_RUN",
                "WATCH_OR_CATALYST_REVIEW": "NEW_RUN",
                "TAX_REVIEW": "NEW_RUN",
                "PORTFOLIO_ALLOCATION_REVIEW": "NEW_RUN",
                "BROKER_RECONCILIATION": "NEW_RUN",
                "INCOME_REVIEW": "NEW_RUN",
                "RETIREMENT_REVIEW": "NEW_RUN",
                "RISK_OR_STOP_EVENT": "NEW_RUN",
                "OPERATOR_REQUEST": "NEW_RUN",
            }

            dispatch_intent = wake_intent
            if wake_intent == "NEW_RUN" or wake_intent == "RESUME_RUN":
                dispatch_intent = wake_intent
            elif wake_intent in LEGACY_INTENT_NORMALIZATION:
                dispatch_intent = LEGACY_INTENT_NORMALIZATION[wake_intent]
            else:
                # Unknown/malformed wake intent → fail closed
                log.warning(
                    "Wake %s has unrecognized wake_intent=%r — not creating run",
                    wake_job_id, wake_intent,
                )
                try:
                    self.wake_store.invalid_intent(
                        wake_job_id,
                        reason=f"Unrecognized wake_intent: {wake_intent}",
                        actor_id="cio_wake_dispatcher",
                    )
                except (ValueError, AttributeError):
                    # If invalid_intent doesn't exist yet, release the claim
                    try:
                        self.wake_store.release(wake_job_id, actor_id="cio_wake_dispatcher")
                    except ValueError:
                        pass
                errors.append({
                    "wake_job_id": wake_job_id,
                    "error": f"Invalid wake_intent: {wake_intent}",
                })
                skipped.append(wake_job_id)
                continue

            run_id = None
            if dispatch_intent == "NEW_RUN":
                if self.run_store is not None:
                    try:
                        trigger_type = self._map_wake_to_run_trigger(
                            wake.get("trigger_type", "SCHEDULE_DUE")
                        )
                        priority = wake.get("priority", "NORMAL").upper()

                        event = self.run_store.create_run(
                            trigger_type=trigger_type,
                            trigger_ref=wake_job_id,
                            priority=priority,
                            required_domains=wake.get("required_domains", []),
                            parent_action_ids=(
                                [wake["parent_cio_action_id"]]
                                if wake.get("parent_cio_action_id") else []
                            ),
                            parent_handoff_ids=(
                                [wake["parent_handoff_id"]]
                                if wake.get("parent_handoff_id") else []
                            ),
                            actor="cio_wake_dispatcher",
                        )
                        run_id = event["payload"]["run_id"]
                    except Exception as e:
                        log.error("Could not create CIO run for wake %s: %s", wake_job_id, e)
                        errors.append({"wake_job_id": wake_job_id, "error": str(e)})
                        try:
                            self.wake_store.release(wake_job_id, actor_id="cio_wake_dispatcher")
                        except ValueError:
                            pass
                        continue
            else:  # RESUME_RUN
                run_id = target_run_id

            # ── Dispatch with linked_run_id ────────────────────────────
            try:
                self.wake_store.dispatch(
                    wake_job_id,
                    linked_run_id=run_id or "",
                    wake_intent=wake_intent,
                    actor_id="cio_wake_dispatcher",
                )
            except ValueError as e:
                log.warning("Could not dispatch wake %s: %s", wake_job_id, e)
                skipped.append(wake_job_id)
                continue

            self._record_dispatch(wake_job_id, run_id or "", wake_intent)
            dispatched.append({
                "wake_job_id": wake_job_id,
                "run_id": run_id,
                "wake_intent": wake_intent,
            })

        return {
            "dispatched_count": len(dispatched),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "recovered_count": len(recovered),
            "dispatched": dispatched,
            "skipped": skipped,
            "errors": errors,
        }

    def mark_in_flight(self, wake_job_id: str) -> bool:
        """Mark a dispatched wake as IN_FLIGHT when the run worker starts."""
        try:
            self.wake_store.set_in_flight(wake_job_id, actor_id="cio_wake_dispatcher")
            return True
        except ValueError:
            return False

    def on_run_completed(
        self,
        wake_job_id: str,
        run_id: str,
        terminal_status: str,
        cio_artifact_id: str = "",
    ) -> bool:
        """Complete a wake after its linked CIO run reaches a terminal state.

        Uses the canonical TERMINAL_STATUSES from cio_run (COMPLETED,
        BLOCKED, FAILED, CANCELLED, EXPIRED).  Only those states
        finalize the linked wake.
        """
        from scripts.lib.cio_run import TERMINAL_STATUSES

        if terminal_status not in TERMINAL_STATUSES:
            return False
        try:
            self.wake_store.complete(
                wake_job_id,
                completion_payload={
                    "cio_run_id": run_id,
                    "run_status": terminal_status,
                    "cio_artifact_id": cio_artifact_id,
                },
                actor_id="cio_wake_dispatcher",
            )
            return True
        except ValueError:
            return False

    @staticmethod
    def _map_wake_to_run_trigger(wake_trigger: str) -> str:
        """Map wake job trigger types to CIO run trigger types."""
        mapping = {
            "SCHEDULE_DUE": "SCHEDULED_DAILY",
            "ACTION_FOLLOWUP_DUE": "ACTION_FOLLOWUP",
            "HANDOFF_COMPLETED": "SPECIALIST_COMPLETION",
            "HERMES_CHALLENGE_RESOLVED": "HERMES_RESOLVED",
            "HEALTH_BLOCK_STARTED": "HEALTH_EVENT",
            "HEALTH_BLOCK_CLEARED": "HEALTH_EVENT",
        }
        return mapping.get(wake_trigger, "SYSTEM")

    def get_dispatch_stats(self) -> dict[str, Any]:
        """Return dispatch statistics from the ledger."""
        return {
            "total_dispatched": len(self._dispatched),
            "ledger_path": str(self.dispatch_ledger_path),
        }
