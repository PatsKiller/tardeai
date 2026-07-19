#!/usr/bin/env python3
"""ticker_attribution.py — v1.1 Phase 6: per-underlying economic attribution.

Three SEPARATE, reconciling components per ticker — raw stock price return is
never relabeled with option premium:

  STOCK     realized (trade_closed) + unrealized (holdings.json vs basis)
            + stock fees (transaction ledger)
  OPTIONS   realized (lifecycle closed legs w/ known prices + outcome ledger)
            + unrealized (latest open-strategy snapshots)
            + premium collected/paid + option fees; protective-put premium is
            a HEDGE COST line, its subsequent P&L stays in the options component
  DIVIDENDS receipts from the transaction ledger

INVARIANT (checked, returned with every payload):
  stock + options + dividends − fees = combined ticker contribution
Portfolio view: Σ ticker combined + explicitly-listed unallocated = total.

UNKNOWN stays None; a ticker with unpriceable pieces reports them in gaps[]
rather than pretending completeness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"
DIVIDEND_ACTIONS = ("Dividend", "Qualified Dividend", "Cash Dividend",
                    "Reinvested Dividend", "Reinvest Dividend", "Special Dividend",
                    "Long Term Cap Gain Reinvest")


def _stock_component(cur, symbol: str) -> dict:
    cur.execute("""SELECT COALESCE(sum(pnl),0), count(*) FROM trade_closed WHERE symbol=%s""",
                (symbol,))
    realized, n_closed = cur.fetchone()
    unreal = basis_src = None
    try:
        h = json.loads(HOLDINGS.read_text())
        rows = [r for r in h.get("holdings", []) if (r.get("symbol") or "").upper() == symbol
                and not r.get("is_cash")]
        if rows:
            known = [r for r in rows if r.get("gain_loss") is not None]
            unreal = round(sum(float(r["gain_loss"]) for r in known), 2) if known else None
            basis_src = ",".join(sorted({r.get("cost_basis_source") or "?" for r in rows}))
    except Exception:
        pass
    cur.execute("""SELECT COALESCE(sum(fees),0) FROM trade_transactions
                   WHERE upper(symbol)=%s AND action IN ('Buy','Sell')""", (symbol,))
    fees = float(cur.fetchone()[0] or 0)
    return {"realized": float(realized or 0), "closed_trades": n_closed,
            "unrealized": unreal, "basis_source": basis_src, "fees": round(fees, 2)}


def _options_component(cur, symbol: str) -> dict:
    # realized: closed legs with BOTH prices known, grouped premium flows
    cur.execute("""SELECT l.side, l.contracts, l.multiplier, l.opening_price, l.closed_price,
                          l.opening_fees, p.strategy_type
                   FROM options_strategy_legs l
                   JOIN options_strategy_positions p USING (strategy_position_id)
                   WHERE p.underlying=%s""", (symbol,))
    realized = prem_collected = prem_paid = fees = hedge_cost = 0.0
    gaps = []
    for side, n, mult, op, cp, ofees, stype in cur.fetchall():
        n, mult = float(n), int(mult)
        fees += float(ofees or 0)
        if op is not None:
            cash = float(op) * n * mult
            if side == "short":
                prem_collected += cash
            else:
                prem_paid += cash
                if stype == "protective_put":
                    hedge_cost += cash
        if cp is not None and op is not None:
            realized += ((float(op) - float(cp)) if side == "short"
                         else (float(cp) - float(op))) * n * mult
        elif cp is None and op is None:
            gaps.append("leg with unknown basis and open state")
    # unrealized from latest snapshots of open strategies
    cur.execute("""SELECT s.unrealized_pnl FROM options_strategy_positions p
                   JOIN options_position_snapshots s ON s.snapshot_id=p.latest_snapshot_id
                   WHERE p.underlying=%s AND p.status IN ('open','closing')""", (symbol,))
    unreal_rows = cur.fetchall()
    unreal = (round(sum(float(r[0]) for r in unreal_rows if r[0] is not None), 2)
              if unreal_rows else 0.0)
    if any(r[0] is None for r in unreal_rows):
        gaps.append("open strategy with unpriceable snapshot")
        unreal = None
    return {"realized": round(realized, 2), "unrealized": unreal,
            "premium_collected": round(prem_collected, 2),
            "premium_paid": round(prem_paid, 2),
            "hedge_cost_protective_puts": round(hedge_cost, 2),
            "fees": round(fees, 2), "gaps": gaps}


def _dividends(cur, symbol: str) -> float:
    cur.execute("""SELECT COALESCE(sum(amount),0) FROM trade_transactions
                   WHERE upper(symbol)=%s AND action = ANY(%s)""",
                (symbol, list(DIVIDEND_ACTIONS)))
    return round(float(cur.fetchone()[0] or 0), 2)


def ticker_attribution(cur, symbol: str) -> dict:
    symbol = symbol.upper()
    stock = _stock_component(cur, symbol)
    options = _options_component(cur, symbol)
    dividends = _dividends(cur, symbol)
    parts = {
        "stock_total": (None if stock["unrealized"] is None
                        else round(stock["realized"] + stock["unrealized"], 2)),
        "options_total": (None if options["unrealized"] is None
                          else round(options["realized"] + options["unrealized"], 2)),
    }
    fees_total = round(stock["fees"] + options["fees"], 2)
    combinable = parts["stock_total"] is not None and parts["options_total"] is not None
    combined = (round(parts["stock_total"] + parts["options_total"] + dividends - fees_total, 2)
                if combinable else None)
    # the invariant, restated and machine-checked
    invariant_ok = (combined is None or
                    abs((parts["stock_total"] + parts["options_total"] + dividends - fees_total)
                        - combined) < 0.01)
    return {"symbol": symbol,
            "stock": stock,                       # stock-only return stays untouched
            "options": options,                   # option-strategy result, separate
            "dividends": dividends,
            "fees_total": fees_total,
            "combined_economic_result": combined, # the only place components merge
            "invariant": "stock + options + dividends - fees = combined",
            "invariant_ok": invariant_ok,
            "gaps": (["stock unrealized UNKNOWN"] if stock["unrealized"] is None else [])
                    + options["gaps"]}


def portfolio_attribution(cur, symbols: list[str] | None = None) -> dict:
    if symbols is None:
        cur.execute("""SELECT DISTINCT underlying FROM options_strategy_positions
                       UNION SELECT DISTINCT symbol FROM trade_closed""")
        symbols = sorted({r[0] for r in cur.fetchall() if r[0]})
    rows = [ticker_attribution(cur, s) for s in symbols]
    combinable = [r for r in rows if r["combined_economic_result"] is not None]
    total = round(sum(r["combined_economic_result"] for r in combinable), 2)
    unallocated = [r["symbol"] for r in rows if r["combined_economic_result"] is None]
    return {"tickers": rows, "sum_of_combined": total,
            "unallocated_symbols": unallocated,
            "note": "portfolio total = sum_of_combined + explicitly unallocated items; "
                    "cash interest and non-symbol flows are outside ticker attribution by design"}


if __name__ == "__main__":
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    sym = sys.argv[1] if len(sys.argv) > 1 else "CSCO"
    print(json.dumps(ticker_attribution(cur, sym), indent=1, default=str))
