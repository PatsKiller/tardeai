"""Active Trader Stage 2 — adapter-neutral broker account discovery core.

READ-ONLY by construction: this module exposes no broker-write method, and the
discovery service cannot reach one. Write capabilities are derived exclusively
from existing adapter fences / repository evidence and are otherwise UNKNOWN —
never probed by calling a write endpoint.

Persistence goes ONLY to the isolated lab database (trade_ai_test); the DSN is
re-validated with the same production-refusing guard as the migration runner.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from active_trader.contracts import (
    ALLOWED_BROKERS, BrokerCapability, CapabilityState, ContractViolation, Environment,
)

# ---------------------------------------------------------------- constants

CAPABILITY_DIMENSIONS = (
    "READ_ACCOUNT", "READ_BALANCES", "READ_POSITIONS", "READ_OPEN_ORDERS",
    "STREAM_ORDER_EVENTS", "PLACE_MARKET_RTH", "PLACE_LIMIT_RTH",
    "PLACE_LIMIT_EXTENDED", "REPLACE_ORDER", "CANCEL_ORDER", "CANCEL_ALL_ACCOUNT",
    "CANCEL_ALL_SYMBOL", "NATIVE_CLOSE_POSITION", "NATIVE_CLOSE_ALL",
    "OPPOSITE_ORDER_CLOSE", "BRACKET_ORDER", "OTO_PROTECTION", "TRAILING_STOP",
    "FRACTIONAL_SHARES", "SHORT_SELL", "MULTI_ACCOUNT", "LIVE_SESSION_UNLOCK",
    "PRETRADE_ESTIMATE", "SYMBOL_TRADABILITY", "ELECTRONIC_ENTRY_ELIGIBILITY",
)

WRITE_CAPABILITIES = frozenset({
    "PLACE_MARKET_RTH", "PLACE_LIMIT_RTH", "PLACE_LIMIT_EXTENDED", "REPLACE_ORDER",
    "CANCEL_ORDER", "CANCEL_ALL_ACCOUNT", "CANCEL_ALL_SYMBOL", "NATIVE_CLOSE_POSITION",
    "NATIVE_CLOSE_ALL", "OPPOSITE_ORDER_CLOSE", "BRACKET_ORDER", "OTO_PROTECTION",
    "TRAILING_STOP", "LIVE_SESSION_UNLOCK",
})

# Stage 2 evidence sources (superset of Stage 1 DB enum where needed; the DB rows
# map RUNTIME_READ_PROBE -> RUNTIME_PROBE and EXISTING_ADAPTER -> DOCUMENTATION-class
# via SOURCE_DB_MAP below, keeping the Stage 1 schema untouched).
EVIDENCE_SOURCES = ("DOCUMENTATION", "RUNTIME_READ_PROBE", "EXISTING_ADAPTER",
                    "BROKER_RESPONSE", "OPERATOR_OVERRIDE")
SOURCE_DB_MAP = {
    "DOCUMENTATION": "DOCUMENTATION",
    "RUNTIME_READ_PROBE": "RUNTIME_PROBE",
    "EXISTING_ADAPTER": "DOCUMENTATION",
    "BROKER_RESPONSE": "BROKER_RESPONSE",
    "OPERATOR_OVERRIDE": "OPERATOR_OVERRIDE",
}

RUNTIME_READ_PROBE_TTL_HOURS = 24        # short-lived, configurable
EXISTING_ADAPTER_REVIEW_DAYS = 30        # or adapter version change


def mask_identifier(raw: Optional[str], keep: int = 4) -> str:
    """Mask any account identifier to '***<last-keep>'. Never returns the input."""
    s = str(raw or "").strip()
    if not s:
        return "***"
    tail = s[-keep:] if len(s) > keep else s[-1:]
    return f"***{tail}"


def evidence_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def make_capability(broker: str, account_label: str, environment: Environment,
                    capability: str, state: CapabilityState, source: str,
                    now: datetime, *, adapter_version: str = "",
                    review_date: Optional[datetime] = None,
                    explicit_expiry: Optional[datetime] = None,
                    ttl_hours: int = RUNTIME_READ_PROBE_TTL_HOURS,
                    note: str = "") -> BrokerCapability:
    """Capability factory enforcing the Stage 2 expiry rules per evidence source."""
    if capability not in CAPABILITY_DIMENSIONS:
        raise ContractViolation(f"unknown capability dimension {capability!r}")
    if source not in EVIDENCE_SOURCES:
        raise ContractViolation(f"unknown evidence source {source!r}")
    if source == "RUNTIME_READ_PROBE":
        expires = now + timedelta(hours=ttl_hours)
    elif source == "EXISTING_ADAPTER":
        if not adapter_version:
            raise ContractViolation("EXISTING_ADAPTER evidence requires an adapter version stamp")
        expires = now + timedelta(days=EXISTING_ADAPTER_REVIEW_DAYS)
    elif source == "DOCUMENTATION":
        if review_date is None:
            raise ContractViolation("DOCUMENTATION evidence requires a review date")
        expires = review_date
    elif source == "OPERATOR_OVERRIDE":
        if explicit_expiry is None:
            raise ContractViolation("OPERATOR_OVERRIDE requires an explicit expiry")
        expires = explicit_expiry
    else:  # BROKER_RESPONSE
        expires = now + timedelta(days=EXISTING_ADAPTER_REVIEW_DAYS)
    if capability in WRITE_CAPABILITIES and source == "RUNTIME_READ_PROBE":
        raise ContractViolation("a write capability can never be evidenced by a read probe")
    return BrokerCapability(
        broker=broker, account_label=account_label, environment=environment,
        capability=capability, state=state,
        source=SOURCE_DB_MAP[source],
        verified_at=now if state != CapabilityState.UNKNOWN else None,
        expires_at=expires)


# ---------------------------------------------------------------- results

@dataclass
class DiscoveredAccount:
    broker: str
    account_label: str
    masked_account_id: str
    environment: str
    account_type: str
    status: str                      # ACTIVE | INACTIVE | NOT_CONFIGURED | ERROR
    read_state: str                  # OK | PARTIAL | UNAVAILABLE
    authentication_state: str        # OK | NOT_CONFIGURED | EXPIRED | ERROR
    capabilities: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    observed_at: str = ""
    expires_at: str = ""
    credential_slot: str = ""
    notes: str = ""

    def __post_init__(self):
        if any(ch.isdigit() for ch in self.masked_account_id[:-4] if ch != "*"):
            raise ContractViolation("masked_account_id retains unmasked leading digits")


@dataclass
class BrokerDiscoveryResult:
    broker: str
    connector_state: str             # AVAILABLE | NOT_INSTALLED | ERROR
    account_discovery: str           # OK | PARTIAL | UNAVAILABLE
    accounts: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    observed_at: str = ""


# ---------------------------------------------------------------- moomoo placeholder

class MoomooDiscovery:
    """Typed placeholder — the SDK/OpenD do not exist on this host (Stage 0 proof).
    Never imports the SDK at module import time; never fails the fleet response."""

    broker = "moomoo"

    def discover(self, now: Optional[datetime] = None) -> BrokerDiscoveryResult:
        now = now or datetime.now(timezone.utc)
        try:
            import importlib.util
            installed = (importlib.util.find_spec("futu") is not None
                         or importlib.util.find_spec("moomoo") is not None)
        except Exception:
            installed = False
        state = "AVAILABLE" if installed else "NOT_INSTALLED"
        return BrokerDiscoveryResult(
            broker="moomoo",
            connector_state=state,
            account_discovery="UNAVAILABLE",
            accounts=[DiscoveredAccount(
                broker="moomoo", account_label="(none)", masked_account_id="***",
                environment=Environment.SHADOW.value, account_type="UNKNOWN",
                status="NOT_CONFIGURED", read_state="UNAVAILABLE",
                authentication_state="NOT_CONFIGURED",
                capabilities=[make_capability(
                    "moomoo", "(none)", Environment.SHADOW, cap, CapabilityState.UNKNOWN,
                    "DOCUMENTATION", now, review_date=now + timedelta(days=90),
                    note="UNSUPPORTED_BY_CURRENT_INSTALLATION")
                    for cap in ("READ_ACCOUNT", "PLACE_LIMIT_RTH", "LIVE_SESSION_UNLOCK")],
                evidence={"connector_state": state,
                          "note": "Stage 5 owns installation; recorded for operator visibility"},
                observed_at=now.isoformat(), notes="OpenD/SDK not installed"),
            ],
            errors=[] if not installed else ["unexpected: moomoo SDK present before Stage 5"],
            observed_at=now.isoformat())


# ---------------------------------------------------------------- projection

DISCREPANCY_KINDS = (
    "configured_but_not_returned_by_broker", "returned_by_broker_but_not_configured",
    "account_label_mismatch", "paper_live_mismatch", "read_only_mismatch",
    "execution_built_mismatch", "missing_account_mapping", "expired_authentication",
    "duplicate_account_mapping",
)


def build_projection(configured: list[dict], results: list[BrokerDiscoveryResult]) -> dict:
    """Join configured registry rows with live discovery. Never repairs anything —
    reports discrepancies for the operator. The existing account source of truth
    is untouched."""
    discovered = {}
    discrepancies = []
    for res in results:
        for acct in res.accounts:
            if acct.status == "NOT_CONFIGURED" and acct.broker == "moomoo":
                continue
            key = (acct.broker, acct.account_label)
            if key in discovered:
                discrepancies.append({"kind": "duplicate_account_mapping",
                                      "broker": acct.broker, "account_label": acct.account_label})
            discovered[key] = acct

    conf_index = {}
    for row in configured:
        key = (row.get("broker"), row.get("account_key") or row.get("account_label"))
        if key in conf_index:
            discrepancies.append({"kind": "duplicate_account_mapping", "broker": key[0],
                                  "account_label": key[1], "side": "config"})
        conf_index[key] = row

    for key, row in conf_index.items():
        broker, label = key
        if broker not in ALLOWED_BROKERS:
            continue  # excluded brokers stay in inventory but outside the v1 plane
        acct = discovered.get(key)
        if acct is None:
            discrepancies.append({"kind": "configured_but_not_returned_by_broker",
                                  "broker": broker, "account_label": label,
                                  "configured_active": bool(row.get("active"))})
            continue
        if acct.authentication_state == "EXPIRED":
            discrepancies.append({"kind": "expired_authentication", "broker": broker,
                                  "account_label": label})
        conf_paper = (row.get("account_id") == "paper" or row.get("type") == "paper"
                      or "paper" in str(row.get("account_key", "")))
        live_env = acct.environment == Environment.LIVE.value
        if conf_paper and live_env:
            discrepancies.append({"kind": "paper_live_mismatch", "broker": broker,
                                  "account_label": label})
        if bool(row.get("read_only")) and any(
                c.state == CapabilityState.SUPPORTED and c.capability in WRITE_CAPABILITIES
                for c in acct.capabilities):
            discrepancies.append({"kind": "read_only_mismatch", "broker": broker,
                                  "account_label": label})
        if row.get("execution_built") is False and any(
                c.state == CapabilityState.SUPPORTED and c.capability in WRITE_CAPABILITIES
                for c in acct.capabilities):
            discrepancies.append({"kind": "execution_built_mismatch", "broker": broker,
                                  "account_label": label})

    for key, acct in discovered.items():
        if key not in conf_index and acct.broker in ALLOWED_BROKERS:
            kind = ("missing_account_mapping" if acct.status == "NEEDS_MAPPING"
                    else "returned_by_broker_but_not_configured")
            discrepancies.append({"kind": kind, "broker": acct.broker,
                                  "account_label": acct.account_label,
                                  "masked_account_id": acct.masked_account_id})

    return {
        "accounts": [asdict(a) | {"capabilities": [
            {"capability": c.capability, "state": c.state.value, "source": c.source,
             "verified_at": c.verified_at.isoformat() if c.verified_at else None,
             "expires_at": c.expires_at.isoformat() if c.expires_at else None}
            for c in a.capabilities]} for a in discovered.values()],
        "discrepancies": discrepancies,
    }


# ---------------------------------------------------------------- lab persistence

def persist_capabilities(dsn: str, results: list[BrokerDiscoveryResult],
                         now: Optional[datetime] = None) -> int:
    """Idempotent upsert of capability rows into the LAB database only."""
    from active_trader.migrate import _resolve_dsn  # reuse the production-refusing guard
    import os
    os.environ.setdefault("ACTIVE_TRADER_TEST_DATABASE_DSN", dsn)
    checked = _resolve_dsn(dsn)
    import psycopg2
    now = now or datetime.now(timezone.utc)
    conn = psycopg2.connect(checked)
    conn.autocommit = False
    written = 0
    try:
        cur = conn.cursor()
        for res in results:
            for acct in res.accounts:
                for cap in acct.capabilities:
                    ev = evidence_hash({"broker": cap.broker, "account": cap.account_label,
                                        "cap": cap.capability, "state": cap.state.value,
                                        "source": cap.source, "observed": acct.observed_at})
                    cur.execute(
                        """INSERT INTO broker_account_capabilities
                               (broker, account_label, environment, capability, state, source,
                                verified_at, expires_at, adapter_version, evidence_ref, notes, updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (broker, account_label, environment, capability)
                           DO UPDATE SET state = EXCLUDED.state, source = EXCLUDED.source,
                                verified_at = EXCLUDED.verified_at, expires_at = EXCLUDED.expires_at,
                                adapter_version = EXCLUDED.adapter_version,
                                evidence_ref = EXCLUDED.evidence_ref, notes = EXCLUDED.notes,
                                updated_at = EXCLUDED.updated_at""",
                        (cap.broker, cap.account_label,
                         cap.environment.value if isinstance(cap.environment, Environment) else cap.environment,
                         cap.capability, cap.state.value, cap.source, cap.verified_at,
                         cap.expires_at, "stage2", ev, acct.notes[:200], now))
                    written += 1
        conn.commit()
        return written
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
