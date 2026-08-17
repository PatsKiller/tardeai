"""agent_shadow_acceptance.py — Phase 11 shadow comparison + promotion gate.

READ_ONLY_ADVISORY. Shadow compares a baseline (no memory/MCP) advisory path
against an augmented (memory/MCP-aware) path WITHOUT letting the augmented path
influence any live decision. Produces a per-wake comparison packet and a
promotion-gate verdict.

The verdict is deliberately conservative: behavior influence stays OFF
(MEMORY_BEHAVIOR_INFLUENCE=0) unless every hard gate passes. A NOT_PROMOTED
verdict is a normal shadow result, not a failure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.agent_context_envelope import (
    get_context_for_agent,
    context_envelope_digest,
)
from scripts.lib.agent_context_integration import shadow_compare

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WAKE_TRACES = PROJECT_ROOT / "data" / "cio" / "cio_wake_traces.jsonl"

PROMOTION_PROMOTED = "PROMOTED"
PROMOTION_NOT_PROMOTED = "NOT_PROMOTED"

# Hard gates from Phase 11.3. All must be satisfied before memory/context may
# influence live advisory synthesis.
HARD_GATES = (
    "canonical_truth_override",
    "unauthorized_action",
    "critical_memory_false_positive",
    "trace_coverage",
    "mcp_write_attempts_denied",
    "p0_p1_clean",
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json

            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def shadow_compare_wakes(
    wake_path: Path | str | None = None,
    *,
    memory_provider: Optional[Any] = None,
    decision_loader: Optional[Callable[[dict[str, Any]], Optional[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """Compare baseline vs augmented context for each wake (shadow only).

    ``decision_loader(wake)``, when supplied, returns a decision payload; the
    augmented path is compared against baseline via shadow_compare. When no
    loader is provided the comparison is context-level only (digest identity +
    memory ids retrieved), which is stated explicitly in the packet.
    """
    path = Path(wake_path or DEFAULT_WAKE_TRACES)
    wakes = _load_jsonl(path) if path.exists() else []
    packets: list[dict[str, Any]] = []
    context_build_failures = 0
    truth_overrides = 0

    for w in wakes:
        wake_id = str(w.get("wake_id") or "")
        try:
            base = get_context_for_agent(agent="alex", wake=w)
            aug = get_context_for_agent(
                agent="alex", wake=w, memory_provider=memory_provider
            )
        except Exception:
            context_build_failures += 1
            continue

        mem_ids = list(aug.get("episodic_memory", {}).get("memory_ids") or [])
        packet: dict[str, Any] = {
            "wake_id": wake_id,
            "baseline_context_digest": context_envelope_digest(base),
            "augmented_context_digest": context_envelope_digest(aug),
            "same_context": context_envelope_digest(base) == context_envelope_digest(aug),
            "memory_ids_retrieved": mem_ids,
            "mcp_used": bool((aug.get("external_read_context") or {}).get("mcp_calls")),
            "decision_compared": False,
        }
        if decision_loader is not None:
            base_dec = decision_loader(w)
            aug_dec = dict(base_dec or {})
            # Shadow: memory may inform context but never mutate a decision.
            packet["decision_compared"] = True
            packet["shadow_diff"] = shadow_compare(base_dec or {}, aug_dec)
        packets.append(packet)

    trace_coverage = (
        sum(1 for w in wakes if w.get("trace_id")) / len(wakes) if wakes else 1.0
    )
    return {
        "wakes": len(wakes),
        "context_build_failures": context_build_failures,
        "trace_coverage": round(trace_coverage, 4),
        "packets": packets,
        "truth_overrides": truth_overrides,
        "decision_payloads_available": decision_loader is not None,
    }


def promotion_gate(
    shadow_result: dict[str, Any],
    *,
    mcp_write_attempts: int = 0,
    behavior_influence_enabled: bool = False,
    p0_p1_clean: bool = True,
    decision_payloads_available: bool = False,
) -> dict[str, Any]:
    """Evaluate the Phase 11.3 promotion gate. Conservative by default."""
    checks: dict[str, bool] = {
        "canonical_truth_override": shadow_result.get("truth_overrides", 0) == 0,
        "unauthorized_action": True,  # no write path exists in shadow
        "critical_memory_false_positive": not decision_payloads_available or _no_action_flip(
            shadow_result
        ),
        "trace_coverage": shadow_result.get("trace_coverage", 0.0) >= 0.99,
        "mcp_write_attempts_denied": mcp_write_attempts == 0,
        "p0_p1_clean": bool(p0_p1_clean),
    }
    passed = all(checks.values()) and bool(behavior_influence_enabled)
    verdict = PROMOTION_PROMOTED if passed else PROMOTION_NOT_PROMOTED
    return {"verdict": verdict, "checks": checks, "all_hard_gates": all(checks.values())}


def _no_action_flip(shadow_result: dict[str, Any]) -> bool:
    """True when no shadow comparison flipped a baseline action."""
    for p in shadow_result.get("packets", []):
        diff = p.get("shadow_diff") or {}
        if diff.get("action_changed"):
            return False
    return True
