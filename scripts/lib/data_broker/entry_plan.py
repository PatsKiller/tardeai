"""Entry Plan — Data Broker read model for watchlist entry zone / stop / target plans.

Batch-reads watchlist_entry_plans (LLM-generated entry zones with stops and targets).
Normalized for decision desks and entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_entry_plans(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {entry_zone_low, entry_zone_high, stop_price, target_price, ...}}
    for a batch, taking only the latest plan per symbol.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, entry_zone_low, entry_zone_high,
                  stop_price, target_price, risk_reward, urgency,
                  proposal_tag
           FROM watchlist_entry_plans
           WHERE upper(symbol) = ANY(%s) AND entry_zone_low IS NOT NULL
           ORDER BY upper(symbol), created_at DESC""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "entry_zone_low": row.get("entry_zone_low"),
                "entry_zone_high": row.get("entry_zone_high"),
                "stop_price": row.get("stop_price"),
                "target_price": row.get("target_price"),
                "risk_reward": row.get("risk_reward"),
                "urgency": row.get("urgency"),
                "proposal_tag": row.get("proposal_tag"),
            }
    return out


def get_entry_ladders(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """{SYMBOL: {suggested_entry, entry_zone_low/high, invalidation_level, targets: [{label, px}], risk_reward,
    urgency, confidence, created_at}} — the latest plan per symbol including its T1/T2/T3 exit ladder
    (Investment Command Center, operator 2026-10-08; get_entry_plans drops the ladder).

    Only prices and labels are read from the ladder — each step's free-text instruction is never copied.
    """
    import json

    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, plan, entry_zone_low, entry_zone_high, limit_price, stop_price,
                  target_price, risk_reward, urgency, confidence, created_at
           FROM watchlist_entry_plans
           WHERE upper(symbol) = ANY(%s)
           ORDER BY upper(symbol), created_at DESC, id DESC""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        plan = row.get("plan")
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except ValueError:
                plan = {}
        plan = plan if isinstance(plan, dict) else {}
        steps = ((plan.get("exit_ladder") or {}).get("steps")) or []
        targets = []
        for st in steps if isinstance(steps, list) else []:
            try:
                px = float(st.get("px"))
            except (TypeError, ValueError, AttributeError):
                continue
            targets.append({"label": str(st.get("label") or f"T{len(targets) + 1}")[:40], "px": px})
        out[sym] = {
            "suggested_entry": (plan.get("proposal") or {}).get("suggested_entry") or row.get("limit_price"),
            "entry_zone_low": row.get("entry_zone_low"),
            "entry_zone_high": row.get("entry_zone_high"),
            "invalidation_level": row.get("stop_price"),
            "plan_target": row.get("target_price"),
            "targets": targets,
            "risk_reward": row.get("risk_reward"),
            "urgency": row.get("urgency"),
            "confidence": row.get("confidence"),
            "created_at": row.get("created_at"),
            "source": "watchlist_entry_plans",
        }
    return out
