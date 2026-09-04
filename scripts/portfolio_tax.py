"""portfolio_tax.py — Trade AI v12 Portfolio Intelligence
FIFO tax lot tracking, realized/unrealized gain computation,
tax loss harvest identification, holding period classification.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Tax constants ─────────────────────────────────────────────────────────────

LONG_TERM_DAYS = 365  # Held > 1 year = long-term capital gain
ST_RATE = 0.37  # Short-term = ordinary income (top bracket)
LT_RATE = 0.20  # Long-term capital gains rate (top bracket)
NIIT_RATE = 0.038  # Net investment income tax (high income)

# Wash sale window (30 days before/after sale)
WASH_SALE_DAYS = 30


# ── Lot Data Structures ───────────────────────────────────────────────────────


def _make_lot(symbol: str, account: str, date: str, shares: float, cost_per_share: float, action: str = "buy") -> Dict:
    return {
        "symbol": symbol,
        "account": account,
        "lot_date": date,
        "shares": shares,
        "shares_remaining": shares,
        "cost_per_share": cost_per_share,
        "total_cost": shares * cost_per_share,
        "action": action,
        "closed": False,
    }


def _days_held(lot_date: str, as_of: Optional[str] = None) -> int:
    try:
        acquired = datetime.strptime(lot_date[:10], "%Y-%m-%d")
        sold_dt = datetime.strptime(as_of[:10], "%Y-%m-%d") if as_of else datetime.now()
        return (sold_dt - acquired).days
    except Exception:
        return 0


def _holding_period(lot_date: str, as_of: Optional[str] = None) -> str:
    days = _days_held(lot_date, as_of)
    return "LONG" if days >= LONG_TERM_DAYS else "SHORT"


# ── Build Lots from Transactions ──────────────────────────────────────────────


def build_tax_lots(transactions: List[Dict], existing_lots: Optional[Dict] = None) -> Dict[str, List[Dict]]:
    """
    Build FIFO tax lot queue from transaction history.
    Returns: {symbol+account_key: [list of lots]}

    For accounts with no transaction history (Rollover IRA, Roth),
    creates synthetic lots from current holdings at cost basis.
    """
    lots: Dict[str, List[Dict]] = defaultdict(list)

    # Which keys does the transaction history actually cover? For those, the history is
    # authoritative and the lot list is rebuilt from it.
    #
    # This used to seed `lots` with the PREVIOUS run's output and then replay the whole
    # transaction history on top, appending a new lot for every buy. Every run therefore
    # added another full copy of every lot it had already recorded: run N held N copies.
    # By the time it was found, tax_lots.json was 98% duplicates -- 12,870 of 13,139 rows
    # -- and AMD:schwab_taxable held 113 identical lots, one per run.
    #
    # Seeding cannot simply be dropped, though: a key with no transactions (an account
    # whose history was never imported) would lose its lots entirely. So existing lots
    # are carried forward only for keys the transactions do not cover.
    txn_keys = {
        f"{str(t.get('symbol', '')).upper()}:{t.get('account', '')}"
        for t in transactions
        if str(t.get("txn_type", "")) in ("buy", "reinvest_shares", "sell")
    }
    if existing_lots:
        for k, v in existing_lots.items():
            if k not in txn_keys:
                lots[k] = v

    # Process transactions chronologically
    txns_sorted = sorted(transactions, key=lambda t: t.get("date", ""))

    for txn in txns_sorted:
        sym = txn.get("symbol", "").upper()
        acct = txn.get("account", "")
        txn_type = txn.get("txn_type", "")
        qty = abs(txn.get("quantity") or 0)
        price = txn.get("price") or 0
        date = txn.get("date", "")
        key = f"{sym}:{acct}"

        if txn_type in ("buy", "reinvest_shares"):
            if qty > 0 and price > 0:
                lots[key].append(_make_lot(sym, acct, date, qty, price, txn_type))

        elif txn_type == "sell":
            if qty > 0:
                _apply_fifo_sell(lots[key], qty, date)

    return dict(lots)


def _apply_fifo_sell(lot_queue: List[Dict], qty_sold: float, sell_date: str) -> List[Dict]:
    """Apply FIFO sell to lot queue. Modifies in place. Returns closed lots."""
    closed = []
    remaining = qty_sold

    for lot in lot_queue:
        if lot["closed"] or lot["shares_remaining"] <= 0:
            continue
        if remaining <= 0:
            break

        if lot["shares_remaining"] <= remaining:
            # Fully close this lot
            closed.append({**lot, "sold_qty": lot["shares_remaining"], "sell_date": sell_date})
            remaining -= lot["shares_remaining"]
            lot["shares_remaining"] = 0
            lot["closed"] = True
        else:
            # Partially close
            closed.append({**lot, "sold_qty": remaining, "sell_date": sell_date})
            lot["shares_remaining"] -= remaining
            remaining = 0

    return closed


# ── Synthetic Lots from Current Holdings ──────────────────────────────────────


def build_synthetic_lots_from_holdings(holdings: List[Dict], as_of: str) -> Dict[str, List[Dict]]:
    """
    For accounts without transaction history, create synthetic lots
    using cost basis from current positions.
    Uses a 3-year-ago date as purchase date (assumes long-term for most positions).
    """
    lots: Dict[str, List[Dict]] = {}
    est_date = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

    for h in holdings:
        sym = h.get("symbol", "").upper()
        acct = h.get("account", "")
        shares = h.get("shares") or 0
        cost_basis = h.get("cost_basis") or 0
        mv = h.get("market_value") or 0

        if h.get("is_loan") or h.get("is_cash") or sym == "CASH":
            continue
        if shares <= 0 or cost_basis <= 0:
            continue

        key = f"{sym}:{acct}"
        if key not in lots:
            cost_per_share = cost_basis / shares if shares > 0 else 0
            lots[key] = [_make_lot(sym, acct, est_date, shares, cost_per_share, "synthetic")]

    return lots


# ── Unrealized Gain Analysis ──────────────────────────────────────────────────


def compute_unrealized_gains(
    holdings: List[Dict],
    lots: Dict[str, List[Dict]],
    as_of: str,
) -> List[Dict]:
    """Compute unrealized gain/loss with holding period and tax estimate."""
    results = []

    for h in holdings:
        if h.get("is_loan") or h.get("is_cash"):
            continue
        sym = h.get("symbol", "").upper()
        acct = h.get("account", "")
        shares = h.get("shares") or 0
        mv = h.get("market_value") or 0
        cb = h.get("cost_basis") or 0
        gl = h.get("gain_loss") or 0
        gl_pct = h.get("gain_loss_pct") or 0

        if mv <= 0 or cb <= 0:
            continue

        # Check lots for holding period
        key = f"{sym}:{acct}"
        lot_list = lots.get(key, [])
        holding_period = "UNKNOWN"
        if lot_list:
            open_lot_dates = [l["lot_date"] for l in lot_list if not l.get("closed")]
            if open_lot_dates:
                oldest_date = min(open_lot_dates)
                holding_period = _holding_period(oldest_date, as_of)
            else:
                # All lots closed (e.g. position was sold) — treat as long-term
                oldest_date = min(l["lot_date"] for l in lot_list)
                holding_period = _holding_period(oldest_date, as_of)

        # Tax estimate
        if gl > 0:
            rate = LT_RATE if holding_period == "LONG" else ST_RATE
            tax_est = gl * rate
        else:
            tax_est = 0

        results.append(
            {
                "symbol": sym,
                "account": h.get("account_display", acct),
                "account_type": h.get("account_type", ""),
                "taxable": h.get("account_type") == "taxable",
                "shares": shares,
                "market_value": mv,
                "cost_basis": cb,
                "unrealized_gain": gl,
                "unrealized_gain_pct": gl_pct,
                "holding_period": holding_period,
                "tax_estimate": tax_est,
                "tax_rate_applied": (LT_RATE if holding_period == "LONG" else ST_RATE) if gl > 0 else 0,
                "after_tax_gain": gl - tax_est,
            }
        )

    results.sort(key=lambda x: -(x["unrealized_gain"] or 0))
    return results


# ── Tax Loss Harvest Candidates ────────────────────────────────────────────────


def find_harvest_candidates(
    unrealized: List[Dict],
    min_loss: float = 500.0,
    min_loss_pct: float = 10.0,
) -> List[Dict]:
    """Identify tax loss harvest candidates with wash sale risk flag."""
    candidates = []

    for u in unrealized:
        gl = u.get("unrealized_gain") or 0
        gl_pct = u.get("unrealized_gain_pct") or 0
        taxable = u.get("taxable", False)
        acct_type = u.get("account_type", "")

        # Only taxable accounts benefit from loss harvesting
        # IRA losses have no tax benefit
        if acct_type in ("401k", "rollover_ira", "roth_ira", "traditional_ira"):
            continue

        if gl < -min_loss and gl_pct < -min_loss_pct:
            candidates.append(
                {
                    **u,
                    "tax_savings_estimate": abs(gl) * ST_RATE,
                    "wash_sale_warning": "Watch 30-day wash sale window if repurchasing same/similar security",
                }
            )

    candidates.sort(key=lambda x: x["unrealized_gain"])
    return candidates


# ── Realized Gain Summary from Transactions ────────────────────────────────────


def compute_realized_gains(transactions: List[Dict]) -> Dict[str, Any]:
    """Compute YTD realized gains from sell transactions."""
    current_year = datetime.now().year
    ytd_gains = []

    sell_txns = [
        t for t in transactions if t.get("txn_type") == "sell" and t.get("date", "").startswith(str(current_year))
    ]

    total_proceeds = sum(abs(t.get("amount") or 0) for t in sell_txns)

    return {
        "ytd_sell_transactions": len(sell_txns),
        "ytd_total_proceeds": total_proceeds,
        "ytd_gains": ytd_gains,  # Would need cost tracking to compute gain per sale
        "note": "Full realized gain tracking requires complete transaction history",
    }


# ── Dividend Income from Transactions ────────────────────────────────────────


def compute_received_dividends(transactions: List[Dict]) -> Dict[str, Any]:
    """Summarize dividends received from transaction history."""
    current_year = datetime.now().year
    ytd_divs = [
        t for t in transactions if t.get("txn_type") == "dividend" and t.get("date", "").startswith(str(current_year))
    ]

    by_symbol: Dict[str, float] = defaultdict(float)
    for d in ytd_divs:
        sym = d.get("symbol", "UNKNOWN")
        by_symbol[sym] += abs(d.get("amount") or 0)

    total = sum(by_symbol.values())
    monthly_avg = total / max(datetime.now().month, 1)

    return {
        "ytd_total": total,
        "ytd_monthly_avg": monthly_avg,
        "ytd_projected_annual": monthly_avg * 12,
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda x: -x[1])),
        "transaction_count": len(ytd_divs),
    }


# ── Main Tax Analysis Entry Point ─────────────────────────────────────────────


def analyze_taxes(portfolio: Dict, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run complete tax analysis on portfolio."""
    holdings = portfolio.get("holdings", [])
    transactions = portfolio.get("transactions", [])
    as_of = portfolio.get("as_of", datetime.now().strftime("%Y-%m-%d"))

    print("  [tax] Building tax lots...")
    # Try to load existing lots from state
    existing_lots = None
    if state_dir:
        lot_path = state_dir / "tax_lots.json"
        if lot_path.exists():
            with open(lot_path) as f:
                existing_lots = json.load(f)

    # Build lots from transactions
    lots = build_tax_lots(transactions, existing_lots)

    # Build synthetic lots for holdings without transaction history
    synthetic = build_synthetic_lots_from_holdings(holdings, as_of)
    for k, v in synthetic.items():
        if k not in lots:
            lots[k] = v

    print("  [tax] Computing unrealized gains...")
    unrealized = compute_unrealized_gains(holdings, lots, as_of)

    print("  [tax] Finding harvest candidates...")
    harvest = find_harvest_candidates(unrealized)

    print("  [tax] Computing realized gains...")
    realized = compute_realized_gains(transactions)

    print("  [tax] Summarizing dividend income...")
    div_income = compute_received_dividends(transactions)

    # Save updated lots
    if state_dir:
        state_dir.mkdir(parents=True, exist_ok=True)
        lot_path = state_dir / "tax_lots.json"
        with open(lot_path, "w") as f:
            json.dump(lots, f, indent=2, default=str)

    # Summary totals
    total_unrealized_gain = sum(u.get("unrealized_gain") or 0 for u in unrealized)
    taxable_unrealized = sum(u.get("unrealized_gain") or 0 for u in unrealized if u.get("taxable"))
    est_tax_if_sold = sum(u.get("tax_estimate") or 0 for u in unrealized if u.get("taxable"))

    return {
        "as_of": as_of,
        "unrealized_gains": unrealized,
        "harvest_candidates": harvest,
        "realized_gains": realized,
        "dividend_income_ytd": div_income,
        "summary": {
            "total_unrealized_gain": total_unrealized_gain,
            "taxable_unrealized_gain": taxable_unrealized,
            "estimated_tax_if_all_sold": est_tax_if_sold,
            "harvest_opportunities": len(harvest),
            "harvest_potential_savings": sum(c.get("tax_savings_estimate") or 0 for c in harvest),
        },
        "lots": lots,
    }
