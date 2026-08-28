"""Bind OutcomeCheckpoint@v1 for held researched plans. Observational only.

Skip CASH sleeve and the Pathward CASH ticker trap. No invented PnL.
READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_investment_product import collect_holdings, held_equity_symbols
from scripts.lib.cio_plans import CIOPlanStore, OPENISH
from scripts.lib.outcome_resolution import NON_SECURITY_RECOMMENDATIONS
from scripts.lib.r17_checkpoint_binding import bind_material_decision, is_cash_decision

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
PRODUCER = "cio_plan_outcome_checkpoints"
CASH_SITUATIONS = frozenset({"S5_CASH_DEPLOYMENT"})


def _syms(plan: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for s in plan.get("symbols") or []:
        u = str(s or "").upper().strip()
        if u and u not in out:
            out.append(u)
    return out


def skip_reason(plan: dict[str, Any], held: set[str]) -> Optional[str]:
    if str(plan.get("status") or "") not in OPENISH:
        return "not_open"
    if not plan.get("hermes_result_id"):
        return "no_hermes_result"
    rec = str(plan.get("recommendation") or plan.get("decision") or "").strip()
    if not rec:
        return "no_decision"
    rec_u = rec.upper()
    if rec_u in NON_SECURITY_RECOMMENDATIONS:
        return "non_security_recommendation"
    if str(plan.get("situation_type") or "") in CASH_SITUATIONS:
        return "s5_cash_deployment"
    syms = _syms(plan)
    if not syms:
        return "no_symbols"
    if all(s == "CASH" for s in syms):
        return "cash_sleeve"
    held_eq = [s for s in syms if s in held]
    if not held_eq:
        return "not_held"
    if "CASH" in held_eq and len(held_eq) == 1:
        return "cash_ticker_trap"
    decision = {
        "symbol": held_eq[0],
        "recommendation": rec,
        "action": rec_u.split()[0] if rec_u else rec,
    }
    if is_cash_decision(decision):
        return "cash_decision"
    return None


def plan_to_decision(plan: dict[str, Any], held: set[str]) -> dict[str, Any]:
    held_eq = [s for s in _syms(plan) if s in held and s != "CASH"]
    rec = str(plan.get("recommendation") or plan.get("decision") or "HOLD")
    pid = str(plan.get("plan_id") or "")
    return {
        "decision_id": f"plan_ckpt_{pid}",
        "symbol": held_eq[0] if held_eq else None,
        "recommendation": rec,
        "action": rec.split()[0].upper() if rec else "HOLD",
        "plan_id": pid,
        "hermes_result_id": plan.get("hermes_result_id"),
        "producer_id": PRODUCER,
        "observational_only": True,
        "thesis_version": plan.get("thesis_version") or plan.get("symbol_thesis_version"),
        "material_generation": str(plan.get("hermes_result_id") or pid),
    }


def select_held_researched_plans(
    store: CIOPlanStore,
    held: set[str],
    *,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    skipped: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for plan in store._plans.values():
        if not isinstance(plan, dict):
            continue
        reason = skip_reason(plan, held)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        selected.append(dict(plan))
    selected.sort(key=lambda p: str(p.get("updated_ts") or p.get("created_ts") or ""), reverse=True)
    if limit:
        selected = selected[:limit]
    return selected, skipped


def bind_held_researched_plan_checkpoints(
    *,
    root: Path | str | None = None,
    store: CIOPlanStore | None = None,
    holdings: dict[str, Any] | None = None,
    apply: bool = False,
    limit: int = 0,
    source_sha: str = "cio_plan_outcome_checkpoints",
    now: datetime | None = None,
) -> dict[str, Any]:
    root_p = Path(root) if root is not None else Path(".")
    store = store or CIOPlanStore()
    holdings = holdings if holdings is not None else collect_holdings(root_p)
    held = set(held_equity_symbols(holdings))
    selected, skipped = select_held_researched_plans(store, held, limit=limit)
    wrote_n = 0
    skipped_bind = 0
    samples: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for plan in selected:
        decision = plan_to_decision(plan, held)
        samples.append({
            "plan_id": plan.get("plan_id"),
            "symbol": decision.get("symbol"),
            "recommendation": str(decision.get("recommendation") or "")[:80],
            "hermes_result_id": plan.get("hermes_result_id"),
            "situation_type": plan.get("situation_type"),
        })
        if not apply:
            continue
        out = bind_material_decision(
            root_p,
            decision,
            source_sha=source_sha,
            persist=True,
            horizons=("1_session",),
            now=now,
        )
        bindings.append(out)
        wrote_n += int(out.get("wrote_n") or 0)
        skipped_bind += int(out.get("skipped_n") or 0)
    return {
        "schema": "PlanOutcomeCheckpointBind@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "observational_only": True,
        "apply": apply,
        "held_n": len(held),
        "eligible_n": len(selected),
        "would_bind": len(selected),
        "wrote_n": wrote_n,
        "skipped_bind_n": skipped_bind,
        "skipped_reasons": skipped,
        "samples": samples[:8],
        "bindings": bindings[:8] if apply else [],
        "notify": False,
    }
