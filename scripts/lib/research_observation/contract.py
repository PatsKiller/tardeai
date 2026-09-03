"""ResearchObservation — additive provenance envelope for research products.

Aligns with architecture v3.3 §5.2 Observation envelope and extends it with
research-specific fields required by Command Center remediation:

  source identity, provider, provider timestamp, observed/received/normalized
  timestamps, business date/session, freshness age/status, quality status,
  entitlement/licensing status, sequence/version, source hash,
  calculation/model version, fallback state, trace ID.

``payload_ref`` and ``raw_evidence_ref`` are opaque handles — never secrets or
restricted source body content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from .statuses import (
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
)

SCHEMA_VERSION = "ResearchObservation@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

# Fields that MUST be present (non-empty / non-UNKNOWN as applicable) for
# proposal-path eligibility. Display may show incomplete records with labels.
REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "source_identity",
    "provider",
    "provider_at",
    "observed_at",
    "received_at",
    "normalized_at",
    "freshness_status",
    "quality_status",
    "entitlement_status",
    "sequence_or_version",
    "source_hash",
    "calculation_or_model_version",
    "fallback_state",
    "trace_id",
    "run_id",
    "schema_version",
)


def required_provenance_fields() -> tuple[str, ...]:
    return REQUIRED_PROVENANCE_FIELDS


def payload_source_hash(payload: Mapping[str, Any] | None) -> str:
    """Deterministic sha256 of a normalized non-secret payload (full hex)."""
    blob = json.dumps(payload or {}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResearchObservation:
    """Immutable research observation with full provenance."""

    # Identity
    source_identity: str  # durable product/class id e.g. hermes_research_results
    source_record_id: str  # producer-side or deterministic id
    provider: str  # e.g. hermes_worker, ri_overnight, internal_synth
    symbol_or_entity: Optional[str] = None

    # Timestamps (ISO-8601 UTC strings; caller-supplied for determinism)
    provider_at: Optional[str] = None  # provider's data timestamp
    observed_at: Optional[str] = None  # event/business observation time
    received_at: Optional[str] = None  # when we received it
    normalized_at: Optional[str] = None  # when we normalized into this envelope
    business_date: Optional[str] = None  # YYYY-MM-DD where relevant
    session: Optional[str] = None  # e.g. RTH, overnight, weekend

    # Freshness / quality / entitlement
    freshness_status: FreshnessStatus = FreshnessStatus.NO_DATA
    freshness_age_seconds: Optional[float] = None
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    entitlement_status: EntitlementStatus = EntitlementStatus.UNKNOWN

    # Versioning / integrity
    sequence_or_version: Optional[str] = None
    source_hash: Optional[str] = None
    calculation_or_model_version: Optional[str] = None
    schema_version: str = SCHEMA_VERSION

    # Correlation
    run_id: Optional[str] = None  # job/correlation id joining log+artifact+CC
    trace_id: Optional[str] = None

    # Fallback + evidence (opaque refs only)
    fallback_state: FallbackState = FallbackState.NONE
    payload_ref: Mapping[str, Any] = field(default_factory=dict)
    raw_evidence_ref: Optional[str] = None  # path/uri handle — not raw body
    degraded_label: Optional[str] = None  # required when display fails open

    # Join / durable-output proof
    durable_output_present: bool = False
    log_success_claimed: bool = False

    authority: str = AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Enum):
                d[k] = v.value
        # Ensure nested enums in case asdict left them
        d["freshness_status"] = self.freshness_status.value
        d["quality_status"] = self.quality_status.value
        d["entitlement_status"] = self.entitlement_status.value
        d["fallback_state"] = self.fallback_state.value
        d["payload_ref"] = dict(self.payload_ref or {})
        return d

    def missing_provenance_fields(self) -> list[str]:
        """Return required provenance fields that are absent or unknown."""
        missing: list[str] = []
        data = self.to_dict()
        for key in REQUIRED_PROVENANCE_FIELDS:
            val = data.get(key)
            if val is None or val == "" or val == "UNKNOWN":
                missing.append(key)
                continue
            if key == "freshness_status" and val == FreshnessStatus.NO_DATA.value:
                # NO_DATA is an explicit status (allowed on the envelope) but
                # blocks eligibility elsewhere; not "missing provenance".
                continue
        return missing

    def is_complete_provenance(self) -> bool:
        return not self.missing_provenance_fields()


def make_research_observation(
    *,
    source_identity: str,
    provider: str,
    freshness_status: FreshnessStatus,
    quality_status: QualityStatus,
    entitlement_status: EntitlementStatus,
    provider_at: Optional[str],
    observed_at: Optional[str],
    received_at: Optional[str],
    normalized_at: Optional[str],
    run_id: str,
    trace_id: str,
    source_hash: Optional[str] = None,
    payload: Mapping[str, Any] | None = None,
    sequence_or_version: Optional[str] = None,
    calculation_or_model_version: Optional[str] = None,
    source_record_id: Optional[str] = None,
    symbol_or_entity: Optional[str] = None,
    business_date: Optional[str] = None,
    session: Optional[str] = None,
    freshness_age_seconds: Optional[float] = None,
    fallback_state: FallbackState = FallbackState.NONE,
    raw_evidence_ref: Optional[str] = None,
    degraded_label: Optional[str] = None,
    durable_output_present: bool = False,
    log_success_claimed: bool = False,
    schema_version: str = SCHEMA_VERSION,
) -> ResearchObservation:
    """Build an immutable ResearchObservation. Timestamps are caller-supplied."""
    payload = dict(payload or {})
    sh = source_hash or payload_source_hash(payload)
    rid = source_record_id or f"{source_identity}:{run_id}:{sh[:16]}"
    return ResearchObservation(
        source_identity=source_identity,
        source_record_id=rid,
        provider=provider,
        symbol_or_entity=symbol_or_entity,
        provider_at=provider_at,
        observed_at=observed_at or provider_at,
        received_at=received_at,
        normalized_at=normalized_at,
        business_date=business_date,
        session=session,
        freshness_status=freshness_status,
        freshness_age_seconds=freshness_age_seconds,
        quality_status=quality_status,
        entitlement_status=entitlement_status,
        sequence_or_version=sequence_or_version,
        source_hash=sh,
        calculation_or_model_version=calculation_or_model_version,
        schema_version=schema_version,
        run_id=run_id,
        trace_id=trace_id,
        fallback_state=fallback_state,
        payload_ref=payload,
        raw_evidence_ref=raw_evidence_ref,
        degraded_label=degraded_label,
        durable_output_present=durable_output_present,
        log_success_claimed=log_success_claimed,
    )


def validate_schema_version(obs: ResearchObservation, expected: str = SCHEMA_VERSION) -> bool:
    return obs.schema_version == expected


def never_relabel_as_fresh(status: FreshnessStatus) -> bool:
    """True if status must not be rewritten to FRESH."""
    return status != FreshnessStatus.FRESH
