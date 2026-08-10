"""
CIO Financial Snapshot Builder — Canonical evidence collection for CIO advisory runs.

Collects deterministic Trade AI evidence across the CIO domain capability matrix.
Each domain returns a typed state from EVIDENCE_QUALITY_STATES.
NEVER fabricates data. NEVER calls external providers.
Produces an immutable snapshot with content hash for provenance.

Semantic domains are driven by the canonical cio_domain_capability_registry.
No domain is populated from semantically unrelated evidence.

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

from scripts.lib.cio_domain_evidence import DomainEvidence, ReasonCode

# ═══════════════════════════════════════════════════════════════════════════════
# Typed evidence states (from canonical registry)
# ═══════════════════════════════════════════════════════════════════════════════

EVIDENCE_QUALITY_STATES = frozenset({
    "AVAILABLE",
    "PARTIAL",
    "STALE",
    "DATA_UNAVAILABLE",
    "CONFLICTED",
    "ERROR",
    "NOT_APPLICABLE",
})

# Legacy alias — keep for backward compat with tests that reference EVIDENCE_STATES
EVIDENCE_STATES = EVIDENCE_QUALITY_STATES

# CIO_DOMAINS is now loaded from the canonical registry at module import.
# This frozenset is a compatibility fallback and will be replaced by the registry
# once it is loaded.
_LEGACY_CIO_DOMAINS = frozenset({
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

# Semantic corrections registered by Gate C:
# These domains were populated from the wrong evidence source.
#   - "risk" was health boundary data → corrected to "health_data_quality"
#   - "watch" was action ledger counts → corrected to "open_cio_actions"
#   - "holdings" was the same as "portfolio" in the legacy builder
# Gate-C: semantic corrections are now enforced structurally in build_canonical_snapshot().
# The SEMANTIC_CORRECTION_MAP below is dead code and kept commented for traceability.
# SEMANTIC_CORRECTION_MAP: dict[str, str] = {
#     "risk": "health_data_quality",
#     "watch": "open_cio_actions",
# }

# Gate-C canonical domain set (lazily loaded from registry)
CIO_DOMAINS: frozenset[str] = _LEGACY_CIO_DOMAINS

# Staleness thresholds per domain (seconds) — legacy fallback.
# The canonical source is now the domain capability registry.
# These thresholds are only used when the registry is not yet loaded.
LEGACY_STALENESS_THRESHOLDS: dict[str, int] = {
    "portfolio": 86400,
    "holdings": 86400,
    "performance": 86400,
    "risk": 86400,
    "watch": 3600,
    "reentry": 86400,
    "rotation": 86400,
    "income": 604800,
    "tax": 2592000,
    "retirement": 2592000,
    "fundamentals": 86400,
    "technicals": 3600,
    "catalysts": 86400,
    "macro": 86400,
    "broker_reconciliation": 172800,
    "operator_profile": 604800,
    "investment_policy_statement": 604800,
}

# Compatibility alias
STALENESS_THRESHOLDS = LEGACY_STALENESS_THRESHOLDS


def canonicalize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_payload(data).encode("utf-8")).hexdigest()


# ── Registry lazy-loading ─────────────────────────────────────────────────────

_REGISTRY_LOADED = False


def _lazy_load_registry() -> None:
    """Load the canonical domain registry and update module globals.

    Called once at first snapshot build. Replaces LEGACY_CIO_DOMAINS and
    LEGACY_STALENESS_THRESHOLDS with registry-driven values.
    """
    global CIO_DOMAINS, STALENESS_THRESHOLDS, _REGISTRY_LOADED
    if _REGISTRY_LOADED:
        return
    try:
        from scripts.lib.cio_domain_registry import CIODomainRegistry

        registry = CIODomainRegistry.load()
        CIO_DOMAINS = frozenset(registry.domain_ids)
        STALENESS_THRESHOLDS = registry.freshness_threshold_map()
        _REGISTRY_LOADED = True
    except Exception:
        # Registry may not be available in all test environments.
        # Fall back to legacy values.
        pass


def get_registry():
    """Return the loaded CIODomainRegistry or None if not yet available."""
    try:
        from scripts.lib.cio_domain_registry import CIODomainRegistry
        return CIODomainRegistry.get_instance()
    except (RuntimeError, ImportError):
        return None


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
        error_detail: Optional[dict[str, Any]] = None,
        reason_code: str = "",
        as_of: Optional[str] = None,
        partial_fields: Optional[list[str]] = None,
    ) -> CIOFinancialSnapshot:
        """Add evidence for a domain. Returns self for chaining."""
        if self._sealed:
            raise RuntimeError("Snapshot is sealed — cannot modify")
        if domain not in CIO_DOMAINS:
            raise ValueError(f"Unknown CIO domain: {domain}")
        if state not in EVIDENCE_QUALITY_STATES:
            raise ValueError(
                f"Invalid evidence state: {state}. "
                f"Must be one of {sorted(EVIDENCE_QUALITY_STATES)}"
            )

        entry: dict[str, Any] = {
            "domain": domain,
            "state": state,
            "source_ref": source_ref,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

        if as_of:
            entry["as_of"] = as_of

        if stale_since:
            entry["stale_since"] = stale_since

        if gap_reason:
            entry["gap_reason"] = gap_reason

        if reason_code:
            entry["reason_code"] = reason_code

        if error_detail:
            entry["error_detail"] = error_detail

        if partial_fields:
            entry["partial_fields"] = partial_fields

        if state == "DATA_UNAVAILABLE" and not gap_reason and not reason_code:
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

    def add_partial(
        self,
        domain: str,
        data: dict[str, Any],
        source_ref: str = "",
        partial_fields: Optional[list[str]] = None,
        gap_reason: str = "",
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with PARTIAL state."""
        return self.add_domain(
            domain, "PARTIAL", data=data, source_ref=source_ref,
            partial_fields=partial_fields, gap_reason=gap_reason,
        )

    def add_conflicted(
        self,
        domain: str,
        data: dict[str, Any],
        source_ref: str = "",
        gap_reason: str = "",
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with CONFLICTED state."""
        return self.add_domain(
            domain, "CONFLICTED", data=data, source_ref=source_ref, gap_reason=gap_reason,
        )

    def add_error(
        self,
        domain: str,
        source_ref: str = "",
        reason_code: str = "",
        error_detail: Optional[dict[str, Any]] = None,
    ) -> CIOFinancialSnapshot:
        """Shorthand: add domain with ERROR state."""
        return self.add_domain(
            domain, "ERROR", source_ref=source_ref,
            reason_code=reason_code, error_detail=error_detail,
        )

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
    """Collect operator profile and IPS evidence deterministically.

    Returns a dict with quality_state=AVAILABLE when evidence is successfully
    collected, or quality_state=PARTIAL when the profile store raises.
    No silent except:pass — exceptions produce typed results.
    """
    result: dict[str, Any] = {
        "profile_version": None,
        "ips_version": None,
        "confirmed_domains": [],
        "profile_hash": None,
        "quality_state": "PARTIAL",
    }
    try:
        all_confirmed = operator_profile.get_all_confirmed()
        result["confirmed_domains"] = sorted(all_confirmed.keys())
        result["profile_version"] = operator_profile._version if hasattr(operator_profile, "_version") else None
        result["ips_version"] = operator_profile._ips_version if hasattr(operator_profile, "_ips_version") else None
        if all_confirmed:
            result["profile_hash"] = compute_content_hash(all_confirmed)
        result["quality_state"] = "AVAILABLE"
    except Exception as exc:
        result["quality_state"] = "ERROR"
        result["error_detail"] = {
            "error": str(exc),
            "exception_type": type(exc).__name__,
        }
    return result


def collect_health_evidence(
    health_boundary: Any,
) -> dict[str, Any]:
    """Collect health boundary advisory state deterministically.

    Returns quality_state=AVAILABLE when the health boundary responds,
    PARTIAL when the boundary object exists but method result is unknown,
    ERROR when the boundary raises.
    """
    result: dict[str, Any] = {
        "advisory_state": "UNKNOWN",
        "decision_id": None,
        "category_states": {},
        "quality_state": "PARTIAL",
    }
    try:
        if hasattr(health_boundary, "current_advisory_state"):
            result["advisory_state"] = health_boundary.current_advisory_state()
        if hasattr(health_boundary, "latest_decision_id"):
            result["decision_id"] = health_boundary.latest_decision_id()
        result["quality_state"] = "AVAILABLE"
    except Exception as exc:
        result["quality_state"] = "ERROR"
        result["error_detail"] = {
            "error": str(exc),
            "exception_type": type(exc).__name__,
        }
    return result


def collect_action_evidence(
    action_ledger: Any,
    since_hours: int = 168,
) -> dict[str, Any]:
    """Collect recent pending and acknowledged actions.

    Returns quality_state=AVAILABLE when the ledger responds, ERROR when it
    raises.  Individual action timestamp parse failures are tracked as
    unparseable_count rather than swallowed silently.
    """
    result: dict[str, Any] = {
        "pending_actions": 0,
        "acknowledged_actions": 0,
        "due_followups": 0,
        "total_open": 0,
        "unparseable_timestamps": 0,
        "quality_state": "PARTIAL",
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
                    result["unparseable_timestamps"] += 1
        result["quality_state"] = "AVAILABLE"
    except Exception as exc:
        result["quality_state"] = "ERROR"
        result["error_detail"] = {
            "error": str(exc),
            "exception_type": type(exc).__name__,
        }
    return result


def build_canonical_snapshot(
    *,
    operator_profile: Any = None,
    health_boundary: Any = None,
    action_ledger: Any = None,
    required_domains: Optional[list[str]] = None,
) -> CIOFinancialSnapshot:
    """Build a canonical financial snapshot for a CIO run.

    Collects evidence from all available sources.  Marks unsupported domains
    as DATA_UNAVAILABLE rather than fabricating.

    Gate-C semantic corrections:
      - health_boundary evidence -> "health_data_quality" (was incorrectly "risk")
      - action_ledger evidence -> "open_cio_actions" (was incorrectly "watch")
      - "risk" and "watch_intelligence" are separate unsourced domains

    Gate-C C4:  After building the basic snapshot, the builder iterates over
    the registry and collects evidence from Data Broker adapters for every
    SUPPORTED domain.  BROKEN adapters are marked DATA_UNAVAILABLE.
    Freshness is checked against each domain's registry threshold.
    """
    _lazy_load_registry()
    registry = get_registry()

    snapshot = CIOFinancialSnapshot()
    supported: set[str] = set()

    # ── Basic snapshot: operator, health, actions ────────────────────────
    if operator_profile is not None:
        profile_ev = collect_operator_evidence(operator_profile)
        snapshot.add_available(
            "operator_profile", profile_ev, source_ref="operator_profile_store"
        )
        ips_available = (
            registry is not None and registry.has("investment_policy")
            and registry.get("investment_policy").is_supported
        )
        if ips_available or registry is None:
            snapshot.add_available(
                "investment_policy", profile_ev, source_ref="operator_profile_store"
            )
        supported.update({"operator_profile", "investment_policy"})

    if health_boundary is not None:
        health_ev = collect_health_evidence(health_boundary)
        snapshot.add_available(
            "health_data_quality", health_ev, source_ref="health_boundary"
        )
        supported.add("health_data_quality")

    if action_ledger is not None:
        action_ev = collect_action_evidence(action_ledger)
        snapshot.add_available(
            "open_cio_actions", action_ev, source_ref="action_ledger"
        )
        supported.add("open_cio_actions")

    # ── Gate-C C4:  Registry-driven Data Broker collection ───────────────
    # Build a domain → collector mapping from cio_portfolio._COLLECTORS
    # plus any external adapters referenced by the registry.
    data_broker_collectors: dict[str, Any] = {}
    try:
        from scripts.lib.data_broker.cio_portfolio import _COLLECTORS as _BROKER_COLLECTORS
        # Registry-domain → _COLLECTORS key mapping (handles mismatches)
        _REGISTRY_TO_COLLECTOR_KEY: dict[str, str] = {
            "broker_reconciliation": "reconciliation",
        }
        for reg_domain_id, collector_fn in _BROKER_COLLECTORS.items():
            data_broker_collectors[reg_domain_id] = collector_fn
        # Also register under alias keys
        for reg_key, coll_key in _REGISTRY_TO_COLLECTOR_KEY.items():
            if coll_key in _BROKER_COLLECTORS:
                data_broker_collectors[reg_key] = _BROKER_COLLECTORS[coll_key]
    except ImportError:
        _BROKER_COLLECTORS = {}

    # Try to import external adapters for registry domains not in cio_portfolio
    _EXTERNAL_ADAPTER_MODULES: dict[str, str] = {
        "watch_intelligence": "scripts.lib.data_broker.watch_intelligence",
        "catalysts": "scripts.lib.data_broker.catalyst_record",
        "analyst_actions": "scripts.lib.data_broker.analyst_detail",
        "reentry": "scripts.lib.data_broker.reentry_decision_desk",
    }
    _EXTERNAL_ADAPTER_FUNCTIONS: dict[str, str] = {
        "watch_intelligence": "get_watch_intelligence",
        "catalysts": "get_catalyst_record",
        "analyst_actions": "get_analyst_detail",
        "reentry": "get_reentry_decision_desk",
    }
    for domain_id, module_path in _EXTERNAL_ADAPTER_MODULES.items():
        try:
            mod = __import__(module_path, fromlist=["*"])
            fn_name = _EXTERNAL_ADAPTER_FUNCTIONS.get(domain_id, f"get_{domain_id}")
            fn = getattr(mod, fn_name, None)
            if fn:
                data_broker_collectors[domain_id] = fn
        except (ImportError, AttributeError):
            pass

    # ── Iterate registry: collect SUPPORTED, mark BROKEN/UNSUPPORTED ────
    if registry is not None:
        now = datetime.now(timezone.utc)

        for domain_id in registry.domain_ids:
            if domain_id in supported:
                continue  # Already collected above

            capability = registry.get(domain_id)

            if capability.is_supported:
                collector = data_broker_collectors.get(domain_id)
                if collector is None:
                    # SUPPORTED by registry but no collector found locally
                    snapshot.add_unavailable(
                        domain_id,
                        gap_reason=f"{domain_id}_collector_not_resolved_at_runtime",
                    )
                    continue

                try:
                    result = collector()
                except Exception as exc:
                    snapshot.add_error(
                        domain_id,
                        source_ref=str(capability.canonical_source or ""),
                        reason_code=ReasonCode.COLLECTOR_EXCEPTION,
                        error_detail={"error": str(exc)},
                    )
                    continue

                if isinstance(result, DomainEvidence):
                    evidence = result
                elif isinstance(result, dict):
                    r_state = result.get("quality_state") or result.get("state", "AVAILABLE")
                    r_as_of = result.get("as_of", "")
                    r_source = result.get("source_ref", str(capability.canonical_source or ""))
                    r_data = result.get("data") or result
                    if r_state == "AVAILABLE":
                        evidence = DomainEvidence.available(
                            domain_id, r_data, source_ref=r_source, as_of=r_as_of,
                        )
                    elif r_state == "PARTIAL":
                        evidence = DomainEvidence.partial(
                            domain_id, r_data, source_ref=r_source, as_of=r_as_of,
                            partial_fields=result.get("partial_fields"),
                            gap_reason=result.get("gap_reason", ""),
                        )
                    elif r_state == "DATA_UNAVAILABLE":
                        evidence = DomainEvidence.unavailable(
                            domain_id,
                            reason_code=result.get("reason_code", ReasonCode.SOURCE_FILE_MISSING),
                            source_ref=r_source,
                            gap_reason=result.get("gap_reason", ""),
                        )
                    else:
                        evidence = DomainEvidence.available(
                            domain_id, r_data, source_ref=r_source, as_of=r_as_of,
                        )
                else:
                    snapshot.add_error(
                        domain_id,
                        source_ref=str(capability.canonical_source or ""),
                        reason_code=ReasonCode.COLLECTOR_EXCEPTION,
                        error_detail={"error": f"Unexpected collector return type: {type(result).__name__}"},
                    )
                    continue

                # ── Freshness check ─────────────────────────────────
                quality_state = evidence.quality_state
                stale_since = None
                if quality_state in ("AVAILABLE", "PARTIAL") and evidence.as_of:
                    try:
                        as_of_dt = datetime.fromisoformat(evidence.as_of)
                        if as_of_dt.tzinfo is None:
                            as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
                        age_s = (now - as_of_dt).total_seconds()
                        threshold = capability.freshness_threshold_seconds
                        if age_s > threshold:
                            quality_state = "STALE"
                            stale_since = evidence.as_of
                    except (ValueError, TypeError):
                        pass

                # ── Add domain to snapshot ──────────────────────────
                snapshot.add_domain(
                    domain_id,
                    quality_state,
                    data=evidence.data,
                    source_ref=evidence.source_ref or str(capability.canonical_source or ""),
                    as_of=evidence.as_of,
                    stale_since=stale_since,
                    gap_reason=evidence.gap_reason or "",
                    reason_code=evidence.reason_code or "",
                    partial_fields=evidence.partial_fields,
                )
                supported.add(domain_id)

            elif capability.is_broken:
                snapshot.add_unavailable(
                    domain_id,
                    gap_reason=f"{domain_id}_adapter_is_BROKEN_in_registry",
                )

            else:
                # UNSUPPORTED — no adapter registered
                snapshot.add_unavailable(
                    domain_id,
                    gap_reason=f"{domain_id}_adapter_is_UNSUPPORTED_in_registry",
                )

    # ── For any remaining domains not covered by the registry ────────────
    known_gaps = CIO_DOMAINS - supported
    for domain in sorted(known_gaps):
        snapshot.add_unavailable(
            domain, gap_reason=f"{domain}_not_yet_collected_by_snapshot_builder"
        )

    return snapshot
