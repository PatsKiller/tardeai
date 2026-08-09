"""CIO Health Boundary — deterministic advisory availability from health evidence.

Consumes canonical Trade AI health evidence.
Produces typed advisory availability state (READY/DEGRADED/BLOCKED/UNKNOWN).
Records durable CIO_DATA_QUALITY_BLOCK actions through P-1.3.
Attaches health metadata to handoffs through P-1.4.
NEVER performs remediation.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Advisory States ──────────────────────────────────────────────
ADVISORY_STATE = frozenset({"READY", "DEGRADED", "BLOCKED", "UNKNOWN"})

# ── CIO Domains ──────────────────────────────────────────────────
CIO_DOMAINS = frozenset({
    "portfolio", "holdings", "performance", "risk", "watch",
    "reentry", "rotation", "income", "tax", "retirement",
    "fundamentals", "technicals", "catalysts", "macro",
    "broker_reconciliation",
})

# ── Reason Codes ─────────────────────────────────────────────────
REASON_CODES = frozenset({
    "DATA_SOURCE_UNAVAILABLE",
    "DATA_STALE",
    "DATA_INVALID",
    "DATA_CONTRADICTORY",
    "BROKER_RECONCILIATION_FAILED",
    "RISK_INPUT_UNAVAILABLE",
    "TAX_LOT_DATA_UNAVAILABLE",
    "HEALTH_EVIDENCE_UNAVAILABLE",
    "HEALTH_POLICY_UNKNOWN",
    "MARKET_DATA_DEGRADED",
    "MARKET_DATA_DATA_UNAVAILABLE",
    "BROKER_DEGRADED",
    "BROKER_DATA_UNAVAILABLE",
    "DATABASE_DEGRADED",
    "DATABASE_DATA_UNAVAILABLE",
    "BACKUP_DEGRADED",
    "BACKUP_DATA_UNAVAILABLE",
    "AGENT_JOBS_DEGRADED",
    "AGENT_JOBS_DATA_UNAVAILABLE",
    "INDICATORS_DEGRADED",
    "INDICATORS_DATA_UNAVAILABLE",
    "SHADOW_BATCH_DEGRADED",
    "SHADOW_BATCH_DATA_UNAVAILABLE",
    "LLM_DEGRADED",
    "LLM_DATA_UNAVAILABLE",
    "API_DEGRADED",
    "API_DATA_UNAVAILABLE",
    "FILE_INTEGRITY_DEGRADED",
    "FILE_INTEGRITY_DATA_UNAVAILABLE",
    "WATCHLIST_DEGRADED",
    "WATCHLIST_DATA_UNAVAILABLE",
})

# ── Domain Scoping: which health categories affect which CIO domains ──
DOMAIN_HEALTH_MAPPING: Dict[str, Tuple[set, int, int]] = {
    # health_category -> (affected_cio_domains, block_if_severity_ge, degrade_if_severity_ge)
    "market_data": ({"portfolio", "holdings", "performance", "risk", "watch", "reentry", "rotation", "fundamentals", "technicals"}, 4, 2),
    "broker": ({"portfolio", "holdings", "risk", "broker_reconciliation"}, 3, 1),
    "database": ({"portfolio", "holdings", "performance", "risk", "watch", "reentry", "rotation", "income", "tax", "retirement", "fundamentals", "technicals", "catalysts", "macro"}, 4, 2),
    "backup": (set(), 5, 3),
    "agent_jobs": ({"watch", "reentry", "rotation", "catalysts"}, 4, 2),
    "indicators": ({"technicals", "fundamentals"}, 4, 2),
    "shadow_batch": ({"performance", "risk"}, 4, 2),
    "llm": ({"watch", "catalysts", "fundamentals"}, 4, 3),
    "api": ({"portfolio", "holdings", "performance", "risk", "broker_reconciliation"}, 4, 2),
    "file_integrity": ({"portfolio", "holdings", "performance", "risk"}, 3, 1),
    "watchlist": ({"watch"}, 4, 2),
}

# ── Policy default max staleness per health finding type ──
DEFAULT_MAX_STALENESS_MINUTES: Dict[str, int] = {
    "market_data": 60,
    "portfolio_snapshot": 120,
    "broker_data": 240,
    "risk_calculation": 120,
    "tax_data": 1440,
    "watchlist_data": 30,
}


@dataclass
class HealthSnapshot:
    """Normalized health evidence consumed by the CIO boundary."""

    health_snapshot_id: str
    observed_at: str
    overall_score: float
    overall_status: str
    category_scores: Dict[str, float] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    data_freshness: Dict[str, Dict[str, str]] = field(default_factory=dict)
    source_status: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthSnapshot":
        return cls(
            health_snapshot_id=d["health_snapshot_id"],
            observed_at=d["observed_at"],
            overall_score=d.get("overall_score", 0),
            overall_status=d.get("overall_status", "UNKNOWN"),
            category_scores=d.get("category_scores", {}),
            findings=d.get("findings", []),
            data_freshness=d.get("data_freshness", {}),
            source_status=d.get("source_status", {}),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdvisoryDecision:
    decision_id: str
    evaluated_at: str
    task_type: str
    required_domains: List[str]
    state: str
    blocked_domains: List[str] = field(default_factory=list)
    degraded_domains: List[str] = field(default_factory=list)
    reason_codes: List[str] = field(default_factory=list)
    health_snapshot_id: str = ""
    finding_refs: List[str] = field(default_factory=list)
    recheck_after: Optional[str] = None
    policy_version: str = "1.0.0"
    decision_hash: str = ""

    def compute_hash(self) -> str:
        """Deterministic hash over decision content (excludes decision_hash itself)."""
        content = {
            "task_type": self.task_type,
            "required_domains": sorted(self.required_domains),
            "state": self.state,
            "blocked_domains": sorted(self.blocked_domains),
            "degraded_domains": sorted(self.degraded_domains),
            "reason_codes": sorted(self.reason_codes),
            "health_snapshot_id": self.health_snapshot_id,
            "finding_refs": sorted(self.finding_refs),
            "policy_version": self.policy_version,
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        self.decision_hash = self.compute_hash()
        return asdict(self)


class CIOHealthBoundary:
    """Deterministic health-to-advisory-availability boundary.

    Reads canonical health evidence. Produces READY/DEGRADED/BLOCKED/UNKNOWN.
    NEVER performs remediation.
    """

    POLICY_VERSION = "1.0.0"

    def __init__(self, health_snapshot: Optional[HealthSnapshot] = None):
        self.health_snapshot = health_snapshot
        self._domain_mapping = DOMAIN_HEALTH_MAPPING

    def load_snapshot(self, snapshot: HealthSnapshot):
        self.health_snapshot = snapshot

    def evaluate(self, task_type: str, required_domains: List[str]) -> AdvisoryDecision:
        """Evaluate advisory availability for a CIO task.

        Args:
            task_type: Type of CIO task (e.g., 'cio_question', 'portfolio_review')
            required_domains: List of CIO domains this task needs

        Returns:
            AdvisoryDecision with READY/DEGRADED/BLOCKED/UNKNOWN state
        """
        decision_id = f"health-decision-{uuid.uuid4().hex[:12]}"
        evaluated_at = datetime.now(timezone.utc).isoformat()

        # Validate domains
        invalid = set(required_domains) - CIO_DOMAINS
        if invalid:
            raise ValueError(f"Unknown CIO domains: {invalid}")

        # If no health snapshot, fail closed
        if self.health_snapshot is None:
            return AdvisoryDecision(
                decision_id=decision_id,
                evaluated_at=evaluated_at,
                task_type=task_type,
                required_domains=list(required_domains),
                state="UNKNOWN",
                reason_codes=["HEALTH_EVIDENCE_UNAVAILABLE"],
                policy_version=self.POLICY_VERSION,
            )

        snapshot = self.health_snapshot
        blocked_domains: set[str] = set()
        degraded_domains: set[str] = set()
        all_reason_codes: set[str] = set()
        all_finding_refs: List[str] = []

        # Collect findings by category
        findings_by_category: Dict[str, list] = {}
        for f in snapshot.findings:
            cat = f.get("category", "unknown")
            findings_by_category.setdefault(cat, []).append(f)

        # Evaluate each health category's impact on required domains
        for health_cat, (affected_domains, block_threshold, degrade_threshold) in self._domain_mapping.items():
            # Which of our required domains does this category affect?
            relevant = set(required_domains) & affected_domains
            if not relevant:
                continue

            # Check category score
            cat_score = snapshot.category_scores.get(health_cat, 100)
            severity = self._score_to_severity(cat_score)

            cat_findings = findings_by_category.get(health_cat, [])

            # Check each finding
            for finding in cat_findings:
                finding_severity = finding.get("severity", 0)
                max_sev = max(severity, finding_severity)

                if max_sev >= block_threshold:
                    blocked_domains.update(relevant)
                    if max_sev >= 4:
                        all_reason_codes.add(f"{health_cat.upper()}_DATA_UNAVAILABLE")
                    else:
                        all_reason_codes.add(health_cat.upper())
                    if finding.get("finding_id"):
                        all_finding_refs.append(finding["finding_id"])
                elif max_sev >= degrade_threshold:
                    degraded_domains.update(relevant)
                    all_reason_codes.add(f"{health_cat.upper()}_DEGRADED")
                    if finding.get("finding_id"):
                        all_finding_refs.append(finding["finding_id"])

        # Also check data freshness
        for domain in required_domains:
            freshness = snapshot.data_freshness.get(domain, {})
            if freshness:
                last_update = freshness.get("last_update")
                status = freshness.get("status", "unknown")
                if status in ("stale", "unavailable") or self._is_stale(last_update, domain):
                    if status == "unavailable":
                        blocked_domains.add(domain)
                        all_reason_codes.add("DATA_SOURCE_UNAVAILABLE")
                    else:
                        degraded_domains.add(domain)
                        all_reason_codes.add("DATA_STALE")

        # Clean up domains
        blocked_domains.discard("")
        degraded_domains.discard("")
        degraded_domains -= blocked_domains

        # Determine overall state
        if not blocked_domains and not degraded_domains:
            state = "READY"
        elif blocked_domains:
            state = "BLOCKED"
        elif degraded_domains:
            state = "DEGRADED"
        else:
            state = "READY"

        if not all_reason_codes:
            all_reason_codes = {"HEALTH_POLICY_UNKNOWN"}

        # Compute recheck_after
        recheck_after: Optional[str] = None
        for domain in required_domains:
            freshness = snapshot.data_freshness.get(domain, {})
            last_update = freshness.get("last_update")
            if last_update:
                try:
                    lu_dt = datetime.fromisoformat(last_update)
                    domain_key = self._domain_to_freshness_key(domain)
                    max_age = DEFAULT_MAX_STALENESS_MINUTES.get(domain_key, 60)
                    recheck = lu_dt + timedelta(minutes=max_age)
                    if recheck_after is None or datetime.fromisoformat(recheck_after) > recheck:
                        recheck_after = recheck.isoformat()
                except (ValueError, TypeError):
                    pass

        decision = AdvisoryDecision(
            decision_id=decision_id,
            evaluated_at=evaluated_at,
            task_type=task_type,
            required_domains=list(required_domains),
            state=state,
            blocked_domains=sorted(blocked_domains),
            degraded_domains=sorted(degraded_domains),
            reason_codes=sorted(all_reason_codes),
            health_snapshot_id=snapshot.health_snapshot_id,
            finding_refs=all_finding_refs,
            recheck_after=recheck_after,
            policy_version=self.POLICY_VERSION,
        )

        return decision

    def _score_to_severity(self, score: float) -> int:
        """Convert 0-100 health score to 1-5 severity."""
        if score >= 90:
            return 1
        if score >= 70:
            return 2
        if score >= 50:
            return 3
        if score >= 30:
            return 4
        return 5

    def _is_stale(self, last_update: Optional[str], domain: str) -> bool:
        """Check if data is stale based on last_update timestamp."""
        if not last_update:
            return True
        try:
            lu_dt = datetime.fromisoformat(last_update)
            domain_key = self._domain_to_freshness_key(domain)
            max_age = DEFAULT_MAX_STALENESS_MINUTES.get(domain_key, 60)
            age = (datetime.now(timezone.utc) - lu_dt).total_seconds() / 60
            return age > max_age
        except (ValueError, TypeError):
            return True

    def _domain_to_freshness_key(self, domain: str) -> str:
        mapping = {
            "portfolio": "portfolio_snapshot",
            "holdings": "portfolio_snapshot",
            "performance": "risk_calculation",
            "risk": "risk_calculation",
            "watch": "watchlist_data",
            "reentry": "watchlist_data",
            "rotation": "watchlist_data",
            "income": "tax_data",
            "tax": "tax_data",
            "retirement": "tax_data",
            "fundamentals": "market_data",
            "technicals": "market_data",
            "catalysts": "market_data",
            "macro": "market_data",
            "broker_reconciliation": "broker_data",
        }
        return mapping.get(domain, "market_data")


# ── CIO_DATA_QUALITY_BLOCK integration ────────────────────────────


def create_data_quality_block(
    decision: AdvisoryDecision,
    ledger=None,  # CIOActionLedger instance
    idempotency_key: str = "",
) -> Optional[dict]:
    """Create a durable CIO_DATA_QUALITY_BLOCK action when advisory is BLOCKED.

    Uses P-1.3 CIOActionLedger to record the block:
    1. Creates the action (status: OPEN)
    2. Transitions to BLOCKED via CIO_ACTION_BLOCKED

    Returns the block transition event or None if not blocked.
    """
    if decision.state != "BLOCKED":
        return None

    if ledger is None:
        from scripts.lib.cio_action_ledger import CIOActionLedger

        ledger = CIOActionLedger()

    # Build idempotency key from policy version, affected domains, reason codes, snapshot
    if not idempotency_key:
        key_parts = [
            decision.policy_version,
            ",".join(sorted(decision.blocked_domains)),
            ",".join(sorted(decision.reason_codes)),
            decision.health_snapshot_id,
        ]
        idempotency_key = hashlib.sha256("|".join(key_parts).encode()).hexdigest()[:32]

    action_id = f"data-quality-block-{idempotency_key[:8]}"

    # Check if action already exists and is already blocked (full idempotency)
    existing = ledger.get_action(action_id)
    if existing is not None and existing.get("current_status") == "BLOCKED":
        return None  # Already blocked — idempotent, no duplicate

    try:
        # Step 1: Create the action (status: OPEN)
        ledger.create_action(
            {
                "cio_action_id": action_id,
                "priority": "HIGH",
                "domain": "data_quality",
                "title": f"CIO_DATA_QUALITY_BLOCK: {', '.join(decision.blocked_domains[:3])}",
                "recommendation": "Wait for canonical data recovery. Do not issue affected advisory.",
                "why_now": ", ".join(decision.reason_codes[:3]),
                "evidence_refs": decision.finding_refs,
                "source_snapshot_id": decision.health_snapshot_id,
                "source_hash": decision.compute_hash(),
                "followup_condition": "All blocked domains return to healthy state",
                "next_check_at": decision.recheck_after,
                "operator_decision_required": False,
                "idempotency_key": idempotency_key + "-create",
            },
            actor_id="cio_health_boundary",
            actor_type="system",
            authority="system",
        )

        # Step 2: Transition to BLOCKED
        event = ledger.transition_action(
            action_id,
            "CIO_ACTION_BLOCKED",
            {
                "reason": f"Data quality block: {', '.join(decision.reason_codes[:3])}",
                "blocked_domains": list(decision.blocked_domains),
                "health_snapshot_id": decision.health_snapshot_id,
                "idempotency_key": idempotency_key,
            },
            actor_id="cio_health_boundary",
            actor_type="system",
            authority="system",
        )
        return event
    except ValueError as e:
        # Duplicate block — expected under idempotency
        if "already exists" in str(e):
            return None
        raise


def unblock_if_healthy(
    block_action_id: str,
    decision: AdvisoryDecision,
    ledger=None,  # CIOActionLedger instance
) -> Optional[dict]:
    """Unblock a previously blocked action if the domain is now healthy."""
    if decision.state not in ("READY", "DEGRADED"):
        return None

    if ledger is None:
        from scripts.lib.cio_action_ledger import CIOActionLedger

        ledger = CIOActionLedger()

    action = ledger.get_action(block_action_id)
    if not action or action.get("current_status") != "BLOCKED":
        return None

    try:
        event = ledger.transition_action(
            block_action_id,
            "CIO_ACTION_UNBLOCKED",
            {
                "reason": f"Health restored. Decision: {decision.state}",
                "health_snapshot_id": decision.health_snapshot_id,
                "unblocked_at": datetime.now(timezone.utc).isoformat(),
            },
            actor_id="cio_health_boundary",
            actor_type="system",
            authority="system",
        )
        return event
    except ValueError:
        return None


def attach_health_metadata_to_handoff(
    handoff_id: str,
    decision: AdvisoryDecision,
    queue=None,  # AgentHandoffQueue instance
) -> Optional[dict]:
    """Attach health boundary metadata to a handoff.

    Does NOT change the handoff status. Adds metadata so the handoff
    consumer can see why it's blocked.
    """
    if queue is None:
        return None  # Cannot attach without queue reference

    handoff = queue.get_handoff(handoff_id)
    if not handoff:
        return None

    return decision.to_dict()


def is_handoff_eligible(
    handoff: dict, boundary: "CIOHealthBoundary", required_domains: List[str]
) -> Tuple[bool, Optional[AdvisoryDecision]]:
    """Check if a handoff is eligible to be claimed/started based on health.

    Returns (eligible, decision).
    """
    decision = boundary.evaluate(
        handoff.get("task_type", "cio_question"), required_domains
    )
    if decision.state == "BLOCKED":
        return False, decision
    return True, decision
