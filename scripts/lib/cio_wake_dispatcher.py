"""
CIO Wake Dispatcher — Polls pending wake jobs and dispatches CIO run workers.

P-2.6 component. One wake = one CIO run. Idempotent by wake_job_id.
Duplicate dispatch prevented. No model calls. No Telegram. No live activation.

The dispatcher polls CIOWakeJobStore for PENDING wakes, claims them,
dispatches a CIORunWorker, and either acknowledges or releases the wake.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_wake_jobs import CIOWakeJobStore

log = logging.getLogger("tradeai.cio_wake_dispatcher")

# ── Dispatch idempotency store path ─────────────────────────────────────────
DISPATCH_LEDGER_PATH = "data/cio/cio_wake_dispatches.jsonl"

# ── Known wake job ID → CIO run ID mapping (in-memory, rebuildable) ─────────
# In production this would also be persisted, but the wake store's event chain
# is authoritative — a completed wake cannot be dispatched twice.


class CIOWakeDispatcher:
    """Polls pending wake jobs and dispatches exactly one CIO run per wake.

    This dispatcher does NOT execute runs — it only claims wakes and creates
    CIO run records. The actual run execution is handled by CIORunWorker.
    """

    def __init__(
        self,
        wake_store: Optional[CIOWakeJobStore] = None,
        run_store: Any = None,
        dispatch_ledger_path: str = DISPATCH_LEDGER_PATH,
    ):
        self.wake_store = wake_store or CIOWakeJobStore()
        self.run_store = run_store  # CIORunStore — injected, not imported to avoid circular deps
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
                        import json as _json
                        entry = _json.loads(stripped)
                        wid = entry.get("wake_job_id")
                        if wid:
                            self._dispatched.add(wid)
                    except Exception:
                        continue
        except Exception:
            pass

    def _record_dispatch(self, wake_job_id: str, run_id: str):
        """Record a dispatch in the ledger for idempotency."""
        entry = json.dumps({
            "wake_job_id": wake_job_id,
            "run_id": run_id,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True) + "\n"
        try:
            with open(self.dispatch_ledger_path, "a") as f:
                f.write(entry)
                f.flush()
        except Exception:
            pass
        self._dispatched.add(wake_job_id)

    def poll_and_dispatch(self, max_dispatches: int = 5) -> dict[str, Any]:
        """Poll for pending wakes and dispatch up to max_dispatches runs.

        Returns a summary of dispatches made.
        """
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

            # Also check if this wake is already completed in the store
            # (safety net for ledger/sync gaps)
            current_wake = self.wake_store.get_wake_job(wake_job_id)
            if current_wake and current_wake.get("current_status") in ("COMPLETED", "DISPATCHED", "ACKNOWLEDGED"):
                self._dispatched.add(wake_job_id)
                skipped.append(wake_job_id)
                continue

            # Claim the wake
            claim_token = str(uuid.uuid4())
            try:
                self.wake_store.claim(wake_job_id, claim_token, actor_id="cio_wake_dispatcher")
            except ValueError as e:
                log.warning("Could not claim wake %s: %s", wake_job_id, e)
                skipped.append(wake_job_id)
                continue

            # Dispatch it
            try:
                self.wake_store.dispatch(wake_job_id, actor_id="cio_wake_dispatcher")
            except ValueError as e:
                log.warning("Could not dispatch wake %s: %s", wake_job_id, e)
                skipped.append(wake_job_id)
                continue

            # Create a CIO run if we have a run store
            run_id = None
            if self.run_store is not None:
                try:
                    trigger_type = wake.get("trigger_type", "SCHEDULE_DUE")
                    run_trigger = self._map_wake_to_run_trigger(trigger_type)
                    # Normalize priority to uppercase for CIORunStore
                    priority = wake.get("priority", "NORMAL").upper()

                    event = self.run_store.create_run(
                        trigger_type=run_trigger,
                        trigger_ref=wake_job_id,
                        priority=priority,
                        required_domains=wake.get("required_domains", []),
                        parent_action_ids=(
                            [wake["parent_cio_action_id"]] if wake.get("parent_cio_action_id") else []
                        ),
                        parent_handoff_ids=(
                            [wake["parent_handoff_id"]] if wake.get("parent_handoff_id") else []
                        ),
                        actor="cio_wake_dispatcher",
                    )
                    run_id = event["payload"]["run_id"]
                except Exception as e:
                    log.error("Could not create CIO run for wake %s: %s", wake_job_id, e)
                    errors.append({"wake_job_id": wake_job_id, "error": str(e)})
                    # Release the wake so it can be retried
                    try:
                        self.wake_store.release(wake_job_id, actor_id="cio_wake_dispatcher")
                    except ValueError:
                        pass
                    continue

            # Acknowledge the wake
            try:
                self.wake_store.acknowledge(wake_job_id, actor_id="cio_wake_dispatcher")
            except ValueError as e:
                log.warning("Could not acknowledge wake %s: %s", wake_job_id, e)

            self._record_dispatch(wake_job_id, run_id or "no_run_store")
            dispatched.append({"wake_job_id": wake_job_id, "run_id": run_id})

        # Complete acknowledged wakes that have associated runs
        for d in dispatched:
            if d["run_id"]:
                try:
                    self.wake_store.complete(
                        d["wake_job_id"],
                        completion_payload={"cio_run_id": d["run_id"]},
                        actor_id="cio_wake_dispatcher",
                    )
                except ValueError:
                    pass

        return {
            "dispatched_count": len(dispatched),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "dispatched": dispatched,
            "skipped": skipped,
            "errors": errors,
        }

    @staticmethod
    def _map_wake_to_run_trigger(wake_trigger: str) -> str:
        """Map wake job trigger types to CIO run trigger types."""
        mapping = {
            "SCHEDULE_DUE": "SCHEDULED_DAILY",
            "ACTION_FOLLOWUP_DUE": "ACTION_FOLLOWUP",
            "HANDOFF_COMPLETED": "SPECIALIST_COMPLETION",
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


import json  # noqa: E402
