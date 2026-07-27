"""Active Trader Stage 1 typed contracts.

Deterministic validation layer for the additive Active Trader schema.
No broker writes, no 2FA, no Moomoo, no network. Pure invariants.

Design laws enforced here (architecture v3.3):
  * environment is always explicit — SHADOW / SIMULATION / LIVE, no default;
  * a LIVE order intent is representable only under a valid, unrevoked,
    unexpired session authorization whose hash matches the immutable draft;
  * an authorized draft is immutable — any changed hash invalidates reuse;
  * feature flags can never authorize trading or enlarge an envelope;
  * unknown broker facts stay UNKNOWN; stale evidence never becomes SUPPORTED;
  * unknown broker rejections are non-retryable by default;
  * sentinel secret values are rejected at runtime.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

SENTINEL_SECRET = "UNSET__OPERATOR_REQUIRED"


class ContractViolation(ValueError):
    """Raised whenever a Stage 1 invariant is violated. Always fail closed."""


def reject_sentinel(value: str, name: str = "secret") -> str:
    if value is None or str(value).strip() == "" or str(value).strip() == SENTINEL_SECRET:
        raise ContractViolation(f"{name} is unset or a sentinel placeholder; operator provisioning required")
    return value


class Environment(str, Enum):
    SHADOW = "SHADOW"
    SIMULATION = "SIMULATION"
    LIVE = "LIVE"

    @classmethod
    def parse(cls, raw: Any) -> "Environment":
        """No implicit default — absent/blank/unknown environment is an error."""
        if isinstance(raw, cls):
            return raw
        if raw is None or str(raw).strip() == "":
            raise ContractViolation("environment is required and has no default")
        try:
            return cls(str(raw).strip().upper())
        except ValueError as exc:
            raise ContractViolation(f"unknown environment {raw!r}") from exc


ALLOWED_BROKERS = ("alpaca", "moomoo", "schwab")  # Active Trader v1 scope (owner ruling)


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def draft_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


# ---------------------------------------------------------------- sessions

@dataclass(frozen=True)
class SessionDraft:
    """Immutable draft version. Editing produces a NEW version, never a mutation."""

    draft_id: str
    draft_version: int
    environment: Environment
    session_name: str
    broker_set: tuple
    account_policy: dict
    symbol_policy: dict
    risk_limits: dict
    time_bounds: dict
    runner_policy: dict
    feature_policy_versions: dict
    created_by: str

    def __post_init__(self):
        Environment.parse(self.environment)
        if self.draft_version < 1:
            raise ContractViolation("draft_version must be >= 1")
        for b in self.broker_set:
            if b not in ALLOWED_BROKERS:
                raise ContractViolation(f"broker {b!r} outside Active Trader v1 scope {ALLOWED_BROKERS}")
        for req in ("max_trades", "max_concurrent_positions", "max_gross_notional",
                    "max_risk_per_trade", "max_daily_loss"):
            if req not in self.risk_limits:
                raise ContractViolation(f"risk_limits missing required bound {req!r}")

    @property
    def hash(self) -> str:
        return draft_hash({
            "draft_id": self.draft_id,
            "draft_version": self.draft_version,
            "environment": self.environment.value,
            "session_name": self.session_name,
            "broker_set": list(self.broker_set),
            "account_policy": self.account_policy,
            "symbol_policy": self.symbol_policy,
            "risk_limits": self.risk_limits,
            "time_bounds": self.time_bounds,
            "runner_policy": self.runner_policy,
            "feature_policy_versions": self.feature_policy_versions,
        })


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENTRY_CUTOFF = "ENTRY_CUTOFF"
    DRAINING = "DRAINING"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class SessionAccount:
    broker: str
    account_label: str
    environment: Environment
    role: str  # PRIMARY | FALLBACK | DISABLED
    max_shares: Optional[float] = None
    max_notional: Optional[float] = None
    max_risk: Optional[float] = None
    fallback_priority: Optional[int] = None

    def __post_init__(self):
        if self.broker not in ALLOWED_BROKERS:
            raise ContractViolation(f"broker {self.broker!r} outside v1 scope")
        if self.role not in ("PRIMARY", "FALLBACK", "DISABLED"):
            raise ContractViolation(f"invalid account role {self.role!r}")
        Environment.parse(self.environment)


@dataclass(frozen=True)
class SessionAuthorization:
    """Hash-bound authorization of ONE immutable draft. 2FA itself is NOT
    implemented in Stage 1 — only the contract a later 2FA stage must satisfy."""

    session_authorization_id: str
    draft: SessionDraft
    authorization_hash: str
    operator_id: str
    status: AuthorizationStatus
    session_start: datetime
    session_entry_cutoff: datetime
    session_expiry: datetime
    accounts: tuple = ()
    revoked_at: Optional[datetime] = None

    def __post_init__(self):
        if self.session_entry_cutoff > self.session_expiry:
            raise ContractViolation("entry cutoff after session expiry")
        if self.authorization_hash != self.expected_hash():
            raise ContractViolation("authorization hash does not bind this draft (draft changed after authorization?)")
        for acct in self.accounts:
            if not isinstance(acct, SessionAccount):
                raise ContractViolation("accounts must be SessionAccount instances")
            if acct.environment != Environment.parse(self.draft.environment):
                raise ContractViolation("session account environment differs from draft environment")

    def expected_hash(self) -> str:
        return draft_hash({
            "draft_hash": self.draft.hash,
            "operator_id": self.operator_id,
            "session_start": self.session_start.isoformat(),
            "session_entry_cutoff": self.session_entry_cutoff.isoformat(),
            "session_expiry": self.session_expiry.isoformat(),
        })

    def check_valid(self, now: datetime) -> None:
        """Fail-closed validity gate used by every later order path."""
        if self.status == AuthorizationStatus.REVOKED or self.revoked_at is not None:
            raise ContractViolation("session authorization revoked")
        if self.status not in (AuthorizationStatus.AUTHORIZED, AuthorizationStatus.ACTIVE):
            raise ContractViolation(f"session authorization not usable in status {self.status.value}")
        if now >= self.session_expiry:
            raise ContractViolation("session authorization expired")

    def check_account(self, broker: str, account_label: str) -> SessionAccount:
        for acct in self.accounts:
            if acct.broker == broker and acct.account_label == account_label and acct.role != "DISABLED":
                return acct
        raise ContractViolation(f"account {broker}/{account_label} not authorized in this session envelope")

    def check_quantity(self, broker: str, account_label: str, shares: float, notional: float) -> None:
        acct = self.check_account(broker, account_label)
        if acct.max_shares is not None and shares > acct.max_shares:
            raise ContractViolation("requested shares exceed the authorized per-account envelope")
        if acct.max_notional is not None and notional > acct.max_notional:
            raise ContractViolation("requested notional exceeds the authorized per-account envelope")


# ---------------------------------------------------------------- order intents

@dataclass(frozen=True)
class OrderIntent:
    order_intent_id: str
    environment: Environment
    broker: str
    account_label: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    time_in_force: str
    trading_session: str
    idempotency_key: str
    session_authorization: Optional[SessionAuthorization] = None
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    now: Optional[datetime] = None

    def __post_init__(self):
        env = Environment.parse(self.environment)
        if self.broker not in ALLOWED_BROKERS:
            raise ContractViolation(f"broker {self.broker!r} outside v1 scope")
        if self.quantity <= 0:
            raise ContractViolation("quantity must be positive")
        if env == Environment.LIVE:
            if self.session_authorization is None:
                raise ContractViolation("LIVE order intent requires a session authorization")
            ts = self.now or datetime.now(timezone.utc)
            self.session_authorization.check_valid(ts)
            self.session_authorization.check_account(self.broker, self.account_label)
        if env == Environment.SHADOW and self.session_authorization is not None:
            raise ContractViolation("SHADOW intents must not carry broker-write authorization")


# ---------------------------------------------------------------- broker capability

class CapabilityState(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"
    RESTRICTED = "RESTRICTED"


@dataclass(frozen=True)
class BrokerCapability:
    broker: str
    account_label: str
    environment: Environment
    capability: str
    state: CapabilityState
    source: str  # DOCUMENTATION | RUNTIME_PROBE | BROKER_RESPONSE | OPERATOR_OVERRIDE
    verified_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def __post_init__(self):
        if self.broker not in ALLOWED_BROKERS:
            raise ContractViolation(f"broker {self.broker!r} outside v1 scope")
        if self.source not in ("DOCUMENTATION", "RUNTIME_PROBE", "BROKER_RESPONSE", "OPERATOR_OVERRIDE"):
            raise ContractViolation(f"invalid capability source {self.source!r}")
        if self.state == CapabilityState.SUPPORTED and self.verified_at is None:
            raise ContractViolation("SUPPORTED requires verification evidence time")

    def effective_state(self, now: datetime) -> CapabilityState:
        """Stale evidence can never silently read as SUPPORTED."""
        if self.expires_at is not None and now >= self.expires_at:
            return CapabilityState.UNKNOWN
        return self.state


KNOWN_REJECTION_CODES = frozenset({
    "SECURITY_REQUIRES_BROKER_ASSISTANCE", "ELECTRONIC_ENTRY_NOT_ALLOWED",
    "LOW_PRICE_OR_MICROCAP_RESTRICTION", "SECURITY_NOT_DAY_TRADE_ELIGIBLE",
    "ACCOUNT_RESTRICTED", "ACCOUNT_NOT_AUTHORIZED", "INSUFFICIENT_BUYING_POWER",
    "INSUFFICIENT_SHARES", "ORDER_TYPE_NOT_SUPPORTED", "SESSION_NOT_SUPPORTED",
    "PRICE_INCREMENT_INVALID", "PRICE_BAND_REJECTED", "QUANTITY_LIMIT_REJECTED",
    "POSITION_OR_ORDER_CONFLICT", "RATE_LIMITED", "MARKET_CLOSED", "HALTED",
    "STALE_ACCOUNT_STATE", "AUTHENTICATION_EXPIRED", "UNKNOWN_BROKER_REJECTION",
})
RETRYABLE_CODES = frozenset({"RATE_LIMITED", "STALE_ACCOUNT_STATE", "MARKET_CLOSED"})
BROKER_CALL_CODES = frozenset({"SECURITY_REQUIRES_BROKER_ASSISTANCE"})


@dataclass(frozen=True)
class NormalizedRejection:
    broker: str
    account_label: str
    environment: Environment
    raw_code: str
    raw_message: str
    normalized_code: str = "UNKNOWN_BROKER_REJECTION"

    def __post_init__(self):
        if self.normalized_code not in KNOWN_REJECTION_CODES:
            raise ContractViolation(f"unregistered normalized rejection code {self.normalized_code!r}")

    @property
    def retryable(self) -> bool:
        return self.normalized_code in RETRYABLE_CODES  # unknown → False by construction

    @property
    def requires_broker_call(self) -> bool:
        return self.normalized_code in BROKER_CALL_CODES

    @property
    def requires_operator(self) -> bool:
        return not self.retryable


# ---------------------------------------------------------------- feature flags

class FlagMode(str, Enum):
    OFF = "OFF"
    READ_ONLY = "READ_ONLY"
    SHADOW = "SHADOW"
    SIMULATION = "SIMULATION"
    LIVE_CANARY = "LIVE_CANARY"


FLAG_REGISTRY = (
    "active_trader_next_visible", "active_trader_next_read_only",
    "active_trader_session_builder_enabled", "active_trader_simulation_enabled",
    "active_trader_live_canary_enabled", "active_trader_multi_account_enabled",
    "active_trader_runner_enabled", "active_trader_overnight_conversion_enabled",
    "broker_alpaca", "broker_moomoo", "broker_schwab", "broker_failover",
    "smart_entry", "quick_add", "cancel_one", "cancel_all", "flatten", "smart_sell",
    "resilience_resistance", "journal_replay", "drive_sync", "operator_email",
)

# Stage 1 defaults: production all OFF; test all OFF unless a test scopes one;
# development may show the shell read-only.
DEFAULTS = {
    "production": {name: FlagMode.OFF for name in FLAG_REGISTRY},
    "test": {name: FlagMode.OFF for name in FLAG_REGISTRY},
    "development": {**{name: FlagMode.OFF for name in FLAG_REGISTRY},
                    "active_trader_next_visible": FlagMode.READ_ONLY},
}


@dataclass(frozen=True)
class FeatureFlag:
    flag_name: str
    mode: FlagMode
    version: int
    reason: str
    changed_by: str
    scope_key: str = "global"
    expires_at: Optional[datetime] = None

    def __post_init__(self):
        if self.flag_name not in FLAG_REGISTRY:
            raise ContractViolation(f"unknown feature flag {self.flag_name!r}")
        if not isinstance(self.mode, FlagMode):
            raise ContractViolation(f"invalid flag mode {self.mode!r}")
        if self.version < 1:
            raise ContractViolation("flag version must be >= 1")
        if not self.reason.strip():
            raise ContractViolation("flag change requires a reason (audited)")

    def effective_mode(self, now: datetime) -> FlagMode:
        if self.expires_at is not None and now >= self.expires_at:
            return FlagMode.OFF
        return self.mode


def flag_default(environment_name: str, flag_name: str) -> FlagMode:
    if environment_name not in DEFAULTS:
        raise ContractViolation(f"unknown deployment environment {environment_name!r}")
    return DEFAULTS[environment_name][flag_name]


def authorize_order(intent: OrderIntent, flags: dict[str, FlagMode] | None = None,
                    now: Optional[datetime] = None) -> None:
    """The ONLY order authorization gate. Feature flags are deliberately not an
    input that can grant anything: a flag may restrict, never authorize.
    LIVE requires a valid session authorization regardless of any flag state."""
    env = Environment.parse(intent.environment)
    if env == Environment.LIVE:
        if intent.session_authorization is None:
            raise ContractViolation("LIVE requires session authorization; no flag can substitute")
        intent.session_authorization.check_valid(now or datetime.now(timezone.utc))
        intent.session_authorization.check_account(intent.broker, intent.account_label)
    if flags:
        broker_flag = flags.get(f"broker_{intent.broker}", FlagMode.OFF)
        if broker_flag == FlagMode.OFF:
            raise ContractViolation(f"broker_{intent.broker} flag OFF: intent blocked (flags restrict, never grant)")


# ---------------------------------------------------------------- rate policy

@dataclass(frozen=True)
class RateBudget:
    action_class: str          # PLACE | MODIFY_CANCEL — MUST be separate budgets
    provider_ceiling: int
    ordinary_budget: int
    reserve_budget: int
    window_seconds: int
    account_scope: str         # required: broker/account identity

    def __post_init__(self):
        if self.action_class not in ("PLACE", "MODIFY_CANCEL"):
            raise ContractViolation("action_class must be PLACE or MODIFY_CANCEL (never shared)")
        if self.window_seconds <= 0:
            raise ContractViolation("rate window must be positive")
        if not self.account_scope.strip():
            raise ContractViolation("rate budget requires an account scope")
        if min(self.provider_ceiling, self.ordinary_budget, self.reserve_budget) < 0:
            raise ContractViolation("rate values must be non-negative")
        if self.ordinary_budget + self.reserve_budget > self.provider_ceiling:
            raise ContractViolation("ordinary + reserve exceeds the provider ceiling")


@dataclass(frozen=True)
class RatePolicy:
    """Architecture-owner approved Moomoo policy (Stage 1 ruling):
    PLACE 15/12/3 per 30s · MODIFY_CANCEL 20/16/4 per 30s, per account."""

    place: RateBudget
    modify_cancel: RateBudget

    def __post_init__(self):
        if self.place.action_class != "PLACE" or self.modify_cancel.action_class != "MODIFY_CANCEL":
            raise ContractViolation("rate policy budgets mis-assigned")
        if self.place.account_scope != self.modify_cancel.account_scope:
            raise ContractViolation("both budgets must scope the same account")

    @classmethod
    def approved_moomoo(cls, account_scope: str) -> "RatePolicy":
        return cls(
            place=RateBudget("PLACE", 15, 12, 3, 30, account_scope),
            modify_cancel=RateBudget("MODIFY_CANCEL", 20, 16, 4, 30, account_scope),
        )

    def consume(self, action_class: str, used_ordinary: int, is_protection: bool) -> None:
        """Validation-only accounting contract (the runtime governor arrives in a
        later stage). Ordinary traffic can NEVER dip into the reserve."""
        budget = self.place if action_class == "PLACE" else self.modify_cancel
        if not is_protection and used_ordinary >= budget.ordinary_budget:
            raise ContractViolation(f"{action_class} ordinary budget exhausted; reserve is protection-only")
        if is_protection and used_ordinary >= budget.ordinary_budget + budget.reserve_budget:
            raise ContractViolation(f"{action_class} provider ceiling would be exceeded — refused even for protection")


# ---------------------------------------------------------------- checkpoint

class CheckpointState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    GREEN_CLOSED = "GREEN_CLOSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"


@dataclass
class RunCheckpoint:
    run_id: str
    architecture_version: str
    program_version: str
    base_sha: str
    branch: str
    current_stage: int
    state: CheckpointState
    last_green_stage: Optional[int] = None
    stage_commits: list = field(default_factory=list)
    drive_artifacts: list = field(default_factory=list)
    pending_operator_actions: list = field(default_factory=list)
    test_summary: str = ""
    failure: Optional[str] = None
    version: int = 1

    def update(self, *, expected_version: int, **changes) -> "RunCheckpoint":
        """Optimistic-versioned, idempotent update. A FAILED checkpoint cannot
        advance without an explicit resume transition."""
        if expected_version != self.version:
            raise ContractViolation(f"optimistic conflict: expected v{expected_version}, have v{self.version}")
        new_state = changes.get("state", self.state)
        if isinstance(new_state, str):
            new_state = CheckpointState(new_state)
            changes["state"] = new_state
        if self.state == CheckpointState.FAILED and new_state not in (CheckpointState.FAILED, CheckpointState.RUNNING):
            raise ContractViolation("FAILED checkpoint cannot advance without explicit resume (state RUNNING first)")
        if self.state == CheckpointState.FAILED and new_state == CheckpointState.RUNNING and not changes.get("resume", False):
            raise ContractViolation("resuming a FAILED run requires resume=True (explicit operator transition)")
        changes.pop("resume", None)
        if new_state == CheckpointState.GREEN_CLOSED:
            unverified = [a for a in changes.get("drive_artifacts", self.drive_artifacts) if not a.get("verified")]
            if unverified:
                raise ContractViolation("GREEN_CLOSED requires every Drive artifact verified")
        for key, value in changes.items():
            if not hasattr(self, key):
                raise ContractViolation(f"unknown checkpoint field {key!r}")
            setattr(self, key, value)
        self.version += 1
        return self


# ---------------------------------------------------------------- drive manifest

@dataclass(frozen=True)
class DriveManifestEntry:
    local_path: str
    github_path: str
    git_ref: str
    sha256: str
    upload_state: str = "PENDING"      # PENDING | UPLOADED | FAILED
    drive_file_id: Optional[str] = None
    verified: bool = False
    retry_count: int = 0
    last_error: Optional[str] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.upload_state not in ("PENDING", "UPLOADED", "FAILED"):
            raise ContractViolation(f"invalid upload_state {self.upload_state!r}")
        if len(self.sha256) != 64:
            raise ContractViolation("sha256 must be a 64-hex digest")
        if self.verified and (self.upload_state != "UPLOADED" or not self.drive_file_id):
            raise ContractViolation("verified requires an UPLOADED state and a Drive file id")


# ---------------------------------------------------------------- litmus report

LITMUS_VERDICTS = ("PASS", "CONDITIONAL_PASS", "FAIL")


@dataclass(frozen=True)
class LitmusReport:
    """Canonical reviewer artifact schema (v3.3 §16J.3 as extended by the
    Stage 1 authorization ruling)."""

    review_id: str
    architecture_version: str
    implementation_sha: str
    reviewer: str
    access_mode_verified: str
    write_attempted: bool
    verdict: str
    blocking_findings: tuple
    nonblocking_findings: tuple
    questions: tuple
    evidence_refs: tuple
    recommended_operator_checks: tuple
    review_hash: str
    completed_at: str

    def __post_init__(self):
        if self.verdict not in LITMUS_VERDICTS:
            raise ContractViolation(f"invalid litmus verdict {self.verdict!r}")
        if self.access_mode_verified != "READ_ONLY":
            raise ContractViolation("litmus reviewer access mode must be READ_ONLY")
        if self.write_attempted:
            raise ContractViolation("a litmus report recording write attempts is invalid evidence")
