"""Active Trader Stage 7 — dev/test-only session builder.

Pure domain logic for building, versioning, cloning, and validating session drafts,
account roles, sizing/quick-add, and dev feature-control changes. No 2FA, no order,
no broker call, no production write. Canonical deterministic draft hash over the
authority-bearing fields. Persistence (Stage 7 dev write plane) targets trade_ai_test
only via the guarded DSN.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from active_trader.contracts import (
    ALLOWED_BROKERS, ContractViolation, Environment, FlagMode, FLAG_REGISTRY,
)

QUICK_ADD_PRESETS = (100, 200, 500, 1000)


class AccountRole(str, Enum):
    PRIMARY = "PRIMARY"
    FALLBACK = "FALLBACK"
    DISABLED = "DISABLED"


class SizingMode(str, Enum):
    SHARES = "SHARES"
    DOLLAR_NOTIONAL = "DOLLAR_NOTIONAL"
    RISK_BASED = "RISK_BASED"


class QuickAddUnit(str, Enum):
    SHARES = "SHARES"
    DOLLARS = "DOLLARS"


# authority-bearing fields — ONLY these enter the canonical hash
AUTHORITY_FIELDS = (
    "environment", "start", "end", "entry_cutoff", "symbol_policy", "account_roles",
    "quantity_policy", "gross_notional_cap", "per_symbol_caps", "per_account_caps",
    "risk_cap", "trade_count_cap", "daily_loss_cap", "fallback_policy",
    "quick_add_config", "runner_policy", "feature_policy_versions",
)


@dataclass
class AccountSelection:
    broker: str
    account_label: str
    role: AccountRole
    capability_state: str = "UNKNOWN"     # SUPPORTED/UNSUPPORTED/UNKNOWN/RESTRICTED/DEGRADED
    per_account_shares: Optional[float] = None
    per_account_notional: Optional[float] = None
    per_account_risk: Optional[float] = None
    allocation_weight: Optional[float] = None

    def __post_init__(self):
        if self.broker not in ALLOWED_BROKERS:
            raise ContractViolation(f"broker {self.broker!r} outside v1 scope")
        if not isinstance(self.role, AccountRole):
            self.role = AccountRole(self.role)
        # a required-write capability that is UNSUPPORTED/UNKNOWN cannot be PRIMARY/FALLBACK
        if self.role in (AccountRole.PRIMARY, AccountRole.FALLBACK) \
                and self.capability_state in ("UNSUPPORTED", "UNKNOWN"):
            raise ContractViolation(
                f"account {self.broker}/{self.account_label} capability {self.capability_state} "
                "cannot be selected for live activity")


@dataclass
class SessionDraftV2:
    """Editable dev draft. Editing bumps draft_version; the authorized version is
    immutable (enforced by the Stage 1 append-only table + this hash)."""

    draft_id: str
    draft_version: int
    environment: Environment
    session_name: str
    start: str
    end: str
    entry_cutoff: str
    symbol_policy: dict
    account_roles: list                 # list[AccountSelection]
    quantity_policy: dict               # {mode, ...}
    gross_notional_cap: float
    per_symbol_caps: dict
    per_account_caps: dict
    risk_cap: float
    trade_count_cap: int
    daily_loss_cap: float
    fallback_policy: dict
    quick_add_config: dict
    runner_policy: dict
    feature_policy_versions: dict
    created_by: str
    notes: str = ""

    def __post_init__(self):
        env = Environment.parse(self.environment)
        self.environment = env
        if self.draft_version < 1:
            raise ContractViolation("draft_version must be >= 1")
        # Moomoo can never be selected for live activity (data-only; credential-gate blocked)
        for acc in self.account_roles:
            sel = acc if isinstance(acc, AccountSelection) else AccountSelection(**acc)
            if sel.broker == "moomoo" and sel.role != AccountRole.DISABLED and env == Environment.LIVE:
                raise ContractViolation("moomoo cannot be selected for LIVE activity")
        for cap in (self.gross_notional_cap, self.risk_cap, self.daily_loss_cap):
            if cap < 0:
                raise ContractViolation("caps must be non-negative")
        if self.trade_count_cap < 0:
            raise ContractViolation("trade_count_cap must be non-negative")
        self._validate_quick_add()

    def _validate_quick_add(self):
        qa = self.quick_add_config or {}
        unit = qa.get("unit", "SHARES")
        if unit not in ("SHARES", "DOLLARS"):
            raise ContractViolation(f"quick-add unit {unit!r} invalid")
        presets = qa.get("presets", list(QUICK_ADD_PRESETS))
        if any((not isinstance(p, (int, float)) or p <= 0) for p in presets):
            raise ContractViolation("quick-add presets must be positive")

    def _authority_payload(self) -> dict:
        def _acc(a):
            s = a if isinstance(a, AccountSelection) else AccountSelection(**a)
            return {"broker": s.broker, "account_label": s.account_label, "role": s.role.value,
                    "per_account_shares": s.per_account_shares,
                    "per_account_notional": s.per_account_notional,
                    "per_account_risk": s.per_account_risk, "allocation_weight": s.allocation_weight}
        return {
            "environment": self.environment.value, "start": self.start, "end": self.end,
            "entry_cutoff": self.entry_cutoff, "symbol_policy": self.symbol_policy,
            "account_roles": sorted([_acc(a) for a in self.account_roles],
                                    key=lambda x: (x["broker"], x["account_label"])),
            "quantity_policy": self.quantity_policy, "gross_notional_cap": self.gross_notional_cap,
            "per_symbol_caps": self.per_symbol_caps, "per_account_caps": self.per_account_caps,
            "risk_cap": self.risk_cap, "trade_count_cap": self.trade_count_cap,
            "daily_loss_cap": self.daily_loss_cap, "fallback_policy": self.fallback_policy,
            "quick_add_config": self.quick_add_config, "runner_policy": self.runner_policy,
            "feature_policy_versions": self.feature_policy_versions,
        }

    @property
    def hash(self) -> str:
        """Canonical deterministic versioned hash over authority-bearing fields ONLY.
        session_name/notes/created_by are NOT authority-bearing → do not change the hash."""
        canon = json.dumps(self._authority_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    def clone(self, new_id: str, created_by: str) -> "SessionDraftV2":
        d = asdict(self)
        d["draft_id"] = new_id
        d["draft_version"] = 1
        d["created_by"] = created_by
        d["environment"] = self.environment.value
        d["account_roles"] = [
            (a if isinstance(a, dict) else asdict(a)) for a in self.account_roles]
        return SessionDraftV2(**d)

    def edit(self, **changes) -> "SessionDraftV2":
        """Editing produces a NEW version (immutability of prior versions)."""
        d = asdict(self)
        d.update(changes)
        d["draft_version"] = self.draft_version + 1
        d["environment"] = changes.get("environment", self.environment.value) \
            if not isinstance(changes.get("environment"), Environment) \
            else changes["environment"].value
        d["account_roles"] = [
            (a if isinstance(a, dict) else asdict(a)) for a in d["account_roles"]]
        return SessionDraftV2(**d)


# ---------------------------------------------------------------- sizing

def compute_sizing(mode: SizingMode, *, requested_shares: Optional[float] = None,
                   notional: Optional[float] = None, price: Optional[float] = None,
                   risk_dollars: Optional[float] = None, per_share_risk: Optional[float] = None,
                   allow_fractions: bool = False) -> dict:
    """Deterministic sizing. Rounds DOWN to whole shares unless fractions allowed;
    surfaces remainder; validates inputs. No order — pure arithmetic."""
    if mode is SizingMode.SHARES:
        if requested_shares is None or requested_shares < 0:
            raise ContractViolation("SHARES mode needs a non-negative share count")
        shares = requested_shares
    elif mode is SizingMode.DOLLAR_NOTIONAL:
        if not price or price <= 0 or notional is None or notional < 0:
            raise ContractViolation("DOLLAR_NOTIONAL needs positive price and non-negative notional")
        shares = notional / price
    elif mode is SizingMode.RISK_BASED:
        if not per_share_risk or per_share_risk <= 0 or risk_dollars is None or risk_dollars < 0:
            raise ContractViolation("RISK_BASED needs positive per-share risk and non-negative risk budget")
        shares = risk_dollars / per_share_risk
    else:
        raise ContractViolation(f"unknown sizing mode {mode!r}")
    whole = shares if allow_fractions else float(int(shares))
    remainder = round(shares - whole, 6)
    return {"mode": mode.value, "shares": round(whole, 6), "remainder": remainder,
            "estimated_notional": round(whole * price, 4) if price else None}


def validate_quick_add(preset: float, unit: QuickAddUnit, *, price: Optional[float],
                       per_share_risk: Optional[float], caps: dict) -> dict:
    """Quick-add uses the same sizing/cap validation as normal entry. No order."""
    if preset <= 0:
        raise ContractViolation("quick-add increment must be positive")
    if unit is QuickAddUnit.SHARES:
        sizing = compute_sizing(SizingMode.SHARES, requested_shares=preset, price=price)
    else:
        sizing = compute_sizing(SizingMode.DOLLAR_NOTIONAL, notional=preset, price=price)
    shares = sizing["shares"]
    notional = (shares * price) if price else None
    violations = []
    if caps.get("max_shares") is not None and shares > caps["max_shares"]:
        violations.append("exceeds per-account share cap")
    if notional is not None and caps.get("max_notional") is not None and notional > caps["max_notional"]:
        violations.append("exceeds notional cap")
    if caps.get("gross_notional_remaining") is not None and notional is not None \
            and notional > caps["gross_notional_remaining"]:
        violations.append("exceeds session gross notional")
    return {"shares": shares, "notional": notional, "blocked": bool(violations),
            "violations": violations}


# ---------------------------------------------------------------- feature controls

DEV_ALLOWED_MODES = (FlagMode.OFF, FlagMode.READ_ONLY, FlagMode.SHADOW, FlagMode.SIMULATION)


def validate_feature_change(flag_name: str, mode: FlagMode) -> None:
    """Dev feature-control update. LIVE_CANARY is rejected; flags can never authorize
    or enlarge authority (that lives only in the signed authorization)."""
    if flag_name not in FLAG_REGISTRY:
        raise ContractViolation(f"unknown feature flag {flag_name!r}")
    if not isinstance(mode, FlagMode):
        raise ContractViolation("mode must be a FlagMode")
    if mode is FlagMode.LIVE_CANARY:
        raise ContractViolation("LIVE_CANARY cannot be set via the dev feature-control plane")
    if mode not in DEV_ALLOWED_MODES:
        raise ContractViolation(f"mode {mode} not permitted in dev plane")
