"""Positions Context — Data Broker read model for "if I own it" (Investment Command Center, operator 2026-10-08).

Per symbol, aggregated across accounts: shares, market value, average cost, cost basis, unrealized gain/loss,
portfolio weight — read through lib/portfolio_positions (the one accessor for the holdings_accounts store), plus
the last sell date from the broker ledger trade_transactions (drives "recently sold").

Realized gain/loss and days held are NOT derived here: a FIFO over trade_transactions mixed pre/post-split prices
and transfer-reset lot dates (SCHD showed +$138,787 realized, 2026-10-08). Their authority is positions_store
(position_lots / realized_lots, which reproduce the broker); they stay "pending" until that reader is approved.

The positions_store tables (positions_current / position_lots / realized_lots) are SHADOW until the operator approves
each phase-3 reader batch (config/data_source_authority.json) — this module does not read them.
Zero provider calls. Read-only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_positions_context(db_query, symbols: list[str], *, today: date | None = None,
                          holdings_path: Optional[Path] = None,
                          quotes: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, dict[str, Any]]:
    """Per symbol across accounts. Positions come through lib/portfolio_positions (the ONE accessor: price from
    the data-broker quote at read time, never a stored current_price; value = shares × price; P&L = value − cost)."""
    try:
        from scripts.lib import portfolio_positions as pp
    except ImportError:  # pragma: no cover - flat import layout
        from lib import portfolio_positions as pp  # type: ignore
    syms = sorted({str(s).upper().strip() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    out: dict[str, dict[str, Any]] = {}
    doc = pp.load_store(holdings_path)
    as_of = doc.get("as_of") or doc.get("data_as_of")
    total_value = _f((doc.get("portfolio_totals") or {}).get("total_value"))
    quotes = quotes or {}
    for r in doc.get("holdings") or []:
        s = str(r.get("symbol") or "").upper()
        qty = _f(r.get("shares", r.get("quantity")))
        if s not in syms or not qty or qty <= 0 or pp.is_cash(r):
            continue
        mark = pp.resolve_mark(r, quote=quotes.get(s))
        vp = pp.value_and_pl(r, mark)
        o = out.setdefault(s, {"shares": 0.0, "market_value": 0.0, "cost_basis": 0.0, "cost_known": True,
                               "accounts": [], "as_of": as_of, "mark": mark,
                               "source": "lib.portfolio_positions (holdings_accounts store)"})
        o["shares"] += qty
        o["market_value"] += vp.get("market_value") or 0.0
        cb = vp.get("cost_basis")
        if cb is None and pp.per_share_cost(r) is not None:
            cb = pp.per_share_cost(r) * qty
        if cb is None:
            o["cost_known"] = False
        else:
            o["cost_basis"] += cb
        o["accounts"].append(r.get("account") or r.get("account_id"))
    for s, o in out.items():
        o["market_value"] = round(o["market_value"], 2)
        if o["cost_known"] and o["cost_basis"]:
            o["avg_cost"] = round(o["cost_basis"] / o["shares"], 4)
            o["unrealized_pl"] = round(o["market_value"] - o["cost_basis"], 2)
            o["unrealized_pl_pct"] = round(o["unrealized_pl"] / o["cost_basis"] * 100, 2)
        else:
            o["avg_cost"] = o["unrealized_pl"] = o["unrealized_pl_pct"] = None
        # weight = market value ÷ portfolio total value (portfolio_pct rows are inconsistent in scale)
        o["weight_pct"] = round(o["market_value"] / total_value * 100, 3) if total_value else None
    # ledger: last sell date only (recently sold) — see the module docstring for why realized is not derived here
    try:
        rows = db_query(
            """SELECT upper(symbol) AS s, max(trade_date) AS last_sell FROM trade_transactions
                WHERE upper(symbol) = ANY(%s) AND lower(action) LIKE 'sell%%' GROUP BY 1""", (syms,)) or []
    except Exception:
        rows = []
    for r in rows:
        o = out.setdefault(r["s"], {"shares": 0.0, "source": "trade_transactions"})
        ls = r.get("last_sell")
        o["last_sell_date"] = ls.isoformat() if hasattr(ls, "isoformat") else (str(ls)[:10] if ls else None)
    for o in out.values():
        o["realized_pl"] = None
        o["days_held"] = None
        o["pending"] = {"realized_pl": "positions_store realized_lots reader awaits operator phase-3 approval",
                        "days_held": "positions_store position_lots reader awaits operator phase-3 approval"}
    for o in out.values():
        o["owned"] = bool(o.get("shares"))
    return out
