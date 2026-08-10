"""
CIO Domain Capability Registry — Single authoritative loader for domain definitions.

Reads config/cio_domain_capability_registry.json and provides typed access to
source authority, adapter state, freshness policy, materiality policy, and
run-purpose evidence requirements.

The registry is the single source of truth. No module should maintain its own
independent domain lists or domain-to-agent mappings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ── Registry value types ──────────────────────────────────────────────────────

AUTHORITY_CLASSES = frozenset({
    "AUTHORITATIVE_POLICY",
    "AUTHORITATIVE_ACCOUNT_STATE",
    "AUTHORITATIVE_INTERNAL_RECORD",
    "EXTERNAL_MARKET_DATA",
    "DERIVED_VALID",
    "NON_AUTHORITATIVE_REFERENCE",
})

ADAPTER_STATES = frozenset({
    "SUPPORTED",
    "UNSUPPORTED",
    "BROKEN",
    "DEPRECATED",
})

EVIDENCE_QUALITY_STATES = frozenset({
    "AVAILABLE",
    "PARTIAL",
    "STALE",
    "DATA_UNAVAILABLE",
    "CONFLICTED",
    "ERROR",
    "NOT_APPLICABLE",
})

VALID_RUN_PURPOSES = frozenset({
    "PORTFOLIO_ALLOCATION_REVIEW",
    "RISK_OR_STOP_EVENT",
    "WATCH_OR_CATALYST_REVIEW",
    "TAX_REVIEW",
    "INCOME_REVIEW",
    "RETIREMENT_REVIEW",
    "BROKER_RECONCILIATION",
    "SCHEDULED_CIO_BRIEF",
    "OPERATOR_REQUEST",
})


@dataclass
class DomainCapability:
    """Typed view of a single domain from the capability registry."""

    domain_id: str
    semantic_definition: str
    authority_class: str
    canonical_source: Optional[str]
    source_adapter: Optional[str]
    source_lineage: list[str]
    freshness_timestamp_field: Optional[str]
    freshness_threshold_seconds: int
    materiality_policy: dict[str, str]
    quality_policy: dict[str, str]
    fallback_policy: dict[str, Any]
    adapter_state: str
    event_types: list[str]
    required_by_run_types: list[str]
    provenance_contract: dict[str, str] = field(default_factory=dict)

    @property
    def is_supported(self) -> bool:
        """Adapter exists and is connected to a known source."""
        return self.adapter_state == "SUPPORTED"

    @property
    def is_broken(self) -> bool:
        """Adapter exists but produces incorrect data."""
        return self.adapter_state == "BROKEN"

    def materiality_for_run_purpose(self, run_purpose: str) -> str:
        """Return REQUIRED/OPTIONAL for a given run purpose, defaulting to OPTIONAL."""
        return self.materiality_policy.get(run_purpose, "OPTIONAL")

    def required_for_run_purpose(self, run_purpose: str) -> bool:
        """True if this domain is REQUIRED for the given run purpose."""
        return self.materiality_for_run_purpose(run_purpose) == "REQUIRED"

    def quality_on(self, condition: str) -> str:
        """Return the evidence quality state for a given error condition."""
        return self.quality_policy.get(condition, "ERROR")


@dataclass
class RunPurposeRequirements:
    """Evidence requirements for a specific run purpose."""

    purpose: str
    required_domains: list[str]
    optional_domains: list[str]


class CIODomainRegistry:
    """Canonical loader for the CIO domain capability registry.

    Loads config/cio_domain_capability_registry.json and provides typed access.
    This is the single source of truth for domain definitions, authority classes,
    adapter states, freshness thresholds, and run-purpose evidence requirements.

    Usage:
        registry = CIODomainRegistry.load()
        domain = registry.get("portfolio")
        reqs = registry.run_purpose_requirements("PORTFOLIO_ALLOCATION_REVIEW")
    """

    _instance: Optional[CIODomainRegistry] = None

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw
        self._schema_version: str = raw.get("_schema_version", "1.0.0")
        self._registry_version: str = raw.get("_registry_version", "unknown")
        self._domains: dict[str, DomainCapability] = {}
        self._parse_domains(raw.get("domains", {}))

    def _parse_domains(self, domains_raw: dict[str, Any]) -> None:
        for domain_id, d in domains_raw.items():
            self._domains[domain_id] = DomainCapability(
                domain_id=domain_id,
                semantic_definition=d.get("semantic_definition", ""),
                authority_class=d.get("authority_class", "NON_AUTHORITATIVE_REFERENCE"),
                canonical_source=d.get("canonical_source"),
                source_adapter=d.get("source_adapter"),
                source_lineage=d.get("source_lineage", []),
                freshness_timestamp_field=d.get("freshness_timestamp_field"),
                freshness_threshold_seconds=d.get("freshness_threshold_seconds", 86400),
                materiality_policy=d.get("materiality_policy", {}),
                quality_policy=d.get("quality_policy", {}),
                fallback_policy=d.get("fallback_policy", {}),
                adapter_state=d.get("adapter_state", "UNSUPPORTED"),
                event_types=d.get("event_types", []),
                required_by_run_types=d.get("required_by_run_types", []),
                provenance_contract=d.get("provenance_contract", {}),
            )

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> CIODomainRegistry:
        """Load the registry from the canonical config file.

        Uses a module-level singleton to avoid repeated disk reads.
        Call load(force_reload=True) or create a new instance directly to bypass.
        """
        if config_path is None:
            config_path = str(
                Path(__file__).resolve().parents[2]
                / "config"
                / "cio_domain_capability_registry.json"
            )

        with open(config_path) as f:
            raw = json.load(f)

        instance = cls(raw)
        cls._instance = instance
        return instance

    @classmethod
    def get_instance(cls) -> CIODomainRegistry:
        """Return the cached singleton instance. Raises if not loaded yet."""
        if cls._instance is None:
            raise RuntimeError(
                "CIODomainRegistry not loaded. Call CIODomainRegistry.load() first."
            )
        return cls._instance

    # ── Accessors ──────────────────────────────────────────────────────────────

    @property
    def schema_version(self) -> str:
        return self._schema_version

    @property
    def registry_version(self) -> str:
        return self._registry_version

    @property
    def registry_hash(self) -> str:
        """Content hash for versioning readiness/handoff decisions."""
        import hashlib
        canonical = json.dumps(self._raw, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def domain_ids(self) -> tuple[str, ...]:
        return tuple(self._domains.keys())

    def get(self, domain_id: str) -> DomainCapability:
        """Return a single domain's capability. Raises KeyError if unknown."""
        if domain_id not in self._domains:
            raise KeyError(f"Unknown domain: {domain_id}")
        return self._domains[domain_id]

    def has(self, domain_id: str) -> bool:
        return domain_id in self._domains

    def all_domains(self) -> dict[str, DomainCapability]:
        return dict(self._domains)

    # ── Authority queries ─────────────────────────────────────────────────────

    def domains_by_authority(self, authority_class: str) -> list[str]:
        return [
            d.domain_id
            for d in self._domains.values()
            if d.authority_class == authority_class
        ]

    def supported_domains(self) -> list[str]:
        """Domains whose adapter_state is SUPPORTED (adapter exists, not BROKEN)."""
        return [
            d.domain_id
            for d in self._domains.values()
            if d.is_supported
        ]

    def unsupported_domains(self) -> list[str]:
        return [
            d.domain_id
            for d in self._domains.values()
            if d.adapter_state == "UNSUPPORTED"
        ]

    def broken_domains(self) -> list[str]:
        return [
            d.domain_id
            for d in self._domains.values()
            if d.adapter_state == "BROKEN"
        ]

    # ── Run-purpose evidence requirements ─────────────────────────────────────

    def run_purpose_requirements(self, run_purpose: str) -> RunPurposeRequirements:
        """Return REQUIRED and OPTIONAL domains for a given run purpose."""
        if run_purpose not in VALID_RUN_PURPOSES:
            raise ValueError(
                f"Unknown run purpose: {run_purpose}. "
                f"Valid: {sorted(VALID_RUN_PURPOSES)}"
            )

        required: list[str] = []
        optional: list[str] = []

        for domain in self._domains.values():
            mat = domain.materiality_for_run_purpose(run_purpose)
            if mat == "REQUIRED":
                required.append(domain.domain_id)
            elif mat == "OPTIONAL":
                optional.append(domain.domain_id)

        return RunPurposeRequirements(
            purpose=run_purpose,
            required_domains=required,
            optional_domains=optional,
        )

    def domain_required_for_run_type(self, domain_id: str, run_type: str) -> bool:
        """Is this domain listed in required_by_run_types for this run type?"""
        try:
            domain = self.get(domain_id)
            return run_type in domain.required_by_run_types
        except KeyError:
            return False

    # ── Post-synthesis action validation ──────────────────────────────────────

    def post_synthesis_action_requirements(
        self, action_type: str
    ) -> tuple[list[str], list[str]]:
        """Return (required_domains, optional_domains) for action validation."""
        ps = self._raw.get("post_synthesis_validation", {})
        action = ps.get(action_type, {"REQUIRED": [], "OPTIONAL": []})
        return action.get("REQUIRED", []), action.get("OPTIONAL", [])

    # ── Freshness thresholds (single source, replaces STALENESS_THRESHOLDS) ──

    def freshness_threshold_map(self) -> dict[str, int]:
        """Return a {domain_id: threshold_seconds} map for all domains."""
        return {
            d.domain_id: d.freshness_threshold_seconds
            for d in self._domains.values()
        }

    def freshness_threshold(self, domain_id: str) -> int:
        return self.get(domain_id).freshness_threshold_seconds
