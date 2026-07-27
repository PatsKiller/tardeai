"""Active Trader Stage 11 — governed learning + observability (production-inactive).

Journal/replay catalog, Darwin (proposal-only), Hermes governance states, and a
disabled-by-default overnight controller. NO broker call, NO live feature activation,
NO autonomous architecture mutation. Learning proposes; humans/oversight promote; nothing
here changes production config, weights, risk, flags, policy, authorization, or guardrails.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------- journal catalog

JOURNAL_EVENT_CATALOG = (
    "session_draft_saved", "session_authorized_test", "candidate_observed",
    "market_reference", "prime_evaluated", "fire_evaluated", "res_scored", "rrs_scored",
    "runner_evaluated", "sim_order_submitted", "sim_order_filled", "sim_order_cancelled",
    "sim_pnl_snapshot", "rejection_classified", "notification_projected",
    "fallback_evaluated", "feature_flag_changed", "operator_action",
    "drive_synced", "email_sent", "darwin_proposal_created", "hypothesis_created",
)


def is_catalog_event(name: str) -> bool:
    return name in JOURNAL_EVENT_CATALOG


@dataclass(frozen=True)
class ReplayIndexEntry:
    session_id: Optional[str]
    symbol: Optional[str]
    decision_ref: Optional[str]
    simulation_ref: Optional[str]
    source: str                          # SHADOW_FIXTURE_OR_REPLAY / SIMULATION / LAB
    data_quality: str                    # HEALTHY / STALE / GAP / ...
    replay_segment_ref: Optional[str]    # replay:// reference — NEVER inlined raw data

    def __post_init__(self):
        if self.replay_segment_ref and not str(self.replay_segment_ref).startswith("replay://"):
            raise ValueError("replay reference must be a replay:// pointer (no inlined raw data)")


# ---------------------------------------------------------------- Darwin

class ReviewState(str, Enum):
    DRAFT = "DRAFT"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    SIMULATION_PENDING = "SIMULATION_PENDING"
    ARCHITECT_REVIEW_PENDING = "ARCHITECT_REVIEW_PENDING"
    OPERATOR_REVIEW_PENDING = "OPERATOR_REVIEW_PENDING"
    APPROVED_INACTIVE = "APPROVED_INACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


PROPOSAL_KINDS = ("feature", "threshold", "risk", "runner", "broker_policy")


@dataclass(frozen=True)
class DarwinProposal:
    """Proposal-only. Never changes production directly. Every proposal REQUIRES
    evidence, sample size, period, cohort, confounders, replay/simulation, rollback,
    expiry, and a review state."""
    proposal_id: str
    kind: str
    statement: str
    evidence_refs: tuple
    sample_size: int
    period: str
    cohort: dict
    confounders: tuple
    replay_or_simulation_ref: str
    rollback_plan: str
    expiry: str
    review_state: ReviewState = ReviewState.DRAFT

    def __post_init__(self):
        if self.kind not in PROPOSAL_KINDS:
            raise ValueError(f"unknown proposal kind {self.kind!r}")
        if not self.evidence_refs:
            raise ValueError("proposal requires evidence")
        if self.sample_size <= 0:
            raise ValueError("proposal requires a positive sample size")
        for f, v in (("period", self.period), ("replay_or_simulation_ref", self.replay_or_simulation_ref),
                     ("rollback_plan", self.rollback_plan), ("expiry", self.expiry)):
            if not str(v).strip():
                raise ValueError(f"proposal requires {f}")
        if not self.confounders:
            raise ValueError("proposal must enumerate confounders (may be a single 'none-identified')")

    def applies_directly(self) -> bool:
        """A Darwin proposal NEVER applies to production directly."""
        return False


# ---------------------------------------------------------------- Hermes governance

# allowed forward transitions; nothing auto-activates
HERMES_TRANSITIONS = {
    ReviewState.DRAFT: {ReviewState.EVIDENCE_PENDING, ReviewState.REJECTED},
    ReviewState.EVIDENCE_PENDING: {ReviewState.SIMULATION_PENDING, ReviewState.REJECTED, ReviewState.EXPIRED},
    ReviewState.SIMULATION_PENDING: {ReviewState.ARCHITECT_REVIEW_PENDING, ReviewState.REJECTED, ReviewState.EXPIRED},
    ReviewState.ARCHITECT_REVIEW_PENDING: {ReviewState.OPERATOR_REVIEW_PENDING, ReviewState.REJECTED, ReviewState.EXPIRED},
    ReviewState.OPERATOR_REVIEW_PENDING: {ReviewState.APPROVED_INACTIVE, ReviewState.REJECTED, ReviewState.EXPIRED},
    ReviewState.APPROVED_INACTIVE: set(),        # terminal: approved but INACTIVE (no auto-activation)
    ReviewState.REJECTED: set(),
    ReviewState.EXPIRED: set(),
}


class HermesGovernanceError(ValueError):
    pass


def hermes_transition(current: ReviewState, target: ReviewState) -> ReviewState:
    if target not in HERMES_TRANSITIONS.get(current, set()):
        raise HermesGovernanceError(f"illegal Hermes transition {current.value} -> {target.value}")
    return target


def hermes_llm_allowed(operation: str) -> bool:
    """LLMs may summarize/draft/compare; never authorize/trade/change-risk/merge/deploy."""
    allowed = {"summarize", "draft", "compare", "cluster", "explain"}
    forbidden = {"authorize", "trade", "change_risk", "merge", "deploy", "activate",
                 "place_order", "unlock"}
    if operation in forbidden:
        return False
    return operation in allowed


# ---------------------------------------------------------------- Bitwarden registry (metadata only)

@dataclass(frozen=True)
class SecretRegistryEntry:
    """Metadata ONLY — names, project-id suffixes, required/optional, sentinel/access
    checks. NEVER a value."""
    secret_name: str
    project_id_suffix: str
    required: bool
    present: Optional[bool] = None
    sentinel_rejected_by_runtime: bool = True

    def __post_init__(self):
        # defensive: refuse anything that looks like a value
        if len(self.project_id_suffix) > 12:
            raise ValueError("store only a project-id SUFFIX, never the full id")


BITWARDEN_REGISTRY = (
    SecretRegistryEntry("ACTIVE_TRADER_TEST_DATABASE_DSN", "1b0a478d", True),
    SecretRegistryEntry("ACTIVE_TRADER_READ_API_DSN", "1b0a478d"[-8:], True),
    SecretRegistryEntry("MOOMOO_DATA_LOGIN_ACCOUNT", "00375f2c", True),
    SecretRegistryEntry("MOOMOO_DATA_LOGIN_PASSWORD", "00375f2c", True),
    SecretRegistryEntry("MOOMOO_DATA_TEST_SYMBOLS", "00375f2c", True),
    SecretRegistryEntry("GMAIL_NOTIFICATION_CREDENTIAL_SLOT", "TODO", False, present=False),
)


# ---------------------------------------------------------------- overnight controller

class ControllerState(str, Enum):
    DISABLED = "DISABLED"
    RUNNING = "RUNNING"
    STAGE_GREEN = "STAGE_GREEN"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass
class OvernightController:
    """Disabled-by-default checkpoint/resume controller scaffolding. One-stage
    transaction, fail-stop. NO auto-merge/deploy/live-flag/real-2FA/broker-order/
    credential-retry loop."""
    enabled: bool = False
    state: ControllerState = ControllerState.DISABLED

    def run_stage(self, stage_fn, *, stage_name: str) -> ControllerState:
        if not self.enabled:
            self.state = ControllerState.DISABLED
            return self.state          # exits without doing anything
        self.state = ControllerState.RUNNING
        try:
            ok = bool(stage_fn())
        except Exception:
            self.state = ControllerState.FAILED
            return self.state          # fail-stop: never advances
        self.state = ControllerState.STAGE_GREEN if ok else ControllerState.FAILED
        return self.state

    # the following are intentionally NOT implemented (prohibited):
    def auto_merge(self, *a, **k):
        raise HermesGovernanceError("auto-merge is prohibited")

    def activate_live_flag(self, *a, **k):
        raise HermesGovernanceError("live-flag activation is prohibited")

    def submit_broker_order(self, *a, **k):
        raise HermesGovernanceError("broker order submission is prohibited")

    def retry_moomoo_login(self, *a, **k):
        raise HermesGovernanceError("credential retry loop is prohibited")
