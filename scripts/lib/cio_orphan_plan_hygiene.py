"""Cancel open plans whose subject is not a held, non-dust position.

Covers S1 and S6 — both ask a question that presupposes a position, and both
reached residuals through a price-ratio branch a residual can never escape
(S6 `disposition_loss_…`, S1 `deep_drawdown_from_basis_…`). On CASH it is a
category error, on a name the operator does not own it is noise, and on a
residual share it is the SCHG mistake again.

Renamed from `cio_orphan_s6_hygiene` on 2026-08-29 when S1 was added: 35 open S1
plans had accumulated on JEPI (20), SRNE (14) and LDOS (1) by exactly the same
mechanism, so the S6-only name had become wrong.

READ_ONLY_ADVISORY. MBI=0. `notify: false`.

**Cancel, never delete.** `update_plan(status="cancelled")` appends a
`PLAN_UPDATED` event; no history row is removed and the plan stays readable.
Dry by default.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
S6 = "S6_CONCENTRATION_OR_DISPOSITION"
S1 = "S1_POSITION_LIFECYCLE"
SUBJECT_SITUATIONS = (S1, S6)
ACTOR = "cio_orphan_plan_hygiene"
REASON = "subject_not_held_non_dust"

CASH_SLEEVE = "cash_sleeve"
DUST_RESIDUAL = "dust_residual"
NOT_HELD = "not_held"


def orphan_reason(
    symbols: list[str],
    *,
    held_non_dust: set[str],
    dust: set[str],
    cash_symbols: set[str],
) -> Optional[str]:
    """Why this S6 plan has no subject, or None when it has a real one.

    A plan naming *any* held non-dust symbol is kept — a multi-symbol plan is
    not orphaned by one bad leg.
    """
    syms = {str(s).strip().upper() for s in (symbols or []) if s}
    if not syms:
        return "no_symbols"
    if syms & held_non_dust:
        return None
    if syms <= cash_symbols:
        return CASH_SLEEVE
    if syms <= dust:
        return DUST_RESIDUAL
    return NOT_HELD


def select_orphan_plans(
    store: Any,
    *,
    holdings: Optional[dict[str, Any]] = None,
    limit: int = 0,
    situations: tuple[str, ...] = SUBJECT_SITUATIONS,
    reasons: Optional[tuple[str, ...]] = None,
) -> list[dict[str, Any]]:
    """Orphaned plans, optionally narrowed to specific orphan reasons.

    `reasons` exists so an authorisation boundary can be stated in the command
    rather than in the operator's head: "cancel the dust ones" is a different
    decision from "cancel everything the detector flags", and a name that is
    merely *not held* may be a data problem worth understanding before it is
    swept away.
    """
    from scripts.lib.cio_investment_product import (
        collect_holdings,
        dust_symbols,
        held_equity_symbols_nondust,
    )
    from scripts.lib.holdings_universe import CASH_SYMBOLS

    holdings = holdings if holdings is not None else collect_holdings(None)
    held_non_dust = set(held_equity_symbols_nondust(holdings))
    dust = set(dust_symbols(holdings))
    cash = set(CASH_SYMBOLS)

    rows: list[dict[str, Any]] = []
    for situation in situations:
        try:
            rows.extend(store.list_open_plans(situation_type=situation, limit=100000) or [])
        except TypeError:
            rows.extend([
                p for p in (store.list_open_plans(limit=100000) or [])
                if p.get("situation_type") == situation
            ])

    out: list[dict[str, Any]] = []
    for plan in rows or []:
        if not isinstance(plan, dict):
            continue
        reason = orphan_reason(
            plan.get("symbols") or [],
            held_non_dust=held_non_dust,
            dust=dust,
            cash_symbols=cash,
        )
        if reason is None:
            continue
        if reasons is not None and reason not in reasons:
            continue
        out.append({
            "plan_id": plan.get("plan_id"),
            "symbols": list(plan.get("symbols") or []),
            "status": plan.get("status"),
            "situation_type": plan.get("situation_type"),
            "orphan_reason": reason,
            "class": "D",
        })
        if limit and len(out) >= int(limit):
            break
    out.sort(key=lambda r: (r["orphan_reason"], str(r["plan_id"])))
    return out


def cancel_orphan_plans(
    store: Any,
    *,
    holdings: Optional[dict[str, Any]] = None,
    apply: bool = False,
    limit: int = 0,
    situations: tuple[str, ...] = SUBJECT_SITUATIONS,
    reasons: Optional[tuple[str, ...]] = None,
) -> dict[str, Any]:
    """Dry by default. Cancels — never deletes — orphaned S1/S6 plans."""
    candidates = select_orphan_plans(
        store, holdings=holdings, limit=limit, situations=situations,
        reasons=reasons,
    )
    cancelled: list[str] = []
    if apply:
        for row in candidates:
            pid = str(row.get("plan_id") or "")
            if not pid:
                continue
            store.update_plan(
                pid,
                status="cancelled",
                status_reason=f"{REASON}:{row['orphan_reason']}",
                actor_id=ACTOR,
            )
            cancelled.append(pid)

    by_reason: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    by_situation: dict[str, int] = {}
    for row in candidates:
        st = str(row.get("situation_type") or "UNKNOWN")
        by_situation[st] = by_situation.get(st, 0) + 1
        by_reason[row["orphan_reason"]] = by_reason.get(row["orphan_reason"], 0) + 1
        for s in row["symbols"]:
            key = str(s).upper()
            by_symbol[key] = by_symbol.get(key, 0) + 1

    return {
        "schema": "OrphanPlanHygiene@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "notify": False,
        "apply": bool(apply),
        "would_cancel": len(candidates),
        "cancelled": len(cancelled),
        "cancelled_plan_ids": cancelled,
        "by_reason": by_reason,
        "by_symbol": by_symbol,
        "by_situation": by_situation,
        "situations": list(situations),
        "reasons_filter": list(reasons) if reasons is not None else None,
        "samples": candidates[:10],
        "deletes_history": False,
        "note": (
            "S1 and S6 both ask a question that presupposes a position. "
            "Cancelled, not deleted; the plan stays readable."
        ),
    }
