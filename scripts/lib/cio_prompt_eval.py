"""CIO prompt evaluation — structural checks + quality rubric.

Layer A: deterministic structural checks (auto, every enrichment).
Layer B: quality rubric 1–5 dimensions (operator or offline scoring).

Usage:
  PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval score --plan plan_xxx
  PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval structural --plan plan_xxx
  PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval probe
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

EVAL_LOG = Path("data/cio/cio_prompt_evals.jsonl")

# Fixed probe set (technique: comparable versions)
PROBE_PLAN_IDS = [
    "plan_1b8d534354fb",  # S5 cash
    "plan_05a414a3d105",  # S6 SCHD
    "plan_51e03253ba2d",  # S1 SPCX
]

QUALITY_WEIGHTS = {
    "thesis_use": 0.25,
    "synthesis": 0.20,
    "options": 0.15,
    "recommendation": 0.15,
    "evidence": 0.15,
    "tone": 0.10,
}

EXEC_VERBS = re.compile(
    r"\b(buy now|sell now|place stop|place order|force fill|market order|"
    r"trim immediately|execute trade|submit order)\b",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_text(plan: dict[str, Any]) -> str:
    parts = [
        str(plan.get("summary") or ""),
        str(plan.get("thesis_alignment") or ""),
        str(plan.get("multi_domain_summary") or ""),
        str(plan.get("recommendation") or ""),
        " ".join(str(r) for r in (plan.get("risks") or [])),
    ]
    for o in plan.get("options") or []:
        if isinstance(o, dict):
            parts.append(str(o.get("label") or ""))
            parts.append(str(o.get("pros") or ""))
            parts.append(str(o.get("cons") or ""))
    return "\n".join(parts)


def structural_check(plan: dict[str, Any], *, evidence: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Layer A — pass/fail structural checks. Critical fails block notify."""
    text = _plan_text(plan)
    pin = str(plan.get("thesis_version") or "")
    fails: list[str] = []
    critical: list[str] = []

    checks: dict[str, bool] = {}

    # Thesis pin present
    checks["thesis_pin_present"] = bool(pin) and (
        pin in text or pin in str(plan.get("summary") or "") or pin in str(plan.get("recommendation") or "")
        or bool(plan.get("thesis_alignment"))
    )
    if not checks["thesis_pin_present"]:
        fails.append("thesis_pin_missing")

    # Thesis tension / fit language
    ta = str(plan.get("thesis_alignment") or "") + " " + str(plan.get("recommendation") or "")
    checks["thesis_tension"] = bool(
        re.search(r"\b(fit|tension|align|conflicts?|honou?r|under desk@|principle|posture)\b", ta, re.I)
    )
    if not checks["thesis_tension"]:
        fails.append("thesis_tension_missing")

    # Required content
    checks["has_summary"] = len(str(plan.get("summary") or "").strip()) >= 40
    checks["has_recommendation"] = len(str(plan.get("recommendation") or "").strip()) >= 20
    if not checks["has_recommendation"]:
        critical.append("missing_recommendation")
        fails.append("missing_recommendation")
    if not checks["has_summary"]:
        fails.append("thin_summary")

    opts = [o for o in (plan.get("options") or []) if isinstance(o, dict)]
    checks["options_count_2_3"] = 2 <= len(opts) <= 5
    complete = 0
    for o in opts[:3]:
        pros = str(o.get("pros") or "").strip()
        cons = str(o.get("cons") or "").strip()
        if len(pros) >= 8 and len(cons) >= 8 and not pros.endswith("…") and not cons.endswith("…"):
            complete += 1
    checks["options_complete_plus_minus"] = complete >= min(2, len(opts)) if opts else False
    if not checks["options_complete_plus_minus"]:
        fails.append("options_incomplete")

    # Execution language
    checks["no_execution_language"] = not bool(EXEC_VERBS.search(text))
    if not checks["no_execution_language"]:
        critical.append("execution_language")
        fails.append("execution_language")

    # Truncation mid-word heuristic
    checks["no_mid_truncation"] = not bool(re.search(r"[a-zA-Z]{3,}\…\s*$", text, re.M))
    if not checks["no_mid_truncation"]:
        fails.append("truncation")

    # Provenance
    checks["prompt_version_recorded"] = bool(plan.get("prompt_version") or plan.get("prompt_content_hash"))
    if not checks["prompt_version_recorded"]:
        fails.append("prompt_provenance_missing")

    # Multi-domain presence (soft)
    md = str(plan.get("multi_domain_summary") or "")
    domains = plan.get("evidence_domains") or []
    checks["multi_domain_signal"] = (
        len(md) >= 30
        or len(domains) >= 2
        or ("domain" in md.lower() and len(md) > 20)
    )
    if not checks["multi_domain_signal"]:
        fails.append("multi_domain_weak")

    # Opens with thesis lens (soft)
    sum0 = str(plan.get("summary") or "").strip().lower()
    checks["opens_with_thesis_lens"] = sum0.startswith("under desk@") or "under desk@" in sum0[:80]
    if not checks["opens_with_thesis_lens"]:
        fails.append("missing_thesis_lens_open")

    n = len(checks) or 1
    score = round(100.0 * sum(1 for v in checks.values() if v) / n, 1)
    return {
        "structural_score": score,
        "checks": checks,
        "fails": fails,
        "critical_fails": critical,
        "pass": len(critical) == 0 and score >= 60,
        "block_notify": len(critical) > 0,
    }


def quality_rubric_template() -> dict[str, Any]:
    return {
        "dimensions": list(QUALITY_WEIGHTS.keys()),
        "weights": dict(QUALITY_WEIGHTS),
        "scale": "1-5",
        "promotion_threshold_mean": 3.5,
        "min_dimension": 2,
    }


def score_quality(scores: dict[str, float]) -> dict[str, Any]:
    """Weighted quality total from dimension scores 1–5."""
    total = 0.0
    wsum = 0.0
    clean: dict[str, float] = {}
    for k, w in QUALITY_WEIGHTS.items():
        v = scores.get(k)
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        fv = max(1.0, min(5.0, fv))
        clean[k] = fv
        total += fv * w
        wsum += w
    overall = round(total / wsum, 2) if wsum else None
    return {
        "quality": clean,
        "total": overall,
        "total_100": round(overall * 20, 1) if overall is not None else None,
        "weights": QUALITY_WEIGHTS,
    }


def heuristic_quality_score(plan: dict[str, Any]) -> dict[str, Any]:
    """Offline proxy for Layer B when operator has not scored (not ground truth)."""
    text = _plan_text(plan)
    pin = str(plan.get("thesis_version") or "")
    # thesis_use
    ta = str(plan.get("thesis_alignment") or "")
    thesis_use = 1
    if pin and pin in text:
        thesis_use = 2
    if re.search(r"\b(fit|tension|align)\b", ta, re.I):
        thesis_use = 3
    if ta.lower().startswith("under desk@") or "under desk@" in ta.lower()[:40]:
        thesis_use = 4
    if "CONSTRAINT" in ta or "Operator prior" in str(plan.get("recommendation") or ""):
        thesis_use = 5 if thesis_use >= 3 else 4

    # synthesis
    md = str(plan.get("multi_domain_summary") or "")
    doms = plan.get("evidence_domains") or []
    synthesis = 1
    if len(doms) >= 2 or len(md) > 40:
        synthesis = 3
    if len(doms) >= 4 and len(md) > 80:
        synthesis = 4
    if synthesis >= 3 and re.search(r"\d", md):
        synthesis = min(5, synthesis + 1)

    # options
    opts = [o for o in (plan.get("options") or []) if isinstance(o, dict)]
    options = 1
    if len(opts) >= 2:
        options = 3
    complete = sum(
        1
        for o in opts
        if len(str(o.get("pros") or "")) >= 10 and len(str(o.get("cons") or "")) >= 10
    )
    if complete >= 2:
        options = 4
    if complete >= 3:
        options = 5

    # recommendation
    rec = str(plan.get("recommendation") or "")
    recommendation = 2 if len(rec) > 30 else 1
    if re.search(r"\b(hold|stage|monitor|defer|choose)\b", rec, re.I):
        recommendation = 3
    if "under desk@" in rec.lower() or "highest-signal" in rec.lower():
        recommendation = 4
    if "Operator prior" in rec or "CONSTRAINT" in rec:
        recommendation = 5

    # evidence
    evidence = 3 if plan.get("evidence_refs") or doms else 2
    if "DATA_UNAVAILABLE" in text:
        evidence = max(evidence, 4)  # honest gaps
    if EXEC_VERBS.search(text):
        evidence = 1

    # tone
    tone = 3
    if re.search(r"\b(🚀|!!!|guaranteed|moon)\b", text, re.I):
        tone = 1
    elif "READ_ONLY" in text or "defensive_observe" in text or "stage/observe" in text.lower():
        tone = 4
    if tone >= 3 and thesis_use >= 4:
        tone = 5

    dim = {
        "thesis_use": thesis_use,
        "synthesis": synthesis,
        "options": options,
        "recommendation": recommendation,
        "evidence": evidence,
        "tone": tone,
    }
    scored = score_quality(dim)
    scored["scored_by"] = "heuristic"
    scored["scored_ts"] = _now()
    return scored


def record_eval(
    plan_id: str,
    prompt_version: str,
    *,
    structural: Optional[dict[str, Any]] = None,
    quality: Optional[dict[str, Any]] = None,
    thesis_version: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    p = path or EVAL_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _now(),
        "plan_id": plan_id,
        "prompt_version": prompt_version,
        "thesis_version": thesis_version,
        "structural": structural,
        "quality": quality,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def evaluate_plan(plan: dict[str, Any], *, record: bool = True) -> dict[str, Any]:
    structural = structural_check(plan)
    quality = heuristic_quality_score(plan)
    out = {
        "plan_id": plan.get("plan_id"),
        "thesis_version": plan.get("thesis_version"),
        "prompt_version": plan.get("prompt_version"),
        "structural": structural,
        "quality": quality,
    }
    if record and plan.get("plan_id"):
        try:
            record_eval(
                str(plan.get("plan_id")),
                str(plan.get("prompt_version") or "unknown"),
                structural=structural,
                quality=quality,
                thesis_version=str(plan.get("thesis_version") or ""),
            )
        except Exception:
            pass
    return out


def compare_probe_set(plan_store: Any = None) -> dict[str, Any]:
    if plan_store is None:
        try:
            from scripts.lib.cio_plans import CIOPlanStore
            plan_store = CIOPlanStore()
        except Exception:
            from lib.cio_plans import CIOPlanStore  # type: ignore
            plan_store = CIOPlanStore()
    rows = []
    for pid in PROBE_PLAN_IDS:
        plan = plan_store.get_plan(pid)
        if not plan:
            rows.append({"plan_id": pid, "error": "not_found"})
            continue
        ev = evaluate_plan(plan, record=True)
        rows.append(ev)
    totals = [r["quality"]["total"] for r in rows if r.get("quality") and r["quality"].get("total") is not None]
    mean = round(sum(totals) / len(totals), 2) if totals else None
    return {"probes": rows, "mean_quality": mean, "n": len(totals)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CIO prompt evaluation")
    sub = ap.add_subparsers(dest="cmd")

    p_struct = sub.add_parser("structural", help="Run structural check on a plan")
    p_struct.add_argument("--plan", required=True)

    p_score = sub.add_parser("score", help="Structural + heuristic quality")
    p_score.add_argument("--plan", required=True)

    sub.add_parser("probe", help="Score fixed probe set")
    sub.add_parser("rubric", help="Print rubric template")
    p_j = sub.add_parser("judge", help="LLM-as-judge (DeepSeek Flash) one plan")
    p_j.add_argument("--plan", required=True)
    sub.add_parser("judge-probe", help="LLM-as-judge on fixed probe set")

    args = ap.parse_args(argv)
    if args.cmd == "rubric":
        print(json.dumps(quality_rubric_template(), indent=2))
        return 0

    try:
        from scripts.lib.cio_plans import CIOPlanStore
        store = CIOPlanStore()
    except Exception:
        from lib.cio_plans import CIOPlanStore  # type: ignore
        store = CIOPlanStore()

    if args.cmd == "probe":
        print(json.dumps(compare_probe_set(store), indent=2, default=str))
        return 0

    if args.cmd in ("structural", "score"):
        plan = store.get_plan(args.plan)
        if not plan:
            print(json.dumps({"ok": False, "error": "plan_not_found", "plan_id": args.plan}))
            return 1
        if args.cmd == "structural":
            print(json.dumps(structural_check(plan), indent=2, default=str))
        else:
            print(json.dumps(evaluate_plan(plan), indent=2, default=str))
        return 0

    if args.cmd == "judge":
        try:
            from scripts.lib.cio_prompt_judge import llm_judge_plan
        except Exception:
            from lib.cio_prompt_judge import llm_judge_plan  # type: ignore
        plan = store.get_plan(args.plan)
        if not plan:
            print(json.dumps({"ok": False, "error": "plan_not_found", "plan_id": args.plan}))
            return 1
        print(json.dumps(llm_judge_plan(plan, plan_store=store), indent=2, default=str))
        return 0

    if args.cmd == "judge-probe":
        try:
            from scripts.lib.cio_prompt_judge import judge_probe_set
        except Exception:
            from lib.cio_prompt_judge import judge_probe_set  # type: ignore
        print(json.dumps(judge_probe_set(), indent=2, default=str))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
