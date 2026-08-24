"""MemoryIdentity@v1 + MemoryFact@v2 — bitemporal, closed-open intervals.

Persistence layer assigns transaction time. LLMs must not author authoritative dates.
subject_guid maps to existing issuer/security/listing/entity GUIDs — ticker is alias only.
SHADOW in-memory store. Production writers are not cut over.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from scripts.lib.memory_namespace import DEFAULT_TENANT, require_tenant
from scripts.lib.security_identity import issuer_guid, listing_guid, normalize_symbol, security_guid

AUTHORITY = "READ_ONLY_ADVISORY"
IDENTITY_SCHEMA = "MemoryIdentity@v1"
FACT_SCHEMA = "MemoryFact@v2"
OPEN_END = "9999-12-31T23:59:59+00:00"

STATUSES = (
    "CANDIDATE",
    "CONFIRMED",
    "DISPUTED",
    "SUPERSEDED",
    "EXPIRED",
    "RETRACTED",
    "QUARANTINED",
)

AS_KNOWN_NOW = "AS_KNOWN_NOW"
AS_KNOWN_AT = "AS_KNOWN_AT"
VALID_AT = "VALID_AT"
VALID_AT_AND_KNOWN_AT = "VALID_AT_AND_KNOWN_AT"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse(ts: str) -> datetime:
    t = str(ts)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)


def in_interval(ts: str, start: str, end: str | None) -> bool:
    """Closed-open: start <= ts < end. Missing end is unbounded."""
    x = _parse(ts)
    a = _parse(start)
    if x < a:
        return False
    if not end:
        return True
    return x < _parse(end)


def memory_identity(*, subject_guid: str, predicate: str, tenant_id: str = DEFAULT_TENANT) -> str:
    require_tenant(tenant_id)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:memory:{tenant_id}:{subject_guid}:{predicate}"))


def subject_from_security(*, symbol: str | None = None, cik: str | None = None, company: str | None = None, exchange: str | None = None) -> dict[str, str | None]:
    """Reuse security identity v2. Never mint a second SCHD identity."""
    iss = issuer_guid(cik=cik, company=company)
    sec = security_guid(issuer=iss, share_class="common") if iss else None
    lst = listing_guid(security=sec, exchange=exchange or "US", symbol=symbol) if sec and symbol else None
    alias = str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:ticker:{normalize_symbol(symbol)}")) if symbol else None
    return {
        "issuer_guid": iss,
        "security_guid": sec,
        "listing_guid": lst,
        "ticker_alias_guid": alias,
        "subject_guid": sec or iss or alias,
    }


def build_fact(
    *,
    tenant_id: str,
    namespace: str,
    subject_guid: str,
    predicate: str,
    value: Any,
    category: str,
    valid_from: str,
    valid_to: str | None = None,
    status: str = "CANDIDATE",
    confidence: str = "low",
    source_type: str,
    source_id: str,
    source_as_of: str,
    asserted_by: str,
    trace_id: str | None = None,
    evidence_refs: list[str] | None = None,
    contradiction_refs: list[str] | None = None,
    embedding_ref: str | None = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    require_tenant(tenant_id)
    if status not in STATUSES:
        raise RuntimeError("UNKNOWN_MEMORY_STATUS")
    mid = memory_id or memory_identity(subject_guid=subject_guid, predicate=predicate, tenant_id=tenant_id)
    return {
        "schema": FACT_SCHEMA,
        "memory_id": mid,
        "memory_version_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "namespace": namespace,
        "subject_guid": subject_guid,
        "predicate": predicate,
        "object": value,
        "category": category,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "tx_from": None,  # assigned by store
        "tx_to": None,
        "status": status,
        "confidence": confidence,
        "source_type": source_type,
        "source_id": source_id,
        "source_as_of": source_as_of,
        "asserted_by": asserted_by,
        "trace_id": trace_id,
        "evidence_refs": list(evidence_refs or []),
        "contradiction_refs": list(contradiction_refs or []),
        "embedding_ref": embedding_ref,
        "created_at": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "non_authoritative_context": True,
    }


class MemoryFactStore:
    """In-memory SHADOW. Transaction time assigned here. Not a production writer."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def write(self, fact: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
        require_tenant(fact.get("tenant_id"))
        ts = now or _now()
        row = dict(fact)
        if row.get("tx_from"):
            raise RuntimeError("TX_TIME_RESERVED_FOR_PERSISTENCE_LAYER")
        # close prior version of same memory_id still open in tx time
        for prev in self._rows:
            if prev["memory_id"] == row["memory_id"] and prev["tenant_id"] == row["tenant_id"] and prev.get("tx_to") is None:
                prev["tx_to"] = ts
                if row.get("status") == "CONFIRMED":
                    prev["status"] = prev["status"] if prev["status"] in ("RETRACTED", "EXPIRED") else "SUPERSEDED"
        row["tx_from"] = ts
        row["tx_to"] = None
        self._rows.append(row)
        return row

    def query(
        self,
        *,
        tenant_id: str,
        mode: str,
        valid_at: str | None = None,
        tx_at: str | None = None,
        subject_guid: str | None = None,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        require_tenant(tenant_id)
        now = _now()
        if mode == AS_KNOWN_NOW:
            tx_at = now
            valid_at = now
        elif mode == AS_KNOWN_AT:
            if not tx_at:
                raise RuntimeError("TX_AT_REQUIRED")
        elif mode == VALID_AT:
            if not valid_at:
                raise RuntimeError("VALID_AT_REQUIRED")
            tx_at = now
        elif mode == VALID_AT_AND_KNOWN_AT:
            if not valid_at or not tx_at:
                raise RuntimeError("VALID_AND_TX_REQUIRED")
        else:
            raise RuntimeError("UNKNOWN_QUERY_MODE")
        out = []
        for row in self._rows:
            if row["tenant_id"] != tenant_id:
                continue
            if subject_guid and row["subject_guid"] != subject_guid:
                continue
            if namespace and row["namespace"] != namespace:
                continue
            if not in_interval(tx_at, row["tx_from"], row.get("tx_to")):
                continue
            if valid_at and not in_interval(valid_at, row["valid_from"], row.get("valid_to")):
                continue
            out.append(row)
        return out
