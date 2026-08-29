"""Bind OutcomeCheckpoint@v1 for held researched plans. Observational only.

Skip CASH sleeve and the Pathward CASH ticker trap. No invented PnL.
READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_investment_product import (
    collect_holdings,
    dust_symbols,
    held_equity_symbols,
    held_equity_symbols_nondust,
)
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
    # Wave 2 slice 27: a residual share is not a position to check an outcome
    # against. Binding a checkpoint to SCHG's $8 or SRNE's $0.90 would put a
    # PnL question on something that is already EXITED. Lots are untouched;
    # only eligibility narrows, and both counts are reported.
    held = set(held_equity_symbols_nondust(holdings))
    dust = sorted(dust_symbols(holdings))
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
        "held_n_including_dust": len(set(held_equity_symbols(holdings))),
        "dust_excluded": dust,
        "dust_excluded_n": len(dust),
        "eligible_n": len(selected),
        "would_bind": len(selected),
        "wrote_n": wrote_n,
        "skipped_bind_n": skipped_bind,
        "skipped_reasons": skipped,
        "samples": samples[:8],
        "bindings": bindings[:8] if apply else [],
        "notify": False,
    }


# ── Wave 2 slice 32: complete → checkpoint lineage health ────────────────────

CHECKPOINT_REL = "data/cio/outcome_checkpoints.jsonl"
RESEARCH_PROJECTION_REL = "data/cio/hermes_research_projection.json"
NON_SECURITY_SUBJECTS = frozenset({"CASH", "PORTFOLIO", "BOOK", "REENTRY", "MMKT"})


def _checkpoint_symbol(row: dict[str, Any]) -> Optional[str]:
    receipt = row.get("context_receipt") if isinstance(row.get("context_receipt"), dict) else {}
    raw = receipt.get("symbol") or row.get("symbol")
    return str(raw).strip().upper() if raw else None


def checkpoint_lineage_health(
    *,
    root: Path | str,
    holdings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """How much of the research→checkpoint chain is actually joinable.

    The honest answer here is a *reason*, not a percentage. Checkpoints key on
    `decision_id` and carry no `plan_id`, and a completed research row keys on
    `plan_id` — so the two ends cannot be joined at all. Reporting 0% would
    read as "the pipeline never binds" (it binds 523 times); reporting 100%
    would be an invention. The rate is UNCOMPUTABLE and says why.
    """
    import json as _json

    base = Path(root)
    rows: list[dict[str, Any]] = []
    try:
        with open(base / CHECKPOINT_REL, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError:
        rows = []

    completed_plans: set[str] = set()
    try:
        proj = _json.loads((base / RESEARCH_PROJECTION_REL).read_text(encoding="utf-8"))
        for rec in (proj.get("by_research_id") or {}).values():
            if isinstance(rec, dict) and rec.get("status") == "completed" and rec.get("plan_id"):
                completed_plans.add(str(rec["plan_id"]))
    except (OSError, ValueError, AttributeError):
        pass

    dust: set[str] = set()
    if holdings is not None:
        try:
            dust = set(dust_symbols(holdings))
        except Exception:
            dust = set()

    by_status: dict[str, int] = {}
    by_horizon: dict[str, int] = {}
    with_plan = with_guid = with_symbol = 0
    non_security: dict[str, int] = {}
    on_dust: dict[str, int] = {}
    for rec in rows:
        st = str(rec.get("status") or "UNKNOWN")
        by_status[st] = by_status.get(st, 0) + 1
        hz = str(rec.get("horizon") or "UNKNOWN")
        by_horizon[hz] = by_horizon.get(hz, 0) + 1
        if rec.get("plan_id"):
            with_plan += 1
        if rec.get("subject_guid"):
            with_guid += 1
        sym = _checkpoint_symbol(rec)
        if sym:
            with_symbol += 1
            if sym in NON_SECURITY_SUBJECTS:
                non_security[sym] = non_security.get(sym, 0) + 1
            elif sym in dust:
                on_dust[sym] = on_dust.get(sym, 0) + 1

    joinable = with_plan > 0 and bool(completed_plans)
    return {
        "schema": "CheckpointLineageHealth@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "checkpoints_total": len(rows),
        "by_status": by_status,
        "by_horizon": by_horizon,
        "with_plan_id": with_plan,
        "with_subject_guid": with_guid,
        "with_symbol": with_symbol,
        "completed_research_plans": len(completed_plans),
        "joinable_by_plan_id": joinable,
        "complete_to_checkpoint_rate": None,
        "rate_state": "OK" if joinable else "UNCOMPUTABLE",
        "rate_reason": None if joinable else (
            "checkpoints key on decision_id and carry no plan_id, while a "
            "completed research row keys on plan_id — the two ends do not join. "
            "Not 0%: the binder wrote "
            f"{len(rows)} checkpoints."
        ),
        "non_security_subjects": non_security,
        "on_dust_symbols": on_dust,
        "class": "D",
        "note": (
            "Lineage health, not a score. A subject the binder could not resolve "
            "is counted, never guessed."
        ),
    }
