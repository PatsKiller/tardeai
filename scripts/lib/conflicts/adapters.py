"""Pure adapters over supplied, identity-confirmed producer rows. No source reads.

The caller obtains canonical facts from cio_truth, not a second store. Producer
timestamps are retained; the poll clock never becomes evidence time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math

from .engine import Finding, Input, Subject, UNKNOWN, evaluate, headline
from .profiles import NumericFactProfile, ScheduleStateProfile, SecurityStanceProfile, _n
from .profiles.rulebook import RULEBOOK


def timestamp(value):
    if not value:
        return None
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return at if at.tzinfo and at.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


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
    subject = Subject("security", str(security_guid or ""), symbol, {"held": held})
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
                                 subject_id=canonical.get("security_guid") or canonical.get("subject_id"))
    card = card or {}
    review = card.get("cio_review") or {}
    if review.get("verdict"):
        result.inputs.append(Input("watchlist CIO review", review["verdict"], timestamp(review.get("completed_at")),
                                   subject_id=review.get("security_guid") or card.get("security_guid")))
    decision = card.get("decision") or {}
    synthesis = decision.get("inputs") or {}
    if synthesis.get("synthesis"):
        result.inputs.append(Input("watchlist_final_synthesis", synthesis["synthesis"],
                                   timestamp(synthesis.get("synthesis_at")), subject_id=card.get("security_guid")))
    if card.get("trade_ai_state"):
        result.inputs.append(Input("trade_ai", card["trade_ai_state"], timestamp(card.get("trade_ai_as_of")),
                                   role="gate", subject_id=card.get("security_guid"), detail="Trade AI checks"))
    if reentry and reentry.get("state"):
        result.inputs.append(Input("reentry_decision_desk", reentry["state"],
                                   timestamp(reentry.get("price_as_of")), subject_id=reentry.get("security_guid")))
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
    return security_inputs(security_guid=truth.get("security_guid"), symbol=truth.get("symbol"),
                           canonical=truth.get("canonical"), held=(truth.get("context") or {}).get("held"),
                           card=card, reentry=reentry, extras=[*protection, *extras])


def numeric_inputs(metric, canonical, readers, *, unit="$", approximate=False):
    """W1 aggregate fields and named reader observations, without recomputing facts.

    Counts compare exactly. Approximation must be explicitly requested per metric.
    Money never has relative tolerance.
    """
    profile = NumericFactProfile(unit=unit, abs_tolerance=0 if unit == "count" else RULEBOOK["numeric_fact"]["abs_tolerance"],
                                 rel_tolerance=RULEBOOK["numeric_fact"]["rel_tolerance"] if approximate else 0)
    def item(row):
        return Input(row["source"], row.get("value"), timestamp(row.get("as_of")), subject_id=row.get("subject_id"))
    return EvaluationInputs(Subject("metric", metric, metric, {"unit": unit}),
                            item(canonical) if canonical else None, [item(r) for r in readers], profile)


def schedule_inputs(lane_id, registry, observations):
    def item(row):
        return Input(row["source"], row.get("state"), timestamp(row.get("as_of")), subject_id=row.get("lane_id"))
    return EvaluationInputs(Subject("job", lane_id, lane_id), item(registry) if registry else None,
                            [item(r) for r in observations], ScheduleStateProfile())


def _data_error(bundle, source, reason, index):
    return Finding("DATA_ERROR", "U1", f"{source}: {reason}", "the producer supplies confirmed identity, vocabulary and time",
                   "notify_operator", "warn", [], f"{bundle.subject.kind}:{bundle.subject.id}:U1adapter:{source}:{index}")


def evaluate_inputs(bundle: EvaluationInputs, *, now: datetime, history=()):
    """Validate producer boundaries, then run the unmodified reference core."""
    if timestamp(now) is None:
        raise ValueError("now must be timezone-aware")
    errors = [_data_error(bundle, "canonical context", reason, n) for n, reason in enumerate(bundle.gaps)]
    if bundle.gaps:
        return errors
    valid = []
    canonical = bundle.canonical
    for n, item in enumerate(([canonical] if canonical else []) + list(bundle.inputs)):
        reason = None
        if item.subject_id and item.subject_id != bundle.subject.id:
            reason = "different subject ID"
        elif timestamp(item.as_of) is None or item.as_of > now:
            reason = "missing, naive or future evidence time"
        elif item.role not in RULEBOOK["universal"]["roles"]:
            reason = "unknown input role"
        elif item.role == "claim" and bundle.profile.compare(item.value, item.value, bundle.subject) == UNKNOWN:
            reason = "unknown claim vocabulary or unit"
        elif isinstance(bundle.profile, NumericFactProfile):
            try:
                if isinstance(item.value, bool) or not math.isfinite(float(item.value)):
                    reason = "non-finite or non-numeric value"
            except (ValueError, TypeError, OverflowError):
                reason = "non-numeric value"
        elif isinstance(bundle.profile, SecurityStanceProfile) and item.role != "claim":
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
    if bundle.canonical and canonical is None:
        return errors
    history = [{**h, "opened_at": timestamp(h.get("opened_at"))} for h in history]
    history = [h for h in history if h["opened_at"] and h["opened_at"] <= now]
    return errors + evaluate(bundle.subject, canonical, [i for i in valid if i is not canonical], bundle.profile,
                             now=now, history=history)


def findings_section(findings, *, gap=None):
    """One read-only section for W1/W7/W9/W4; pages do not classify values."""
    findings = list(findings)
    return {"findings": [f.as_dict() if isinstance(f, Finding) else f for f in findings],
            "headline": headline([f if isinstance(f, Finding) else Finding(**{k: v for k, v in f.items()
                         if k not in {"schema", "engine"}}) for f in findings]), "gap": gap}
