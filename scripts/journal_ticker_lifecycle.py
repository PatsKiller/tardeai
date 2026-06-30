#!/usr/bin/env python3
"""Ticker lifecycle aggregation for imported broker activity.

Pure helpers first, DB/CLI second: tests can validate Fidelity examples without
network access or broker writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

CASH_ACTIONS = {"Cash Receipt", "Cash Transfer", "Transfer", "Rollover", "Journal"}
DIVIDEND_ACTIONS = {"Dividend", "Reinvested Dividend"}
BUY_ACTIONS = {"Buy", "Reinvested Dividend"}
SELL_ACTIONS = {"Sell"}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _date(raw) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except Exception:
        return None


def _amount(row: dict) -> float:
    amount = _f(row.get("amount"))
    if amount:
        return amount
    qty = _f(row.get("quantity"))
    price = _f(row.get("price"))
    return qty * price


def _cost_from_buy(row: dict) -> float:
    amount = abs(_amount(row))
    if amount:
        return amount
    return abs(_f(row.get("quantity")) * _f(row.get("price")))


def aggregate_ticker_activity(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate normalized trade_transactions-like rows by ticker.

    Buys build an average-cost lot queue. Sells realize P/L against the current
    weighted average. Dividends are income, not trade wins. Rollover/cash rows
    are reported separately and excluded from trading P/L.
    """
    state: dict[str, dict[str, Any]] = {}
    lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)

    def ensure(sym: str) -> dict[str, Any]:
        if sym not in state:
            state[sym] = {
                "symbol": sym,
                "total_buys": 0.0,
                "total_sells": 0.0,
                "weighted_average_cost": 0.0,
                "realized_pnl": 0.0,
                "realized_pnl_pct": 0.0,
                "dividends_received": 0.0,
                "entries": 0,
                "exits": 0,
                "wins": 0,
                "losses": 0,
                "average_hold_days": None,
                "best_trade": None,
                "worst_trade": None,
                "current_open_shares": 0.0,
                "lifetime_ticker_pnl": 0.0,
                "cash_movement": 0.0,
                "round_trips": [],
            }
        return state[sym]

    ordered = sorted(rows, key=lambda r: (str(r.get("trade_date") or ""), str(r.get("trade_time") or "")))
    for row in ordered:
        action = str(row.get("action") or "").strip()
        sym = str(row.get("symbol") or "CASH").upper().strip() or "CASH"
        qty = abs(_f(row.get("quantity")))
        d = _date(row.get("trade_date"))
        rec = ensure(sym)

        if action in CASH_ACTIONS or sym == "CASH":
            rec["cash_movement"] = round(rec["cash_movement"] + _amount(row), 2)
            continue

        if action in DIVIDEND_ACTIONS:
            rec["dividends_received"] = round(rec["dividends_received"] + abs(_amount(row)), 2)

        if action in BUY_ACTIONS and qty > 0:
            cost = _cost_from_buy(row)
            rec["total_buys"] = round(rec["total_buys"] + cost, 2)
            rec["entries"] += 1
            lots[sym].append({"qty": qty, "cost": cost, "date": d})

        if action in SELL_ACTIONS and qty > 0:
            proceeds = abs(_amount(row))
            sell_qty = qty
            cost_basis = 0.0
            held_days_total = 0.0
            matched_qty = 0.0
            while sell_qty > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                take = min(sell_qty, lot["qty"])
                lot_unit_cost = lot["cost"] / lot["qty"] if lot["qty"] else 0.0
                cost_basis += take * lot_unit_cost
                if d and lot.get("date"):
                    held_days_total += take * max((d - lot["date"]).days, 0)
                matched_qty += take
                lot["qty"] -= take
                lot["cost"] -= take * lot_unit_cost
                sell_qty -= take
                if lot["qty"] <= 1e-9:
                    lots[sym].popleft()
            if matched_qty <= 1e-9:
                cost_basis = abs(_f(row.get("cost_basis")))
                matched_qty = qty
            pnl = proceeds - cost_basis
            pnl_pct = (pnl / cost_basis * 100.0) if cost_basis else 0.0
            trade = {
                "date": row.get("trade_date"),
                "qty": round(qty, 6),
                "proceeds": round(proceeds, 2),
                "cost_basis": round(cost_basis, 2),
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(pnl_pct, 2),
                "hold_days": round(held_days_total / matched_qty, 1) if matched_qty else None,
            }
            rec["total_sells"] = round(rec["total_sells"] + proceeds, 2)
            rec["realized_pnl"] = round(rec["realized_pnl"] + pnl, 2)
            rec["exits"] += 1
            rec["wins"] += 1 if pnl > 0 else 0
            rec["losses"] += 1 if pnl < 0 else 0
            rec["round_trips"].append(trade)
            rec["best_trade"] = max(rec["round_trips"], key=lambda x: x["realized_pnl"])
            rec["worst_trade"] = min(rec["round_trips"], key=lambda x: x["realized_pnl"])

    for sym, rec in state.items():
        open_qty = sum(l["qty"] for l in lots[sym])
        open_cost = sum(l["cost"] for l in lots[sym])
        rec["current_open_shares"] = round(open_qty, 6)
        rec["weighted_average_cost"] = round(open_cost / open_qty, 4) if open_qty else 0.0
        closed_cost = sum(t["cost_basis"] for t in rec["round_trips"])
        rec["realized_pnl_pct"] = round(rec["realized_pnl"] / closed_cost * 100.0, 2) if closed_cost else 0.0
        hold_days = [t["hold_days"] for t in rec["round_trips"] if t.get("hold_days") is not None]
        rec["average_hold_days"] = round(sum(hold_days) / len(hold_days), 1) if hold_days else None
        rec["lifetime_ticker_pnl"] = round(rec["realized_pnl"] + rec["dividends_received"], 2)
    return state


def load_from_db(account: str | None = None, days: int = 365) -> list[dict[str, Any]]:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if account:
        cur.execute("""SELECT trade_date, action, symbol, quantity, price, amount, fees, description, account, trade_time
                       FROM trade_transactions
                       WHERE account=%s AND trade_date >= %s
                       ORDER BY trade_date, trade_time NULLS LAST""", (account, start))
    else:
        cur.execute("""SELECT trade_date, action, symbol, quantity, price, amount, fees, description, account, trade_time
                       FROM trade_transactions
                       WHERE trade_date >= %s
                       ORDER BY trade_date, trade_time NULLS LAST""", (start,))
    keys = ["trade_date", "action", "symbol", "quantity", "price", "amount", "fees", "description", "account", "trade_time"]
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate broker activity into ticker lifecycle metrics.")
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    print(json.dumps(aggregate_ticker_activity(load_from_db(args.account, args.days)), indent=2, default=str))


if __name__ == "__main__":
    main()
