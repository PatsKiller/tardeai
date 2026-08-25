"""R18 — Outcome & decision calibration fabric.

Consumes genuine OutcomeObservation records when they exist. Does not invent LIVE
outcomes. Analytical only. Activation default OFF.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
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
SCHEMA_REPLAY = "CalibrationReplay@v1"
MIN_TRUTH_N = 8
OBS_PATH = "data/cio/outcome_observations.jsonl"
CK_PATH = "data/cio/outcome_checkpoints.jsonl"
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


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_historical_records(root: Path | str) -> dict[str, Any]:
    """Load repository jsonl. Does not invent LIVE outcomes."""
    root_p = Path(root)
    observations = _jsonl(root_p / OBS_PATH)
    checkpoints = _jsonl(root_p / CK_PATH)
    ck_by_dec = {}
    for row in checkpoints:
        did = row.get("decision_id")
        if did and did not in ck_by_dec:
            ck_by_dec[did] = row
    return {
        "observations": observations,
        "checkpoints": checkpoints,
        "checkpoint_by_decision": ck_by_dec,
        "observation_ids": [r.get("outcome_id") for r in observations if r.get("outcome_id")],
        "checkpoint_ids": [r.get("checkpoint_id") for r in checkpoints if r.get("checkpoint_id")],
        "joined_n": sum(1 for r in observations if r.get("decision_id") in ck_by_dec),
    }


def _derived_quality(outcome: dict[str, Any]) -> float | None:
    realized = outcome.get("realized_state") if isinstance(outcome.get("realized_state"), dict) else {}
    if outcome.get("observed_quality") is not None:
        try:
            return float(outcome["observed_quality"])
        except (TypeError, ValueError):
            return None
    if realized.get("linked") is True:
        return 1.0
    if realized.get("linked") is False:
        return 0.0
    return None


def replay_calibration(
    root: Path | str,
    *,
    evidence_class: str,
    universe_by_symbol: dict[str, dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """HISTORICAL_REPLAY ingest. Source record IDs are listed. Tiny n is not truth."""
    cls = require_evidence_class(evidence_class)
    if cls == "LIVE":
        return gated_live_run("R18", evidence_class=cls) | {"schema": SCHEMA_REPLAY}
    hist = load_historical_records(root)
    uni = universe_by_symbol or {}
    observations = []
    leaks = 0
    for outcome in hist["observations"]:
        ck = hist["checkpoint_by_decision"].get(outcome.get("decision_id")) or {}
        state = ck.get("original_decision_state") if isinstance(ck.get("original_decision_state"), dict) else {}
        decision = {
            "decision_id": outcome.get("decision_id") or ck.get("decision_id"),
            "recommendation": state.get("recommendation"),
            "confidence": state.get("confidence") or ck.get("confidence"),
            "runtime_source_sha": ck.get("runtime_source_sha"),
            "security_guid": outcome.get("subject_guid") or ck.get("subject_guid"),
            "research_lane": ck.get("research_lane") or "institutional_learning",
            "horizon": outcome.get("horizon") or ck.get("horizon"),
        }
        row = dict(outcome)
        q = _derived_quality(outcome)
        if q is not None:
            row["observed_quality"] = q
        sym = state.get("symbol")
        universe_row = uni.get(str(sym).upper()) if sym else None
        cutoff = as_of or outcome.get("source_as_of") or outcome.get("observed_at")
        la = reject_lookahead(
            {"evidence": [{"id": ref, "as_of": outcome.get("observed_at")} for ref in (outcome.get("source_refs") or [])]},
            as_of=str(cutoff),
        )
        if not la.get("allowed"):
            leaks += 1
            continue
        rec = calibration_observation(
            outcome=row, decision=decision, universe_row=universe_row,
            evidence_class=cls, as_of=str(cutoff),
        )
        rec["source_record_ids"] = {
            "outcome_id": outcome.get("outcome_id"),
            "decision_id": outcome.get("decision_id"),
            "checkpoint_id": ck.get("checkpoint_id"),
        }
        rec["quality_derivation"] = "observed_quality" if outcome.get("observed_quality") is not None else "realized_state.linked"
        observations.append(rec)

    def pack(dim: str) -> dict[str, Any]:
        return cohort_aggregate(observations, dim, evidence_class=cls)

    rec_hits: dict[str, list[float]] = defaultdict(list)
    for rec in observations:
        hz = rec.get("horizon") or "unknown"
        if rec.get("observed_quality") is None:
            continue
        rec_hits[str(hz)].append(float(rec["observed_quality"]))
    hit_rate = []
    for hz, vals in sorted(rec_hits.items()):
        n = len(vals)
        p = (sum(1 for v in vals if v >= 0.5) / n) if n else None
        se = ((p * (1 - p) / n) ** 0.5) if n and p is not None else None
        hit_rate.append({
            "horizon": hz,
            "n": n,
            "hit_rate": round(p, 4) if n >= MIN_TRUTH_N and p is not None else None,
            "se": round(se, 4) if se is not None and n >= MIN_TRUTH_N else None,
            "sufficient_for_truth": n >= MIN_TRUTH_N,
            "uncertainty": "INSUFFICIENT_SAMPLE" if n < MIN_TRUTH_N else "BOUNDED",
        })
    return {
        "schema": SCHEMA_REPLAY,
        "evidence_class": cls,
        "source_observation_ids": hist["observation_ids"],
        "source_checkpoint_ids": hist["checkpoint_ids"],
        "joined_observation_checkpoint_n": hist["joined_n"],
        "observation_n": len(observations),
        "lookahead_excluded": leaks,
        "confidence_calibration": pack("confidence_bucket"),
        "hit_rate_by_horizon": hit_rate,
        "hit_rate_uses_derived_linked_flag_not_pnl": True,
        "sector_cohorts": pack("sector"),
        "industry_cohorts": pack("industry"),
        "catalyst_cohorts": pack("catalyst"),
        "research_lane_cohorts": pack("research_lane"),
        "tiny_samples_are_not_truth": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
