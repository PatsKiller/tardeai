"""agent_memory_shadow_measure.py — Phase 2 decision-level shadow metrics.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE must stay 0.

Builds a dual-path decision_evaluator for ``shadow_compare_wakes`` using
DecisionPayload@v1 rows when present, and computes the Phase 2 weekly metrics.
Never promotes influence. Never mutates live decisions.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_decision_payload import PAYLOAD_SCHEMA, count_decision_payloads
from scripts.lib.agent_feature_flags import behavior_influence_active, load_feature_flags
from scripts.lib.agent_run_trace import DEFAULT_TRACE_PATH
from scripts.lib.agent_shadow_acceptance import (
    DEFAULT_WAKE_TRACES,
    promotion_gate,
    shadow_compare_wakes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "data" / "cio" / "memory_shadow_measure_latest.json"
EVALUATOR_VERSION = "memory-shadow-measure-v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return rows


def load_decision_payloads(trace_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return DecisionPayload@v1 dicts from agent_run_traces (newest last)."""
    rows = _load_jsonl(Path(trace_path) if trace_path else DEFAULT_TRACE_PATH)
    out: list[dict[str, Any]] = []
    for r in rows:
        dec = r.get("decision")
        if isinstance(dec, dict) and dec.get("schema") == PAYLOAD_SCHEMA:
            # Skip synthesized for promotion arithmetic consumers
            out.append(dec)
    return out


def _payload_index(payloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """wake_id → latest payload (and also decision_id index)."""
    by_wake: dict[str, dict[str, Any]] = {}
    for p in payloads:
        wid = str(p.get("wake_id") or "")
        if wid:
            by_wake[wid] = p
    return by_wake


def make_decision_evaluator(
    payloads_by_wake: dict[str, dict[str, Any]],
):
    """Return dual-path evaluator: fresh dict each call; action from payload or HOLD.

    Baseline: memory_ids_used=[].
    Augmented: memory_ids_used from context episodic_memory (retrieval visible;
    influence must remain off so action should match baseline).
    """

    def evaluator(wake: dict[str, Any], context: dict[str, Any], mode: str) -> dict[str, Any]:
        wake = wake if isinstance(wake, dict) else {}
        context = context if isinstance(context, dict) else {}
        wid = str(wake.get("wake_id") or "")
        pl = payloads_by_wake.get(wid) or {}
        action = str(pl.get("current_action") or "HOLD").upper() or "HOLD"
        did = str(pl.get("decision_id") or f"dec_{wid or 'unknown'}_{mode}")
        mem_ids: list[str] = []
        if mode == "augmented":
            mem_ids = [
                str(x)
                for x in ((context.get("episodic_memory") or {}).get("memory_ids") or [])
                if x
            ]
        return {
            "decision_id": f"{did}_{mode}",
            "current_action": action,
            "act_now": bool(pl.get("act_now")) if pl else False,
            "memory_ids_used": list(mem_ids),
            "surface": pl.get("surface"),
            "decision_origin": pl.get("decision_origin"),
            "authority": "READ_ONLY_ADVISORY",
            "financial_action": False,
            "schema": PAYLOAD_SCHEMA,
        }

    return evaluator


def compute_phase2_metrics(
    shadow_result: dict[str, Any],
    *,
    payload_stats: dict[str, Any],
    flags: dict[str, Any],
) -> dict[str, Any]:
    """Phase 2 weekly metrics (measured; missing → honest UNAVAILABLE)."""
    packets = list(shadow_result.get("packets") or [])
    wakes = int(shadow_result.get("wakes") or 0)
    with_retrieval = 0
    changed_decision = 0
    changed_notification = 0
    for p in packets:
        mem = p.get("memory_ids_retrieved") or []
        if mem:
            with_retrieval += 1
        diff = p.get("shadow_diff") if isinstance(p.get("shadow_diff"), dict) else {}
        if diff.get("action_changed"):
            changed_decision += 1
        # notification_changed may live under diff_effects
        effects = diff.get("diff_effects") if isinstance(diff.get("diff_effects"), dict) else diff
        if isinstance(effects, dict) and effects.get("notification_changed"):
            changed_notification += 1

    retrieval_rate = (with_retrieval / wakes) if wakes else None
    changed_given_retrieval = (
        (changed_decision / with_retrieval) if with_retrieval else None
    )

    return {
        "as_of": _now(),
        "memory_retrieval_rate": (
            round(retrieval_rate, 4) if retrieval_rate is not None else "UNAVAILABLE"
        ),
        "memory_changed_decision": (
            round(changed_given_retrieval, 4)
            if changed_given_retrieval is not None
            else "UNAVAILABLE"
        ),
        "memory_changed_notification": (
            round((changed_notification / wakes), 4) if wakes else "UNAVAILABLE"
        ),
        "operator_recall_hit": "UNAVAILABLE",  # needs labeled reject corpus
        "memory_false_positive": "UNAVAILABLE",  # needs adjudication target
        "truth_override_attempts": 0,  # structural: influence off
        "wakes_compared": wakes,
        "wakes_with_memory_retrieval": with_retrieval,
        "decision_payload_trace_rows": payload_stats.get("rows"),
        "decision_payload_v1_count": payload_stats.get("with_decision_payload_v1"),
        "decision_payload_coverage_on_traces": payload_stats.get("coverage"),
        "shadow_decision_payloads_available": shadow_result.get(
            "decision_payloads_available"
        ),
        "shadow_dual_path_executed": shadow_result.get("dual_path_executed"),
        "memory_attributable_action_flips": shadow_result.get(
            "memory_attributable_action_flips"
        ),
        "behavior_influence_active": behavior_influence_active(flags),
        "flags": {
            "MEMORY_PROVIDER": flags.get("MEMORY_PROVIDER"),
            "MEMORY_SHADOW": flags.get("MEMORY_SHADOW"),
            "MEMORY_BEHAVIOR_INFLUENCE": flags.get("MEMORY_BEHAVIOR_INFLUENCE"),
            "AGENT_DECISION_PAYLOAD": flags.get("AGENT_DECISION_PAYLOAD"),
        },
    }


def run_measure(
    *,
    wake_path: Path | str | None = None,
    trace_path: Path | str | None = None,
    out_path: Path | str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Run one shadow measure cycle. Fail-soft; never enables influence."""
    flags = load_feature_flags()
    root_p = Path(root) if root else PROJECT_ROOT
    wake_p = Path(wake_path) if wake_path else (root_p / "data/cio/cio_wake_traces.jsonl")
    if not wake_path and not wake_p.exists():
        wake_p = DEFAULT_WAKE_TRACES
    trace_p = Path(trace_path) if trace_path else (root_p / "data/cio/agent_run_traces.jsonl")
    if not trace_path and not trace_p.exists():
        trace_p = DEFAULT_TRACE_PATH
    out_p = Path(out_path) if out_path else (root_p / "data/cio/memory_shadow_measure_latest.json")

    payload_stats = count_decision_payloads(trace_p)
    payloads = load_decision_payloads(trace_p)
    # Exclude SYNTHESIZED from evaluator index used for promotion-facing digests
    live_payloads = [p for p in payloads if p.get("decision_origin") != "SYNTHESIZED"]
    by_wake = _payload_index(live_payloads)

    memory_provider = None
    try:
        from scripts.lib.agent_memory_provider import get_memory_provider

        memory_provider = get_memory_provider(flags)
    except Exception:
        memory_provider = None

    evaluator = make_decision_evaluator(by_wake)
    shadow = shadow_compare_wakes(
        wake_p,
        memory_provider=memory_provider,
        decision_evaluator=evaluator,
        evaluator_version=EVALUATOR_VERSION,
    )
    metrics = compute_phase2_metrics(shadow, payload_stats=payload_stats, flags=flags)

    # Promotion gate with influence still OFF → must be NOT_PROMOTED
    gate = promotion_gate(
        shadow,
        behavior_influence_enabled=False,
        metrics={
            "canonical_truth_overrides": 0,
            "unauthorized_actions": 0,
            "critical_memory_false_positives": 0,
            "operator_rejection_recall": None,  # unmeasured → fail closed
            "mcp_write_attempts": 0,
            "mcp_write_denied": 0,
            "p0_p1_clean": True,
        },
    )

    origins = Counter(str(p.get("decision_origin") or "") for p in live_payloads)
    surfaces = Counter(str(p.get("surface") or "") for p in live_payloads)

    report = {
        "schema": "MemoryShadowMeasure@v1",
        "as_of": _now(),
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "window": {
            "note": "Populate DecisionPayload corpus with AGENT_DECISION_PAYLOAD=1; "
            "decision-level promotion evidence needs ≥5 trading days of coverage.",
            "payload_v1_count": payload_stats.get("with_decision_payload_v1"),
            "wake_rows_compared": shadow.get("wakes"),
        },
        "metrics": metrics,
        "payload_origins": dict(origins),
        "payload_surfaces": dict(surfaces),
        "shadow": {
            "wakes": shadow.get("wakes"),
            "trace_coverage": shadow.get("trace_coverage"),
            "decision_payloads_available": shadow.get("decision_payloads_available"),
            "decision_comparisons_completed": shadow.get(
                "decision_comparisons_completed"
            ),
            "dual_path_executed": shadow.get("dual_path_executed"),
            "memory_attributable_action_flips": shadow.get(
                "memory_attributable_action_flips"
            ),
            "evaluation_failures": shadow.get("evaluation_failures"),
            "packets_sample": (shadow.get("packets") or [])[:5],
        },
        "promotion_gate": {
            "verdict": gate.get("verdict"),
            "all_hard_gates": gate.get("all_hard_gates"),
            "reasons": gate.get("reasons") or gate.get("failed") or [],
            "note": "Influence remains OFF. Do not weaken gates.",
        },
        "ttl_policy": {
            "decision": "KEEP_CURRENT_TTLS",
            "operator_choice": "2026-08-21 — keep EPISODIC 30d / PROCEDURAL 14d / "
            "RESEARCH 90d / OPERATOR_INFERRED 180d / OPERATOR_EXPLICIT 365d",
        },
    }

    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_p.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(out_p)
        report["written_to"] = str(out_p)
    except Exception as exc:
        report["write_error"] = f"{type(exc).__name__}:{exc}"[:160]

    return report
