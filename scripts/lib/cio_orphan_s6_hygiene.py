"""Cancel open S6 plans whose subject is not a held, non-dust position.

Wave 2 — operator-authorised follow-up to slice 16, which surfaced three open
`S6_CONCENTRATION_OR_DISPOSITION` plans on names that are not in the book:
`CASH`, `QCOM` and dust `SRNE`.

A concentration/disposition question presupposes a position to concentrate or
dispose of. On CASH it is a category error, on a name the operator does not own
it is noise, and on a residual share it is the SCHG mistake again — the same
dust rule applies.

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
ACTOR = "cio_orphan_s6_hygiene"
REASON = "s6_subject_not_held_non_dust"

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


def select_orphan_s6(
    store: Any,
    *,
    holdings: Optional[dict[str, Any]] = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
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

    try:
        rows = store.list_open_plans(situation_type=S6, limit=100000)
    except TypeError:
        rows = [
            p for p in (store.list_open_plans(limit=100000) or [])
            if p.get("situation_type") == S6
        ]

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
        out.append({
            "plan_id": plan.get("plan_id"),
            "symbols": list(plan.get("symbols") or []),
            "status": plan.get("status"),
            "orphan_reason": reason,
            "class": "D",
        })
        if limit and len(out) >= int(limit):
            break
    out.sort(key=lambda r: (r["orphan_reason"], str(r["plan_id"])))
    return out


def cancel_orphan_s6(
    store: Any,
    *,
    holdings: Optional[dict[str, Any]] = None,
    apply: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Dry by default. Cancels — never deletes — orphaned S6 plans."""
    candidates = select_orphan_s6(store, holdings=holdings, limit=limit)
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
    for row in candidates:
        by_reason[row["orphan_reason"]] = by_reason.get(row["orphan_reason"], 0) + 1
        for s in row["symbols"]:
            key = str(s).upper()
            by_symbol[key] = by_symbol.get(key, 0) + 1

    return {
        "schema": "OrphanS6Hygiene@v1",
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
        "samples": candidates[:10],
        "deletes_history": False,
        "note": (
            "S6 asks a concentration/disposition question, which presupposes a "
            "position. Cancelled, not deleted; the plan stays readable."
        ),
    }
