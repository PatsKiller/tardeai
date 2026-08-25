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
import hashlib
from pathlib import Path

from scripts.lib.cio_institutional_learning import (
    MIN_LESSON_SAMPLES,
    hypothesis_from_lesson,
    identity_safe_subject,
    lesson_candidate_v2,
    preregister,
    promotion_advance,
    shadow_experiment,
)
from scripts.lib.cio_model_learning import snapshot_registries

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
    if len(supporting_outcome_ids) < MIN_LESSON_SAMPLES:
        return {
            "schema": SCHEMA,
            "evidence_class": cls,
            "status": "INSUFFICIENT_EVIDENCE",
            "stage": None,
            "lesson": None,
            "hypothesis": None,
            "supporting_outcome_ids": list(supporting_outcome_ids),
            "auto_policy": False,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
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


def registry_fingerprint(root: Path | str) -> dict[str, str]:
    snap = snapshot_registries(root)
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in snap.items()}


def replay_learning_pipeline(
    *,
    outcomes: list[dict[str, Any]],
    evidence_class: str,
    statement: str,
    train_cutoff: str,
    repo_root: Path | str,
    recommendation: str | None = None,
) -> dict[str, Any]:
    """Train/eval split by observed_at. Preregister before evaluation. No registry writes."""
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R19", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    from scripts.lib.cio_institutional_learning import _parse_ts
    cutoff = _parse_ts(train_cutoff)
    train, evaluate = [], []
    for row in outcomes:
        ts = _parse_ts(row.get("observed_at") or row.get("source_as_of"))
        rec = str(row.get("recommendation") or (row.get("original_decision_state") or {}).get("recommendation") or recommendation or "")
        item = dict(row)
        item["_recommendation"] = rec
        if cutoff and ts and ts < cutoff:
            train.append(item)
        else:
            evaluate.append(item)
    support = [str(r.get("outcome_id")) for r in train if r.get("outcome_id")]
    contra = [str(r.get("outcome_id")) for r in train if r.get("counterexample")]
    before = registry_fingerprint(repo_root)
    if len(support) < MIN_LESSON_SAMPLES:
        after = registry_fingerprint(repo_root)
        return {
            "schema": SCHEMA,
            "evidence_class": cls,
            "status": "INSUFFICIENT_EVIDENCE",
            "lesson": None,
            "hypothesis": None,
            "supporting_outcome_ids": support,
            "train_n": len(train),
            "eval_n": len(evaluate),
            "train_cutoff": train_cutoff,
            "windows_overlap": False,
            "registry_hash_before": before,
            "registry_hash_after": after,
            "registry_unchanged": before == after,
            "auto_policy": False,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
    decision = {
        "decision_id": train[0].get("decision_id"),
        "recommendation": train[0].get("_recommendation") or "UNKNOWN",
        "security_guid": identity_safe_subject(train[0]),
        "runtime_source_sha": train[0].get("runtime_source_sha"),
    }
    rec = build_learning_record(
        decision=decision,
        outcome=train[0],
        statement=statement,
        supporting_outcome_ids=support,
        counterexamples=contra,
        searched_counterexamples=True,
        evidence_class=cls,
    )
    rec = advance_learning_stage(rec, "SHADOW")
    if not evaluate:
        after = registry_fingerprint(repo_root)
        rec["status"] = "INSUFFICIENT_EVIDENCE"
        rec["stage"] = "SHADOW"
        rec["reason"] = "NO_HOLDOUT_WINDOW"
        rec["lesson"] = rec.get("lesson")
        rec["supporting_outcome_ids"] = support
        rec["train_n"] = len(train)
        rec["eval_n"] = 0
        rec["train_cutoff"] = train_cutoff
        rec["windows_overlap"] = False
        rec["registry_hash_before"] = before
        rec["registry_hash_after"] = after
        rec["registry_unchanged"] = before == after
        rec["auto_policy"] = False
        return rec
    control = [{"observed_quality": float(r.get("observed_quality") or (1.0 if (r.get("realized_state") or {}).get("linked") else 0.0))} for r in train]
    candidate = [{"observed_quality": float(r.get("observed_quality") or (1.0 if (r.get("realized_state") or {}).get("linked") else 0.0))} for r in evaluate]
    rec = advance_learning_stage(rec, "EVALUATED", control=control, candidate=candidate)
    rec = advance_learning_stage(rec, "REVIEW_READY", control=control, candidate=candidate)
    after = registry_fingerprint(repo_root)
    rec["status"] = "REVIEW_READY"
    rec["supporting_outcome_ids"] = support
    rec["contradictory_visible"] = bool(contra)
    rec["train_n"] = len(train)
    rec["eval_n"] = len(evaluate)
    rec["train_cutoff"] = train_cutoff
    rec["windows_overlap"] = False
    rec["registry_hash_before"] = before
    rec["registry_hash_after"] = after
    rec["registry_unchanged"] = before == after
    rec["auto_policy"] = False
    blocked = advance_learning_stage(rec, "OPERATOR_AUTHORIZED")
    rec["self_authorize_blocked"] = blocked.get("ok") is False
    return rec
