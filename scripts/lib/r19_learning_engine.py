"""R19 — Institutional learning engine (propose only).

Pipeline: decision → outcome → attribution → pattern → lesson candidate →
hypothesis → preregistered shadow experiment → evaluation → REVIEW_READY.

The engine never performs OPERATOR_AUTHORIZED. Activation default OFF.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_forward_program import (
    AUTHORITY,
    MBI,
    PROMOTION_CEILING,
    gated_live_run,
    require_evidence_class,
)
from scripts.lib.cio_institutional_learning import (
    hypothesis_from_lesson,
    identity_safe_subject,
    lesson_candidate_v2,
    preregister,
    promotion_advance,
    shadow_experiment,
)

SCHEMA = "InstitutionalLearningRecord@v1"
STAGES = (
    "CANDIDATE",
    "SHADOW",
    "EVALUATED",
    "REVIEW_READY",
    "OPERATOR_AUTHORIZED",
)
# Map onto the R16 firewall vocabulary.
_STAGE_TO_R16 = {
    "CANDIDATE": "CANDIDATE",
    "SHADOW": "SHADOW_TESTED",
    "EVALUATED": "SHADOW_TESTED",
    "REVIEW_READY": "REVIEW_READY",
    "OPERATOR_AUTHORIZED": "OPERATOR_APPROVED",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_learning_record(
    *,
    decision: dict[str, Any],
    outcome: dict[str, Any],
    statement: str,
    supporting_outcome_ids: list[str],
    counterexamples: list[str] | None,
    searched_counterexamples: bool,
    evidence_class: str,
    universe_row: dict[str, Any] | None = None,
    research_artifact_ids: list[str] | None = None,
    catalyst_guids: list[str] | None = None,
    model_lane: str | None = None,
    prompt_or_code_version: str | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R19", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    subject = identity_safe_subject(outcome) or identity_safe_subject(decision)
    lesson = lesson_candidate_v2(
        scope="security" if subject else "unresolved_identity",
        task_class=str(decision.get("recommendation") or "UNKNOWN"),
        statement=statement,
        supporting_outcome_ids=supporting_outcome_ids,
        counterexamples=counterexamples,
        searched_counterexamples=searched_counterexamples,
    )
    hyp = hypothesis_from_lesson(
        lesson,
        claim=statement,
        baseline="current_behavior",
        candidate="proposed_behavior",
        metric="observed_quality",
        population=str(subject or "unresolved"),
    )
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "stage": "CANDIDATE",
        "promotion_ceiling": PROMOTION_CEILING,
        "decision_id": decision.get("decision_id"),
        "outcome_id": outcome.get("outcome_id"),
        "subject_guid": subject,
        "ticker_alias": (universe_row or {}).get("symbol") or decision.get("symbol"),
        "sector": (universe_row or {}).get("sector"),
        "industry": (universe_row or {}).get("industry"),
        "catalyst_guids": list(catalyst_guids or (universe_row or {}).get("catalyst_guids") or []),
        "research_artifact_ids": list(research_artifact_ids or []),
        "model_lane": model_lane,
        "prompt_or_code_version": prompt_or_code_version or decision.get("runtime_source_sha"),
        "lesson": lesson,
        "hypothesis": hyp,
        "auto_policy": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }


def advance_learning_stage(
    record: dict[str, Any],
    target: str,
    *,
    operator_authorized: bool = False,
    control: list[dict[str, Any]] | None = None,
    candidate: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out = dict(record)
    current = str(out.get("stage") or "CANDIDATE")
    if target not in STAGES:
        return {**out, "ok": False, "reason": "unknown_stage"}
    r16_target = _STAGE_TO_R16[target]
    r16_current = _STAGE_TO_R16.get(current, "CANDIDATE")
    step = promotion_advance(r16_current, r16_target, operator_authorized=operator_authorized)
    if not step.get("ok"):
        out["ok"] = False
        out["reason"] = step.get("reason")
        out["stage"] = current
        return out
    if target == "SHADOW":
        hyp = out.get("hypothesis") or {}
        prereg = preregister(
            hyp,
            primary_metric="observed_quality",
            success_threshold=0.05,
            sample_count=max(len(control or []), len(candidate or []), 1),
            cost_ceiling=0.0,
        )
        out["hypothesis"] = prereg
        out["experiment"] = None
    if target in {"EVALUATED", "REVIEW_READY"} and control is not None and candidate is not None:
        hyp = out.get("hypothesis") or {}
        if not hyp.get("preregistered"):
            hyp = preregister(hyp, primary_metric="observed_quality", success_threshold=0.05, sample_count=5, cost_ceiling=0.0)
            out["hypothesis"] = hyp
        out["experiment"] = shadow_experiment(
            control=control, candidate=candidate, metric="observed_quality", prereg=hyp,
        )
    out["ok"] = True
    out["stage"] = target
    out["auto_policy"] = False
    out["authority"] = AUTHORITY
    return out
