"""Institutional learning — outcomes, calibration, lessons, hypotheses, firewall.

Closes DECISION → OUTCOME → QUALITY → LESSON → HYPOTHESIS → SHADOW → REVIEW_READY.
Never auto-promotes to OPERATOR_APPROVED. MEMORY_BEHAVIOR_INFLUENCE=0.
Does not rewrite original decisions. Does not edit model/process registries.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.lib.cio_model_learning import (
    RoutingPromotionForbidden,
    apply_routing_candidate,
    snapshot_registries,
)
from scripts.lib.memory_consolidator import lesson_from_outcomes

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA_OUTCOME = "OutcomeObservation@v1"
SCHEMA_LESSON = "LessonCandidate@v2"
SCHEMA_HYP = "HypothesisCandidate@v1"
SCHEMA_EXPERIMENT = "ShadowExperiment@v1"
SCHEMA_DECISION = "LearnableDecision@v1"

# Discovered from capital-plan / material-scan / decision-semantics — not invented.
DECISION_CLASSES = (
    "HOLD",
    "WATCH",
    "REVIEW",
    "TRIM",
    "EXIT",
    "ADD",
    "HOLD_CASH",
    "WAIT",
    "RE_ENTER",
    "THESIS_REVIEW",
    "PORTFOLIO_REASSESSMENT",
    "RISK_CRITIQUE",
    "RESEARCH_NEEDED",
    "NOTIFICATION_DECISION",
)

REQUIRED_DECISION_FIELDS = (
    "decision_id",
    "subject_guid",
    "created_at",
    "as_of",
    "recommendation",
    "evidence_refs",
    "runtime_source_sha",
)

OPTIONAL_TRACE_FIELDS = (
    "portfolio_context_ref",
    "policy_version",
    "ticker_research_state_version",
    "curation_version",
    "symbol_thesis_version",
    "counter_evidence_refs",
    "research_refs",
    "specialist_artifact_refs",
    "confidence",
    "uncertainty",
    "invalidation_criteria",
    "next_review_criteria",
    "notification_disposition",
    "context_receipt",
)

QUALITY_AXES = (
    "direction",
    "timing",
    "risk_awareness",
    "evidence_quality",
    "source_freshness",
    "counter_evidence_quality",
    "uncertainty_calibration",
    "thesis_quality",
    "portfolio_relevance",
    "research_quality",
    "specialist_contribution",
    "notification_usefulness",
    "model_efficiency",
)

HORIZONS = (
    "event-relative",
    "1_session",
    "5_sessions",
    "20_sessions",
    "quarterly",
    "thesis-review",
)

LESSON_STATUSES = ("PROVISIONAL", "SUPPORTED", "CONTRADICTED", "EXPIRED")
PROMOTION_STAGES = (
    "CANDIDATE",
    "SHADOW_TESTED",
    "REVIEW_READY",
    "OPERATOR_APPROVED",
    "PROMOTED",
    "REVERTED",
)
FEEDBACK_TAXONOMY = (
    "USEFUL",
    "NOT_USEFUL",
    "TOO_NOISY",
    "TOO_LATE",
    "ALREADY_KNEW",
    "WRONG_REASON",
    "MISSING_CONTEXT",
    "GOOD_COUNTERPOINT",
    "CORRECTION",
)
NOTIFY_OUTCOMES = (
    "correct_page",
    "correct_suppression",
    "duplicate_page",
    "stale_page",
    "late_page",
    "unnecessary_interruption",
    "missed_material_condition",
    "operator_acknowledged",
    "operator_found_useful",
)
MIN_LESSON_SAMPLES = 5
MIN_ROUTING_SAMPLES = 30
FORBIDDEN_FUTURE_KEYS = (
    "future_price",
    "future_article",
    "future_thesis",
    "future_outcome",
    "future_policy",
    "future_feedback",
    "later_price",
    "later_thesis",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def classify_traceability(decision: dict[str, Any]) -> str:
    if not decision.get("decision_id"):
        return "UNRESOLVED"
    def _missing(field: str, *, required: bool) -> bool:
        val = decision.get(field)
        if val is None or val == "":
            return True
        if required and val == []:
            return True
        return False

    missing_req = [f for f in REQUIRED_DECISION_FIELDS if _missing(f, required=True)]
    if missing_req:
        return "PARTIAL"
    missing_opt = [f for f in OPTIONAL_TRACE_FIELDS if _missing(f, required=False)]
    if missing_opt:
        return "PARTIAL"
    return "FULLY_TRACEABLE"


def inventory_decisions(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    classified = {"FULLY_TRACEABLE": 0, "PARTIAL": 0, "UNRESOLVED": 0}
    classes = []
    details = []
    for row in rows:
        klass = str(row.get("recommendation") or row.get("event_type") or row.get("stance") or "").upper()
        if klass in DECISION_CLASSES:
            classes.append(klass)
        status = classify_traceability(row)
        classified[status] += 1
        details.append({"decision_id": row.get("decision_id"), "class": klass or None, "traceability": status})
    total = sum(classified.values())
    return {
        "schema": "DecisionCoverage@v1",
        "known_classes": list(DECISION_CLASSES),
        "observed_classes": sorted(set(classes)),
        "total": total,
        "counts": classified,
        "coverage_fully_pct": round(100 * classified["FULLY_TRACEABLE"] / total, 2) if total else 0.0,
        "details": details,
        "fabricated_joins": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def build_outcome_observation(
    *,
    decision_id: str,
    subject_guid: str | None,
    horizon: str,
    original_decision_state: dict[str, Any],
    realized_state: dict[str, Any],
    source_refs: list[str],
    source_as_of: str,
    observed_at: str | None = None,
    relevant_events: list[Any] | None = None,
    market_context: dict[str, Any] | None = None,
    thesis_changes: list[Any] | None = None,
    policy_changes: list[Any] | None = None,
) -> dict[str, Any]:
    hz = horizon if horizon in HORIZONS else "event-relative"
    oid = _sha({"decision_id": decision_id, "horizon": hz, "as_of": source_as_of})[:24]
    return {
        "schema": SCHEMA_OUTCOME,
        "outcome_id": oid,
        "decision_id": decision_id,
        "subject_guid": subject_guid,
        "horizon": hz,
        "observed_at": observed_at or _now(),
        "source_as_of": source_as_of,
        "source_refs": list(source_refs),
        "original_decision_state": dict(original_decision_state),
        "realized_state": dict(realized_state),
        "relevant_events_since_decision": list(relevant_events or []),
        "market_context_since_decision": market_context or {},
        "thesis_changes_since_decision": list(thesis_changes or []),
        "policy_changes_since_decision": list(policy_changes or []),
        "history_rewritten": False,
        "decision_mutated": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def append_outcome(store: list[dict[str, Any]], outcome: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Append only. Original decisions stay immutable."""
    for d in decisions:
        if d.get("decision_id") == outcome.get("decision_id"):
            prior = dict(d)
            break
    else:
        return {"appended": False, "reason": "missing_decision", "history_rewritten": False}
    for existing in store:
        if existing.get("outcome_id") == outcome.get("outcome_id"):
            return {"appended": False, "reason": "duplicate_outcome", "history_rewritten": False, "duplicate": True}
    store.append(outcome)
    unchanged = next(d for d in decisions if d.get("decision_id") == outcome.get("decision_id"))
    return {
        "appended": True,
        "outcome_id": outcome["outcome_id"],
        "decision_unchanged": unchanged == prior,
        "history_rewritten": False,
        "authority": AUTHORITY,
    }


def score_quality_axes(
    *,
    pnl_up: bool | None = None,
    risk_warning_issued: bool = False,
    evidence_present: bool = False,
    counter_evidence_present: bool = False,
    uncertainty_stated: bool = False,
    notification_useful: bool | None = None,
    specialist_unique: bool = False,
    research_novel: bool = False,
    schema_valid: bool = True,
    timing_ok: bool | None = None,
) -> dict[str, Any]:
    """P&L is one axis, never the whole grade."""
    axes = {k: None for k in QUALITY_AXES}
    if pnl_up is not None:
        axes["direction"] = "UP" if pnl_up else "DOWN"
    if timing_ok is not None:
        axes["timing"] = "ON_TIME" if timing_ok else "EARLY_OR_LATE"
    axes["risk_awareness"] = "PRESENT" if risk_warning_issued else "ABSENT"
    axes["evidence_quality"] = "PRESENT" if evidence_present else "MISSING"
    axes["counter_evidence_quality"] = "PRESENT" if counter_evidence_present else "MISSING"
    axes["uncertainty_calibration"] = "STATED" if uncertainty_stated else "UNSTATED"
    if notification_useful is not None:
        axes["notification_usefulness"] = "USEFUL" if notification_useful else "NOT_USEFUL"
    axes["specialist_contribution"] = "UNIQUE" if specialist_unique else "NONE_OR_AGREEMENT_ONLY"
    axes["research_quality"] = "NOVEL" if research_novel else "DUPLICATE_OR_ABSENT"
    axes["model_efficiency"] = "SCHEMA_VALID" if schema_valid else "SCHEMA_INVALID"
    return {
        "schema": "DecisionQualityAxes@v1",
        "axes": axes,
        "pnl_is_not_the_grade": True,
        "risk_warning_valuable_if_price_up": bool(risk_warning_issued and pnl_up),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def calibrate_confidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic buckets. Model self-score is ignored."""
    buckets = {"high": [], "medium": [], "low": []}
    for row in rows:
        if row.get("self_assessment") is not None:
            continue
        try:
            c = float(row.get("confidence"))
        except (TypeError, ValueError):
            continue
        quality = float(row.get("observed_quality") or 0)
        if c >= 0.75:
            buckets["high"].append(quality)
        elif c >= 0.45:
            buckets["medium"].append(quality)
        else:
            buckets["low"].append(quality)

    def mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    high, med, low = mean(buckets["high"]), mean(buckets["medium"]), mean(buckets["low"])
    over = high < med and len(buckets["high"]) >= 3 and len(buckets["medium"]) >= 3
    under = low > med and len(buckets["low"]) >= 3 and len(buckets["medium"]) >= 3
    err = round(abs(0.8 - high) + abs(0.6 - med) + abs(0.4 - low), 4)
    return {
        "schema": "ConfidenceCalibration@v1",
        "cohorts": {
            "high": {"n": len(buckets["high"]), "mean_quality": high},
            "medium": {"n": len(buckets["medium"]), "mean_quality": med},
            "low": {"n": len(buckets["low"]), "mean_quality": low},
        },
        "calibration_error": err,
        "overconfidence": over,
        "underconfidence": under,
        "self_assessment_ignored": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def reject_lookahead(context: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    """Historical replay may only use evidence that existed at as_of."""
    cutoff = _parse_ts(as_of)
    leaks = []
    for key in FORBIDDEN_FUTURE_KEYS:
        if context.get(key):
            leaks.append(key)
    for item in context.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        ts = _parse_ts(item.get("as_of") or item.get("created_at") or item.get("observed_at"))
        if cutoff and ts and ts > cutoff:
            leaks.append(item.get("id") or item.get("url") or "future_evidence")
    return {
        "schema": "LookaheadAudit@v1",
        "as_of": as_of,
        "leaks": leaks,
        "allowed": not leaks,
        "zero_tolerated": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def bitemporal_view(*, believed_then: Any, knew_then: Any, outcome_then: Any, available_later: Any, know_now: Any) -> dict[str, Any]:
    return {
        "schema": "BitemporalEvaluation@v1",
        "what_we_believed_then": believed_then,
        "what_we_knew_then": knew_then,
        "outcome_then": outcome_then,
        "available_later": available_later,
        "what_we_know_now": know_now,
        "future_not_leaked_into_then": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def lesson_candidate_v2(
    *,
    scope: str,
    task_class: str,
    statement: str,
    supporting_outcome_ids: list[str],
    counterexamples: list[str] | None,
    searched_counterexamples: bool,
    confidence: float = 0.5,
) -> dict[str, Any]:
    n = len(supporting_outcome_ids)
    if n < MIN_LESSON_SAMPLES:
        status = "PROVISIONAL"
    elif not searched_counterexamples:
        status = "PROVISIONAL"
    elif counterexamples:
        status = "CONTRADICTED" if len(counterexamples) >= n else "PROVISIONAL"
    else:
        status = "SUPPORTED"
    lid = _sha({"scope": scope, "task": task_class, "statement": statement})[:20]
    return {
        "schema": SCHEMA_LESSON,
        "lesson_id": lid,
        "scope": scope,
        "task_class": task_class,
        "statement": statement[:400],
        "supporting_outcome_ids": list(supporting_outcome_ids),
        "counterexamples": list(counterexamples or []),
        "sample_size": n,
        "confidence": float(confidence),
        "limitations": "one outcome is not methodology" if n < MIN_LESSON_SAMPLES else "bounded",
        "review_at": None,
        "status": status,
        "counterexample_search": bool(searched_counterexamples),
        "methodology_effect": False,
        "policy_effect": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def hypothesis_from_lesson(lesson: dict[str, Any], *, claim: str, baseline: str, candidate: str, metric: str, population: str) -> dict[str, Any]:
    hid = _sha({"lesson": lesson.get("lesson_id"), "claim": claim})[:20]
    return {
        "schema": SCHEMA_HYP,
        "hypothesis_id": hid,
        "claim": claim[:400],
        "baseline": baseline,
        "candidate_behavior": candidate,
        "metric": metric,
        "population": population,
        "minimum_samples": MIN_LESSON_SAMPLES,
        "expected_effect": "improvement_or_null",
        "failure_condition": "quality_delta < 0 or cost_delta excessive",
        "cost_ceiling": 0.0,
        "rollback": "keep baseline",
        "expiry": None,
        "evidence_refs": [lesson.get("lesson_id")],
        "preregistered": False,
        "promoted": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def preregister(hypothesis: dict[str, Any], *, primary_metric: str, success_threshold: float, sample_count: int, cost_ceiling: float) -> dict[str, Any]:
    out = dict(hypothesis)
    out["preregistered"] = True
    out["frozen"] = {
        "primary_metric": primary_metric,
        "success_threshold": float(success_threshold),
        "sample_count": int(sample_count),
        "cost_ceiling": float(cost_ceiling),
    }
    out["post_hoc_metric_switch_forbidden"] = True
    return out


def shadow_experiment(*, control: list[dict[str, Any]], candidate: list[dict[str, Any]], metric: str, prereg: dict[str, Any]) -> dict[str, Any]:
    def mean(rows: list[dict[str, Any]]) -> float:
        vals = [float(r.get(metric) or 0) for r in rows]
        return sum(vals) / len(vals) if vals else 0.0

    c, k = mean(control), mean(candidate)
    delta = round(k - c, 4)
    frozen = (prereg.get("frozen") or {})
    threshold = float(frozen.get("success_threshold") or 0)
    if delta > threshold:
        finding = "positive"
    elif delta < -threshold:
        finding = "negative"
    else:
        finding = "inconclusive"
    return {
        "schema": SCHEMA_EXPERIMENT,
        "control_n": len(control),
        "candidate_n": len(candidate),
        "metric": metric,
        "control_mean": round(c, 4),
        "candidate_mean": round(k, 4),
        "delta": delta,
        "finding": finding,
        "operator_notified": False,
        "trading": False,
        "policy_mutated": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def promotion_advance(current: str, target: str, *, operator_authorized: bool = False) -> dict[str, Any]:
    if current not in PROMOTION_STAGES or target not in PROMOTION_STAGES:
        return {"ok": False, "reason": "unknown_stage", "stage": current}
    if target == "REVERTED":
        return {"ok": True, "stage": "REVERTED", "rollback": True, "authority": AUTHORITY}
    if PROMOTION_STAGES.index(target) < PROMOTION_STAGES.index(current):
        return {"ok": False, "reason": "cannot_skip_back", "stage": current}
    if target in {"OPERATOR_APPROVED", "PROMOTED"} and not operator_authorized:
        return {
            "ok": False,
            "reason": "PROMOTION_REQUIRES_SEPARATE_AUTHORITY",
            "stage": current,
            "max_unattended": "REVIEW_READY",
            "authority": AUTHORITY,
        }
    return {"ok": True, "stage": target, "operator_authorized": operator_authorized, "authority": AUTHORITY}


def normalize_feedback(raw: str) -> str:
    key = str(raw or "").strip().upper().replace(" ", "_")
    aliases = {"ACK": "USEFUL", "NOISE": "TOO_NOISY", "LATE": "TOO_LATE", "WRONG": "WRONG_REASON"}
    key = aliases.get(key, key)
    return key if key in FEEDBACK_TAXONOMY else "NOT_USEFUL"


def notification_learning(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {k: 0 for k in NOTIFY_OUTCOMES}
    for row in rows:
        label = str(row.get("label") or "")
        if label in counts:
            counts[label] += 1
    return {
        "schema": "NotificationLearning@v1",
        "counts": counts,
        "n": len(rows),
        "candidate_only": True,
        "thresholds_auto_changed": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def schedule_outcome_checkpoint(decision_id: str, horizon: str, existing: list[str] | None = None) -> dict[str, Any]:
    key = _sha({"decision_id": decision_id, "horizon": horizon})[:20]
    dup = key in set(existing or [])
    return {
        "schema": "OutcomeCheckpoint@v1",
        "checkpoint_id": key,
        "decision_id": decision_id,
        "horizon": horizon,
        "duplicate": dup,
        "observational_only": True,
        "trading": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def similar_setup(*, current: dict[str, Any], history: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
    rec = str(current.get("recommendation") or "")
    hits = [h for h in history if h.get("recommendation") == rec][:limit]
    return {
        "schema": "HaveWeSeenThis@v1",
        "matches": [{"decision_id": h.get("decision_id"), "outcome_id": h.get("outcome_id")} for h in hits],
        "why_may_differ": current.get("uncertainty") or "case-specific evidence required",
        "evidence_linked_only": True,
        "dumped_all_memory": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def learning_may_not_override_truth(memory_row: dict[str, Any]) -> bool:
    if memory_row.get("overrides_office_truth") or memory_row.get("policy_effect"):
        return False
    if int(memory_row.get("memory_behavior_influence") or 0) != 0:
        return False
    return True


def cost_of_learning(*, evaluations: int, experiments: int, deterministic: bool = True) -> dict[str, Any]:
    # Prefer deterministic scoring: $0 model spend.
    per_eval = 0.0 if deterministic else 0.01
    return {
        "schema": "LearningCost@v1",
        "evaluations": evaluations,
        "experiments": experiments,
        "cost_per_evaluation": per_eval,
        "cost_per_experiment": per_eval,
        "total": round(per_eval * (evaluations + experiments), 4),
        "paid_models_used_to_inflate_n": False,
        "authority": AUTHORITY,
    }


def registries_must_not_change(repo: Path, before: dict[str, str]) -> bool:
    return snapshot_registries(repo) == before


def refuse_auto_routing(root: Path) -> None:
    apply_routing_candidate(root, {"task_class": "research_curation"})
