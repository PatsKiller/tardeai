"""Active Trader Stage 8 — session authorization + live-inactive action contracts.

No real 2FA, no broker write, no live activation. Providers model authorization
without integrating any real SMS/TOTP/email/broker verification. Every action route
returns only a typed inactive result and may create lab/test intents + journal events —
never a broker call or an executable production record.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from active_trader.contracts import ContractViolation, Environment


# ---------------------------------------------------------------- providers

class ProviderResult(str, Enum):
    VERIFIED_TEST = "VERIFIED_TEST"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    LIVE_INACTIVE = "LIVE_INACTIVE"


class AuthorizationProvider:
    """Abstract. Real 2FA integration is intentionally absent in Stage 8."""
    name = "abstract"

    def verify(self, draft_hash: str, operator_id: str) -> ProviderResult:
        raise NotImplementedError


class TestAuthorizationProvider(AuthorizationProvider):
    __test__ = False  # not a pytest class
    """One successful TEST verification authorizes one bounded test session.
    No real code is sent or checked — this is a deterministic test double."""
    name = "test"

    def __init__(self, accept: bool = True):
        self._accept = accept

    def verify(self, draft_hash: str, operator_id: str) -> ProviderResult:
        return ProviderResult.VERIFIED_TEST if self._accept else ProviderResult.NOT_CONFIGURED


class UnavailableProductionAuthorizationProvider(AuthorizationProvider):
    """Production provider — never performs real verification here."""
    name = "production"

    def verify(self, draft_hash: str, operator_id: str) -> ProviderResult:
        return ProviderResult.LIVE_INACTIVE      # deliberately inert; no real SMS/TOTP/broker


# ---------------------------------------------------------------- authorization

class AuthStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


@dataclass
class SessionAuthorization:
    authorization_id: str
    draft_id: str
    draft_version: int
    draft_hash: str                      # authority hash bound at verification time
    operator_id: str
    environment: Environment
    authorized_accounts: tuple           # ((broker, label, role), ...)
    symbols: tuple                       # explicit symbols OR ("__UNIVERSE__", rule_version)
    quantity_envelope: dict              # aggregate + per-account caps
    risk_envelope: dict
    allowed_actions: frozenset
    fallback_policy: dict
    feature_policy_versions: dict
    issued_at: datetime
    not_before: datetime
    expiry: datetime
    provider: str
    verification_reference: str
    version: int = 1
    status: AuthStatus = AuthStatus.AUTHORIZED
    revoked_at: Optional[datetime] = None

    def check_active(self, now: datetime) -> None:
        if self.status in (AuthStatus.REVOKED, AuthStatus.CLOSED) or self.revoked_at is not None:
            raise ContractViolation("authorization revoked/closed")
        if now < self.not_before:
            raise ContractViolation("authorization not yet valid")
        if now >= self.expiry:
            raise ContractViolation("authorization expired")

    def check_account(self, broker: str, label: str) -> tuple:
        for b, l, role in self.authorized_accounts:
            if b == broker and l == label and role != "DISABLED":
                return (b, l, role)
        raise ContractViolation(f"account {broker}/{label} not in authorization envelope")

    def check_symbol(self, symbol: str) -> None:
        if self.symbols and self.symbols[0] == "__UNIVERSE__":
            return  # dynamic universe rule bound in envelope
        if symbol not in self.symbols:
            raise ContractViolation(f"symbol {symbol} outside authorized set")

    def binds(self, draft_hash: str) -> bool:
        return draft_hash == self.draft_hash


class ReauthorizationRequired(ContractViolation):
    pass


def issue_test_authorization(*, draft_id: str, draft_version: int, draft_hash: str,
                             operator_id: str, environment: Environment,
                             authorized_accounts: tuple, symbols: tuple,
                             quantity_envelope: dict, risk_envelope: dict,
                             allowed_actions: frozenset, fallback_policy: dict,
                             feature_policy_versions: dict, now: datetime,
                             ttl_hours: int = 4,
                             provider: Optional[AuthorizationProvider] = None) -> SessionAuthorization:
    """Issue ONE bounded test authorization after a successful test verification.
    Production authorization is never issued here (LIVE_INACTIVE)."""
    provider = provider or TestAuthorizationProvider()
    result = provider.verify(draft_hash, operator_id)
    if result is not ProviderResult.VERIFIED_TEST:
        raise ContractViolation(f"authorization not issued: provider result {result.value}")
    if environment not in (Environment.SHADOW, Environment.SIMULATION):
        raise ContractViolation("Stage 8 issues SHADOW/SIMULATION authorizations only")
    auth_hash = hashlib.sha256(
        f"{draft_hash}|{operator_id}|{now.isoformat()}".encode()).hexdigest()
    return SessionAuthorization(
        authorization_id=str(uuid.uuid4()), draft_id=draft_id, draft_version=draft_version,
        draft_hash=draft_hash, operator_id=operator_id, environment=environment,
        authorized_accounts=authorized_accounts, symbols=symbols,
        quantity_envelope=quantity_envelope, risk_envelope=risk_envelope,
        allowed_actions=allowed_actions, fallback_policy=fallback_policy,
        feature_policy_versions=feature_policy_versions, issued_at=now, not_before=now,
        expiry=now + timedelta(hours=ttl_hours), provider=provider.name,
        verification_reference=auth_hash[:16])


def requires_reauthorization(auth: SessionAuthorization, *, new_draft_hash: Optional[str] = None,
                             new_account: Optional[tuple] = None,
                             larger_quantity: bool = False,
                             environment_change: bool = False) -> bool:
    """Any material change requires reauthorization."""
    if new_draft_hash is not None and not auth.binds(new_draft_hash):
        return True
    if new_account is not None and new_account not in auth.authorized_accounts:
        return True
    return bool(larger_quantity or environment_change)


# ---------------------------------------------------------------- inactive actions

class ActionType(str, Enum):
    PRIME = "prime"
    FIRE = "fire"
    QUICK_ADD = "quick_add"
    SMART_ENTRY = "smart_entry"
    REPLACE = "replace"
    CANCEL_ONE = "cancel_one"
    CANCEL_ALL_SYMBOL = "cancel_all_symbol"
    CANCEL_ALL_ACCOUNT = "cancel_all_account"
    SMART_SELL = "smart_sell"
    FLATTEN_SYMBOL = "flatten_symbol"
    FLATTEN_ACCOUNT = "flatten_account"
    SCALE_OUT = "scale_out"
    RUNNER_CONVERT = "runner_convert"
    OVERNIGHT_CONVERT = "overnight_convert"


class ActionResult(str, Enum):
    VALIDATED_INACTIVE = "VALIDATED_INACTIVE"
    BLOCKED = "BLOCKED"
    REAUTHORIZATION_REQUIRED = "REAUTHORIZATION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    STALE_DATA = "STALE_DATA"
    RISK_REJECTED = "RISK_REJECTED"


DESTRUCTIVE_ACTIONS = frozenset({
    ActionType.CANCEL_ALL_SYMBOL, ActionType.CANCEL_ALL_ACCOUNT,
    ActionType.FLATTEN_SYMBOL, ActionType.FLATTEN_ACCOUNT, ActionType.OVERNIGHT_CONVERT,
})


@dataclass(frozen=True)
class ActionRequest:
    action: ActionType
    authorization: SessionAuthorization
    broker: str
    account_label: str
    symbol: Optional[str]
    quantity: Optional[float] = None
    capability_state: str = "SUPPORTED"     # SUPPORTED/UNSUPPORTED/UNKNOWN/RESTRICTED/DEGRADED
    data_state: str = "HEALTHY"             # HEALTHY/STALE/GAP
    risk_ok: bool = True
    confirmation_token: Optional[str] = None
    idempotency_key: Optional[str] = None
    now: Optional[datetime] = None


@dataclass(frozen=True)
class ActionOutcome:
    result: ActionResult
    reason: str
    action: str
    inactive: bool = True                   # ALWAYS true — never executes
    intent_id: Optional[str] = None
    journal_event: Optional[str] = None


def _confirm_ok(req: ActionRequest) -> bool:
    if req.action not in DESTRUCTIVE_ACTIONS:
        return True
    # deterministic confirmation contract: token must equal the expected phrase
    expected = f"CONFIRM:{req.action.value}:{req.symbol or req.account_label}"
    return req.confirmation_token == expected


def evaluate_action(req: ActionRequest) -> ActionOutcome:
    """Pure, side-effect-free inactive-action evaluation. Never calls a broker;
    never executes. May DESCRIBE the lab/test intent + journal event it would create."""
    now = req.now or datetime.now(timezone.utc)
    a = req.action.value

    def out(result: ActionResult, reason: str, with_intent: bool = False):
        iid = None
        if with_intent and result is ActionResult.VALIDATED_INACTIVE:
            base = req.idempotency_key or f"{a}|{req.broker}|{req.account_label}|{req.symbol}"
            iid = "lab-" + hashlib.sha256(base.encode()).hexdigest()[:16]
        return ActionOutcome(result=result, reason=reason, action=a, intent_id=iid,
                             journal_event=f"inactive_action:{a}")

    # 1. authorization validity + membership
    try:
        req.authorization.check_active(now)
    except ContractViolation as e:
        return out(ActionResult.BLOCKED, f"authorization: {e}")
    if req.action not in req.authorization.allowed_actions:
        return out(ActionResult.BLOCKED, "action not in authorized allowed_actions")
    try:
        req.authorization.check_account(req.broker, req.account_label)
        if req.symbol:
            req.authorization.check_symbol(req.symbol)
    except ContractViolation as e:
        # an unauthorized account/symbol is a reauthorization matter for alternates
        return out(ActionResult.REAUTHORIZATION_REQUIRED, str(e))

    # 2. capability gating
    if req.capability_state == "UNSUPPORTED":
        return out(ActionResult.UNSUPPORTED, "broker capability unsupported")
    if req.capability_state == "UNKNOWN":
        return out(ActionResult.UNKNOWN_CAPABILITY, "broker capability unknown (fail closed)")

    # 3. data + risk
    if req.data_state in ("STALE", "GAP"):
        return out(ActionResult.STALE_DATA, f"data {req.data_state}")
    if not req.risk_ok:
        return out(ActionResult.RISK_REJECTED, "risk envelope rejected")

    # 4. destructive confirmation
    if not _confirm_ok(req):
        return out(ActionResult.BLOCKED, "destructive action requires explicit confirmation token")

    # 5. quantity envelope (adds/entries)
    if req.action in (ActionType.QUICK_ADD, ActionType.SMART_ENTRY, ActionType.SCALE_OUT):
        cap = req.authorization.quantity_envelope.get("max_aggregate_shares")
        if cap is not None and req.quantity is not None and req.quantity > cap:
            return out(ActionResult.RISK_REJECTED, "quantity exceeds authorized envelope")

    return out(ActionResult.VALIDATED_INACTIVE, "validated; inactive (no execution)", with_intent=True)
