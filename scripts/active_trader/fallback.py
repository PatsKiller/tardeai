"""Active Trader Stage 3 — authorized fallback policy and pure evaluator.

The evaluator is a PURE function over typed inputs; it submits nothing, calls no
broker, and requests no 2FA. It exists so that duplicate-exposure safety can be
exhaustively tested before any execution stage is authorized.

Constitutional constraints enforced here (v3.3 Laws 26-27, §16F.8/16F.9):
  * automatic failover only to an account already in the signed envelope, marked
    FALLBACK, for an allowed rejection class, with explicit caps;
  * impossible until the SOURCE order is terminal with a confirmed fill quantity;
  * aggregate exposure can never exceed the authorized envelope;
  * anything ambiguous → WAIT_FOR_SOURCE_FINALITY or BLOCKED, never action;
  * an alternate not in the envelope → REAUTHORIZE_SESSION (pause + notify),
    never a silent addition.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from active_trader.contracts import ContractViolation, CapabilityState
from active_trader.rejections import Classification

# source order states that make automatic fallback POSSIBLE
FINAL_SOURCE_STATES = frozenset({
    "REJECTED_WITH_ZERO_FILL",
    "CANCELLED_WITH_CONFIRMED_FILL_QUANTITY",
    "EXPIRED_WITH_CONFIRMED_FILL_QUANTITY",
})
# states that must BLOCK fallback outright
BLOCKING_SOURCE_STATES = frozenset({
    "SUBMITTED", "ACCEPTED", "PENDING_REPLACE", "PENDING_CANCEL", "UNKNOWN", "STALE",
    "PARTIALLY_FILLED_WITH_UNCONFIRMED_REMAINDER", "BROKER_UNREACHABLE",
})


class FallbackDecision(str, Enum):
    AUTO_FAILOVER_ELIGIBLE = "AUTO_FAILOVER_ELIGIBLE"
    PROMPT_OPERATOR = "PROMPT_OPERATOR"
    REAUTHORIZE_SESSION = "REAUTHORIZE_SESSION"
    WAIT_FOR_SOURCE_FINALITY = "WAIT_FOR_SOURCE_FINALITY"
    NO_FALLBACK = "NO_FALLBACK"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class FallbackPolicy:
    session_authorization_id: str
    source_account_id: str
    fallback_account_id: str
    priority: int
    allowed_normalized_codes: tuple
    max_fallback_shares: float
    max_fallback_notional: float
    max_fallback_risk: float
    auto_failover: bool
    requires_operator_confirmation: bool
    expires_at: Optional[datetime]
    policy_version: str

    def __post_init__(self):
        if min(self.max_fallback_shares, self.max_fallback_notional, self.max_fallback_risk) < 0:
            raise ContractViolation("fallback caps must be non-negative")
        if not self.allowed_normalized_codes:
            raise ContractViolation("fallback policy must name allowed rejection classes explicitly")


@dataclass(frozen=True)
class EvaluationInput:
    source_order_state: str
    source_filled_quantity: Optional[float]
    source_remaining_quantity: Optional[float]
    source_rejection: Classification
    fallback_account_capability: CapabilityState        # for the required order capability
    fallback_symbol_eligible: Optional[bool]            # None = unknown
    fallback_in_envelope: bool                          # account present in signed session
    fallback_role_is_fallback: bool                     # marked FALLBACK (not PRIMARY/DISABLED)
    policy: Optional[FallbackPolicy]
    requested_quantity: float
    price: float
    per_share_risk: float
    # session/aggregate state (synthetic in Stage 3)
    authorized_aggregate_quantity: float
    confirmed_aggregate_filled: float
    confirmed_working_quantity: float
    session_gross_notional_remaining: float
    session_risk_remaining: float
    session_trades_remaining: int
    session_within_time_bounds: bool
    market_thesis_valid: bool
    now: datetime


@dataclass(frozen=True)
class EvaluationResult:
    decision: FallbackDecision
    reasons: tuple
    max_new_quantity: float
    idempotency_key: str


def evaluate(inp: EvaluationInput) -> EvaluationResult:
    """Deterministic, side-effect-free fallback decision."""
    reasons: list[str] = []

    def out(decision: FallbackDecision, qty: float = 0.0) -> EvaluationResult:
        key = hashlib.sha256("|".join([
            inp.source_order_state, str(inp.source_filled_quantity),
            inp.source_rejection.matched_rule_id,
            inp.policy.policy_version if inp.policy else "no-policy",
            str(inp.requested_quantity), decision.value]).encode()).hexdigest()
        return EvaluationResult(decision, tuple(reasons), qty, key)

    # 1. source finality is the FIRST gate — nothing else matters until terminal
    if inp.source_order_state in BLOCKING_SOURCE_STATES:
        reasons.append(f"source_not_final:{inp.source_order_state}")
        return out(FallbackDecision.WAIT_FOR_SOURCE_FINALITY
                   if inp.source_order_state not in ("UNKNOWN", "STALE", "BROKER_UNREACHABLE")
                   else FallbackDecision.BLOCKED)
    if inp.source_order_state not in FINAL_SOURCE_STATES:
        reasons.append(f"unrecognized_source_state:{inp.source_order_state}")
        return out(FallbackDecision.BLOCKED)
    if inp.source_filled_quantity is None:
        reasons.append("source_fill_quantity_unconfirmed")
        return out(FallbackDecision.BLOCKED)

    # 2. envelope membership — never silently add an account
    if not inp.fallback_in_envelope:
        reasons.append("alternate_account_not_in_signed_envelope")
        return out(FallbackDecision.REAUTHORIZE_SESSION)
    if not inp.fallback_role_is_fallback:
        reasons.append("account_not_marked_FALLBACK")
        return out(FallbackDecision.NO_FALLBACK)
    if inp.policy is None:
        reasons.append("no_fallback_policy_defined")
        return out(FallbackDecision.NO_FALLBACK)
    if inp.policy.expires_at is not None and inp.now >= inp.policy.expires_at:
        reasons.append("fallback_policy_expired")
        return out(FallbackDecision.NO_FALLBACK)

    # 3. rejection class must be explicitly allowed
    if inp.source_rejection.normalized_code not in inp.policy.allowed_normalized_codes:
        reasons.append(f"rejection_class_not_allowed:{inp.source_rejection.normalized_code}")
        return out(FallbackDecision.NO_FALLBACK)

    # 4. alternate eligibility
    if inp.fallback_account_capability is not CapabilityState.SUPPORTED:
        reasons.append(f"fallback_capability_{inp.fallback_account_capability.value.lower()}")
        return out(FallbackDecision.NO_FALLBACK)
    if inp.fallback_symbol_eligible is not True:
        reasons.append("fallback_symbol_ineligible_or_unknown")
        return out(FallbackDecision.NO_FALLBACK)

    # 5. market and session validity
    if not inp.session_within_time_bounds:
        reasons.append("session_time_bounds_exceeded")
        return out(FallbackDecision.NO_FALLBACK)
    if not inp.market_thesis_valid:
        reasons.append("market_thesis_no_longer_valid")
        return out(FallbackDecision.NO_FALLBACK)
    if inp.session_trades_remaining < 1:
        reasons.append("session_trade_count_exhausted")
        return out(FallbackDecision.NO_FALLBACK)

    # 6. quantity/risk reconciliation — duplicate-exposure arithmetic
    envelope_room = (inp.authorized_aggregate_quantity
                     - inp.confirmed_aggregate_filled
                     - inp.confirmed_working_quantity)
    if envelope_room <= 0:
        reasons.append("aggregate_envelope_exhausted")
        return out(FallbackDecision.NO_FALLBACK)
    qty = min(inp.requested_quantity, envelope_room, inp.policy.max_fallback_shares)
    if inp.price > 0:
        qty = min(qty, inp.policy.max_fallback_notional / inp.price,
                  inp.session_gross_notional_remaining / inp.price)
    if inp.per_share_risk > 0:
        qty = min(qty, inp.policy.max_fallback_risk / inp.per_share_risk,
                  inp.session_risk_remaining / inp.per_share_risk)
    qty = float(int(qty))            # whole shares, floor — never round exposure UP
    if qty < 1:
        reasons.append("caps_reduce_quantity_below_one_share")
        return out(FallbackDecision.NO_FALLBACK)

    # 7. mode
    reasons.append(f"eligible_within_caps:max_qty={qty}")
    if inp.policy.auto_failover and not inp.policy.requires_operator_confirmation:
        return out(FallbackDecision.AUTO_FAILOVER_ELIGIBLE, qty)
    reasons.append("policy_requires_operator_confirmation")
    return out(FallbackDecision.PROMPT_OPERATOR, qty)


def unapproved_alternate_projection(symbol: str, alternates_visible: tuple) -> tuple:
    """State projection for the no-authorized-fallback path (§16F.9). Pure data."""
    return (
        "REJECTION_RECEIVED",
        "NO_AUTHORIZED_FALLBACK",
        f"SYMBOL_PAUSED:{symbol}",
        "OPERATOR_NOTIFIED",
        f"ALTERNATES_DISPLAYED:{','.join(alternates_visible) or 'none'}",
        "SESSION_AMENDMENT_REQUIRED",
    )
