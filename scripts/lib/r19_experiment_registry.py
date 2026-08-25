"""R19 experiment registry — preregister before holdout is inspected.

LIVE contemporaneous registration cannot occur after holdout_start.
HISTORICAL_REPLAY may reconstruct registration as_of training_cutoff, labeled as such.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, require_evidence_class
from scripts.lib.cio_institutional_learning import _parse_ts

SCHEMA = "HypothesisRegistration@v1"
PATH = "data/cio/hypothesis_registrations.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _spec_payload(spec: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "statement", "source_lesson_ids", "cohort_definition", "metric",
        "expected_direction", "minimum_sample_size", "training_cutoff",
        "holdout_start", "holdout_end", "acceptance_criteria",
    )
    return {k: spec.get(k) for k in keys}


def register_hypothesis(
    root: Path | str,
    spec: dict[str, Any],
    *,
    evidence_class: str,
    source_sha: str,
    registered_at: str | None = None,
    mode: str = "CONTEMPORANEOUS",
    persist: bool = True,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    ts = registered_at or _now()
    holdout_start = spec.get("holdout_start")
    train_cut = spec.get("training_cutoff")
    if mode == "CONTEMPORANEOUS":
        if holdout_start and _parse_ts(ts) and _parse_ts(holdout_start) and _parse_ts(ts) > _parse_ts(holdout_start):
            return {
                "ok": False,
                "reason": "REGISTRATION_AFTER_HOLDOUT_VISIBLE",
                "authority": AUTHORITY,
            }
        if cls == "LIVE" and mode != "CONTEMPORANEOUS":
            return {"ok": False, "reason": "LIVE_REQUIRES_CONTEMPORANEOUS", "authority": AUTHORITY}
    if mode == "RECONSTRUCTED_AS_OF":
        if cls == "LIVE":
            return {"ok": False, "reason": "LIVE_FORBIDS_RECONSTRUCTED_REGISTRATION", "authority": AUTHORITY}
        ts = train_cut or ts
    cut_ts = _parse_ts(train_cut)
    hs_ts = _parse_ts(holdout_start)
    if cut_ts and hs_ts and hs_ts < cut_ts:
        return {"ok": False, "reason": "TRAIN_HOLDOUT_OVERLAP", "authority": AUTHORITY}
    frozen = _spec_payload(spec)
    hid = _sha({"spec": frozen, "registered_at": ts, "source_sha": source_sha})[:24]
    row = {
        "schema": SCHEMA,
        "hypothesis_id": hid,
        "statement": spec.get("statement"),
        "source_lesson_ids": list(spec.get("source_lesson_ids") or []),
        "eligible_cohort_definition": spec.get("cohort_definition"),
        "metric": spec.get("metric"),
        "expected_direction": spec.get("expected_direction"),
        "minimum_sample_size": int(spec.get("minimum_sample_size") or 8),
        "training_cutoff": train_cut,
        "holdout_start": holdout_start,
        "holdout_end": spec.get("holdout_end"),
        "acceptance_criteria": spec.get("acceptance_criteria") or {},
        "registered_at": ts,
        "source_sha": source_sha,
        "spec_hash": _sha(frozen),
        "mode": mode,
        "evidence_class": cls,
        "criteria_locked": True,
        "persisted": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    if persist:
        path = Path(root) / PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        row["persisted"] = True
    return {"ok": True, "registration": row}


def evaluate_registration(
    registration: dict[str, Any],
    *,
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Holdout scores are inspected only here, after registration exists."""
    if _sha(_spec_payload(spec)) != registration.get("spec_hash"):
        return {"ok": False, "status": "CRITERIA_CHANGED_AFTER_REGISTRATION", "authority": AUTHORITY}
    cut = _parse_ts(registration.get("training_cutoff"))
    hs = _parse_ts(registration.get("holdout_start"))
    he = _parse_ts(registration.get("holdout_end"))
    if cut and hs and hs < cut:
        return {"ok": False, "status": "TRAIN_HOLDOUT_OVERLAP", "authority": AUTHORITY}

    def _row_ts(row: dict[str, Any]):
        return _parse_ts(row.get("decision_timestamp") or row.get("observed_at") or row.get("recorded_at"))

    for row in train_rows:
        ts = _row_ts(row)
        if hs and ts and ts >= hs:
            return {"ok": False, "status": "TRAIN_HOLDOUT_OVERLAP", "authority": AUTHORITY}
    for row in holdout_rows:
        ts = _row_ts(row)
        if cut and ts and ts < cut:
            return {"ok": False, "status": "TRAIN_HOLDOUT_OVERLAP", "authority": AUTHORITY}
        if he and ts and ts > he:
            return {"ok": False, "status": "HOLDOUT_OUTSIDE_REGISTERED_WINDOW", "authority": AUTHORITY}

    min_n = int(registration.get("minimum_sample_size") or 8)
    if len(holdout_rows) < min_n or len(train_rows) < min_n:
        return {
            "ok": False,
            "status": "INSUFFICIENT_SAMPLE",
            "train_n": len(train_rows),
            "holdout_n": len(holdout_rows),
            "minimum_sample_size": min_n,
            "authority": AUTHORITY,
        }
    metric = str(registration.get("metric") or "objective_score")

    def mean(rows: list[dict[str, Any]]) -> float:
        vals = [float(r.get(metric) or 0) for r in rows]
        return sum(vals) / len(vals) if vals else 0.0

    train_m, hold_m = mean(train_rows), mean(holdout_rows)
    delta = round(hold_m - train_m, 4)
    crit = registration.get("acceptance_criteria") or {}
    threshold = float(crit.get("min_delta") or 0.0)
    direction = str(registration.get("expected_direction") or "improve")
    earned = (delta >= threshold) if direction == "improve" else (delta <= -threshold)
    train_ids = [str(r.get("decision_id")) for r in train_rows if r.get("decision_id")]
    hold_ids = [str(r.get("decision_id")) for r in holdout_rows if r.get("decision_id")]
    contra = [str(r.get("decision_id") or r.get("outcome_id")) for r in holdout_rows if r.get("counterexample")]
    status = "REVIEW_READY" if earned else "NO_HYPOTHESIS_EARNED_REVIEW_READY"
    return {
        "ok": True,
        "status": status,
        "hypothesis_id": registration.get("hypothesis_id"),
        "statement": registration.get("statement"),
        "metric": metric,
        "train_n": len(train_rows),
        "holdout_n": len(holdout_rows),
        "train_mean": round(train_m, 4),
        "holdout_mean": round(hold_m, 4),
        "delta": delta,
        "acceptance_threshold": threshold,
        "actual_result": {
            "train_mean": round(train_m, 4),
            "holdout_mean": round(hold_m, 4),
            "delta": delta,
            "earned": earned,
        },
        "uncertainty": "BOUNDED" if len(holdout_rows) >= min_n else "INSUFFICIENT_SAMPLE",
        "underlying_decision_ids": sorted(set(train_ids + hold_ids)),
        "cohort_definition": registration.get("eligible_cohort_definition"),
        "training_sample": {"n": len(train_rows), "decision_ids": train_ids},
        "holdout_sample": {"n": len(holdout_rows), "decision_ids": hold_ids},
        "contradictions": contra,
        "provenance": {
            "spec_hash": registration.get("spec_hash"),
            "registered_at": registration.get("registered_at"),
            "mode": registration.get("mode"),
            "source_sha": registration.get("source_sha"),
            "criteria_locked": registration.get("criteria_locked"),
        },
        "source_sha": registration.get("source_sha"),
        "evidence_class": registration.get("evidence_class"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
