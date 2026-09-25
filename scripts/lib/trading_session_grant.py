"""TradingSessionGrant@v1 — the check every broker mutation must pass.

PROPOSED under AGENTS.md 1.3.0 (see docs/governance/TRADING_SESSION_GRANT_CONTRACT.md).
This module is a PURE VERIFIER. It places, modifies and cancels nothing, reads no
credential, opens no connection and imports no broker adapter. It is not yet wired
into any broker call site: under the ACTIVE AGENTS.md (§0 rule 2) the broker
subsystem may not be modified until the amendment is ratified. The contract doc
lists the exact call sites it will guard.

Why it exists: architecture v3.3 §1.2 says "All live scalp orders must carry
session_authorization_id and authorization_hash. An order that cannot prove current
authorization is rejected before the adapter." Nothing enforced that at the adapter
boundary; the P3 session-control plane (scripts/active_trader/session_control.py)
builds and hashes the envelope but never checks an individual mutation against it.

Design rules (each one maps to a negative test in
tests/test_trading_session_grant_20260925.py):

* One hash definition. The envelope and its authorization_hash come from
  session_control.build_envelope / compute_authorization_hash; this module never
  re-implements canonicalisation.
* No invented limits. Every numeric bound is read from the operator-signed envelope.
  A missing or non-positive bound DENIES with OPERATOR_DECISION_REQUIRED — the
  verifier never substitutes a default.
* Risk-reducing actions survive a stopped session. After the entry cutoff, on expiry,
  on revocation or on the exit-only kill switch, new entries and adds are refused,
  while protective management and exits of positions the session opened are still
  allowed (v3.3 §1.2 / §1.4: "Session revocation never removes protection from an
  open position").
* Only the deterministic execution path may call. An LLM-originated request, or a
  request arriving from any entry point not on the allow-list, is refused.
* Fail closed. Anything the verifier cannot prove is a denial with a reason code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

try:  # repo-root imports (tests) and scripts/ on sys.path (runtime)
    from scripts.active_trader import session_control as SC  # type: ignore
except ImportError:  # pragma: no cover
    from active_trader import session_control as SC  # type: ignore

CONTRACT = "TradingSessionGrant@v1"
REQUEST_CONTRACT = "TradingMutationRequest@v1"
DECISION_CONTRACT = "TradingAuthorizationDecision@v1"

# Mutation classes at the broker boundary.
ENTRY = "ENTRY"  # opens or adds to a position
MODIFY = "MODIFY"  # reprices / resizes a working entry order
CANCEL = "CANCEL"  # cancels a working order
PROTECTION = "PROTECTION"  # installs / adjusts broker-native protective orders
EXIT = "EXIT"  # reduces or closes a position
MUTATION_CLASSES = frozenset({ENTRY, MODIFY, CANCEL, PROTECTION, EXIT})

# Classes that only reduce or protect existing exposure. These remain permitted after
# new entries stop, for positions this session opened.
RISK_REDUCING = frozenset({CANCEL, PROTECTION, EXIT})
# Classes that can add exposure. Refused once entries stop.
EXPOSURE_ADDING = frozenset({ENTRY, MODIFY})

# The only caller allowed to reach the broker boundary with session authority.
# Operator-set; widening this list is an AGENTS.md §17 decision.
DETERMINISTIC_ENTRY_POINTS = frozenset({"deterministic_execution_path"})

# Session states in which the grant can authorize anything at all.
ENTRY_STATES = frozenset({SC.ACTIVE})
MANAGE_ONLY_STATES = frozenset({SC.ENTRY_CUTOFF, SC.DRAINING, SC.PAUSED, SC.REVOKED, SC.KILLED})

OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"

# Reason codes (stable; tests and receipts key on them).
ALLOW = "ALLOW"
DENY_UNKNOWN_CLASS = "UNKNOWN_MUTATION_CLASS"
DENY_ALTERNATE_ENTRY_POINT = "ALTERNATE_ENTRY_POINT"
DENY_LLM_ORIGIN = "LLM_ORIGINATED_ORDER"
DENY_NO_SESSION = "NO_SESSION_AUTHORIZATION"
DENY_SESSION_MISMATCH = "SESSION_ID_MISMATCH"
DENY_NOT_AUTHORIZED = "SESSION_NOT_AUTHORIZED"
DENY_NO_2FA = "NO_2FA_VERIFICATION_REF"
DENY_ALTERED_ENVELOPE = "ALTERED_ENVELOPE"
DENY_HASH_MISMATCH = "AUTHORIZATION_HASH_MISMATCH"
DENY_EXPIRED = "SESSION_EXPIRED"
DENY_REVOKED = "SESSION_REVOKED"
DENY_ENTRY_CUTOFF = "AFTER_ENTRY_CUTOFF"
DENY_NOT_STARTED = "BEFORE_SESSION_START"
DENY_WRONG_BROKER = "WRONG_BROKER"
DENY_WRONG_ACCOUNT = "WRONG_ACCOUNT"
DENY_WRONG_SYMBOL = "WRONG_SYMBOL"
DENY_WRONG_STRATEGY = "WRONG_STRATEGY"
DENY_POLICY_VERSION = "POLICY_VERSION_MISMATCH"
DENY_ORDER_TYPE = "ORDER_TYPE_NOT_ALLOWED"
DENY_OVER_LIMIT = "OVER_LIMIT"
DENY_DUPLICATE = "DUPLICATE_REQUEST"
DENY_NOT_SESSION_POSITION = "POSITION_NOT_OPENED_BY_SESSION"
DENY_EXPOSURE_INCREASE = "RISK_REDUCING_ACTION_WOULD_INCREASE_EXPOSURE"
DENY_LIMIT_UNSET = OPERATOR_DECISION_REQUIRED


@dataclass(frozen=True)
class SessionGrant:
    """The operator-signed session, as the broker boundary sees it.

    ``envelope`` is the immutable session_control.AuthorizationEnvelope. The other
    fields are the authorization facts recorded when the operator completed the 2FA
    ceremony; none of them is bound into the hash (they are about the ceremony, not
    the trading bounds), and each is checked separately."""

    session_id: str
    envelope: Any  # session_control.AuthorizationEnvelope
    authorized_hash: str  # the hash the operator signed at authorization time
    state: str  # session_control lifecycle state
    operator_identity: str
    twofa_verification_ref: str  # reference to the 2FA ceremony record, never a code
    revoked_at: Optional[float] = None
    kill_switch_exit_only: bool = False


@dataclass(frozen=True)
class SessionUsage:
    """Live counters the execution path maintains. The verifier never computes them."""

    trades_used: int = 0
    open_positions: int = 0
    gross_notional_open: float = 0.0
    realized_loss_today: float = 0.0  # positive number = money lost
    seen_request_ids: frozenset = field(default_factory=frozenset)
    # position_id -> {"session_id", "symbol", "account_id", "qty"}
    positions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class MutationRequest:
    """TradingMutationRequest@v1 — one proposed broker mutation."""

    request_id: str  # idempotency key; a replay is refused
    mutation_class: str
    entry_point: str  # who is calling the broker boundary
    origin: str  # "deterministic" | "llm" | "operator_manual" | ...
    session_id: Optional[str]
    authorization_hash: Optional[str]
    broker: str
    account_id: str
    symbol: str
    strategy: str
    candidate_policy_version: str
    risk_policy_version: str
    order_type: str = ""
    notional: float = 0.0  # absolute notional this request adds (ENTRY/MODIFY)
    risk: float = 0.0  # risk to stop this request adds (ENTRY/MODIFY)
    chase_bps: float = 0.0
    order_ttl_sec: float = 0.0
    qty: float = 0.0  # for EXIT: quantity to close
    position_id: Optional[str] = None  # required for CANCEL/PROTECTION/EXIT
    universe_membership_ref: Optional[str] = None  # required under a universe rule


@dataclass(frozen=True)
class Decision:
    """TradingAuthorizationDecision@v1."""

    allowed: bool
    reason: str
    detail: str = ""
    contract: str = DECISION_CONTRACT

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "detail": self.detail, "contract": self.contract}


def _deny(reason: str, detail: str = "") -> Decision:
    return Decision(False, reason, detail)


def parse_symbol_scope(scope: str) -> tuple[str, Any]:
    """``"universe:<rule>"`` → ("universe", rule); otherwise an explicit list.

    The explicit list accepts ``"symbols:A,B"`` or a bare ``"A,B"``; symbols are
    upper-cased. An empty scope authorizes no symbol."""
    s = str(scope or "").strip()
    if s.lower().startswith("universe:"):
        return "universe", s.split(":", 1)[1].strip()
    if s.lower().startswith("symbols:"):
        s = s.split(":", 1)[1]
    syms = frozenset(x.strip().upper() for x in s.replace(" ", ",").split(",") if x.strip())
    return "list", syms


def _limit(env: Any, name: str) -> Optional[float]:
    """The operator's bound, or None when absent / non-positive (never a default)."""
    try:
        v = float(getattr(env, name))
    except (TypeError, ValueError, AttributeError):
        return None
    return v if v > 0 else None


def _in(value: str, allowed: Iterable[str]) -> bool:
    return str(value or "").strip().lower() in {str(a).strip().lower() for a in allowed or ()}


def verify_mutation(
    grant: Optional[SessionGrant], request: MutationRequest, usage: SessionUsage, *, now: float
) -> Decision:
    """Allow or refuse one broker mutation. Pure; ``now`` is epoch seconds."""
    # 1. Who is calling, and what.
    if request.mutation_class not in MUTATION_CLASSES:
        return _deny(DENY_UNKNOWN_CLASS, str(request.mutation_class))
    if str(request.origin or "").lower() == "llm":
        return _deny(DENY_LLM_ORIGIN, "an LLM cannot originate or route an order")
    if request.entry_point not in DETERMINISTIC_ENTRY_POINTS:
        return _deny(DENY_ALTERNATE_ENTRY_POINT, str(request.entry_point))
    if request.request_id in usage.seen_request_ids:
        return _deny(DENY_DUPLICATE, request.request_id)

    # 2. Is there a real, signed, unaltered session behind it.
    if grant is None or not request.session_id or not request.authorization_hash:
        return _deny(DENY_NO_SESSION)
    if request.session_id != grant.session_id:
        return _deny(DENY_SESSION_MISMATCH)
    if not str(grant.twofa_verification_ref or "").strip():
        return _deny(DENY_NO_2FA)
    env = grant.envelope
    if env is None or env.recompute_hash() != env.authorization_hash or env.authorization_hash != grant.authorized_hash:
        return _deny(DENY_ALTERED_ENVELOPE, "envelope does not hash to the signed value")
    if request.authorization_hash != grant.authorized_hash:
        return _deny(DENY_HASH_MISMATCH)
    if grant.operator_identity != env.operator_identity:
        return _deny(DENY_ALTERED_ENVELOPE, "operator identity differs from the signed envelope")

    # 3. Bindings that apply to every class.
    if not _in(request.broker, env.brokers):
        return _deny(DENY_WRONG_BROKER, request.broker)
    if not _in(request.account_id, env.account_ids):
        return _deny(DENY_WRONG_ACCOUNT, request.account_id)
    if str(request.strategy or "").upper() != str(env.strategy or "").upper():
        return _deny(DENY_WRONG_STRATEGY, request.strategy)
    if (
        request.candidate_policy_version != env.candidate_policy_version
        or request.risk_policy_version != env.risk_policy_version
    ):
        return _deny(DENY_POLICY_VERSION)

    # 4. Risk-reducing actions: allowed while the session is ACTIVE or winding down,
    #    but only on positions this session opened, and never adding exposure.
    if request.mutation_class in RISK_REDUCING:
        return _verify_risk_reducing(grant, request, usage)

    # 5. Exposure-adding actions: the session must be live and inside its window.
    if (
        grant.revoked_at is not None
        or grant.state == SC.REVOKED
        or grant.kill_switch_exit_only
        or grant.state == SC.KILLED
    ):
        return _deny(DENY_REVOKED)
    if grant.state not in ENTRY_STATES:
        return _deny(DENY_NOT_AUTHORIZED, grant.state)
    if now < float(env.session_start):
        return _deny(DENY_NOT_STARTED)
    if now >= float(env.expiry):
        return _deny(DENY_EXPIRED)
    if now >= float(env.entry_cutoff):
        return _deny(DENY_ENTRY_CUTOFF)
    scope_kind, scope = parse_symbol_scope(env.symbol_list_or_universe_rule)
    if scope_kind == "list":
        if str(request.symbol or "").upper() not in scope:
            return _deny(DENY_WRONG_SYMBOL, request.symbol)
    elif not request.universe_membership_ref:
        return _deny(DENY_WRONG_SYMBOL, f"no membership proof under universe rule {scope!r}")
    if not _in(request.order_type, env.allowed_order_types):
        return _deny(DENY_ORDER_TYPE, request.order_type)
    return _verify_limits(env, request, usage)


def _verify_risk_reducing(grant: SessionGrant, request: MutationRequest, usage: SessionUsage) -> Decision:
    if grant.state not in ENTRY_STATES | MANAGE_ONLY_STATES:
        return _deny(DENY_NOT_AUTHORIZED, grant.state)
    pos = usage.positions.get(str(request.position_id or ""))
    if not pos or pos.get("session_id") != grant.session_id:
        return _deny(DENY_NOT_SESSION_POSITION, str(request.position_id))
    if str(pos.get("symbol", "")).upper() != str(request.symbol or "").upper() or str(pos.get("account_id", "")) != str(
        request.account_id
    ):
        return _deny(DENY_NOT_SESSION_POSITION, "symbol/account differ from the session position")
    if request.mutation_class == EXIT:
        held = float(pos.get("qty") or 0)
        if request.qty <= 0 or request.qty > held:
            return _deny(DENY_EXPOSURE_INCREASE, f"exit qty {request.qty} vs held {held}")
    if request.notional > 0 or request.risk > 0:
        return _deny(DENY_EXPOSURE_INCREASE, "risk-reducing class carried added notional/risk")
    return Decision(True, ALLOW, request.mutation_class)


def _verify_limits(env: Any, request: MutationRequest, usage: SessionUsage) -> Decision:
    needed = (
        "max_trades",
        "max_concurrent_positions",
        "max_gross_notional",
        "max_notional_per_trade",
        "max_risk_per_trade",
        "max_daily_loss",
        "max_chase_bps",
        "max_order_ttl_sec",
    )
    limits = {n: _limit(env, n) for n in needed}
    unset = [n for n, v in limits.items() if v is None]
    if unset:
        return _deny(DENY_LIMIT_UNSET, "operator must set: " + ",".join(unset))
    is_new_position = request.mutation_class == ENTRY
    checks = (
        (is_new_position and usage.trades_used + 1 > limits["max_trades"], "max_trades"),
        (is_new_position and usage.open_positions + 1 > limits["max_concurrent_positions"], "max_concurrent_positions"),
        (request.notional > limits["max_notional_per_trade"], "max_notional_per_trade"),
        (usage.gross_notional_open + request.notional > limits["max_gross_notional"], "max_gross_notional"),
        (request.risk > limits["max_risk_per_trade"], "max_risk_per_trade"),
        (usage.realized_loss_today >= limits["max_daily_loss"], "max_daily_loss"),
        (request.chase_bps > limits["max_chase_bps"], "max_chase_bps"),
        (request.order_ttl_sec > limits["max_order_ttl_sec"], "max_order_ttl_sec"),
    )
    for breached, name in checks:
        if breached:
            return _deny(DENY_OVER_LIMIT, name)
    return Decision(True, ALLOW, request.mutation_class)


__all__ = [
    "CONTRACT",
    "REQUEST_CONTRACT",
    "DECISION_CONTRACT",
    "MUTATION_CLASSES",
    "ENTRY",
    "MODIFY",
    "CANCEL",
    "PROTECTION",
    "EXIT",
    "DETERMINISTIC_ENTRY_POINTS",
    "OPERATOR_DECISION_REQUIRED",
    "SessionGrant",
    "SessionUsage",
    "MutationRequest",
    "Decision",
    "verify_mutation",
    "parse_symbol_scope",
]
