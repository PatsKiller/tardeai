"""CIODecisionLineage@v1 — direct, read-only decision projection.

This is a composition view over existing CIO workflow, research, checkpoint,
and operator-feedback records. It is not a new source of truth and it never
infers a runtime state in the client.

Stage states are derived, never presence-guessed:

* LIVE — a durable row matched to THIS decision carries the stage value, a
  parseable ``source_as_of`` and a ``source_ref``.
* PARTIAL — a matched row exists but a required field is missing.
* PENDING — a checkpoint/outcome horizon has not matured (or the producer
  recorded PENDING).
* NOT_RUN — the producer explicitly recorded a skip / not-yet-run.
* NOT_APPLICABLE — the producer recorded the stage as not required.
* UNWIRED — the stage has no producer contract in this system
  (``UNWIRED_STAGES`` names each one with its reason).
* UNAVAILABLE — the stage's source store is missing or unreadable.
* UNKNOWN — none of the above could be established.

``False``, ``0`` and ``""`` are never evidence.  ``source_ref``, ``run_id``,
``trace_id`` and ``source_as_of`` come only from the matched row.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
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

# Stages with no producer contract anywhere in this system: no writer emits
# the stage's fields for a decision.  A matched row still wins (it would prove
# a producer exists); absent one, the stage is UNWIRED rather than UNKNOWN.
UNWIRED_STAGES: dict[str, str] = {
    "canon_frameworks": (
        "no producer writes framework_refs/canon_refs/methodology_ref onto a "
        "CIO decision, workflow envelope or intelligence lineage"
    ),
    "specialist_disagreement": (
        "no producer writes specialist_disagreement/disagreement_receipt; "
        "specialist review records dispatch only, not disagreement"
    ),
}

# Store labels.  Each stage names the primary store whose absence makes the
# stage UNAVAILABLE, then every store it may match a row from.
_WORKFLOW = "cio_workflow_lineage"
_INTEL = "intelligence_lineages"
_CHECKPOINTS = "outcome_checkpoints"
_DISPOSITIONS = "decision_dispositions"
_RESEARCH = "research_provenance"
_COGNITION = "institutional_cognition"
_LEARNING = "learning"
_CASES = "cio_production_cases"

# stage -> (value keys, PARTIAL-only keys, producer stage_status key, primary store)
_STAGE_SPECS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str | None, str]] = {
    "wake_event": (("event_id", "wake_id", "discovery_id"), (), None, _WORKFLOW),
    "security_identity": (("subject_guid", "security_guid", "entity_guid"), (), None, _WORKFLOW),
    "office_truth": (("decision_input_digest", "inputs_digest", "office_truth_ref", "truth_receipt"), (), None, _WORKFLOW),
    "institutional_cognition": (("memory_ids", "memory_retrieval_ids", "cognition_receipt"), (), None, _COGNITION),
    "canon_frameworks": (("framework_refs", "canon_refs", "methodology_ref"), (), None, _WORKFLOW),
    "research_retrieved": (
        ("research_result_id", "research_result_ids", "research_artifact_id"),
        ("research_request_id", "research_request_ids"),
        "research", _RESEARCH,
    ),
    "research_used": (("used_research_ids", "research_used", "advisory_use"), (), None, _RESEARCH),
    "research_rejected": (("rejected_research_ids", "research_rejected"), (), None, _RESEARCH),
    "research_gap": (("research_gap", "research_gaps"), (), None, _WORKFLOW),
    "specialist_delegation": (("specialist_dispatch_id", "specialist_artifact_id"), (), "specialist", _WORKFLOW),
    "specialist_disagreement": (("specialist_disagreement", "disagreement_receipt"), (), None, _WORKFLOW),
    # ``model`` is what AgentRunTrace holdings decisions record (the LLM that made them).
    "model_route": (("model_route", "model_used", "model", "provider", "model_provider"), (), None, _WORKFLOW),
    "judgment": (("judgment", "recommendation", "action"), (), "cio", _WORKFLOW),
    "counter_thesis": (("counter_thesis", "counter_case"), (), None, _WORKFLOW),
    "confidence": (("confidence", "confidence_raw", "confidence_score"), (), None, _WORKFLOW),
    "falsifier": (("falsifier", "invalidation", "invalidation_condition"), (), None, _WORKFLOW),
    "notification": (("notification_id", "notification_classification", "suppression_reason"), (), "notification", _WORKFLOW),
    "checkpoint": (("checkpoint_id",), (), "checkpoint", _CHECKPOINTS),
    "belief_calibration_lesson": (("lesson_id", "reflection_id", "score_id", "calibration_receipt"), (), None, _LEARNING),
}

# Producer ``stage_status`` vocabulary -> lineage state.  Only an explicit
# producer record maps to NOT_RUN / NOT_APPLICABLE.
_PRODUCER_STATUS = {
    "NOT_YET_CREATED": "NOT_RUN",
    "NOT_RUN": "NOT_RUN",
    "SKIPPED": "NOT_RUN",
    "SUPPRESSED": "NOT_RUN",
    # A producer cannot declare its own contract absent; it recorded that it
    # did not run this stage.
    "UNWIRED": "NOT_RUN",
    "NOT_REQUIRED": "NOT_APPLICABLE",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
    "PENDING": "PENDING",
    "FAILED": "UNAVAILABLE",
    "UNAVAILABLE": "UNAVAILABLE",
    # COMPLETED without a matched field is not LIVE evidence.
    "COMPLETED": "PARTIAL",
}

_IDENTITY_KEYS = (
    "semantic_key", "checkpoint_id", "outcome_id", "trace_id", "artifact_id",
    "context_id", "lesson_id", "id", "decision_key", "decision_id", "workflow_id",
)
_PENDING_CHECKPOINT = {"SCHEDULED", "OPEN", "OUTCOME_PENDING_DATA", "PENDING", "DUE"}
_NOT_RESOLVABLE_CHECKPOINT = {"NOT_PRICE_RESOLVABLE", "NOT_APPLICABLE", "NOT_REQUIRED"}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _evidence(value: Any) -> bool:
    """True only for a value that can witness a stage: never False/0/""."""
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, (list, tuple, set, dict)):
        return any(_evidence(item) for item in (value.values() if isinstance(value, dict) else value))
    return _text(value).lower() not in {"", "none", "null", "false"}


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if _evidence(value):
            return value
    return None


def _iso(value: Any) -> str | None:
    """Return a parseable ISO timestamp or None (never a guessed clock)."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _timestamp(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "source_as_of", "as_of", "updated_at", "recorded_at", "created_at",
        "occurred_at", "resolved_at", "retrieved_at", "timestamp", "ts",
    ):
        stamp = _iso(row.get(key))
        if stamp:
            return stamp
    return None


def _refs(value: Any) -> list[str]:
    """Normalize source references without treating a string as an iterable."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return sorted({_text(item) for item in value if _text(item)})
    return [_text(value)] if _text(value) else []


def _row_ref(row: dict[str, Any], store: str) -> str | None:
    """A matched row's own reference, else ``store:identity``; never a bare store."""
    own = _first(row, "source_ref", "source_store")
    if isinstance(own, str) and own.strip():
        return own.strip()
    identity = _first(row, *_IDENTITY_KEYS)
    return f"{store}:{_text(identity)}" if identity is not None and not isinstance(identity, (dict, list)) else None


def _stage(
    *,
    state: str,
    state_reason: str,
    composition_as_of: str,
    row: dict[str, Any] | None = None,
    store: str | None = None,
    value: Any = None,
    source_as_of: Any = None,
) -> dict[str, Any]:
    """One stage record; provenance fields come only from the matched row."""
    row = row if isinstance(row, dict) and row else None
    return {
        "state": state if state in VALID_STATES else "UNKNOWN",
        "state_reason": state_reason,
        "producer": _first(row, "producer", "producer_id", "source_surface", "source") if row else None,
        "consumer": _first(row, "consumer", "consumer_id") if row else None,
        "source_ref": _row_ref(row, store or "unknown_store") if row else None,
        "source_as_of": (source_as_of or _timestamp(row)) if row else None,
        "composition_as_of": composition_as_of,
        "evidence_class": _first(row, "evidence_class", "evidence") if row else None,
        "source_sha": _first(row, "source_sha", "source_version", "runtime_source_sha") if row else None,
        "run_id": _first(row, "run_id", "wake_id", "workflow_id") if row else None,
        "trace_id": _first(row, "trace_id", "trace") if row else None,
        "value": value,
    }


def _matched_stage(stage: str, row: dict[str, Any], store: str, value: Any, *, composed: str,
                   source_as_of: Any = None, partial_reason: str | None = None) -> dict[str, Any]:
    """LIVE when the matched row carries a source_ref and parseable source_as_of."""
    rec = _stage(state="LIVE", state_reason="", composition_as_of=composed, row=row, store=store,
                 value=value, source_as_of=source_as_of)
    missing = [name for name in ("source_ref", "source_as_of") if not rec[name]]
    if partial_reason or missing:
        rec["state"] = "PARTIAL"
        reasons = [partial_reason] if partial_reason else []
        if missing:
            reasons.append(f"matched {store} row lacks {', '.join(missing)}")
        rec["state_reason"] = "; ".join(reasons)
    else:
        rec["state_reason"] = f"matched {store} row for this decision"
    return rec


def _latest(rows: Iterable[dict[str, Any]], *, key: str | None = None) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if key and not _text(row.get(key)):
            continue
        found = row
    return found


def _producer_status(envelope: dict[str, Any], key: str | None) -> tuple[str, str] | None:
    if not key:
        return None
    statuses = envelope.get("stage_status")
    if not isinstance(statuses, dict):
        return None
    raw = _text(statuses.get(key)).upper()
    state = _PRODUCER_STATUS.get(raw)
    if not state:
        return None
    return state, f"producer stage_status.{key}={raw}"


def _case_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _case_row(row: dict[str, Any]) -> dict[str, Any]:
    """A production-case event with its own reference: case id plus event type."""
    out = dict(row)
    case_id, event = _text(row.get("case_id")), _text(row.get("event_type")) or _text(row.get("status"))
    if case_id:
        out["source_ref"] = f"{_CASES}:{case_id}#{event}" if event else f"{_CASES}:{case_id}"
    return out


def _case_disposition(row: dict[str, Any]) -> dict[str, Any] | None:
    """Operator disposition recorded on a production case, in either shape it was written."""
    if _text(row.get("event_type")).upper() == "OPERATOR_DISPOSITION":
        value = _case_payload(row).get("operator_disposition") or _case_payload(row)
    else:
        value = row.get("operator_disposition")
    return value if isinstance(value, dict) and _evidence(value.get("disposition")) else None


# Outcome statuses that record "the horizon elapsed and no market result was
# measured". They are a recorded verdict, not a win or loss, so they read
# NOT_APPLICABLE with the producer's own status and reason, mirroring how a
# checkpoint resolved NOT_PRICE_RESOLVABLE is shown.
_NO_MARKET_OUTCOME = {"EXPIRED"}


def _case_outcome_stage(row: dict[str, Any], composed: str) -> dict[str, Any]:
    payload = _case_payload(row)
    status = _text(payload.get("outcome_status")).upper() or "UNSTATED"
    reason = _text(payload.get("reason"))
    horizon = _text(payload.get("evaluation_horizon"))
    as_of = _iso(payload.get("maturity_at")) or _timestamp(row)
    detail = f"production case outcome {status}" + (f": {reason}" if reason else "") + (f" ({horizon} horizon)" if horizon else "")
    if status in _NO_MARKET_OUTCOME or "no_market_outcome" in reason:
        return _stage(state="NOT_APPLICABLE", state_reason=f"{detail}; no market result was measured",
                      composition_as_of=composed, row=row, store=_CASES, value=status, source_as_of=as_of)
    return _matched_stage("outcome", row, _CASES, status, composed=composed, source_as_of=as_of)


def review_metadata_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    """Stage fields an LLM review stored inside ``cio_decisions.metadata``.

    options_cio_review / buy_ready_cio_review persist the model and the review as
    nested JSON, which a top-level key match never sees. Only values the review
    actually recorded are lifted; nothing is derived or defaulted.
    """
    if not isinstance(row, dict):
        return {}
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            import json
            meta = json.loads(meta)
        except ValueError:
            return {}
    if not isinstance(meta, dict):
        return {}
    out: dict[str, Any] = {}
    model = meta.get("model")
    if isinstance(model, dict):
        for key in ("model_used", "provider"):
            if _evidence(model.get(key)):
                out[key] = model[key]
    review = meta.get("review")
    if isinstance(review, dict):
        if _evidence(review.get("confidence")):
            out["confidence"] = review["confidence"]
        if _evidence(review.get("evidence_against")):
            out["counter_case"] = review["evidence_against"]
        if _evidence(review.get("falsifier")):
            out["falsifier"] = review["falsifier"]
    return out


def _row_for_decision(row: dict[str, Any], decision_id: str) -> bool:
    did = _text(row.get("decision_id"))
    return did == decision_id or _text(row.get("workflow_id")) == decision_id


def _for_decision(row: dict[str, Any], did: str) -> bool:
    ids = row.get("decision_ids") or row.get("related_decisions") or []
    return _text(row.get("decision_id")) == did or (isinstance(ids, list) and did in {_text(i) for i in ids})


def _block_available(block: dict[str, Any] | None) -> bool | None:
    """A composed block is unavailable only when every source it read is missing."""
    if not isinstance(block, dict) or not isinstance(block.get("sources"), list) or not block["sources"]:
        return None
    return any(_text(src.get("evidence_class")).upper() != "UNAVAILABLE" for src in block["sources"] if isinstance(src, dict))


def _due_state(row: dict[str, Any], composed: str) -> tuple[str, str]:
    """Horizon maturity of one unresolved checkpoint."""
    due = _iso(row.get("due_at"))
    if not due:
        horizon = _text(row.get("horizon")) or "unstated"
        return "PENDING", f"checkpoint horizon {horizon} has no due_at; not matured"
    try:
        due_at = datetime.fromisoformat(due.replace("Z", "+00:00"))
        now = datetime.fromisoformat(composed.replace("Z", "+00:00"))
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    except ValueError:
        return "UNKNOWN", "checkpoint due_at or composition clock unparseable"
    if due_at > now:
        return "PENDING", f"checkpoint horizon matures at {due}"
    return "PARTIAL", f"checkpoint matured at {due} without a recorded outcome"


def project_decision_lineage(
    decision_id: str,
    *,
    decision: dict[str, Any] | None = None,
    decision_source: str = "cio_decisions",
    workflow_records: Iterable[dict[str, Any]] = (),
    intelligence_records: Iterable[dict[str, Any]] = (),
    checkpoint_records: Iterable[dict[str, Any]] = (),
    disposition_records: Iterable[dict[str, Any]] = (),
    production_case_records: Iterable[dict[str, Any]] = (),
    research_provenance: dict[str, Any] | None = None,
    institutional_cognition: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
    source_availability: dict[str, bool] | None = None,
    composition_as_of: str | None = None,
    identity_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose one exact decision projection from canonical evidence rows.

    ``source_availability`` maps a store label to whether the store could be
    read; an unread store is UNAVAILABLE, never UNKNOWN or LIVE.

    ``identity_resolution`` is a read-time identity-registry lookup for a
    decision whose producer recorded only a symbol. It is consulted after every
    producer row and carries its own ``identity_registry:<guid>`` source_ref, so
    a producer-stamped GUID always wins and a read-time one is never disguised
    as recorded.
    """
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
    cases = [r for r in production_case_records if isinstance(r, dict) and _text(r.get("decision_id")) == did]
    case_outcomes = [_case_row(r) for r in cases if _text(r.get("event_type")).upper() == "OUTCOME_OBSERVED"]
    case_dispositions = [_case_row(r) for r in cases if _case_disposition(r) is not None]

    research = research_provenance if isinstance(research_provenance, dict) else {}
    artifacts = [a for a in research.get("artifacts") or [] if isinstance(a, dict) and _for_decision(a, did)]
    cognition = institutional_cognition if isinstance(institutional_cognition, dict) else {}
    cognition_items = [
        i for i in cognition.get("items") or []
        if isinstance(i, dict) and _for_decision(i, did) and (i.get("retrieved") is True or i.get("used") is True)
    ]
    learn = learning if isinstance(learning, dict) else {}
    lessons = [r for r in learn.get("lessons") or [] if isinstance(r, dict) and _for_decision(r, did)]
    settled = [r for r in learn.get("settled_outcomes") or [] if isinstance(r, dict) and _for_decision(r, did)]
    pending_outcomes = [r for r in learn.get("pending_outcomes") or [] if isinstance(r, dict) and _for_decision(r, did)]

    available: dict[str, bool | None] = {
        _RESEARCH: _block_available(research_provenance),
        _COGNITION: _block_available(institutional_cognition),
        _LEARNING: _block_available(learning),
    }
    available.update({k: bool(v) for k, v in (source_availability or {}).items() if v is not None})

    keyed_rows = ((decision_source, d), (_WORKFLOW, env), (_INTEL, intel), (_CHECKPOINTS, checkpoint))

    def unmatched(stage: str, spec_status: str | None, primary: str, stores: list[str]) -> dict[str, Any]:
        declared = _producer_status(env, spec_status)
        if declared:
            state, reason = declared
            if state == "PARTIAL":
                reason += " but no matched field for this decision"
            return _stage(state=state, state_reason=reason, composition_as_of=composed, row=env, store=_WORKFLOW)
        if stage in UNWIRED_STAGES:
            return _stage(state="UNWIRED", state_reason=UNWIRED_STAGES[stage], composition_as_of=composed)
        if available.get(primary) is False:
            return _stage(state="UNAVAILABLE", state_reason=f"source store {primary} missing or unreadable",
                          composition_as_of=composed)
        searched = ", ".join(dict.fromkeys(stores))
        return _stage(state="UNKNOWN", state_reason=f"no matched row for this decision in {searched}",
                      composition_as_of=composed)

    def keyed(stage: str, *, extra: Iterable[tuple[str, dict[str, Any], Any]] = (),
              rows: Iterable[tuple[str, dict[str, Any]]] = keyed_rows,
              skip: tuple[str, str] | None = None) -> dict[str, Any]:
        keys, partial_keys, status_key, primary = _STAGE_SPECS[stage]
        rows = list(rows)
        # Rows from composed blocks first: they are the canonical stage records.
        for store, row, value in extra:
            return _matched_stage(stage, row, store, value, composed=composed)
        for store, row in rows:
            value = _first(row, *keys) if row else None
            if value is not None:
                return _matched_stage(stage, row, store, value, composed=composed)
        for store, row in rows:
            value = _first(row, *partial_keys) if row and partial_keys else None
            if value is not None:
                return _matched_stage(stage, row, store, value, composed=composed,
                                      partial_reason=f"only {', '.join(partial_keys)} recorded; no result for this decision")
        if skip:
            store, reason = skip
            return _stage(state="NOT_RUN", state_reason=reason, composition_as_of=composed,
                          row=d if store == decision_source else env, store=store)
        return unmatched(stage, status_key, primary, [primary, *(s for s, r in rows if r)])

    stages: dict[str, dict[str, Any]] = {}
    stages["security_identity"] = keyed(
        "security_identity",
        rows=[*keyed_rows, *((("identity_registry", identity_resolution),) if identity_resolution else ())],
    )
    for name in ("wake_event", "office_truth", "canon_frameworks", "research_gap",
                 "specialist_delegation", "specialist_disagreement", "model_route", "judgment",
                 "counter_thesis", "confidence", "falsifier", "notification"):
        stages[name] = keyed(name)

    cognition_refs = d.get("cognition_refs") if isinstance(d.get("cognition_refs"), dict) else {}
    cognition_skip = (
        (decision_source, f"producer recorded cognition_refs.skipped={_text(cognition_refs.get('skipped'))}")
        if _evidence(cognition_refs.get("skipped")) else None
    )
    stages["institutional_cognition"] = keyed(
        "institutional_cognition",
        extra=[(_COGNITION, item, item.get("id")) for item in cognition_items[-1:]],
        skip=cognition_skip,
    )

    def research_extra(statuses: set[str]) -> list[tuple[str, dict[str, Any], Any]]:
        hits = [a for a in artifacts if _text(a.get("status")).upper() in statuses]
        if not hits:
            return []
        return [(_RESEARCH, hits[0], sorted({_text(a.get("artifact_id")) for a in hits}))]

    stages["research_retrieved"] = keyed("research_retrieved", extra=research_extra({"RETRIEVED", "USED_IN_JUDGMENT", "REJECTED"}))
    stages["research_used"] = keyed("research_used", extra=research_extra({"USED_IN_JUDGMENT"}))
    stages["research_rejected"] = keyed("research_rejected", extra=research_extra({"REJECTED"}))

    if disposition:
        stages["operator_disposition"] = _matched_stage("operator_disposition", disposition, _DISPOSITIONS,
                                                        disposition, composed=composed)
    elif case_dispositions:
        row = case_dispositions[-1]
        stages["operator_disposition"] = _matched_stage("operator_disposition", row, _CASES,
                                                        _case_disposition(row), composed=composed)
    else:
        stages["operator_disposition"] = unmatched("operator_disposition", None, _DISPOSITIONS, [_DISPOSITIONS])

    checkpoint_rows = [(_CHECKPOINTS, r) for r in reversed(checkpoints)] + [(_WORKFLOW, env)]
    stages["checkpoint"] = keyed("checkpoint", rows=checkpoint_rows)

    # Outcome: settled outcome > not-resolvable verdict > horizon maturity.
    resolved = [r for r in reversed(checkpoints) if _evidence(r.get("outcome_id")) or _evidence(r.get("outcome"))]
    if resolved:
        row = resolved[0]
        stages["outcome"] = _matched_stage("outcome", row, _CHECKPOINTS, _first(row, "outcome_id", "outcome"),
                                           composed=composed, source_as_of=_iso(row.get("resolved_at")) or _timestamp(row))
    elif settled:
        row = settled[-1]
        stages["outcome"] = _matched_stage("outcome", row, "advisory_outcomes_v1", row.get("outcome_id"), composed=composed)
    elif checkpoints:
        open_rows = [r for r in reversed(checkpoints) if _text(r.get("status")).upper() in _PENDING_CHECKPOINT]
        closed = [r for r in reversed(checkpoints) if _text(r.get("status")).upper() in _NOT_RESOLVABLE_CHECKPOINT]
        if open_rows:
            # The soonest-maturing open checkpoint decides PENDING vs matured.
            graded = [(_due_state(r, composed), r) for r in open_rows]
            pending = [(g, r) for g, r in graded if g[0] == "PENDING"]
            (state, reason), row = (pending or graded)[0]
            rec = _stage(state=state, state_reason=reason, composition_as_of=composed, row=row, store=_CHECKPOINTS)
        elif closed:
            row = closed[0]
            reason = _text(row.get("resolution_reason")) or _text(row.get("status"))
            rec = _stage(state="NOT_APPLICABLE", state_reason=f"checkpoint resolved {_text(row.get('status'))}: {reason}",
                         composition_as_of=composed, row=row, store=_CHECKPOINTS,
                         source_as_of=_iso(row.get("resolved_at")) or _timestamp(row))
        else:
            row = checkpoints[-1]
            rec = _stage(state="UNKNOWN", state_reason=f"checkpoint status {_text(row.get('status')) or 'unstated'} carries no outcome",
                         composition_as_of=composed, row=row, store=_CHECKPOINTS)
        stages["outcome"] = rec
    elif pending_outcomes:
        row = pending_outcomes[-1]
        stages["outcome"] = _stage(state="PENDING", state_reason=f"advisory outcome {_text(row.get('status')) or 'PENDING'} not settled",
                                   composition_as_of=composed, row=row, store="advisory_outcomes_v1")
    elif case_outcomes:
        stages["outcome"] = _case_outcome_stage(case_outcomes[-1], composed)
    else:
        declared = _producer_status(env, "checkpoint")
        if declared and declared[0] == "NOT_RUN":
            stages["outcome"] = _stage(state="NOT_RUN", state_reason=f"no checkpoint to settle ({declared[1]})",
                                       composition_as_of=composed, row=env, store=_WORKFLOW)
        else:
            stages["outcome"] = unmatched("outcome", None, _CHECKPOINTS, [_CHECKPOINTS, _LEARNING])

    stages["belief_calibration_lesson"] = keyed(
        "belief_calibration_lesson",
        extra=[(_LEARNING, row, row.get("lesson_id") or row.get("id")) for row in lessons[-1:]],
    )

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
        "unwired_stages": dict(UNWIRED_STAGES),
        # Additive projection only.  The research block is composed from the
        # canonical research products; it is not a second store and does not
        # make the frontend infer use or rejection.
        "research_provenance": research_provenance,
        "institutional_cognition": institutional_cognition,
        "learning": learning,
        "source_refs": sorted(set(refs)),
        "source_as_of": min((s["source_as_of"] for s in stages.values() if s.get("source_as_of")), default=None),
        "composition_as_of": composed,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "memory_behavior_influence": 0,
        "source_availability": {k: v for k, v in available.items() if v is not None},
        "matched_sources": {
            "workflow_records": len(workflows),
            "intelligence_records": len(intelligence),
            "checkpoint_records": len(checkpoints),
            "disposition_records": len(dispositions),
            "research_artifacts": len(artifacts),
            "cognition_items": len(cognition_items),
        },
    }


def direct_match(decision_id: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only exact decision matches; never fall back to symbol identity."""
    did = _text(decision_id)
    return [row for row in rows if isinstance(row, dict) and _row_for_decision(row, did)]
