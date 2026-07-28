"""Active Trader P4 — broker capability layer (pure, read-only; NO orders, NO send).

Every routing/execution decision in this program must be gated on *verified*
capability, never on a UI label. This module turns a capability **snapshot / fixture**
(never a live broker call) into a typed :class:`CapabilityRecord` per account and answers
one question deterministically: *is this account execution-eligible right now?*

Hard rules encoded here (each one is a fail-closed default):

  1. Capability is NEVER inferred from a UI label. Only an explicit ``capabilities``
     evidence block backed by an ``evidence_source`` counts. A "Trading Enabled" badge
     with no evidence block is treated as UNKNOWN.
  2. UNKNOWN capability FAILS CLOSED — ``trade_capability`` is False and the account is
     not execution-eligible.
  3. EXPIRED verification (now past ``expires_at``) FAILS CLOSED the same way.
  4. Thinkorswim / any ``manual`` environment is a manual handoff ONLY — never routable,
     never execution-eligible.
  5. ``data_plane`` accounts (e.g. the Moomoo L2/tape role) are read-only — never tradeable.
  6. In THIS build, ``live`` environments are never execution-eligible. Only ``paper`` can be.

PURE: takes ``(account_id, snapshot)`` and returns a record. No I/O, no network, no
broker client, no order, no send. Deterministic given the same snapshot + ``now``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

CONTRACT = "active-trader-broker-capabilities-v1"

# ── brokers ────────────────────────────────────────────────────────────────────
BROKER_ALPACA = "alpaca"
BROKER_MOOMOO = "moomoo"
BROKER_SCHWAB = "schwab"
BROKER_TOS = "thinkorswim"  # manual handoff ONLY — never routable

# ── environments ───────────────────────────────────────────────────────────────
ENV_PAPER = "paper"
ENV_LIVE = "live"
ENV_DATA_PLANE = "data_plane"
ENV_MANUAL = "manual"
KNOWN_ENVS = (ENV_PAPER, ENV_LIVE, ENV_DATA_PLANE, ENV_MANUAL)

ENV_UNKNOWN = "unknown"

# ── eligibility reasons ────────────────────────────────────────────────────────
REASON_VERIFIED = "verified"
REASON_UNKNOWN = "unknown_capability_fail_closed"
REASON_ACCOUNT_MISSING = "account_not_in_snapshot"
REASON_EXPIRED = "verification_expired"
REASON_MANUAL = "manual_handoff_only"
REASON_DATA_PLANE = "data_plane_read_only"
REASON_LIVE_BLOCKED = "live_not_execution_eligible_this_build"


@dataclass(frozen=True)
class CapabilityRecord:
    broker: str
    account_id: str
    environment: str
    account_type: str
    read_capability: bool
    trade_capability: bool
    session_capability: bool
    order_type_capability: tuple[str, ...]
    replace_cancel_capability: bool
    protection_capability: bool
    verified_at: Optional[float]
    expires_at: Optional[float]
    verification_fresh: bool
    routable: bool
    evidence_source: str
    eligibility_reason: str
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["order_type_capability"] = list(self.order_type_capability)
        return d


# ── helpers ────────────────────────────────────────────────────────────────────

def _s(v: Any) -> str:
    return str(v or "").strip()


def _norm(v: Any) -> str:
    return _s(v).lower()


def _ts(v: Any) -> Optional[float]:
    """Parse an epoch (int/float) or ISO-8601 string into epoch seconds. None on failure."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def _resolve_now(now: Any, snapshot: Mapping[str, Any]) -> Optional[float]:
    n = _ts(now)
    if n is not None:
        return n
    if isinstance(snapshot, Mapping):
        return _ts(snapshot.get("now"))
    return None


def _norm_order_types(v: Any) -> tuple[str, ...]:
    if not v:
        return ()
    if isinstance(v, str):
        v = [v]
    out: list[str] = []
    for item in v:
        t = _norm(item)
        # MARKET is intentionally dropped — this program is price-controlled only.
        if t and t != "market" and t not in out:
            out.append(t)
    return tuple(out)


def _unknown_record(
    account_id: str,
    *,
    broker: str = "",
    environment: str = ENV_UNKNOWN,
    account_type: str = "unknown",
    evidence_source: str = "",
    reason: str = REASON_UNKNOWN,
) -> CapabilityRecord:
    """Fail-closed skeleton: no trade authority, nothing fresh, nothing routable."""
    return CapabilityRecord(
        broker=broker,
        account_id=str(account_id),
        environment=environment,
        account_type=account_type,
        read_capability=False,
        trade_capability=False,
        session_capability=False,
        order_type_capability=(),
        replace_cancel_capability=False,
        protection_capability=False,
        verified_at=None,
        expires_at=None,
        verification_fresh=False,
        routable=False,
        evidence_source=evidence_source,
        eligibility_reason=reason,
    )


def resolve_capability(
    account_id: str,
    snapshot: Mapping[str, Any] | None,
    *,
    now: Any = None,
) -> CapabilityRecord:
    """Resolve one account's capability record from a snapshot/fixture. Never calls a broker.

    Fails closed to an UNKNOWN record (trade_capability=False) whenever the account is
    absent, has no evidence-backed ``capabilities`` block, or its verification is expired.
    """
    if not isinstance(snapshot, Mapping) or not snapshot:
        return _unknown_record(account_id, reason=REASON_ACCOUNT_MISSING)

    accounts = snapshot.get("accounts")
    accounts = accounts if isinstance(accounts, Mapping) else {}
    raw = accounts.get(account_id)
    if not isinstance(raw, Mapping):
        return _unknown_record(account_id, reason=REASON_ACCOUNT_MISSING)

    broker = _norm(raw.get("broker"))
    env = _norm(raw.get("environment")) or ENV_UNKNOWN
    account_type = _s(raw.get("account_type")) or "unknown"
    evidence_source = _s(raw.get("evidence_source"))
    verified_at = _ts(raw.get("verified_at"))
    expires_at = _ts(raw.get("expires_at"))

    # Rule 1: capability is NEVER inferred from a UI label. Require an explicit,
    # evidence-sourced capabilities block. A `ui_label` / `label` alone is ignored.
    caps = raw.get("capabilities")
    if not isinstance(caps, Mapping) or not evidence_source:
        return _unknown_record(
            account_id,
            broker=broker,
            environment=env if env in KNOWN_ENVS else ENV_UNKNOWN,
            account_type=account_type,
            evidence_source=evidence_source,
            reason=REASON_UNKNOWN,
        )

    now_ts = _resolve_now(now, snapshot)
    is_expired = (
        expires_at is None
        or now_ts is None
        or verified_at is None
        or now_ts > expires_at
    )
    verification_fresh = not is_expired

    # Rule 4: manual / Thinkorswim is never routable.
    routable = env != ENV_MANUAL and broker != BROKER_TOS

    read_capability = bool(caps.get("read"))
    session_capability = bool(caps.get("session"))
    order_types = _norm_order_types(caps.get("order_types"))
    replace_cancel = bool(caps.get("replace_cancel"))
    protection = bool(caps.get("protection"))
    trade_capability = bool(caps.get("trade"))

    reason = REASON_VERIFIED
    if not routable:
        # Rule 4 dominates: manual handoff only.
        trade_capability = False
        reason = REASON_MANUAL
    elif env == ENV_DATA_PLANE:
        # Rule 5: data plane is read-only.
        trade_capability = False
        reason = REASON_DATA_PLANE
    elif is_expired:
        # Rule 3: expired verification fails closed.
        trade_capability = False
        reason = REASON_EXPIRED
    elif env == ENV_LIVE:
        # Rule 6: live carries broker trade capability but is not eligible in this build.
        reason = REASON_LIVE_BLOCKED

    return CapabilityRecord(
        broker=broker,
        account_id=str(account_id),
        environment=env,
        account_type=account_type,
        read_capability=read_capability,
        trade_capability=trade_capability,
        session_capability=session_capability,
        order_type_capability=order_types,
        replace_cancel_capability=replace_cancel,
        protection_capability=protection,
        verified_at=verified_at,
        expires_at=expires_at,
        verification_fresh=verification_fresh,
        routable=routable,
        evidence_source=evidence_source,
        eligibility_reason=reason,
    )


def supports_price_controlled(cap: CapabilityRecord) -> bool:
    """True only if the account can place a price-controlled (limit) entry."""
    return isinstance(cap, CapabilityRecord) and "limit" in cap.order_type_capability


def is_execution_eligible(cap: CapabilityRecord) -> bool:
    """True ONLY for a paper account with fresh verification and trade+protection capability.

    Live / data_plane / manual environments and any UNKNOWN or expired record fail closed.
    This is the single authority the execution path consults; it never routes or sends.
    """
    if not isinstance(cap, CapabilityRecord):
        return False
    return (
        cap.environment == ENV_PAPER   # Rule 6: only paper can be eligible in this build
        and cap.routable
        and cap.verification_fresh     # Rule 3: expired fails closed
        and cap.trade_capability       # Rule 2: unknown fails closed
        and cap.protection_capability
        and cap.read_capability
    )
