"""Adapters that wrap existing research product records into ResearchObservation.

Does not rewrite stores or producers. Maps known fields when present; marks
missing provenance explicitly so eligibility fails closed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .contract import ResearchObservation, make_research_observation, payload_source_hash
from .statuses import EntitlementStatus, FallbackState, FreshnessStatus, QualityStatus


def _g(m: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in m and m[k] not in (None, ""):
            return m[k]
    return default


def _enum_or(default: Any, raw: Any, enum_cls: type) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return enum_cls(str(raw).upper())
    except ValueError:
        return default


def wrap_research_record(
    record: Mapping[str, Any],
    *,
    source_identity: str,
    provider: str,
    run_id: Optional[str] = None,
    received_at: Optional[str] = None,
    normalized_at: Optional[str] = None,
    freshness_status: Optional[FreshnessStatus] = None,
    freshness_age_seconds: Optional[float] = None,
    entitlement_status: Optional[EntitlementStatus] = None,
    durable_output_present: bool = True,
    log_success_claimed: bool = True,
    calculation_or_model_version: Optional[str] = None,
    raw_evidence_ref: Optional[str] = None,
) -> ResearchObservation:
    """Wrap a durable research product row/dict into the provenance envelope."""
    rid = run_id or _g(record, "run_id", "correlation_id", "job_id")
    trace = _g(record, "trace_id") or (f"trace:{rid}" if rid else None)
    provider_at = _g(record, "provider_at", "completed_ts", "published_at", "as_of")
    observed_at = _g(record, "observed_at", "as_of", "effective_at", "provider_at")
    recv = received_at or _g(record, "received_at", "retrieved_at")
    norm = normalized_at or _g(record, "normalized_at") or recv

    body = {
        k: v
        for k, v in record.items()
        if k
        not in (
            "raw_body",
            "secrets",
            "api_key",
            "token",
            "authorization",
            "password",
        )
    }
    source_hash = _g(record, "source_hash", "snapshot_hash") or payload_source_hash(body)

    fs = freshness_status or _enum_or(
        FreshnessStatus.PARTIAL, _g(record, "freshness_status", "freshness_state"), FreshnessStatus
    )
    qs = _enum_or(QualityStatus.UNVERIFIED, _g(record, "quality_status", "quality_state", "quality"), QualityStatus)
    es = entitlement_status or _enum_or(
        EntitlementStatus.UNKNOWN,
        _g(record, "entitlement_status", "entitlement_state", "licensing_status"),
        EntitlementStatus,
    )
    fb = _enum_or(FallbackState.NONE, _g(record, "fallback_state"), FallbackState)

    return make_research_observation(
        source_identity=source_identity,
        provider=provider,
        freshness_status=fs,
        quality_status=qs,
        entitlement_status=es,
        provider_at=provider_at,
        observed_at=observed_at,
        received_at=recv,
        normalized_at=norm,
        business_date=_g(record, "business_date", "trade_date"),
        session=_g(record, "session", "market_session"),
        freshness_age_seconds=freshness_age_seconds,
        run_id=str(rid) if rid else "",
        trace_id=str(trace) if trace else "",
        source_hash=source_hash,
        sequence_or_version=str(_g(record, "sequence_or_version", "sequence", "version", "source_version", default=""))
        or None,
        calculation_or_model_version=calculation_or_model_version
        or _g(record, "calculation_or_model_version", "model_version", "transform_version"),
        fallback_state=fb,
        durable_output_present=durable_output_present,
        log_success_claimed=log_success_claimed,
        payload=body,
        raw_evidence_ref=raw_evidence_ref or _g(record, "evidence_ref", "path", "store_path"),
        symbol_or_entity=_g(record, "symbol", "symbol_or_entity", "entity"),
        source_record_id=str(_g(record, "source_record_id", "id", "artifact_id", default="")) or None,
        degraded_label=_g(record, "degraded_label"),
    )


def wrap_no_data(
    *,
    source_identity: str,
    provider: str,
    run_id: str,
    received_at: str,
    normalized_at: str,
    reason: str = "no durable research record",
) -> ResearchObservation:
    """Explicit NO_DATA envelope — never labeled FRESH."""
    return make_research_observation(
        source_identity=source_identity,
        provider=provider,
        freshness_status=FreshnessStatus.NO_DATA,
        quality_status=QualityStatus.UNKNOWN,
        entitlement_status=EntitlementStatus.UNKNOWN,
        provider_at=None,
        observed_at=None,
        received_at=received_at,
        normalized_at=normalized_at,
        run_id=run_id,
        trace_id=f"trace:{run_id}",
        durable_output_present=False,
        log_success_claimed=False,
        degraded_label=f"NO_DATA: {reason}",
        calculation_or_model_version="n/a",
        sequence_or_version="n/a",
        source_hash=payload_source_hash({"status": "NO_DATA", "reason": reason}),
        payload={"status": "NO_DATA", "reason": reason},
    )


def wrap_gap(
    *,
    source_identity: str,
    provider: str,
    run_id: str,
    received_at: str,
    normalized_at: str,
    gap_reason: str,
    business_date: Optional[str] = None,
) -> ResearchObservation:
    """Explicit GAP envelope — coverage hole, not freshness."""
    return make_research_observation(
        source_identity=source_identity,
        provider=provider,
        freshness_status=FreshnessStatus.GAP,
        quality_status=QualityStatus.UNVERIFIED,
        entitlement_status=EntitlementStatus.INTERNAL,
        provider_at=None,
        observed_at=None,
        received_at=received_at,
        normalized_at=normalized_at,
        business_date=business_date,
        run_id=run_id,
        trace_id=f"trace:{run_id}",
        durable_output_present=False,
        log_success_claimed=False,
        degraded_label=f"GAP: {gap_reason}",
        calculation_or_model_version="n/a",
        sequence_or_version="gap",
        source_hash=payload_source_hash({"status": "GAP", "reason": gap_reason}),
        payload={"status": "GAP", "reason": gap_reason},
    )


def wrap_error(
    *,
    source_identity: str,
    provider: str,
    run_id: str,
    received_at: str,
    normalized_at: str,
    error: str,
    log_success_claimed: bool = False,
) -> ResearchObservation:
    """ERROR envelope for producer/join failures."""
    return make_research_observation(
        source_identity=source_identity,
        provider=provider,
        freshness_status=FreshnessStatus.ERROR,
        quality_status=QualityStatus.FAILED,
        entitlement_status=EntitlementStatus.UNKNOWN,
        provider_at=None,
        observed_at=None,
        received_at=received_at,
        normalized_at=normalized_at,
        run_id=run_id,
        trace_id=f"trace:{run_id}",
        durable_output_present=False,
        log_success_claimed=log_success_claimed,
        degraded_label=f"ERROR: {error}",
        calculation_or_model_version="n/a",
        sequence_or_version="error",
        source_hash=payload_source_hash({"status": "ERROR", "error": error}),
        payload={"status": "ERROR", "error": error},
    )


def project_to_canonical_clocks(obs: ResearchObservation) -> dict[str, Any]:
    """Map ResearchObservation clocks onto the backend ObservationEnvelope names.

    Mechanical reconciliation for Command Center: research and portfolio use the
    same four-clock vocabulary (provider / observed / received / normalized /
    business_date) without composing ResearchObservation into the portfolio
    envelope object.
    """
    return {
        "dataset": "research",
        "source_identity": obs.source_identity,
        "provider_timestamp": obs.provider_at,
        "observed_at": obs.observed_at,
        "received_at": obs.received_at,
        "normalized_at": obs.normalized_at,
        "business_date": obs.business_date,
        "market_session": obs.session or "UNKNOWN",
        "freshness": {
            "status": str(
                obs.freshness_status.value if hasattr(obs.freshness_status, "value") else obs.freshness_status
            )
        },
        "quality": str(obs.quality_status.value if hasattr(obs.quality_status, "value") else obs.quality_status),
        "entitlement": str(
            obs.entitlement_status.value if hasattr(obs.entitlement_status, "value") else obs.entitlement_status
        ),
        "fallback": str(obs.fallback_state.value if hasattr(obs.fallback_state, "value") else obs.fallback_state),
        "trace_id": obs.trace_id,
        "source_hash": obs.source_hash,
        "contract_bridge": "research_observation→canonical_observation.clocks",
    }
