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
GOAL_WAKE_DEDUP_PATH = "data/cio/cio_goal_wake_dedup.jsonl"

# ── Default lease duration for claimed wakes ────────────────────────────────
DEFAULT_LEASE_SECONDS = 300  # 5 minutes
DEFAULT_STALE_LEASE_MULTIPLIER = 2  # 2x lease before auto-recover
# Dedup window for goal-sourced wakes (same agent+goal within this many minutes)
GOAL_WAKE_DEDUP_MINUTES = 30


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
        goal_store: Any = None,
        readiness_registry: Any = None,
    ):
        self.wake_store = wake_store or CIOWakeJobStore()
        self.run_store = run_store  # CIORunStore, injected
        self.lease_seconds = lease_seconds
        self.dispatch_ledger_path = Path(dispatch_ledger_path)
        self.dispatch_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.goal_wake_dedup_path = Path(GOAL_WAKE_DEDUP_PATH)
        self.goal_wake_dedup_path.parent.mkdir(parents=True, exist_ok=True)
        self._dispatched: set[str] = set()
        self._goal_store = goal_store  # optional CIOGoalStore
        self._readiness = readiness_registry
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

        Also enqueues NEW_RUN wakes for due/idle goals (WS2) before claim path.
        Does NOT mark wakes complete. Wake completion is linked to
        terminal run state via on_run_completed().
        """
        # Goal/event secondary path (never replaces event-bus claim authority)
        goal_enqueue = self.enqueue_goal_wakes(max_new=max_dispatches)

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
                            context=wake.get("context") or {},
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
            "goal_enqueue": goal_enqueue,
        }

    # ── Goal-sourced wakes (WS2) ─────────────────────────────────────────

    def _goal_store_or_default(self) -> Any:
        if self._goal_store is not None:
            return self._goal_store
        try:
            from scripts.lib.cio_goals import CIOGoalStore
            self._goal_store = CIOGoalStore()
        except Exception as exc:
            log.warning("CIOGoalStore unavailable: %s", exc)
            self._goal_store = None
        return self._goal_store

    def _readiness_or_default(self) -> Any:
        if self._readiness is not None:
            return self._readiness
        try:
            from scripts.lib.cio_agent_readiness import AgentReadinessRegistry
            self._readiness = AgentReadinessRegistry.load()
        except Exception:
            try:
                from scripts.lib.cio_agent_readiness import AgentReadinessRegistry
                # some versions use from_catalog / get_instance
                if hasattr(AgentReadinessRegistry, "from_catalog"):
                    self._readiness = AgentReadinessRegistry.from_catalog()
                elif hasattr(AgentReadinessRegistry, "get_instance"):
                    self._readiness = AgentReadinessRegistry.get_instance()
            except Exception as exc:
                log.warning("AgentReadinessRegistry unavailable: %s", exc)
                self._readiness = None
        return self._readiness

    def _goal_dedup_hit(self, agent_id: str, goal_id: str) -> bool:
        """True if we already enqueued agent+goal within GOAL_WAKE_DEDUP_MINUTES."""
        if not self.goal_wake_dedup_path.exists():
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=GOAL_WAKE_DEDUP_MINUTES)
        try:
            with open(self.goal_wake_dedup_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("agent_id") != agent_id or row.get("goal_id") != goal_id:
                        continue
                    ts = row.get("ts")
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff:
                            return True
                    except Exception:
                        continue
        except Exception:
            return False
        return False

    def _record_goal_dedup(self, agent_id: str, goal_id: str, wake_job_id: str) -> None:
        entry = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "goal_id": goal_id,
            "wake_job_id": wake_job_id,
        }, sort_keys=True) + "\n"
        try:
            with open(self.goal_wake_dedup_path, "a") as fh:
                fh.write(entry)
                fh.flush()
        except Exception:
            pass

    def enqueue_goal_wakes(
        self,
        max_new: int = 5,
        *,
        recent_event_types: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Enqueue NEW_RUN wakes for due/idle goals or goals linked to recent events.

        Dedup: same agent + goal within GOAL_WAKE_DEDUP_MINUTES.
        NOT_READY owners → blocked list (no wake enqueued).
        """
        store = self._goal_store_or_default()
        result: dict[str, Any] = {
            "enqueued": [],
            "skipped_dedup": [],
            "blocked_not_ready": [],
            "errors": [],
        }
        if store is None:
            result["errors"].append("no_goal_store")
            return result

        candidates: list[dict[str, Any]] = []
        try:
            candidates.extend(store.list_due_or_idle_goals(limit=max_new * 2))
            if recent_event_types:
                for g in store.goals_for_event_types(recent_event_types, limit=max_new):
                    if g.get("goal_id") not in {c.get("goal_id") for c in candidates}:
                        g = dict(g)
                        g["_wake_reason"] = "event_linked"
                        candidates.append(g)
        except Exception as exc:
            result["errors"].append(str(exc))
            return result

        readiness = self._readiness_or_default()
        enqueued_n = 0
        for g in candidates:
            if enqueued_n >= max_new:
                break
            agent_id = (g.get("owner_agent") or "").lower()
            goal_id = g.get("goal_id") or ""
            if not agent_id or not goal_id:
                continue

            # Readiness fence (SHADOW-first):
            # - Allow agents operable in agent_runtime FLEET (SHADOW) even if the
            #   maturity catalog still says DESIGNED (catalog lag is common).
            # - Block only hard disabled / suspended when not fleet-operable.
            fleet_ok = False
            try:
                import sys
                from pathlib import Path
                scripts = str(Path(__file__).resolve().parents[1])
                if scripts not in sys.path:
                    sys.path.insert(0, scripts)
                from agent_runtime.agents.definitions import FLEET
                spec = FLEET.get(agent_id)
                fleet_ok = bool(spec and getattr(spec, "is_operable_now", False))
            except Exception:
                fleet_ok = False

            if not fleet_ok and readiness is not None:
                try:
                    if hasattr(readiness, "has") and not readiness.has(agent_id):
                        result["blocked_not_ready"].append({
                            "goal_id": goal_id,
                            "agent_id": agent_id,
                            "reason": "UNKNOWN_AGENT",
                        })
                        continue
                    agent_r = readiness.get(agent_id)
                    if agent_r is not None:
                        if not getattr(agent_r, "enabled", True):
                            result["blocked_not_ready"].append({
                                "goal_id": goal_id,
                                "agent_id": agent_id,
                                "reason": "AGENT_DISABLED",
                            })
                            continue
                        if getattr(agent_r, "readiness_state", "") == "SUSPENDED":
                            result["blocked_not_ready"].append({
                                "goal_id": goal_id,
                                "agent_id": agent_id,
                                "reason": "SUSPENDED",
                            })
                            continue
                except KeyError:
                    result["blocked_not_ready"].append({
                        "goal_id": goal_id,
                        "agent_id": agent_id,
                        "reason": "UNKNOWN_AGENT",
                    })
                    continue
                except Exception:
                    pass

            if self._goal_dedup_hit(agent_id, goal_id):
                result["skipped_dedup"].append({"goal_id": goal_id, "agent_id": agent_id})
                continue

            reason = g.get("_wake_reason") or "due"
            trigger = "GOAL_EVENT_LINKED" if reason == "event_linked" else "GOAL_DUE"
            # Stable wake id for idempotency within the hour bucket
            hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
            wake_job_id = f"wake_goal_{goal_id}_{hour_bucket}"
            try:
                ctx = store.get_context_for_agent(agent_id)
                payload = {
                    "wake_job_id": wake_job_id,
                    "trigger_type": trigger,
                    "trigger_ref": goal_id,
                    "trigger_hash": hashlib.sha256(f"{agent_id}:{goal_id}:{hour_bucket}".encode()).hexdigest()[:16],
                    "reason_codes": [
                        "GOAL_DUE" if reason == "due" else
                        "GOAL_IDLE" if reason == "idle" else
                        "GOAL_NEVER_WOKEN" if reason == "never_woken" else
                        "GOAL_EVENT_LINKED"
                    ],
                    "required_domains": list(g.get("required_domains") or ["portfolio"]),
                    "wake_intent": "NEW_RUN",
                    "idempotency_key": f"goal:{agent_id}:{goal_id}:{hour_bucket}",
                    "source_snapshot_id": "",
                    "context": {
                        "goal_id": goal_id,
                        "owner_agent": agent_id,
                        "title": g.get("title"),
                        "thesis_summary": g.get("thesis_summary"),
                        "thesis_version": (
                            (ctx.get("desk_thesis") or {}).get("thesis_version")
                            if isinstance(ctx.get("desk_thesis"), dict)
                            else None
                        ),
                        "agent_context": {
                            "open_goal_count": len(ctx.get("open_goals") or []),
                            "thesis_snippet_count": len(ctx.get("thesis_snippets") or []),
                            "desk_thesis_version": (
                                (ctx.get("desk_thesis") or {}).get("thesis_version")
                                if isinstance(ctx.get("desk_thesis"), dict)
                                else None
                            ),
                        },
                    },
                }
                self.wake_store.enqueue(payload, actor_id="cio_wake_dispatcher")
                self._record_goal_dedup(agent_id, goal_id, wake_job_id)
                try:
                    store.record_wake(goal_id, agent_id=agent_id, outcome="wake_enqueued")
                except Exception:
                    pass
                result["enqueued"].append({
                    "wake_job_id": wake_job_id,
                    "goal_id": goal_id,
                    "agent_id": agent_id,
                    "reason": reason,
                })
                enqueued_n += 1
            except ValueError as exc:
                # already exists / validation — treat as dedup
                if "already exists" in str(exc).lower() or "idempoten" in str(exc).lower():
                    result["skipped_dedup"].append({"goal_id": goal_id, "agent_id": agent_id, "detail": str(exc)})
                else:
                    result["errors"].append({"goal_id": goal_id, "error": str(exc)})
            except Exception as exc:
                result["errors"].append({"goal_id": goal_id, "error": str(exc)})

        return result

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
            "GOAL_DUE": "SYSTEM",
            "GOAL_EVENT_LINKED": "SYSTEM",
            "OPPORTUNITY_QUEUE": "OPPORTUNITY_QUEUE",
        }
        return mapping.get(wake_trigger, "SYSTEM")

    def get_dispatch_stats(self) -> dict[str, Any]:
        """Return dispatch statistics from the ledger."""
        return {
            "total_dispatched": len(self._dispatched),
            "ledger_path": str(self.dispatch_ledger_path),
        }
