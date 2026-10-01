"""CIODecisionLineage@v1 — direct, read-only decision projection.

This is a composition view over existing CIO workflow, research, checkpoint,
and operator-feedback records. It is not a new source of truth and it never
infers a runtime state in the client.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA = "CIODecisionLineage@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
VALID_STATES = frozenset({
    "LIVE", "PARTIAL", "UNWIRED", "NOT_RUN", "NOT_APPLICABLE", "PENDING",
    "UNAVAILABLE", "UNKNOWN",
})

STAGE_KEYS = (
    "wake_event", "security_identity", "office_truth", "institutional_cognition",
    "canon_frameworks", "research_retrieved", "research_used", "research_rejected",
    "research_gap", "specialist_delegation", "specialist_disagreement", "model_route",
    "judgment", "counter_thesis", "confidence", "falsifier", "notification",
    "operator_disposition", "checkpoint", "outcome", "belief_calibration_lesson",
)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "" and value != []:
            return value
    return None


def _timestamp(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    return _first(row, "source_as_of", "as_of", "updated_at", "recorded_at", "created_at", "timestamp", "ts")


def _has(value: Any) -> bool:
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None and _text(value) != ""


def _refs(value: Any) -> list[str]:
    """Normalize source references without treating a string as an iterable."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return sorted({_text(item) for item in value if _text(item)})
    return [_text(value)] if _text(value) else []


def _state(raw: Any, *, present: bool) -> str:
    value = _text(raw).upper()
    if value in VALID_STATES:
        return value
    return "LIVE" if present else "UNKNOWN"


def _stage(
    *,
    state: str,
    producer: Any = None,
    consumer: Any = None,
    source_ref: Any = None,
    source_as_of: Any = None,
    composition_as_of: str,
    evidence_class: Any = None,
    source_sha: Any = None,
    run_id: Any = None,
    trace_id: Any = None,
    value: Any = None,
) -> dict[str, Any]:
    return {
        "state": state if state in VALID_STATES else "UNKNOWN",
        "producer": producer,
        "consumer": consumer,
        "source_ref": source_ref,
        "source_as_of": source_as_of,
        "composition_as_of": composition_as_of,
        "evidence_class": evidence_class,
        "source_sha": source_sha,
        "run_id": run_id,
        "trace_id": trace_id,
        "value": value,
    }


def _latest(rows: Iterable[dict[str, Any]], *, key: str | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if key and not _text(row.get(key)):
            continue
        found = row
    return found


def _stage_status(envelope: dict[str, Any], key: str) -> str | None:
    statuses = envelope.get("stage_status")
    if not isinstance(statuses, dict):
        return None
    raw = _text(statuses.get(key)).upper()
    return {
        "COMPLETED": "LIVE",
        "NOT_REQUIRED": "NOT_APPLICABLE",
        "NOT_YET_CREATED": "NOT_RUN",
        "SUPPRESSED": "PARTIAL",
        "FAILED": "UNAVAILABLE",
        "UNAVAILABLE": "UNAVAILABLE",
    }.get(raw, raw if raw in VALID_STATES else None)


def _row_for_decision(row: dict[str, Any], decision_id: str) -> bool:
    did = _text(row.get("decision_id"))
    return did == decision_id or _text(row.get("workflow_id")) == decision_id


def project_decision_lineage(
    decision_id: str,
    *,
    decision: dict[str, Any] | None = None,
    workflow_records: Iterable[dict[str, Any]] = (),
    intelligence_records: Iterable[dict[str, Any]] = (),
    checkpoint_records: Iterable[dict[str, Any]] = (),
    disposition_records: Iterable[dict[str, Any]] = (),
    composition_as_of: str | None = None,
) -> dict[str, Any]:
    """Compose one exact decision projection from canonical evidence rows."""
    did = _text(decision_id)
    composed = composition_as_of or datetime.now(timezone.utc).isoformat()
    d = dict(decision or {})
    workflows = [r for r in workflow_records if isinstance(r, dict) and _row_for_decision(r, did)]
    intelligence = [r for r in intelligence_records if isinstance(r, dict) and _row_for_decision(r, did)]
    checkpoints = [r for r in checkpoint_records if isinstance(r, dict) and _row_for_decision(r, did)]
    dispositions = [r for r in disposition_records if isinstance(r, dict) and _text(r.get("decision_id")) == did]
    env = _latest([r for r in workflows if r.get("record_type") == "envelope"]) or _latest(workflows)
    intel = _latest(intelligence)
    checkpoint = _latest(checkpoints)
    disposition = _latest(dispositions)

    def value(*keys: str) -> Any:
        for row in (d, env, intel, checkpoint):
            candidate = _first(row, *keys)
            if candidate is not None:
                return candidate
        return None

    def source(*rows: dict[str, Any]) -> dict[str, Any]:
        return next((row for row in rows if row), {})

    def make(stage: str, keys: tuple[str, ...], *, source_ref: str | None = None, forced_state: str | None = None) -> dict[str, Any]:
        raw = value(*keys)
        row = source(d if _has(_first(d, *keys)) else {}, env if _has(_first(env, *keys)) else {}, intel if _has(_first(intel, *keys)) else {}, checkpoint if _has(_first(checkpoint, *keys)) else {})
        return _stage(
            state=forced_state or _state(None, present=_has(raw)),
            producer=_first(row, "producer", "producer_id", "source") if row else None,
            consumer=_first(row, "consumer", "consumer_id") if row else None,
            source_ref=source_ref or (_first(row, "source_ref", "source_store") if row else None),
            source_as_of=_timestamp(row),
            composition_as_of=composed,
            evidence_class=_first(row, "evidence_class", "evidence") if row else None,
            source_sha=_first(row, "source_sha", "source_version") if row else None,
            run_id=_first(row, "run_id", "wake_id", "workflow_id") if row else None,
            trace_id=_first(row, "trace_id", "trace") if row else None,
            value=raw,
        )

    stage_status = env.get("stage_status") if isinstance(env.get("stage_status"), dict) else {}
    stages: dict[str, dict[str, Any]] = {}
    stages["wake_event"] = make("wake_event", ("event_id", "wake_id", "discovery_id"), source_ref="cio_wake_jobs")
    stages["security_identity"] = make("security_identity", ("subject_guid", "security_guid", "entity_guid"), source_ref="identity_registry")
    stages["office_truth"] = make("office_truth", ("decision_input_digest", "office_truth_ref", "truth_receipt"), source_ref="cio_decisions")
    stages["institutional_cognition"] = make("institutional_cognition", ("memory_ids", "memory_retrieval_ids", "cognition_receipt"), source_ref="institutional_memory")
    stages["canon_frameworks"] = make("canon_frameworks", ("framework_refs", "canon_refs", "methodology_ref"), source_ref="canon_frameworks")
    stages["research_retrieved"] = make("research_retrieved", ("research_request_id", "research_request_ids", "research_result_id", "research_result_ids"), source_ref="hermes_research")
    stages["research_used"] = make("research_used", ("used_research_ids", "research_used", "advisory_use"), source_ref="research_consumption_receipt")
    stages["research_rejected"] = make("research_rejected", ("rejected_research_ids", "research_rejected"), source_ref="research_rejection_receipt")
    stages["research_gap"] = make("research_gap", ("research_gap", "research_gaps"), source_ref="research_gap_register")
    stages["specialist_delegation"] = make("specialist_delegation", ("specialist_dispatch_id", "specialist_artifact_id"), source_ref="cio_workflow_lineage", forced_state=_stage_status(env, "specialist"))
    stages["specialist_disagreement"] = make("specialist_disagreement", ("specialist_disagreement", "disagreement_receipt"), source_ref="specialist_review")
    stages["model_route"] = make("model_route", ("model_route", "model_used", "provider", "model_provider"), source_ref="model_route_receipt")
    stages["judgment"] = make("judgment", ("judgment", "recommendation", "action"), source_ref="cio_decisions")
    stages["counter_thesis"] = make("counter_thesis", ("counter_thesis", "counter_case"), source_ref="cio_decisions")
    stages["confidence"] = make("confidence", ("confidence", "confidence_raw", "confidence_score"), source_ref="cio_decisions")
    stages["falsifier"] = make("falsifier", ("falsifier", "invalidation", "invalidation_condition"), source_ref="cio_decisions")

    notification_value = _first(env, "notification_id", "notification_classification")
    notification_state = _stage_status(env, "notification") or _state(None, present=_has(notification_value))
    stages["notification"] = make("notification", ("notification_id", "notification_classification", "suppression_reason"), source_ref="cio_notification_audit", forced_state=notification_state)
    stages["operator_disposition"] = _stage(
        state="LIVE" if disposition else "UNKNOWN",
        producer=_first(disposition, "producer", "source_surface") if disposition else None,
        consumer="cio_operator" if disposition else None,
        source_ref="decision_dispositions" if disposition else None,
        source_as_of=_timestamp(disposition),
        composition_as_of=composed,
        evidence_class=_first(disposition, "evidence_class") if disposition else None,
        source_sha=_first(disposition, "source_sha") if disposition else None,
        run_id=_first(disposition, "run_id") if disposition else None,
        trace_id=_first(disposition, "trace_id") if disposition else None,
        value=disposition or None,
    )
    stages["checkpoint"] = make("checkpoint", ("checkpoint_id",), source_ref="outcome_checkpoints", forced_state=_stage_status(env, "checkpoint"))
    outcome_state = _state(_first(checkpoint, "state", "outcome_state"), present=_has(_first(checkpoint, "outcome_id", "outcome")))
    if not _has(_first(checkpoint, "outcome_id", "outcome")) and checkpoint:
        outcome_state = "PENDING"
    stages["outcome"] = _stage(
        state=outcome_state,
        producer=_first(checkpoint, "producer", "producer_id") if checkpoint else None,
        consumer=_first(checkpoint, "consumer", "consumer_id") if checkpoint else None,
        source_ref="outcome_checkpoints" if checkpoint else None,
        source_as_of=_timestamp(checkpoint),
        composition_as_of=composed,
        evidence_class=_first(checkpoint, "evidence_class", "evidence") if checkpoint else None,
        source_sha=_first(checkpoint, "source_sha") if checkpoint else None,
        run_id=_first(checkpoint, "run_id", "workflow_id") if checkpoint else None,
        trace_id=_first(checkpoint, "trace_id") if checkpoint else None,
        value=_first(checkpoint, "outcome_id", "outcome") if checkpoint else None,
    )
    stages["belief_calibration_lesson"] = make("belief_calibration_lesson", ("lesson_id", "reflection_id", "score_id", "calibration_receipt"), source_ref="cio_learning")

    lineage_id = _first(env, "lineage_id", "workflow_id") or _first(intel, "lineage_id")
    refs: list[str] = []
    for row in (d, env, intel, checkpoint, disposition):
        refs.extend(_refs(_first(row, "source_refs", "source_ref")))
    return {
        "schema": SCHEMA,
        "decision_id": did,
        "lineage_id": lineage_id,
        "decision": d or None,
        "stages": stages,
        "source_refs": sorted(set(refs)),
        "source_as_of": min((s["source_as_of"] for s in stages.values() if s.get("source_as_of")), default=None),
        "composition_as_of": composed,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "memory_behavior_influence": 0,
        "matched_sources": {
            "workflow_records": len(workflows),
            "intelligence_records": len(intelligence),
            "checkpoint_records": len(checkpoints),
            "disposition_records": len(dispositions),
        },
    }


def direct_match(decision_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only exact decision matches; never fall back to symbol identity."""
    did = _text(decision_id)
    return [row for row in rows if isinstance(row, dict) and _row_for_decision(row, did)]
