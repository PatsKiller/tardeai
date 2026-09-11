"""C1 — deterministic material residual question gate (pre-model).

Proceeds to a paid L3 model call only when Lane B GroundedJudgmentInput@v1
satisfies identity, grounding, free-first research, material residual question,
evidence sufficiency/freshness, budget/cap, and off-peak (or urgent) rules.

Otherwise persists an explicit durable state — never a model judgment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from scripts.lib.judgment_schema import (
    CAP_REFUSED,
    EVIDENCE_INSUFFICIENT,
    FREE_FIRST_PENDING,
    GATE_PROCEED,
    NO_MATERIAL_RESIDUAL,
    OFFPEAK_DEFERRED,
    SCHEMA_INVALID,
    UNGROUNDED_REFUSED,
    WRONG_SUBJECT_REFUSED,
    GateDecision,
    JudgmentSchemaError,
    validate_grounded_input,
)
from scripts.lib.model_policy import (
    L3ModelPolicy,
    default_l3_policy,
    evaluate_offpeak_eligibility,
    evaluate_urgent_materiality,
)


def _as_of(grounded: Mapping[str, Any], now: datetime | None) -> datetime:
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    raw = grounded.get("as_of_utc")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _subject_resolved(subject: Mapping[str, Any], policy: L3ModelPolicy) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    guid = str(subject.get("subject_guid") or "").strip()
    if not guid:
        reasons.append("subject_guid_unresolved")
    try:
        conf = float(subject.get("resolution_confidence", 0))
    except (TypeError, ValueError):
        conf = -1.0
        reasons.append("resolution_confidence_invalid")
    if conf < policy.min_resolution_confidence:
        reasons.append("subject_ambiguous_or_low_confidence")
    kind = str(subject.get("subject_kind") or "").strip()
    if kind and kind not in policy.allowed_subject_kinds:
        reasons.append("subject_kind_not_allowed")
    return (not reasons), reasons


def _select_subject_facts(
    grounded: Mapping[str, Any],
    policy: L3ModelPolicy,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    subject = grounded.get("subject") or {}
    subject_guid = str(subject.get("subject_guid") or "")
    selected: list[dict[str, Any]] = []
    reasons: list[str] = []
    ages: list[float] = []
    decays: list[float] = []
    contradictions_visible: list[dict[str, Any]] = []

    for fact in grounded.get("memory_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        fg = str(fact.get("subject_guid") or "").strip()
        if fg and fg != subject_guid:
            continue  # wrong-subject handled separately
        try:
            decay = float(fact.get("decay_weight", 0))
        except (TypeError, ValueError):
            decay = 0.0
        try:
            age = float(fact.get("age_hours", 0))
        except (TypeError, ValueError):
            age = 0.0
        if decay < policy.min_decay_weight_for_selection:
            continue
        if age > policy.max_fact_age_hours:
            # Still visible for evidence panel, but not selected as grounding.
            contradictions_visible.append(
                {
                    "memory_fact_id": fact.get("memory_fact_id"),
                    "note": "stale_beyond_max_age",
                    "age_hours": age,
                    "decay_weight": decay,
                }
            )
            continue
        selected.append(dict(fact))
        ages.append(age)
        decays.append(decay)
        contr = fact.get("contradiction") if isinstance(fact.get("contradiction"), Mapping) else {}
        state = str(contr.get("state") or "none")
        if state not in ("", "none"):
            contradictions_visible.append(
                {
                    "memory_fact_id": fact.get("memory_fact_id"),
                    "contradiction_state": state,
                    "counterpart_fact_ids": list(contr.get("counterpart_fact_ids") or []),
                    "age_hours": age,
                    "decay_weight": decay,
                }
            )

    visible = {
        "selected_count": len(selected),
        "age_hours_min": min(ages) if ages else None,
        "age_hours_max": max(ages) if ages else None,
        "decay_weight_min": min(decays) if decays else None,
        "decay_weight_max": max(decays) if decays else None,
        "contradictions": contradictions_visible,
        "retrieval": dict(grounded.get("retrieval") or {}),
    }
    if not selected:
        reasons.append("no_subject_specific_memory_selected")
    return selected, reasons, visible


def evaluate_material_residual_gate(
    raw_input: Any,
    *,
    policy: L3ModelPolicy | None = None,
    now: datetime | None = None,
    budget_remaining_usd: float | None = None,
    model_available: bool = True,
    lane_calls_remaining: int | None = None,
    request_cap_remaining: int | None = None,
) -> GateDecision:
    """Deterministic pre-model gate. Zero provider calls from this function."""
    policy = policy or default_l3_policy()
    try:
        grounded = validate_grounded_input(raw_input)
    except JudgmentSchemaError as exc:
        return GateDecision(
            state=SCHEMA_INVALID,
            proceed=False,
            reasons=[str(exc)],
            provider_calls_allowed=0,
        )

    subject = grounded.get("subject") or {}
    ok_subj, subj_reasons = _subject_resolved(subject, policy)
    if not ok_subj:
        return GateDecision(
            state=UNGROUNDED_REFUSED,
            proceed=False,
            reasons=subj_reasons,
            provider_calls_allowed=0,
        )

    wrong_ids = list(grounded.get("_wrong_subject_fact_ids") or [])
    retrieval = grounded.get("retrieval") or {}
    filtered_wrong = int(retrieval.get("filtered_wrong_subject") or 0)
    if wrong_ids:
        return GateDecision(
            state=WRONG_SUBJECT_REFUSED,
            proceed=False,
            reasons=[f"wrong_subject_facts:{','.join(wrong_ids[:8])}"],
            provider_calls_allowed=0,
            evidence_visible={"wrong_subject_fact_ids": wrong_ids, "filtered_wrong_subject": filtered_wrong},
        )

    # Grounding hard precondition
    grounded_flag = bool(grounded.get("grounded"))
    facts = grounded.get("memory_facts") or []
    selected, sel_reasons, visible = _select_subject_facts(grounded, policy)

    mrq = grounded.get("material_residual_question") or {}
    question_class = str(mrq.get("question_class") or mrq.get("class") or "default")
    research_only_ok = question_class in policy.research_only_question_classes

    if not grounded_flag or (not selected and not research_only_ok):
        return GateDecision(
            state=UNGROUNDED_REFUSED,
            proceed=False,
            reasons=["grounded_false_or_empty_memory"] + sel_reasons,
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    research = grounded.get("research") or {}
    if research.get("free_first_exhausted") is not True:
        return GateDecision(
            state=FREE_FIRST_PENDING,
            proceed=False,
            reasons=["free_first_not_exhausted"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    # If free-first research already answered the residual (effect none + present false)
    present = bool(mrq.get("present"))
    question_text = (mrq.get("question_text") or None) if present else None
    if not present or not str(question_text or "").strip():
        return GateDecision(
            state=NO_MATERIAL_RESIDUAL,
            proceed=False,
            reasons=["no_named_material_residual_question"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    # Evidence sufficiency / freshness thresholds
    if len(selected) < policy.min_selected_facts and not research_only_ok:
        return GateDecision(
            state=EVIDENCE_INSUFFICIENT,
            proceed=False,
            reasons=[f"selected_facts<{policy.min_selected_facts}"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            evidence_visible=visible,
            provider_calls_allowed=0,
        )
    if policy.require_fact_text_for_model and not research_only_ok:
        with_text = [f for f in selected if str(f.get("fact_text") or "").strip()]
        if not with_text:
            return GateDecision(
                state=EVIDENCE_INSUFFICIENT,
                proceed=False,
                reasons=["fact_text_absent_for_model"],
                selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
                evidence_visible={
                    **visible,
                    "note": "Lane B digest-only input; wake must call build_grounded_judgment_input(include_fact_text=True) for L3",
                },
                provider_calls_allowed=0,
            )
    if (
        visible.get("decay_weight_max") is not None
        and float(visible["decay_weight_max"]) < policy.min_evidence_freshness_decay
    ):
        return GateDecision(
            state=EVIDENCE_INSUFFICIENT,
            proceed=False,
            reasons=["evidence_freshness_below_threshold"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    # Caps
    if budget_remaining_usd is not None and budget_remaining_usd <= 0:
        return GateDecision(
            state=CAP_REFUSED,
            proceed=False,
            reasons=["budget_remaining_usd<=0"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            material_question=str(question_text),
            evidence_visible=visible,
            provider_calls_allowed=0,
        )
    if lane_calls_remaining is not None and lane_calls_remaining <= 0:
        return GateDecision(
            state=CAP_REFUSED,
            proceed=False,
            reasons=["lane_call_cap_exhausted"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            material_question=str(question_text),
            evidence_visible=visible,
            provider_calls_allowed=0,
        )
    if request_cap_remaining is not None and request_cap_remaining <= 0:
        return GateDecision(
            state=CAP_REFUSED,
            proceed=False,
            reasons=["request_cap_exhausted"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            material_question=str(question_text),
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    if not model_available:
        return GateDecision(
            state="MODEL_UNAVAILABLE",
            proceed=False,
            reasons=["model_unavailable"],
            selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
            material_question=str(question_text),
            evidence_visible=visible,
            provider_calls_allowed=0,
        )

    when = _as_of(grounded, now)
    offpeak = evaluate_offpeak_eligibility(when, policy=policy)
    trigger = str(grounded.get("trigger") or "").strip().lower()
    urgent_ok = False
    urgent_reasons: list[str] = []
    if not offpeak.eligible:
        # Urgent exception requires deterministic materiality — not caller prose.
        urgent_ok, urgent_reasons = evaluate_urgent_materiality(grounded, policy=policy)
        if trigger != "urgent" or not urgent_ok:
            return GateDecision(
                state=OFFPEAK_DEFERRED,
                proceed=False,
                reasons=[offpeak.reason] + (urgent_reasons if trigger == "urgent" else ["trigger_not_urgent"]),
                selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
                material_question=str(question_text),
                evidence_visible={**visible, "offpeak": offpeak.to_dict(), "urgent": urgent_reasons},
                provider_calls_allowed=0,
            )

    return GateDecision(
        state=GATE_PROCEED,
        proceed=True,
        reasons=["eligible"] + ([f"urgent:{r}" for r in urgent_reasons] if urgent_ok else []),
        material_question=str(question_text),
        selected_memory_fact_ids=[str(f.get("memory_fact_id")) for f in selected],
        evidence_visible={**visible, "offpeak": offpeak.to_dict()},
        provider_calls_allowed=2,  # author + critic
    )
