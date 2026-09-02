"""Fail-closed eligibility policy for research observations.

Missing provenance, stale data, failed quality, or unknown entitlement must
fail closed and explain why. Display-only consumers may still receive a
labeled envelope; proposal / downstream-agent consumers must not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .contract import SCHEMA_VERSION, ResearchObservation, validate_schema_version
from .statuses import (
    EligibilityDecision,
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class EligibilityPolicy:
    """Tunable gates. Defaults are fail-closed for proposal use."""

    max_freshness_age_seconds: float = 86_400.0  # 24h default research SLA
    max_future_skew_seconds: float = 300.0  # allow small clock skew forward
    allow_display_when_stale: bool = True  # display may fail open with label
    require_durable_output: bool = True
    require_run_id_match: bool = True
    expected_schema_version: str = SCHEMA_VERSION
    allowed_entitlements_for_eligible: frozenset[EntitlementStatus] = frozenset(
        {
            EntitlementStatus.LICENSED,
            EntitlementStatus.INTERNAL,
            EntitlementStatus.DELAYED_OK,
        }
    )
    blocking_quality: frozenset[QualityStatus] = frozenset(
        {
            QualityStatus.FAILED,
            QualityStatus.UNKNOWN,
            QualityStatus.UNVERIFIED,
        }
    )
    blocking_freshness_for_eligible: frozenset[FreshnessStatus] = frozenset(
        {
            FreshnessStatus.NO_DATA,
            FreshnessStatus.GAP,
            FreshnessStatus.STALE,
            FreshnessStatus.PARTIAL,
            FreshnessStatus.INELIGIBLE,
            FreshnessStatus.ERROR,
        }
    )


DEFAULT_POLICY = EligibilityPolicy()


@dataclass(frozen=True)
class EligibilityResult:
    decision: EligibilityDecision
    reasons: tuple[str, ...]
    observation: ResearchObservation
    policy_version: str = "ResearchEligibility@v1"

    @property
    def eligible(self) -> bool:
        return self.decision == EligibilityDecision.ELIGIBLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "policy_version": self.policy_version,
            "source_identity": self.observation.source_identity,
            "run_id": self.observation.run_id,
            "trace_id": self.observation.trace_id,
            "freshness_status": self.observation.freshness_status.value,
        }


def _clock_reasons(
    obs: ResearchObservation,
    *,
    now: datetime,
    policy: EligibilityPolicy,
) -> list[str]:
    reasons: list[str] = []
    for label, ts in (
        ("provider_at", obs.provider_at),
        ("observed_at", obs.observed_at),
        ("received_at", obs.received_at),
        ("normalized_at", obs.normalized_at),
    ):
        dt = _parse_iso(ts)
        if dt is None and ts:
            reasons.append(f"CLOCK_UNPARSEABLE:{label}")
            continue
        if dt is None:
            continue
        # Future skew
        skew = (dt - now).total_seconds()
        if skew > policy.max_future_skew_seconds:
            reasons.append(f"FUTURE_SKEW:{label}:{int(skew)}s")
        # Clock regression: received/normalized should not precede provider/observed
        # by an absurd margin; flag normalized < provider beyond skew as regression.
    provider_dt = _parse_iso(obs.provider_at)
    received_dt = _parse_iso(obs.received_at)
    if provider_dt and received_dt and (provider_dt - received_dt).total_seconds() > policy.max_future_skew_seconds:
        reasons.append("CLOCK_REGRESSION:provider_at_after_received_at")
    normalized_dt = _parse_iso(obs.normalized_at)
    if received_dt and normalized_dt and (received_dt - normalized_dt).total_seconds() > policy.max_future_skew_seconds:
        reasons.append("CLOCK_REGRESSION:received_at_after_normalized_at")
    return reasons


def evaluate_eligibility(
    obs: ResearchObservation,
    *,
    policy: EligibilityPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
    expected_run_id: Optional[str] = None,
    expected_source_hash: Optional[str] = None,
    consumer_kind: str = "proposal",  # proposal | display | agent
) -> EligibilityResult:
    """Evaluate fail-closed eligibility. Always returns an explained decision."""
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    # Schema version mismatch
    if not validate_schema_version(obs, policy.expected_schema_version):
        reasons.append(f"SCHEMA_VERSION_MISMATCH:got={obs.schema_version}:expected={policy.expected_schema_version}")

    # Missing provenance
    missing = obs.missing_provenance_fields()
    if missing:
        reasons.append("MISSING_PROVENANCE:" + ",".join(missing))

    # Durable output join
    if policy.require_durable_output:
        if obs.log_success_claimed and not obs.durable_output_present:
            reasons.append("LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT")
        if not obs.durable_output_present and obs.freshness_status == FreshnessStatus.FRESH:
            reasons.append("FRESH_WITHOUT_DURABLE_OUTPUT")
        if not obs.durable_output_present and consumer_kind in ("proposal", "agent"):
            if "LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT" not in reasons:
                if obs.freshness_status not in (
                    FreshnessStatus.NO_DATA,
                    FreshnessStatus.GAP,
                    FreshnessStatus.ERROR,
                ):
                    reasons.append("DURABLE_OUTPUT_ABSENT")

    # Run ID correlation
    if expected_run_id is not None:
        if not obs.run_id or obs.run_id != expected_run_id:
            reasons.append(f"WRONG_RUN_ID:got={obs.run_id!r}:expected={expected_run_id!r}")

    # Source hash
    if expected_source_hash is not None:
        if not obs.source_hash or obs.source_hash != expected_source_hash:
            reasons.append(f"WRONG_SOURCE_HASH:got={obs.source_hash!r}:expected={expected_source_hash!r}")

    # Freshness status gates
    if obs.freshness_status in policy.blocking_freshness_for_eligible:
        reasons.append(f"FRESHNESS_BLOCK:{obs.freshness_status.value}")

    # Age SLA (when age known and status claims FRESH)
    if obs.freshness_age_seconds is not None:
        if obs.freshness_age_seconds < 0:
            reasons.append("NEGATIVE_FRESHNESS_AGE")
        elif obs.freshness_age_seconds > policy.max_freshness_age_seconds:
            reasons.append(f"STALE_AGE:{int(obs.freshness_age_seconds)}s>max={int(policy.max_freshness_age_seconds)}s")

    # Quality
    if obs.quality_status in policy.blocking_quality:
        reasons.append(f"QUALITY_FAILURE:{obs.quality_status.value}")

    # Entitlement
    if obs.entitlement_status not in policy.allowed_entitlements_for_eligible:
        reasons.append(f"ENTITLEMENT_BLOCK:{obs.entitlement_status.value}")

    # Fallback
    if obs.fallback_state == FallbackState.SILENT_FORBIDDEN:
        reasons.append("SILENT_FALLBACK_FORBIDDEN")

    # Clock checks
    reasons.extend(_clock_reasons(obs, now=now, policy=policy))

    # Never allow NO_DATA/GAP to be treated as eligible even if other fields pass
    if obs.freshness_status in (FreshnessStatus.NO_DATA, FreshnessStatus.GAP):
        if f"FRESHNESS_BLOCK:{obs.freshness_status.value}" not in reasons:
            reasons.append(f"FRESHNESS_BLOCK:{obs.freshness_status.value}")

    if reasons:
        if consumer_kind == "display" and policy.allow_display_when_stale:
            # Display may fail open only with an explicit degraded label.
            if obs.degraded_label:
                return EligibilityResult(
                    decision=EligibilityDecision.DISPLAY_ONLY,
                    reasons=tuple(reasons) + ("DISPLAY_WITH_DEGRADED_LABEL",),
                    observation=obs,
                )
            return EligibilityResult(
                decision=EligibilityDecision.INELIGIBLE,
                reasons=tuple(reasons) + ("DISPLAY_MISSING_DEGRADED_LABEL",),
                observation=obs,
            )
        return EligibilityResult(
            decision=EligibilityDecision.INELIGIBLE,
            reasons=tuple(reasons),
            observation=obs,
        )

    return EligibilityResult(
        decision=EligibilityDecision.ELIGIBLE,
        reasons=("ALL_GATES_PASSED",),
        observation=obs,
    )
