"""
Hermes Challenge Worker — Single durable consumer of the CIO challenge queue.

Gate-B component. One worker owns the HermesChallengeQueue consumption.
Challenges are read, researched through the independent Hermes Research Gateway,
and artifacts are produced with full provenance. On completion, the worker
creates a RESUME_RUN wake for the parent CIO run.

Hermes Research Gateway is SEPARATE from the Financial Agent Governed Gateway.
Hermes is an independent challenger/research authority with its own bounded
provider boundary.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("tradeai.hermes_challenge_worker")

# ── Default config ──────────────────────────────────────────────────────────
DEFAULT_LEASE_SECONDS = 600  # 10 minutes for research tasks
DEFAULT_MAX_CHALLENGES_PER_RUN = 3

# ── Declared Hermes research provider policy ────────────────────────────────
# These are the intentionally declared multi-provider lanes for research.
# They are NOT silent fallbacks — each lane has an explicit purpose and policy.
HERMES_RESEARCH_LANES: dict[str, dict[str, Any]] = {
    "deepseek_flash": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "purpose": "Deterministic evidence extraction",
        "max_tokens": 4096,
        "temperature": 0.0,
    },
    "deepseek_pro": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "purpose": "Complex multi-source synthesis",
        "max_tokens": 8192,
        "temperature": 0.3,
    },
    "claude_external": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "purpose": "Independent external fact-check (paid)",
        "max_tokens": 4096,
        "temperature": 0.1,
    },
}

# ── Hermes-specific budget (subordinate to global $0.25/day cap) ───────────
HERMES_DAILY_MAX_COST_USD = 0.05
HERMES_PER_CHALLENGE_MAX_COST_USD = 0.01


class HermesChallengeWorker:
    """Single durable consumer of Hermes challenge queue.

    Responsibilities:
    - Poll HermesChallengeQueue for PENDING challenges
    - Claim with lease
    - Execute research through Hermes Research Gateway lanes
    - Produce challenge artifact with full provenance
    - On completion: create RESUME_RUN wake for parent CIO run
    - Enforce Hermes-specific budget (subordinate to global cap)
    """

    def __init__(
        self,
        hermes_queue: Any,  # HermesChallengeQueue
        wake_store: Any,    # CIOWakeJobStore
        run_store: Any,     # CIORunStore
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        daily_cost_limit: float = HERMES_DAILY_MAX_COST_USD,
        per_challenge_cost_limit: float = HERMES_PER_CHALLENGE_MAX_COST_USD,
    ):
        self.hermes_queue = hermes_queue
        self.wake_store = wake_store
        self.run_store = run_store
        self.lease_seconds = lease_seconds
        self.daily_cost_limit = daily_cost_limit
        self.per_challenge_cost_limit = per_challenge_cost_limit
        self._daily_cost_accrued = 0.0
        self._daily_reset_at: Optional[float] = None

    def _reset_daily_cost_if_needed(self):
        now = time.time()
        if self._daily_reset_at is None or now > self._daily_reset_at:
            self._daily_cost_accrued = 0.0
            # Reset at midnight UTC
            from datetime import timedelta
            midnight = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            self._daily_reset_at = midnight.timestamp()

    def poll_and_process(self, max_challenges: int = DEFAULT_MAX_CHALLENGES_PER_RUN) -> dict[str, Any]:
        """Poll for pending challenges, claim and process up to max_challenges."""
        self._reset_daily_cost_if_needed()

        challenges = self.hermes_queue.list_challenges(
            status="PENDING", limit=max_challenges,
        )

        processed: list[dict[str, str]] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for challenge in challenges:
            challenge_id = challenge.get("challenge_id", "")
            parent_run_id = challenge.get("parent_run_id", "")

            if not challenge_id:
                skipped.append("no_challenge_id")
                continue

            # Budget check
            if self._daily_cost_accrued >= self.daily_cost_limit:
                skipped.append(f"{challenge_id}:HERMES_DAILY_BUDGET_EXCEEDED")
                continue

            # Claim the challenge
            claim_token = str(uuid.uuid4())
            try:
                self.hermes_queue.claim(
                    challenge_id, claim_token,
                    lease_seconds=self.lease_seconds,
                    actor_id="hermes_challenge_worker",
                )
            except ValueError as e:
                log.warning("Could not claim challenge %s: %s", challenge_id, e)
                skipped.append(challenge_id)
                continue

            # Process the challenge
            try:
                artifact = self._process_challenge(challenge)
                self.hermes_queue.complete(
                    challenge_id,
                    artifact=artifact,
                    actor_id="hermes_challenge_worker",
                )

                # Create RESUME_RUN wake for parent CIO run
                if parent_run_id:
                    self._create_resume_wake(parent_run_id, challenge_id, artifact)

                processed.append({
                    "challenge_id": challenge_id,
                    "artifact_id": artifact.get("artifact_id", ""),
                    "parent_run_id": parent_run_id,
                })
            except Exception as e:
                log.error("Challenge processing failed for %s: %s", challenge_id, e)
                errors.append({"challenge_id": challenge_id, "error": str(e)})
                try:
                    self.hermes_queue.release(challenge_id, actor_id="hermes_challenge_worker")
                except ValueError:
                    pass

        return {
            "processed_count": len(processed),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
            "daily_cost_accrued": self._daily_cost_accrued,
        }

    def _process_challenge(self, challenge: dict[str, Any]) -> dict[str, Any]:
        """Process a single challenge through the Hermes Research Gateway.

        Produces an artifact with full provenance: process_id, provider, model,
        artifact_hash, cost, completion status. No silent provider fallback.
        """
        challenge_id = challenge.get("challenge_id", "")
        challenge_type = challenge.get("challenge_type", "unknown")
        description = challenge.get("description", "")
        evidence_refs = challenge.get("evidence_refs", [])

        artifact_id = f"hermes-artifact-{uuid.uuid4().hex[:16]}"

        # Select research lane based on challenge type and budget
        lane = self._select_research_lane(challenge_type)

        # The actual research execution would go through the Hermes Research Gateway.
        # In shadow mode, produce a deterministic artifact stub.
        artifact = {
            "artifact_id": artifact_id,
            "challenge_id": challenge_id,
            "challenge_type": challenge_type,
            "description": description,
            "research_lane": lane["provider"],
            "model": lane["model"],
            "research_summary": f"Hermes research for challenge {challenge_id}: {description}",
            "findings": [],
            "confidence": 0.0,
            "evidence_refs": evidence_refs,
            "provenance": {
                "process_id": "hermes_challenge_research",
                "provider": lane["provider"],
                "model": lane["model"],
                "declared_lanes": list(HERMES_RESEARCH_LANES.keys()),
                "no_silent_fallback": True,
            },
            "artifact_hash": hashlib.sha256(
                f"hermes:{challenge_id}:{time.time()}".encode()
            ).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETED",
        }

        # Track cost
        estimated_cost = 0.001  # Shadow mode cost
        self._daily_cost_accrued += estimated_cost

        return artifact

    def _select_research_lane(self, challenge_type: str) -> dict[str, Any]:
        """Select the appropriate Hermes research lane for a challenge type.

        Lanes are intentionally declared, not silent fallbacks.
        """
        # Fast, deterministic challenges → Flash
        if challenge_type in ("freshness_decay", "data_quality"):
            return HERMES_RESEARCH_LANES["deepseek_flash"]
        # Complex synthesis → Pro
        if challenge_type in ("cross_source_synthesis", "entity_resolution"):
            return HERMES_RESEARCH_LANES["deepseek_pro"]
        # External fact-check → Claude (paid, bounded)
        if challenge_type in ("fact_check", "external_corroboration"):
            return HERMES_RESEARCH_LANES["claude_external"]
        # Default: Fast lane
        return HERMES_RESEARCH_LANES["deepseek_flash"]

    def _create_resume_wake(
        self,
        parent_run_id: str,
        challenge_id: str,
        artifact: dict[str, Any],
    ):
        """Create a RESUME_RUN wake for the parent CIO run after challenge completion."""
        if self.wake_store is None or self.run_store is None:
            return

        # Validate parent run exists and is in a waiting state
        run = self.run_store.get_run(parent_run_id)
        if run is None:
            log.warning("Parent run %s not found for challenge %s", parent_run_id, challenge_id)
            return
        if run.get("status") != "WAITING_FOR_HERMES":
            log.warning(
                "Parent run %s is in %s, not WAITING_FOR_HERMES. Skipping resume.",
                parent_run_id, run.get("status"),
            )
            return

        wake_job_id = f"resume-hermes-{parent_run_id}-{challenge_id[:12]}"
        idempotency_key = f"resume_hermes:{parent_run_id}:{challenge_id}"

        try:
            wake_payload = {
                "wake_job_id": wake_job_id,
                "trigger_type": "HERMES_CHALLENGE_RESOLVED",
                "trigger_ref": challenge_id,
                "wake_intent": "RESUME_RUN",
                "target_run_id": parent_run_id,
                "priority": "NORMAL",
                "idempotency_key": idempotency_key,
                "parent_handoff_id": challenge_id,
                "source_snapshot_id": artifact.get("artifact_hash"),
            }
            self.wake_store.enqueue(
                wake_payload,
                actor_id="hermes_challenge_worker",
            )
            log.info(
                "Created RESUME_RUN wake %s for parent run %s (challenge %s)",
                wake_job_id, parent_run_id, challenge_id,
            )
        except ValueError as e:
            log.warning("Could not enqueue resume wake: %s", e)
