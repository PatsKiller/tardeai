"""Join job logs, durable research output, and Command Center status by run_id.

A successful log line without durable output is NOT success.
Wrong run_id or source_hash fails the join.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .contract import ResearchObservation, make_research_observation, payload_source_hash
from .statuses import (
    EntitlementStatus,
    FallbackState,
    FreshnessStatus,
    QualityStatus,
)


@dataclass(frozen=True)
class JoinResult:
    ok: bool
    run_id: str
    reasons: tuple[str, ...]
    observation: Optional[ResearchObservation] = None
    log_present: bool = False
    durable_present: bool = False
    cc_status_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "reasons": list(self.reasons),
            "log_present": self.log_present,
            "durable_present": self.durable_present,
            "cc_status_present": self.cc_status_present,
            "observation": self.observation.to_dict() if self.observation else None,
        }


def _get(m: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not m:
        return default
    for k in keys:
        if k in m and m[k] not in (None, ""):
            return m[k]
    return default


def _parse_fallback(raw: Any) -> FallbackState:
    text = str(raw or "NONE").upper()
    try:
        return FallbackState(text)
    except ValueError:
        return FallbackState.NONE


def correlate_run(
    *,
    run_id: str,
    log_record: Mapping[str, Any] | None,
    durable_output: Mapping[str, Any] | None,
    cc_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return correlation facts for one run_id across the three surfaces."""
    log_rid = _get(log_record, "run_id", "correlation_id", "job_id")
    dur_rid = _get(durable_output, "run_id", "correlation_id", "job_id")
    cc_rid = _get(cc_status, "run_id", "correlation_id", "job_id")
    return {
        "requested_run_id": run_id,
        "log_run_id": log_rid,
        "durable_run_id": dur_rid,
        "cc_run_id": cc_rid,
        "log_match": log_rid == run_id if log_record is not None else False,
        "durable_match": dur_rid == run_id if durable_output is not None else False,
        "cc_match": (cc_rid == run_id) if cc_status is not None else None,
        "log_success_claimed": bool(_get(log_record, "success", "ok", default=False)),
        "durable_present": durable_output is not None and bool(durable_output),
    }


def join_run_artifacts(
    *,
    run_id: str,
    source_identity: str,
    provider: str,
    log_record: Mapping[str, Any] | None,
    durable_output: Mapping[str, Any] | None,
    cc_status: Mapping[str, Any] | None = None,
    expected_source_hash: Optional[str] = None,
    received_at: Optional[str] = None,
    normalized_at: Optional[str] = None,
    calculation_or_model_version: Optional[str] = None,
    entitlement_status: EntitlementStatus = EntitlementStatus.INTERNAL,
    max_freshness_age_seconds: float = 86_400.0,
    now_epoch: Optional[float] = None,
) -> JoinResult:
    """Join log + durable output (+ optional CC status) into one observation.

    Fail closed when:
    - log claims success but durable output is missing
    - run_ids disagree
    - expected source_hash disagrees with durable payload
    """
    reasons: list[str] = []
    corr = correlate_run(
        run_id=run_id,
        log_record=log_record,
        durable_output=durable_output,
        cc_status=cc_status,
    )
    log_present = log_record is not None
    durable_present = bool(corr["durable_present"])
    cc_present = cc_status is not None

    if log_present and not corr["log_match"]:
        reasons.append(f"WRONG_RUN_ID:log={corr['log_run_id']!r}:expected={run_id!r}")
    if durable_present and not corr["durable_match"]:
        reasons.append(f"WRONG_RUN_ID:durable={corr['durable_run_id']!r}:expected={run_id!r}")
    if cc_present and corr["cc_match"] is False:
        reasons.append(f"WRONG_RUN_ID:cc={corr['cc_run_id']!r}:expected={run_id!r}")

    log_success = bool(corr["log_success_claimed"])
    if log_success and not durable_present:
        reasons.append("LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT")

    if not durable_present and not log_present:
        reasons.append("NO_DATA")
        obs = make_research_observation(
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
            degraded_label="NO_DATA: no log and no durable output",
            calculation_or_model_version=calculation_or_model_version or "unknown",
            sequence_or_version="none",
            payload={},
        )
        return JoinResult(
            ok=False,
            run_id=run_id,
            reasons=tuple(reasons),
            observation=obs,
            log_present=log_present,
            durable_present=False,
            cc_status_present=cc_present,
        )

    if not durable_present:
        # Gap / missing durable — never FRESH
        status = FreshnessStatus.GAP if log_present else FreshnessStatus.NO_DATA
        if log_success:
            status = FreshnessStatus.ERROR  # claimed success without artifact
        obs = make_research_observation(
            source_identity=source_identity,
            provider=provider,
            freshness_status=status,
            quality_status=QualityStatus.FAILED if log_success else QualityStatus.UNKNOWN,
            entitlement_status=entitlement_status,
            provider_at=_get(log_record, "provider_at", "completed_ts", "as_of"),
            observed_at=_get(log_record, "as_of", "observed_at", "completed_ts"),
            received_at=received_at or _get(log_record, "received_at", "ts"),
            normalized_at=normalized_at or received_at,
            run_id=run_id,
            trace_id=_get(log_record, "trace_id") or f"trace:{run_id}",
            durable_output_present=False,
            log_success_claimed=log_success,
            degraded_label="missing durable output for run",
            calculation_or_model_version=calculation_or_model_version
            or _get(log_record, "model_version", "calc_version", default="unknown"),
            sequence_or_version=_get(log_record, "sequence", "version", default="log-only"),
            payload={"log_keys": sorted(log_record.keys()) if log_record else []},
            raw_evidence_ref=_get(log_record, "evidence_ref", "log_path"),
        )
        return JoinResult(
            ok=False,
            run_id=run_id,
            reasons=tuple(reasons) or ("DURABLE_OUTPUT_ABSENT",),
            observation=obs,
            log_present=log_present,
            durable_present=False,
            cc_status_present=cc_present,
        )

    # Durable present — hash check
    # Prefer explicit source_hash on durable; else hash non-secret payload body.
    assert durable_output is not None  # durable_present True above
    durable: Mapping[str, Any] = durable_output
    payload_obj = durable.get("payload")
    if isinstance(payload_obj, dict):
        body: dict[str, Any] = dict(payload_obj)
    else:
        body = {
            k: v
            for k, v in durable.items()
            if k not in ("run_id", "correlation_id", "job_id", "source_hash", "secrets", "raw_body")
        }
    computed_hash = _get(durable, "source_hash") or payload_source_hash(body)
    if expected_source_hash is not None and computed_hash != expected_source_hash:
        reasons.append(f"WRONG_SOURCE_HASH:got={computed_hash!r}:expected={expected_source_hash!r}")

    provider_at = _get(durable, "provider_at", "completed_ts", "as_of")
    observed_at = _get(durable, "observed_at", "as_of", "provider_at")
    recv = received_at or _get(durable, "received_at") or _get(log_record, "received_at", "ts")
    norm = normalized_at or _get(durable, "normalized_at") or recv

    # Freshness age from provider_at if epoch provided
    age: Optional[float] = None
    freshness = FreshnessStatus.FRESH

    def _epoch(ts: Optional[str]) -> Optional[float]:
        if not ts:
            return None
        text = str(ts).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    if now_epoch is not None and provider_at:
        pe = _epoch(provider_at)
        if pe is not None:
            age = now_epoch - pe
            if age > max_freshness_age_seconds:
                freshness = FreshnessStatus.STALE
                reasons.append(f"STALE_AGE:{int(age)}s")
            elif age < -300:
                reasons.append(f"FUTURE_SKEW:provider_at:{int(-age)}s")
                freshness = FreshnessStatus.ERROR

    # Partial if required content keys missing
    required_content = durable.get("required_fields_present")
    if required_content is False:
        freshness = FreshnessStatus.PARTIAL
        reasons.append("PARTIAL_CONTENT")

    quality_raw = str(_get(durable, "quality_status", "quality", default="OK")).upper()
    try:
        quality = QualityStatus(quality_raw)
    except ValueError:
        quality = QualityStatus.UNKNOWN
        reasons.append(f"QUALITY_UNKNOWN:{quality_raw}")

    if (
        reasons
        and freshness == FreshnessStatus.FRESH
        and any(r.startswith("WRONG_") or r.startswith("LOG_ONLY") for r in reasons)
    ):
        freshness = FreshnessStatus.ERROR

    obs = make_research_observation(
        source_identity=source_identity,
        provider=provider,
        freshness_status=freshness if not any(r.startswith("WRONG_RUN_ID") for r in reasons) else FreshnessStatus.ERROR,
        quality_status=quality,
        entitlement_status=entitlement_status,
        provider_at=provider_at,
        observed_at=observed_at,
        received_at=recv,
        normalized_at=norm,
        business_date=_get(durable, "business_date"),
        session=_get(durable, "session"),
        freshness_age_seconds=age,
        run_id=run_id,
        trace_id=_get(durable, "trace_id") or _get(log_record, "trace_id") or f"trace:{run_id}",
        source_hash=computed_hash,
        sequence_or_version=str(_get(durable, "sequence_or_version", "sequence", "version", default="1")),
        calculation_or_model_version=calculation_or_model_version
        or _get(durable, "calculation_or_model_version", "model_version", default="unknown"),
        fallback_state=_parse_fallback(_get(durable, "fallback_state", default="NONE")),
        durable_output_present=True,
        log_success_claimed=log_success,
        payload=body,
        raw_evidence_ref=_get(durable, "evidence_ref", "path"),
        symbol_or_entity=_get(durable, "symbol", "symbol_or_entity"),
        degraded_label=None if not reasons else ";".join(reasons[:3]),
    )

    ok = not reasons
    return JoinResult(
        ok=ok,
        run_id=run_id,
        reasons=tuple(reasons) if reasons else ("JOIN_OK",),
        observation=obs,
        log_present=log_present,
        durable_present=True,
        cc_status_present=cc_present,
    )
