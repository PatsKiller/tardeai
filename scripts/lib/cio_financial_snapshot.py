"""
CIO Financial Snapshot Builder — Canonical evidence collection for CIO advisory runs.

Collects deterministic Trade AI evidence across the CIO domain capability matrix.
Each domain returns a typed state: AVAILABLE, STALE, DATA_UNAVAILABLE, or NOT_APPLICABLE.
NEVER fabricates data. NEVER calls external providers.
Produces an immutable snapshot with content hash for provenance.

Evidence domains:
  portfolio, holdings, performance, risk, watch, reentry, rotation,
  income, tax, retirement, fundamentals, technicals, catalysts, macro,
  broker_reconciliation, operator_profile, investment_policy_statement

This module is pure deterministic collection — no model calls, no Telegram.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# Typed evidence states
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_STATES = frozenset({
    "AVAILABLE",
    "STALE",
    "DATA_UNAVAILABLE",
    "NOT_APPLICABLE",
})

CIO_DOMAINS = frozenset({
    "portfolio",
    "holdings",
    "performance",
    "risk",
    "watch",
    "reentry",
    "rotation",
    "income",
    "tax",
    "retirement",
    "fundamentals",
    "technicals",
    "catalysts",
    "macro",
    "broker_reconciliation",
    "operator_profile",
    "investment_policy_statement",
})

# Staleness thresholds per domain (seconds)
STALENESS_THRESHOLDS: dict[str, int] = {
    "portfolio": 86400,       # 24h
    "holdings": 86400,
    "performance": 86400,
    "risk": 86400,
    "watch": 3600,            # 1h
    "reentry": 86400,
    "rotation": 86400,
    "income": 604800,         # 7d
    "tax": 2592000,           # 30d
    "retirement": 2592000,
    "fundamentals": 86400,
    "technicals": 3600,
    "catalysts": 86400,
    "macro": 86400,
    "broker_reconciliation": 172800,  # 2d
    "operator_profile": 604800,
    "investment_policy_statement": 604800,
}


def canonicalize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(data).encode("utf-8")).hexdigest()


class CIOFinancialSnapshot:
    """Immutable financial evidence snapshot for a CIO advisory run."""

    def __init__(
        self,
        snapshot_id: Optional[str] = None,
        observed_at: Optional[str] = None,
    ):
        self.snapshot_id = snapshot_id or str(uuid.uuid4())
        self.observed_at = observed_at or datetime.now(timezone.utc).isoformat()
        self._domains: dict[str, dict[str, Any]] = {}
        self._sealed = False
        self._content_hash: Optional[str] = None

    # ── Domain collectors ──────────────────────────────────────────────────

    def add_domain(
        self,
        domain: str,
        state: str,
        data: Optional[dict[str, Any]] = None,
        source_ref: str = "",
        stale_since: Optional[str] = None,
        gap_reason: str = "",
    ) -> CIOFinancialSnapshot:
        """Add evidence for a domain. Returns self for chaining."""
        if self._sealed:
            raise RuntimeError("Snapshot is sealed — cannot modify")
        if domain not in CIO_DOMAINS:
            raise ValueError(f"Unknown CIO domain: {domain}")
        if state not in EVIDENCE_STATES:
            raise ValueError(f"Invalid evidence state: {state}. Must be one of {sorted(EVIDENCE_STATES)}")

        entry: dict[str, Any] = {
            "domain": domain,
            "state": state,
            "source_ref": source_ref,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

        if stale_since:
            entry["stale_since"] = stale_since

        if gap_reason:
            entry["gap_reason"] = gap_reason

        if state == "DATA_UNAVAILABLE" and not gap_reason:
            entry["gap_reason"] = f"{domain}_data_not_collectable"

        if data is not None:
            entry["data_hash"] = compute_content_hash(data)
            entry["data"] = data

        self._domains[domain] = entry
        return self

    def add_available(
        self,
        domain: str,
        data: dict[str, Any],
        source_ref: str = "",
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with AVAILABLE state."""
        return self.add_domain(domain, "AVAILABLE", data=data, source_ref=source_ref)

    def add_stale(
        self,
        domain: str,
        data: Optional[dict[str, Any]] = None,
        source_ref: str = "",
        stale_since: Optional[str] = None,
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with STALE state."""
        return self.add_domain(domain, "STALE", data=data, source_ref=source_ref, stale_since=stale_since)

    def add_unavailable(
        self,
        domain: str,
        gap_reason: str = "",
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with DATA_UNAVAILABLE state."""
        return self.add_domain(domain, "DATA_UNAVAILABLE", gap_reason=gap_reason)

    def add_not_applicable(self, domain: str) -> CIOFinancialSnapshot:
        """Shorthand: add domain as NOT_APPLICABLE."""
        return self.add_domain(domain, "NOT_APPLICABLE")

    # ── Sealing and hashing ────────────────────────────────────────────────

    def seal(self) -> str:
        """Seal the snapshot and return its content hash."""
        if self._sealed:
            return self._content_hash  # type: ignore[return-value]

        # Content hash is based on domain states only (excludes timestamps)
        # so that same domain states produce the same content hash
        content = {
            "snapshot_id": self.snapshot_id,
            "domains": {
                domain: {
                    "state": entry["state"],
                    "source_ref": entry.get("source_ref", ""),
                    "gap_reason": entry.get("gap_reason", ""),
                    "data_hash": entry.get("data_hash", ""),
                }
                for domain, entry in sorted(self._domains.items())
            },
        }

        self._content_hash = compute_content_hash(content)
        self._sealed = True
        return self._content_hash

    # ── Accessors ──────────────────────────────────────────────────────────

    @property
    def content_hash(self) -> Optional[str]:
        return self._content_hash

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    @property
    def domains(self) -> dict[str, dict[str, Any]]:
        return dict(self._domains)

    def get_domain_state(self, domain: str) -> str:
        entry = self._domains.get(domain)
        if entry is None:
            return "DATA_UNAVAILABLE"
        return entry["state"]

    def available_domains(self) -> set[str]:
        return {d for d, e in self._domains.items() if e["state"] == "AVAILABLE"}

    def stale_domains(self) -> set[str]:
        return {d for d, e in self._domains.items() if e["state"] == "STALE"}

    def unavailable_domains(self) -> set[str]:
        return {d for d, e in self._domains.items() if e["state"] == "DATA_UNAVAILABLE"}

    def not_applicable_domains(self) -> set[str]:
        return {d for d, e in self._domains.items() if e["state"] == "NOT_APPLICABLE"}

    def missing_domains(self, required: set[str]) -> set[str]:
        """Return which required domains are unavailable or missing."""
        missing: set[str] = set()
        for d in required:
            state = self.get_domain_state(d)
            if state in ("DATA_UNAVAILABLE",):
                missing.add(d)
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "observed_at": self.observed_at,
            "content_hash": self._content_hash,
            "sealed": self._sealed,
            "domain_count": len(self._domains),
            "available_count": len(self.available_domains()),
            "stale_count": len(self.stale_domains()),
            "unavailable_count": len(self.unavailable_domains()),
            "not_applicable_count": len(self.not_applicable_domains()),
            "domains": {d: {"state": e["state"], "source_ref": e.get("source_ref", "")}
                       for d, e in sorted(self._domains.items())},
        }

    def to_evidence_record(self) -> dict[str, Any]:
        """Return a summary suitable for attaching to a CIO run event."""
        self.seal()
        return {
            "snapshot_id": self.snapshot_id,
            "observed_at": self.observed_at,
            "content_hash": self._content_hash,
            "available": sorted(self.available_domains()),
            "stale": sorted(self.stale_domains()),
            "unavailable": sorted(self.unavailable_domains()),
            "not_applicable": sorted(self.not_applicable_domains()),
        }

    # ── Builder methods for common collection patterns ────────────────────

    @classmethod
    def from_known_gaps(cls, supported_domains: set[str]) -> CIOFinancialSnapshot:
        """Build a snapshot where known unsupported domains are typed DATA_UNAVAILABLE.

        This is the safe default: any domain we know we can't support is explicitly
        marked unavailable rather than silently omitted.
        """
        snapshot = cls()
        known_gaps = CIO_DOMAINS - supported_domains
        for domain in sorted(known_gaps):
            snapshot.add_unavailable(domain, gap_reason=f"{domain}_not_yet_collected")
        return snapshot


# ═══════════════════════════════════════════════════════════════════════════════
# Deterministic evidence collectors (zero model calls)
# ═══════════════════════════════════════════════════════════════════════════════


def collect_operator_evidence(
    operator_profile: Any,
) -> dict[str, Any]:
    """Collect operator profile and IPS evidence deterministically."""
    result: dict[str, Any] = {
        "profile_version": None,
        "ips_version": None,
        "confirmed_domains": [],
        "profile_hash": None,
    }
    try:
        all_confirmed = operator_profile.get_all_confirmed()
        result["confirmed_domains"] = sorted(all_confirmed.keys())
        result["profile_version"] = operator_profile._version if hasattr(operator_profile, "_version") else None
        result["ips_version"] = operator_profile._ips_version if hasattr(operator_profile, "_ips_version") else None
        if all_confirmed:
            result["profile_hash"] = compute_content_hash(all_confirmed)
    except Exception:
        pass
    return result


def collect_health_evidence(
    health_boundary: Any,
) -> dict[str, Any]:
    """Collect health boundary advisory state deterministically."""
    result: dict[str, Any] = {
        "advisory_state": "UNKNOWN",
        "decision_id": None,
        "category_states": {},
    }
    try:
        if hasattr(health_boundary, "current_advisory_state"):
            result["advisory_state"] = health_boundary.current_advisory_state()
        if hasattr(health_boundary, "latest_decision_id"):
            result["decision_id"] = health_boundary.latest_decision_id()
    except Exception:
        pass
    return result


def collect_action_evidence(
    action_ledger: Any,
    since_hours: int = 168,
) -> dict[str, Any]:
    """Collect recent pending and acknowledged actions."""
    result: dict[str, Any] = {
        "pending_actions": 0,
        "acknowledged_actions": 0,
        "due_followups": 0,
        "total_open": 0,
    }
    try:
        actions = action_ledger.list_actions()
        now = datetime.now(timezone.utc)
        for a in actions:
            status = a.get("current_status", "")
            if status in ("DONE", "EXPIRED", "SUPERSEDED", "CANCELLED"):
                continue
            result["total_open"] += 1
            if status == "ACKNOWLEDGED":
                result["acknowledged_actions"] += 1
            elif status == "OPEN":
                result["pending_actions"] += 1
            next_check = a.get("next_check_at")
            if next_check:
                try:
                    nc = datetime.fromisoformat(next_check)
                    if nc.tzinfo is None:
                        nc = nc.replace(tzinfo=timezone.utc)
                    if nc <= now:
                        result["due_followups"] += 1
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return result


def build_canonical_snapshot(
    *,
    operator_profile: Any = None,
    health_boundary: Any = None,
    action_ledger: Any = None,
    required_domains: Optional[list[str]] = None,
) -> CIOFinancialSnapshot:
    """Build a canonical financial snapshot for a CIO run.

    Collects evidence from all available sources. Marks unsupported domains
    as DATA_UNAVAILABLE rather than fabricating.
    """
    snapshot = CIOFinancialSnapshot()

    supported: set[str] = set()

    if operator_profile is not None:
        profile_ev = collect_operator_evidence(operator_profile)
        snapshot.add_available("operator_profile", profile_ev, source_ref="operator_profile_store")
        snapshot.add_available("investment_policy_statement", profile_ev, source_ref="operator_profile_store")
        supported.update({"operator_profile", "investment_policy_statement"})

    if health_boundary is not None:
        health_ev = collect_health_evidence(health_boundary)
        snapshot.add_available("risk", health_ev, source_ref="health_boundary")
        supported.add("risk")

    if action_ledger is not None:
        action_ev = collect_action_evidence(action_ledger)
        snapshot.add_available("watch", action_ev, source_ref="action_ledger")
        supported.add("watch")

    # Mark all unsupported domains explicitly as DATA_UNAVAILABLE
    known_gaps = CIO_DOMAINS - supported
    for domain in sorted(known_gaps):
        snapshot.add_unavailable(domain, gap_reason=f"{domain}_not_yet_collected_by_snapshot_builder")

    return snapshot
