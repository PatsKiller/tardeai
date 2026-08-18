"""Baseline vs enhanced advisory comparator. Neither output is executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.lib.advisory_influence.gates import (
    current_gates,
    fs_receipt_eligible,
    inject_lessons,
    lesson_eligible,
    present_enhanced,
)
from scripts.lib.maturity_control.lessons import collect_lessons
from scripts.lib.maturity_control.schema import utc_now
from scripts.lib.maturity_control.store import resolve_root


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _append(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


def _canonical_truth(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": payload.get("canonical_action") or payload.get("action"),
        "act_now": payload.get("act_now"),
        "cash": payload.get("cash"),
        "holdings_digest": payload.get("holdings_digest"),
        "risk_limits": payload.get("risk_limits"),
    }


def compare_run(
    payload: dict[str, Any],
    *,
    root: Path | str | None = None,
    env: dict[str, str] | None = None,
    fs_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gates = current_gates(env)
    truth = _canonical_truth(payload)
    baseline = {
        "verdict": payload.get("baseline_verdict") or payload.get("verdict") or "HOLD",
        "conviction": float(payload.get("baseline_conviction") or payload.get("conviction") or 0),
        "influenced": False,
        "lessons": [],
        "fs_receipts": [],
    }

    used_lessons: list[dict[str, Any]] = []
    conflicts: list[str] = []
    if inject_lessons(gates["lesson_mode"]):
        view = collect_lessons(root=root)
        for les in view.get("lessons") or []:
            if not lesson_eligible(les.get("lifecycle")):
                continue
            if les.get("lifecycle") == "CANDIDATE":
                continue
            used_lessons.append({
                "lesson_id": les.get("lesson_id"),
                "source": les.get("source"),
                "evidence_refs": les.get("evidence_refs"),
                "status": les.get("lifecycle"),
                "applications": les.get("applications"),
                "hit_rate": les.get("hit_rate"),
                "scope": les.get("symbols"),
            })
            if len(used_lessons) >= 5:
                break

    used_fs = []
    for rec in fs_receipts or []:
        if fs_receipt_eligible(rec):
            used_fs.append({
                "request_id": rec.get("request_id"),
                "provider": rec.get("provider") or rec.get("fs_provider"),
                "capability": rec.get("capability") or rec.get("fs_capability"),
                "source": (rec.get("source_provenance") or {}).get("source_type"),
                "as_of": rec.get("source_asof"),
                "freshness": rec.get("quality_summary"),
                "quality": rec.get("quality_summary"),
                "validation": rec.get("status"),
                "fact_count": rec.get("fact_count"),
                "estimate_count": rec.get("estimate_count"),
            })
        else:
            conflicts.append("fs_ineligible:" + str(rec.get("status") or rec.get("request_id") or "unknown"))

    # Canonical truth wins: enhanced may not change action/act_now/cash/risk.
    enhanced_verdict = baseline["verdict"]
    enhanced_conviction = baseline["conviction"]
    rationale = []
    if used_lessons and inject_lessons(gates["lesson_mode"]):
        rationale.append("ratified lessons available as advisory context")
        if payload.get("lesson_conflicts_canonical"):
            conflicts.append("lesson_conflicts_canonical_truth")
            rationale.append("learned context contradicted by current canonical truth; ignored.")
        elif gates["lesson_mode"] != "OFF":
            enhanced_conviction = min(1.0, enhanced_conviction + 0.02 * len(used_lessons))
    if used_fs and inject_lessons(gates["financial_senses_mode"]) or (
        used_fs and gates["financial_senses_mode"] in {"SHADOW", "CANARY", "ACTIVE_ADVISORY"}
    ):
        rationale.append("validated Financial Senses receipts attached")

    enhanced = {
        "verdict": enhanced_verdict,
        "conviction": enhanced_conviction,
        "influenced": bool(used_lessons or used_fs) and gates["lesson_mode"] != "OFF",
        "lessons": used_lessons if gates["lesson_mode"] != "OFF" else [],
        "fs_receipts": used_fs if gates["financial_senses_mode"] != "OFF" else [],
        "rationale": rationale,
        "primary": present_enhanced(gates["lesson_mode"]) or present_enhanced(gates["financial_senses_mode"]),
    }

    # Hard wall: enhanced cannot change canonical actionability.
    if enhanced["verdict"] != baseline["verdict"]:
        conflicts.append("verdict_delta_forced_back_to_canonical")
        enhanced["verdict"] = baseline["verdict"]

    rec = {
        "run_id": "inf_" + _digest({"t": utc_now(), "p": payload})[:16],
        "at": utc_now(),
        "input_digest": _digest(payload),
        "gates": gates,
        "canonical_truth": truth,
        "baseline": baseline,
        "enhanced": enhanced,
        "conflicts": conflicts,
        "executed": False,
        "financial_action": False,
        "authority": "READ_ONLY_ADVISORY",
    }
    _append(resolve_root(root) / "data" / "cio" / "advisory_influence_runs.jsonl", rec)
    return rec


def metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(runs)
    matured = sum(1 for r in runs if r.get("matured_outcome"))
    return {
        "eligible_runs": n,
        "matured_outcomes": matured,
        "baseline_changes": 0,
        "enhanced_changes": sum(1 for r in runs if (r.get("enhanced") or {}).get("conviction") != (r.get("baseline") or {}).get("conviction")),
        "authority_violations": sum(1 for r in runs if r.get("financial_action")),
        "canonical_truth_overrides": sum(1 for r in runs if r.get("conflicts")),
    }
