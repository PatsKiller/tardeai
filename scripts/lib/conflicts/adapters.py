"""Pure adapters over supplied, identity-confirmed producer rows. No source reads.

The caller obtains canonical facts from cio_truth, not a second store. Producer
timestamps are retained; the poll clock never becomes evidence time.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
import math

from .engine import Finding, Input, Subject, UNKNOWN, evaluate, headline, finding_sort_key
from .profiles import NumericFactProfile, ScheduleStateProfile, SecurityStanceProfile, _n
from .producers import ownership_facts
from .profiles.rulebook import RULEBOOK


def timestamp(value):
    if not value:
        return None
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at if at.tzinfo and at.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _metadata(raw, metadata=None):
    return {**(metadata or {}), **({"time_error": True} if raw is not None and raw != "" and timestamp(raw) is None else {})}


def _row_time_metadata(row, clock_key, extra=None):
    value = _metadata(row.get(clock_key), extra)
    if "inputs_as_of" in row:
        value = _metadata(row.get("inputs_as_of"), value)
        value["material_time_required"] = True
    return value


@dataclass
class EvaluationInputs:
    subject: Subject
    canonical: Input | None
    inputs: list[Input] = field(default_factory=list)
    profile: object = field(default_factory=SecurityStanceProfile)
    gaps: list[str] = field(default_factory=list)


def security_inputs(*, security_guid, symbol, canonical, held, card=None, reentry=None, extras=()):
    """W1 canonical row + already joined Watch producer rows -> reference inputs.

    ``held=None`` is unknown and refuses stance evaluation; it never means unheld.
    Extras are typed Input observations, including W1's persisted stop states.
    """
    subject = Subject("security" if security_guid else "identity", str(security_guid or symbol or "unresolved"),
                      symbol, {"held": held, "identity_confirmed": bool(security_guid)})
    result = EvaluationInputs(subject, None)
    if not security_guid:
        result.gaps.append("confirmed security GUID unavailable")
    if not isinstance(held, bool):
        result.gaps.append("holding state unknown: canonical identity coverage incomplete")
    canonical = canonical or {}
    value = canonical.get("stance", canonical.get("value"))
    if value is not None:
        source = canonical.get("source")
        result.canonical = Input(source if isinstance(source, str) else "the CIO", value,
                                 timestamp(canonical.get("as_of")),
                                 subject_id=canonical.get("security_guid") or canonical.get("subject_id"),
                                 inputs_as_of=timestamp(canonical.get("inputs_as_of")),
                                 metadata=_row_time_metadata(canonical, "as_of", canonical.get("metadata")))
    card = card or {}
    review = card.get("cio_review") or {}
    if review.get("verdict"):
        result.inputs.append(Input("watchlist CIO review", review["verdict"], timestamp(review.get("completed_at")),
                                   subject_id=review.get("security_guid") or card.get("security_guid"),
                                   inputs_as_of=timestamp(review.get("inputs_as_of")),
                                   metadata=_row_time_metadata(review, "completed_at", {"quality": "complete" if review.get("status", "COMPLETE") == "COMPLETE" else "failed"})))
    decision = card.get("decision") or {}
    synthesis = decision.get("inputs") or {}
    if synthesis.get("synthesis"):
        result.inputs.append(Input("watchlist_final_synthesis", synthesis["synthesis"],
                                   timestamp(synthesis.get("synthesis_at")), subject_id=card.get("security_guid"),
                                   inputs_as_of=timestamp(synthesis.get("inputs_as_of")),
                                   metadata=_row_time_metadata(synthesis, "synthesis_at")))
    if card.get("trade_ai_state"):
        result.inputs.append(Input("trade_ai", card["trade_ai_state"], timestamp(card.get("trade_ai_as_of")),
                                   role="claim" if _n(card["trade_ai_state"]) == "AVOID" else "gate",
                                   subject_id=card.get("security_guid"), detail="Trade AI checks",
                                   metadata=_metadata(card.get("trade_ai_as_of"))))
    if reentry and reentry.get("state"):
        # R1: the desk's age is its oldest material (quote, plan); producer_registry picks the binding one.
        result.inputs.append(Input("reentry_decision_desk", reentry["state"],
                                   timestamp(reentry.get("price_as_of")), subject_id=reentry.get("security_guid"),
                                   metadata=_metadata(reentry.get("price_as_of"), {"materials": {
                                       "quote": reentry.get("price_as_of"), "plan": reentry.get("plan_as_of")}})))
    result.inputs.extend(extras)
    if card.get("symbol") and str(card["symbol"]).upper() != str(symbol).upper():
        result.gaps.append("producer symbol does not match confirmed identity join")
    return result


def security_inputs_from_truth(truth, *, card=None, reentry=None, extras=()):
    """Consume W1.security_inputs_for without inferring ownership or joining symbols."""
    protection = []
    for raw in truth.get("protection_inputs") or []:
        value = _n(raw.get("value"))
        # A held row with an observed filled stop awaits holdings/fill reconciliation.
        if value == "FILLED":
            value = "AWAITING_FILL"
        protection.append(Input(raw["source"], value, timestamp(raw.get("as_of")), role="protection",
                                subject_id=raw.get("subject_id"), account=raw.get("account")))
    # R12: stance/position-vs-fill disagreements the CIO prospect builder saved are ownership DATA_ERROR facts.
    ownership = ownership_facts(truth.get("saved_diagnostics") or [], subject_id=truth.get("security_guid"))
    result = security_inputs(security_guid=truth.get("security_guid"), symbol=truth.get("symbol"),
                           canonical=truth.get("canonical"), held=(truth.get("context") or {}).get("held"),
                           card=card, reentry=reentry, extras=[*protection, *ownership, *extras])
    result.subject.context.update(truth.get("context") or {})
    result.subject.context["conviction"] = truth.get("conviction")
    return result


def numeric_inputs(metric, canonical, readers, *, unit="$", approximate=False):
    """W1 aggregate fields and named reader observations, without recomputing facts.

    Counts compare exactly. Approximation must be explicitly requested per metric.
    Money never has relative tolerance.
    """
    profile = NumericFactProfile(unit=unit, abs_tolerance=RULEBOOK["numeric_fact"]["abs_tolerance"] if unit == "$" else 0,
                                 rel_tolerance=RULEBOOK["numeric_fact"]["rel_tolerance"] if approximate else 0)
    def item(row):
        return Input(row["source"], row.get("value"), timestamp(row.get("as_of")), subject_id=row.get("subject_id"),
                     metadata={"unit": row.get("unit", unit)})
    return EvaluationInputs(Subject("metric", metric, metric, {"unit": unit}),
                            item(canonical) if canonical else None, [item(r) for r in readers], profile)


def schedule_inputs(lane_id, registry, observations):
    def item(row):
        return Input(row["source"], row.get("state"), timestamp(row.get("as_of")), subject_id=row.get("lane_id"))
    return EvaluationInputs(Subject("job", lane_id, lane_id), item(registry) if registry else None,
                            [item(r) for r in observations], ScheduleStateProfile())


def _data_error(bundle, source, reason, index):
    return Finding("DATA_ERROR", "U1", f"{source}: {reason}", "the producer supplies confirmed identity, vocabulary and time",
                   "notify_operator", "warn", [], f"{bundle.subject.kind}:{bundle.subject.id}:U1adapter:{source}:{index}", tier=1)


def evaluate_inputs(bundle: EvaluationInputs, *, now: datetime, history=()):
    """Validate producer boundaries, then run the unmodified reference core."""
    if timestamp(now) is None:
        raise ValueError("now must be timezone-aware")
    errors = [_data_error(bundle, "canonical context", reason, n) for n, reason in enumerate(bundle.gaps)]
    if bundle.gaps and not isinstance(bundle.profile, SecurityStanceProfile):
        return errors
    # R1 producer metadata (cadence, writes_compared_input, binding material time) from the one registry.
    from .producer_registry import annotate_all
    if isinstance(bundle.profile, SecurityStanceProfile):
        annotated = annotate_all(([bundle.canonical] if bundle.canonical else []) + list(bundle.inputs), now=now)
        bundle = EvaluationInputs(bundle.subject, annotated[0] if bundle.canonical else None,
                                  annotated[1:] if bundle.canonical else annotated, bundle.profile, list(bundle.gaps))
    valid = []
    canonical = bundle.canonical
    for n, item in enumerate(([canonical] if canonical else []) + list(bundle.inputs)):
        if item is not canonical and item.role in {"claim", "judgment"} and (
                item.metadata.get("paper") or item.metadata.get("intra_synthesis") or
                item.metadata.get("quality", "complete") != "complete"):
            continue
        reason = None
        if item.subject_id and item.subject_id != bundle.subject.id:
            reason = "different subject ID"
        elif item.metadata.get("time_error") or item.as_of is not None and (timestamp(item.as_of) is None or item.as_of > now):
            reason = "naive, unreadable or future evidence time"
        elif item.role not in RULEBOOK["universal"]["roles"]:
            reason = "unknown input role"
        elif item.role == "claim" and item.metadata.get("instrument", "equity") == "equity" and bundle.profile.compare(item.value, item.value, bundle.subject) == UNKNOWN:
            reason = "unknown claim vocabulary or unit"
        elif isinstance(bundle.profile, NumericFactProfile):
            try:
                if item.metadata.get("unit", bundle.profile.unit) != bundle.profile.unit:
                    reason = "different or unknown numeric unit"
                elif isinstance(item.value, bool) or not math.isfinite(float(item.value)):
                    reason = "non-finite or non-numeric value"
            except (ValueError, TypeError, OverflowError):
                reason = "non-numeric value"
        elif isinstance(bundle.profile, SecurityStanceProfile) and item.role not in {"claim", "judgment", "fact"} and not (
                item.role == "policy" and isinstance(item.value, dict)):
            vocab = RULEBOOK["security_stance"].get(item.role + "_known", [])
            if _n(item.value) not in vocab:
                reason = "unknown role vocabulary"
        if reason:
            errors.append(_data_error(bundle, item.source, reason, n))
            if item is canonical:
                canonical = None
        else:
            valid.append(item)
    # An invalid canonical is a data defect, never a forced owner judgment.
    if bundle.canonical and canonical is None and not isinstance(bundle.profile, SecurityStanceProfile):
        return errors
    history = [{**h, "opened_at": timestamp(h.get("opened_at"))} for h in history]
    history = [h for h in history if "signature" in h or h["opened_at"] and h["opened_at"] <= now]
    rest = [i for i in valid if i is not canonical]
    findings = evaluate(bundle.subject, canonical, rest, bundle.profile, now=now, history=history)
    anchored = _hysteresis_subject(bundle.subject, rest, findings, now=now)
    if anchored is not None:
        findings = evaluate(anchored, canonical, rest, bundle.profile, now=now, history=history)
    return errors + findings


def _hysteresis_subject(subject, inputs, findings, *, now):
    """R15: when the recorded decision's anchor still holds, hand the engine that anchor (else None).

    The anchor is recorded at decision time (ledger.transition -> hysteresis.record_anchor). This checks ACTIONS
    (no anchored side changed, no new disagreeing side) on the engine's own sides for this run; the engine then
    compares conviction against the anchor (RULEBOOK hysteresis.conviction_delta) and keeps the resolution.
    """
    from dataclasses import replace
    from .hysteresis import anchor_holds
    from .profiles.vocabulary import ordinal
    if subject.kind != "security" or subject.context.get("decision_anchor"):
        return None
    decisions = [i for i in inputs if i.metadata.get("recorded_by") in {"operator", "cio"} and i.metadata.get("anchor")
                 and i.metadata.get("reason") and timestamp(i.metadata.get("expires_at")) and
                 timestamp(i.metadata.get("expires_at")) > now]
    if not decisions:
        return None
    decision = min(decisions, key=lambda i: 0 if i.metadata["recorded_by"] == "operator" else 1)
    anchor = decision.metadata["anchor"]
    held = subject.context.get("held")
    for finding in findings:
        if finding.rule not in {"R15", "U7", "R11"} or finding.kind not in {"AGREEMENT", "CONFLICT", "NEEDS_OPERATOR"}:
            continue
        if not any(side.get("source") == decision.source for side in finding.sides):
            continue
        if not anchor_holds(anchor, finding.sides, held):
            return None
        signature = sorted([side["source"], ordinal(side["value"], held)] for side in finding.sides)
        value = {"signature": signature, "recorded_at": decision.as_of.isoformat() if decision.as_of else None}
        if isinstance(anchor.get("conviction"), (int, float)) and not isinstance(anchor.get("conviction"), bool):
            value["conviction"] = anchor["conviction"]
        return replace(subject, context={**subject.context, "decision_anchor": value})
    return None


def findings_section(findings, *, gap=None):
    """One read-only section for W1/W7/W9/W4; pages do not classify values."""
    allowed = {f.name for f in fields(Finding)}
    pairs = [(f, f.as_dict()) if isinstance(f, Finding) else
             (Finding(**{k: v for k, v in f.items() if k in allowed}), dict(f)) for f in findings]
    pairs.sort(key=lambda pair: finding_sort_key(pair[0]))
    return {"findings": [pair[1] for pair in pairs], "headline": headline(pair[0] for pair in pairs), "gap": gap}


def concentration_inputs(rows):
    """W1 limits plus W7 numeric exposures; classification remains in the profile."""
    return [Input(row.get("source") or "canonical look-through", {k: row.get(k) for k in
                  ("exposure_pct", "limit_pct", "near_limit_pct", "near_pct", "gap", "instrument_class", "limit_key", "approval_ref")},
                  timestamp(row.get("as_of")), role="policy", subject_id=row.get("security_guid"),
                  account=row.get("account"), detail=row.get("label")) for row in rows]
