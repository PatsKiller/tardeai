"""R18 — Outcome & decision calibration fabric.

Consumes genuine OutcomeObservation records when they exist. Does not invent LIVE
outcomes. Analytical only. Activation default OFF.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_forward_program import (
    AUTHORITY,
    MBI,
    gated_live_run,
    identity_roll_up,
    require_evidence_class,
)
from scripts.lib.cio_institutional_learning import (
    QUALITY_AXES,
    identity_safe_subject,
    reject_lookahead,
)

SCHEMA_OBS = "CalibrationObservation@v1"
SCHEMA_COHORT = "CalibrationCohort@v1"
SCHEMA_PROFILE = "DecisionQualityProfile@v1"
MIN_TRUTH_N = 8
DIMENSIONS = (
    "security_guid",
    "issuer_guid",
    "ticker_alias",
    "sector",
    "industry",
    "catalyst",
    "thesis_version",
    "decision_type",
    "confidence_bucket",
    "research_lane",
    "membership_reason",
    "research_tier",
    "market_regime",
    "horizon",
    "evidence_type",
    "holding_state",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bucket_confidence(value: Any) -> str | None:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return None
    if c >= 0.75:
        return "high"
    if c >= 0.45:
        return "medium"
    return "low"


def calibration_observation(
    *,
    outcome: dict[str, Any],
    decision: dict[str, Any] | None = None,
    universe_row: dict[str, Any] | None = None,
    evidence_class: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    """One outcome × decision × identity slice. Tiny n is reported, never sold as truth."""
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R18", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA_OBS}
    ident = identity_roll_up({**(universe_row or {}), **(decision or {}), **(outcome or {})})
    subject = identity_safe_subject(outcome) or identity_safe_subject(decision or {}) or ident.get("security_guid")
    decision = decision or {}
    as_of = as_of or outcome.get("source_as_of") or outcome.get("observed_at") or _now()
    lookahead = reject_lookahead(
        {"evidence": (outcome.get("source_refs") or []) and [{"id": r, "as_of": as_of} for r in (outcome.get("source_refs") or [])]},
        as_of=as_of,
    )
    quality = outcome.get("observed_quality")
    try:
        q = float(quality) if quality is not None else None
    except (TypeError, ValueError):
        q = None
    return {
        "schema": SCHEMA_OBS,
        "evidence_class": cls,
        "outcome_id": outcome.get("outcome_id"),
        "decision_id": outcome.get("decision_id") or decision.get("decision_id"),
        "horizon": outcome.get("horizon"),
        "observed_at": outcome.get("observed_at"),
        "source_as_of": as_of,
        "identity": ident,
        "subject_guid": subject,
        "ticker_alias": ident.get("ticker_alias"),
        "sector": (universe_row or {}).get("sector"),
        "industry": (universe_row or {}).get("industry"),
        "catalyst_guids": list((universe_row or {}).get("catalyst_guids") or []),
        "membership_reasons": list((universe_row or {}).get("membership_reasons") or []),
        "research_tier": (universe_row or {}).get("current_research_tier"),
        "decision_type": decision.get("recommendation") or decision.get("decision_type"),
        "confidence_bucket": _bucket_confidence(decision.get("confidence")),
        "research_lane": decision.get("research_lane") or decision.get("producer"),
        "thesis_version": decision.get("symbol_thesis_version") or decision.get("thesis_version"),
        "decision_version": decision.get("runtime_source_sha"),
        "market_regime": (outcome.get("market_context_since_decision") or {}).get("regime"),
        "holding_state": (universe_row or {}).get("currently_held"),
        "observed_quality": q,
        "lookahead_allowed": lookahead.get("allowed"),
        "unresolved_identity": ident.get("unresolved"),
        "pnl_is_not_the_grade": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": gate["activated"],
    }


def cohort_aggregate(
    observations: list[dict[str, Any]],
    dimension: str,
    *,
    evidence_class: str,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    if dimension not in DIMENSIONS:
        return {"schema": SCHEMA_COHORT, "ok": False, "reason": "unknown_dimension", "authority": AUTHORITY}
    groups: dict[str, list[float]] = defaultdict(list)
    unresolved = 0
    for row in observations:
        if row.get("unresolved_identity"):
            unresolved += 1
            continue
        key = row.get(dimension)
        if dimension == "security_guid":
            key = (row.get("identity") or {}).get("security_guid") or row.get("subject_guid")
        if dimension == "issuer_guid":
            key = (row.get("identity") or {}).get("issuer_guid")
        if dimension == "catalyst":
            key = ",".join(row.get("catalyst_guids") or []) or None
        if dimension == "membership_reason":
            reasons = row.get("membership_reasons") or []
            key = reasons[0] if reasons else None
        if key is None or row.get("observed_quality") is None:
            continue
        groups[str(key)].append(float(row["observed_quality"]))
    cohorts = []
    for key, vals in sorted(groups.items()):
        n = len(vals)
        mean = round(sum(vals) / n, 4) if n else None
        sufficient = n >= MIN_TRUTH_N
        cohorts.append({
            "key": key,
            "n": n,
            "mean_quality": mean if sufficient else None,
            "mean_quality_unauthoritative": None if sufficient else (round(sum(vals) / n, 4) if n else None),
            "sufficient_for_truth": sufficient,
            "uncertainty": "INSUFFICIENT_SAMPLE" if not sufficient else "BOUNDED",
        })
    return {
        "schema": SCHEMA_COHORT,
        "evidence_class": cls,
        "dimension": dimension,
        "cohorts": cohorts,
        "unresolved_excluded": unresolved,
        "min_n_for_truth": MIN_TRUTH_N,
        "tiny_samples_are_not_truth": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def decision_quality_profile(
    observations: list[dict[str, Any]],
    *,
    subject_guid: str | None,
    evidence_class: str,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    rows = [r for r in observations if (r.get("subject_guid") or (r.get("identity") or {}).get("security_guid")) == subject_guid]
    n = len(rows)
    qualities = [float(r["observed_quality"]) for r in rows if r.get("observed_quality") is not None]
    sufficient = len(qualities) >= MIN_TRUTH_N
    axes = {k: None for k in QUALITY_AXES}
    return {
        "schema": SCHEMA_PROFILE,
        "evidence_class": cls,
        "subject_guid": subject_guid,
        "n": n,
        "mean_quality": round(sum(qualities) / len(qualities), 4) if qualities and sufficient else None,
        "sufficient_for_truth": sufficient,
        "uncertainty": "INSUFFICIENT_SAMPLE" if not sufficient else "BOUNDED",
        "axes": axes,
        "ticker_guid_is_not_security": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
