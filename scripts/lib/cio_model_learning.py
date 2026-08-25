"""ModelTaskPerformance@v1 — observational routing intelligence, never auto-policy.

Learns a *recommendation*. Does not edit llm_model_registry.json or
llm_process_registry.json. Shadow evaluation uses stored fixtures.
MEMORY_BEHAVIOR_INFLUENCE=0.
"""
from __future__ import annotations

import fcntl
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA_PERF = "ModelTaskPerformance@v1"
SCHEMA_CANDIDATE = "ModelRoutingCandidate@v1"
SCHEMA_SHADOW = "ModelRoutingShadowEval@v1"
PERF_PATH = "data/cio/model_task_performance.jsonl"
CANDIDATE_PATH = "data/cio/model_routing_candidates.jsonl"
SHADOW_PATH = "data/cio/model_routing_shadow.jsonl"

TASK_COHORTS = (
    "extraction",
    "classification",
    "research_curation",
    "contradiction_reconciliation",
    "risk_critique",
    "tax_critique",
    "portfolio_synthesis",
    "operator_explanation",
    "notification_rendering",
    "deep_invalidation_review",
)
DEFAULT_MIN_SAMPLES = 30
QUALITY_DELTA_MIN = 0.03
REGISTRY_FILES = ("config/llm_model_registry.json", "config/llm_process_registry.json")


class RoutingPromotionForbidden(RuntimeError):
    """Candidates cannot autonomously edit model/process registries."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def record_performance(
    *,
    task_class: str,
    process_id: str,
    requested_policy: str,
    executed_policy: str,
    model_id: str,
    prompt_version: str,
    input_size: int = 0,
    output_size: int = 0,
    latency: float = 0.0,
    cost: float = 0.0,
    schema_valid: bool = True,
    citation_valid: bool = True,
    critique_verdict: str = "PASS",
    retry_count: int = 0,
    material_result: bool = False,
    operator_feedback: str | None = None,
    outcome_refs: list[str] | None = None,
    self_assessment: Any = None,
) -> dict[str, Any]:
    """Never ask the same model 'were you good?' — self_assessment is ignored."""
    cohort = task_class if task_class in TASK_COHORTS else "research_curation"
    row = {
        "schema": SCHEMA_PERF,
        "task_class": cohort,
        "process_id": process_id,
        "requested_policy": requested_policy,
        "executed_policy": executed_policy,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "input_size": int(input_size),
        "output_size": int(output_size),
        "latency": float(latency),
        "cost": float(cost),
        "schema_valid": bool(schema_valid),
        "citation_valid": bool(citation_valid),
        "critique_verdict": critique_verdict,
        "retry_count": int(retry_count),
        "material_result": bool(material_result),
        "operator_feedback": operator_feedback,
        "outcome_refs": list(outcome_refs or []),
        "self_assessment_ignored": self_assessment is not None,
        "recorded_at": _now(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "policy": False,
        "financial_action": False,
    }
    row["objective_score"] = objective_score(row)
    return row


def persist_performance(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    _append(Path(root) / PERF_PATH, row)
    return row


def objective_score(row: dict[str, Any]) -> float:
    """Deterministic composite. Ignores any model self-score."""
    score = 0.0
    score += 0.25 if row.get("schema_valid") else 0.0
    score += 0.20 if row.get("citation_valid") else 0.0
    score += 0.15 if str(row.get("critique_verdict") or "").upper() in {"PASS", "ACCEPT", "ACCEPTED"} else 0.0
    score += 0.10 if int(row.get("retry_count") or 0) == 0 else 0.0
    if row.get("operator_feedback") in {"ACCEPTED", "DONE", "ACKNOWLEDGED"}:
        score += 0.15
    elif row.get("operator_feedback") in {"REJECTED"}:
        score += 0.0
    else:
        score += 0.05
    if row.get("outcome_refs"):
        score += 0.10
    cost = float(row.get("cost") or 0)
    latency = float(row.get("latency") or 0)
    score += 0.03 if cost <= 0.02 else 0.01
    score += 0.02 if latency <= 8000 else 0.0
    return round(min(score, 1.0), 4)


def load_cohort(root: Path | str, task_class: str) -> list[dict[str, Any]]:
    return [r for r in _jsonl(Path(root) / PERF_PATH) if r.get("task_class") == task_class]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _wilson_low(successes: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - adj) / denom)


def summarize_policy(rows: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    subset = [r for r in rows if r.get("executed_policy") == policy]
    n = len(subset)
    schema_ok = sum(1 for r in subset if r.get("schema_valid"))
    return {
        "policy": policy,
        "n": n,
        "schema_valid_rate": round(schema_ok / n, 4) if n else 0.0,
        "schema_wilson_low": round(_wilson_low(schema_ok, n), 4),
        "mean_score": round(_mean([float(r.get("objective_score") or 0) for r in subset]), 4),
        "mean_cost": round(_mean([float(r.get("cost") or 0) for r in subset]), 6),
        "mean_latency": round(_mean([float(r.get("latency") or 0) for r in subset]), 2),
        "failure_rate": round(sum(1 for r in subset if not r.get("schema_valid")) / n, 4) if n else 0.0,
    }


def routing_candidate(
    *,
    task_class: str,
    current_policy: str,
    rows: list[dict[str, Any]],
    candidate_policy: str,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    if task_class not in TASK_COHORTS:
        raise ValueError(f"unknown_cohort:{task_class}")
    current = summarize_policy(rows, current_policy)
    proposed = summarize_policy(rows, candidate_policy)
    sample = min(current["n"], proposed["n"]) if proposed["n"] else current["n"]
    if sample < int(min_samples) or proposed["n"] < int(min_samples):
        status = "INSUFFICIENT_MODEL_SAMPLES"
        promote = False
        reason = f"n={proposed['n']} < min_samples={min_samples}"
    else:
        quality_delta = proposed["mean_score"] - current["mean_score"]
        cost_delta = proposed["mean_cost"] - current["mean_cost"]
        promote = quality_delta >= QUALITY_DELTA_MIN
        status = "CANDIDATE_ROUTE" if promote else "CURRENT_ROUTE"
        reason = (
            f"{candidate_policy} quality_delta={quality_delta:.4f} "
            f"cost_delta={cost_delta:.6f} vs {current_policy}"
        )
    row = {
        "schema": SCHEMA_CANDIDATE,
        "task_class": task_class,
        "CURRENT_ROUTE": current_policy,
        "CANDIDATE_ROUTE": candidate_policy if status == "CANDIDATE_ROUTE" else current_policy,
        "status": status,
        "evidence": {"current": current, "candidate": proposed},
        "sample_size": sample,
        "quality_delta": round(proposed["mean_score"] - current["mean_score"], 4),
        "cost_delta": round(proposed["mean_cost"] - current["mean_cost"], 6),
        "latency_delta": round(proposed["mean_latency"] - current["mean_latency"], 2),
        "failure_delta": round(proposed["failure_rate"] - current["failure_rate"], 4),
        "reason": reason,
        "automatic_promotion": False,
        "registry_written": False,
        "created_at": _now(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    return row


def persist_candidate(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    _append(Path(root) / CANDIDATE_PATH, row)
    return row


def apply_routing_candidate(root: Path | str, candidate: dict[str, Any]) -> None:
    raise RoutingPromotionForbidden(
        "ModelRoutingCandidate cannot edit llm_model_registry.json or "
        "llm_process_registry.json; promotion requires tests, shadow evaluation, "
        "review, and a governed config change"
    )


def registries_unchanged(repo: Path | str, before: dict[str, str]) -> bool:
    root = Path(repo)
    for rel in REGISTRY_FILES:
        path = root / rel
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current != before.get(rel, current):
            return False
    return True


def snapshot_registries(repo: Path | str) -> dict[str, str]:
    root = Path(repo)
    out = {}
    for rel in REGISTRY_FILES:
        path = root / rel
        out[rel] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return out


def shadow_evaluate(
    *,
    candidate: dict[str, Any],
    fixtures: list[dict[str, Any]],
    budget_authorized_paid: bool = False,
) -> dict[str, Any]:
    """Compare on stored historical fixtures. No operator notification. No live paid calls."""
    current_policy = candidate.get("CURRENT_ROUTE")
    proposed = candidate.get("CANDIDATE_ROUTE")
    current_rows = [f for f in fixtures if f.get("executed_policy") == current_policy]
    proposed_rows = [f for f in fixtures if f.get("executed_policy") == proposed]
    paid_calls = 0 if not budget_authorized_paid else 0
    eval_row = {
        "schema": SCHEMA_SHADOW,
        "task_class": candidate.get("task_class"),
        "current": summarize_policy(current_rows, current_policy),
        "candidate": summarize_policy(proposed_rows, proposed),
        "fixture_count": len(fixtures),
        "live_notification": False,
        "paid_calls": paid_calls,
        "used_historical_fixtures": True,
        "registry_written": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    return eval_row


def persist_shadow(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    _append(Path(root) / SHADOW_PATH, row)
    return row


def _cohort_from_producer(producer: str, lane: str, source: str) -> str:
    blob = f"{producer} {lane} {source}".lower()
    if "guardian" in blob or "risk" in blob:
        return "risk_critique"
    if "ledger" in blob or "tax" in blob:
        return "tax_critique"
    if "contradict" in blob or "challenge" in blob:
        return "contradiction_reconciliation"
    if "notif" in blob or "telegram" in blob:
        return "notification_rendering"
    if "explain" in blob or "operator" in blob or "enrich" in blob:
        return "operator_explanation"
    if "extract" in blob:
        return "extraction"
    if "classif" in blob:
        return "classification"
    if "invalidation" in blob or "deep_review" in blob or "deep-review" in blob:
        return "deep_invalidation_review"
    if "portfolio" in blob or "thesis" in blob or "synthesis" in blob:
        return "portfolio_synthesis"
    return "research_curation"


def historical_receipt_to_performance(row: dict[str, Any], *, evidence_class: str) -> dict[str, Any]:
    """Normalize one existing receipt. Never mixes LIVE/HISTORICAL_REPLAY/GOLDEN_SHADOW."""
    if evidence_class not in {"LIVE", "HISTORICAL_REPLAY", "GOLDEN_SHADOW"}:
        raise ValueError(f"unknown_evidence_class:{evidence_class}")
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    producer = str(row.get("producer") or row.get("source") or row.get("prompt_version") or "unknown")
    lane = str(row.get("lane") or row.get("model") or meta.get("lane") or "unknown")
    structural = row.get("structural") if isinstance(row.get("structural"), dict) else {}
    schema_valid = bool(structural.get("pass", row.get("event") not in {"ERROR", "COST_CAP_EXCEEDED"}))
    if row.get("llm_error") or row.get("event") == "ERROR":
        schema_valid = False
    perf = record_performance(
        task_class=_cohort_from_producer(producer, lane, str(row.get("source") or "")),
        process_id=producer[:80],
        requested_policy=str(row.get("requested_policy") or "FAST"),
        executed_policy=str(row.get("executed_policy") or row.get("model") or "FAST"),
        model_id=str(row.get("model") or row.get("model_id") or "unknown"),
        prompt_version=str(row.get("prompt_version") or "historical"),
        latency=float(row.get("latency_ms") or row.get("latency") or 0),
        cost=float(row.get("cost") or row.get("estimated_cost_usd") or 0),
        schema_valid=schema_valid,
        citation_valid=schema_valid,
        critique_verdict="PASS" if schema_valid else "FAIL",
        retry_count=int(row.get("attempt_no") or 0),
        self_assessment=None,
    )
    # executed_policy may be a model id; keep observational honesty
    if perf["executed_policy"] not in {"FAST", "FAST_THINK", "PRO", "PRO_THINK", "PRO_MAX", "DETERMINISTIC", "CHALLENGER"}:
        if "flash" in str(perf["executed_policy"]).lower():
            perf["executed_policy"] = "FAST"
        elif "pro" in str(perf["executed_policy"]).lower():
            perf["executed_policy"] = "PRO"
        else:
            perf["executed_policy"] = "FAST"
    perf["evidence_class"] = evidence_class
    perf["policy"] = False
    return perf


def mine_historical_performance(root: Path | str, *, limit: int = 400) -> dict[str, Any]:
    """HISTORICAL_REPLAY only. Does not write routing policy."""
    base = Path(root)
    rows: list[dict[str, Any]] = []
    sources = [
        base / "data/cio/cio_prompt_evals.jsonl",
        base / "data/cio/cio_llm_enrich_log.jsonl",
        base / "data/cio/research_call_accounting.jsonl",
    ]
    per_source = max(1, int(limit) // max(len(sources), 1))
    for path in sources:
        if not path.is_file():
            continue
        taken = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            event = str(raw.get("event") or "")
            if path.name == "research_call_accounting.jsonl" and event not in {"COMPLETED", "ERROR", "SKIP_GATED"}:
                continue
            if path.name == "cio_prompt_evals.jsonl":
                raw = dict(raw, source="operator_explanation", producer="cio_prompt_eval", prompt_version=raw.get("prompt_version") or "cio_alex_enrich")
            elif path.name == "cio_llm_enrich_log.jsonl":
                raw = dict(raw, source="portfolio_synthesis", producer="cio_llm_enrich")
            rows.append(historical_receipt_to_performance(raw, evidence_class="HISTORICAL_REPLAY"))
            taken += 1
            if taken >= per_source or len(rows) >= int(limit):
                break
        if len(rows) >= int(limit):
            break
    return {
        "schema": "HistoricalReplayIngest@v1",
        "evidence_class": "HISTORICAL_REPLAY",
        "n": len(rows),
        "records": rows,
        "routing_changed": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def golden_shadow_records(*, task_class: str, n: int, policy: str = "FAST") -> list[dict[str, Any]]:
    out = []
    for i in range(int(n)):
        row = record_performance(
            task_class=task_class,
            process_id=f"golden_shadow_{task_class}",
            requested_policy=policy,
            executed_policy=policy,
            model_id="deepseek-v4-flash" if policy.startswith("FAST") else "deepseek-v4-pro",
            prompt_version="golden_shadow_v1",
            latency=800 + i,
            cost=0.01,
            schema_valid=True,
            citation_valid=True,
            critique_verdict="PASS",
        )
        row["evidence_class"] = "GOLDEN_SHADOW"
        out.append(row)
    return out


def cohort_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {c: [] for c in TASK_COHORTS}
    for row in rows:
        by.setdefault(row.get("task_class") or "research_curation", []).append(row)
    out = {}
    for cohort, items in by.items():
        live = [r for r in items if r.get("evidence_class") == "LIVE"]
        replay = [r for r in items if r.get("evidence_class") == "HISTORICAL_REPLAY"]
        shadow = [r for r in items if r.get("evidence_class") == "GOLDEN_SHADOW"]
        n = len(items)
        schema_ok = sum(1 for r in items if r.get("schema_valid"))
        critic_ok = sum(1 for r in items if str(r.get("critique_verdict") or "").upper() in {"PASS", "ACCEPT", "ACCEPTED"})
        out[cohort] = {
            "n_live": len(live),
            "n_replay": len(replay),
            "n_shadow": len(shadow),
            "n_total": n,
            "schema_success": round(schema_ok / n, 4) if n else 0.0,
            "critic_acceptance": round(critic_ok / n, 4) if n else 0.0,
            "cost": round(_mean([float(r.get("cost") or 0) for r in items]), 6) if items else 0.0,
            "latency": round(_mean([float(r.get("latency") or 0) for r in items]), 2) if items else 0.0,
            "error_rate": round(1 - (schema_ok / n), 4) if n else 0.0,
            "sufficient_for_routing": (len(live) + len(replay)) >= DEFAULT_MIN_SAMPLES,
            "classes_mixed": False,
        }
    return out


def model_selection_explanation(
    *,
    executed_policy: str,
    requested_policy: str,
    task_class: str,
    contradiction: bool = False,
    deep_review: bool = False,
    challenger: bool = False,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    why_flash = executed_policy in {"FAST", "FAST_THINK"}
    why_think = executed_policy.endswith("THINK") or contradiction
    why_not_pro = executed_policy not in {"PRO", "PRO_THINK", "PRO_MAX"} and not deep_review
    hist = history or {}
    return {
        "schema": "ModelSelectionExplanation@v1",
        "task_class": task_class,
        "requested_policy": requested_policy,
        "executed_policy": executed_policy,
        "why_flash": "material evidence extraction/curation default" if why_flash else None,
        "why_thinking": "contradiction/reconciliation requires FAST_THINK" if why_think else "thinking not required",
        "why_pro_not_needed": "PRO is exceptional invalidation/deep review, not bulk" if why_not_pro else "deep review authorized",
        "why_challenger": "independent challenge justified" if challenger else "challenger not requested",
        "historical_cost": hist.get("mean_cost"),
        "historical_performance": hist.get("mean_score"),
        "sample_size": hist.get("n") or 0,
        "insufficient_samples": int(hist.get("n") or 0) < DEFAULT_MIN_SAMPLES,
        "gui_cannot_self_promote": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }
