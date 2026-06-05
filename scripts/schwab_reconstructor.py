"""schwab_reconstructor.py
Reconstructs current Schwab positions from transaction CSVs + price cache.
Used by portfolio_loader.py when no positions CSV is available.

Usage:
    from schwab_reconstructor import reconstruct_schwab_positions
    holdings, account_totals = reconstruct_schwab_positions(
        transactions_path, account_key, display_name, price_cache, revoked
    )
"""
from __future__ import annotations
import csv
import re
import json
import os
from pathlib import Path
from datetime import datetime


BUY_ACTIONS  = {"Buy", "Reinvest Shares", "Journaled Shares", "Stock Split",
                "Exchange or Exercise", "Transfer of Security or Option In"}
SELL_ACTIONS = {"Sell", "Sell to Open", "Transfer of Security or Option Out",
                "Exchange or Exercise Out"}
SKIP_ACTIONS = {"Reinvest Dividend", "Cash Dividend", "Qualified Dividend",
                "Bank Interest", "Margin Interest", "Service Fee",
                "Wire Funds", "Wire Received", "Journal", "Misc Cash Entry"}


def _parse_qty(val: str) -> float:
    """Parse quantity string like '1,000' or '0.9179'."""
    return float(val.replace(",", "").strip()) if val.strip() else 0.0


def _parse_price(val: str) -> float:
    """Parse price string like '$73.495'."""
    return float(re.sub(r"[^\d.]", "", val)) if val.strip() else 0.0


def _get_cached_price(sym: str, cache: dict) -> tuple[float, float]:
    """Return (latest_price, prev_price) from price cache."""
    entry = cache.get(sym)
    if not entry or not isinstance(entry, dict):
        return 0.0, 0.0
    dates = sorted(k for k in entry if re.match(r"^\d{4}-\d{2}-\d{2}$", k))
    if not dates:
        return 0.0, 0.0
    latest = float(entry[dates[-1]] or 0)
    prev   = float(entry[dates[-2]] or latest) if len(dates) >= 2 else latest
    return latest, prev


def reconstruct_schwab_positions(
    transactions_path: str,
    account_key: str,
    display_name: str,
    account_type: str,
    price_cache: dict,
    revoked_symbols: set | None = None,
) -> tuple[list[dict], dict]:
    """
    Parse a Schwab transaction CSV and reconstruct current positions.
    Returns (holdings_list, account_summary_dict).
    """
    revoked = revoked_symbols or set()
    positions: dict[str, dict] = {}  # sym -> {shares, last_txn_price, description}

    if not os.path.exists(transactions_path):
        return [], {
            "display_name": display_name,
            "account_type": account_type,
            "broker": "schwab",
            "total_value": 0.0,
            "day_change": 0.0,
            "total_cost": 0.0,
            "total_gain": 0.0,
            "total_gain_pct": 0.0,
            "holding_count": 0,
        }

    with open(transactions_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Process oldest → newest (CSV is newest first, so reverse)
    for row in reversed(rows):
        sym    = (row.get("Symbol") or "").strip()
        action = (row.get("Action") or "").strip()
        if not sym or not action:
            continue
        if sym in revoked:
            continue

        qty   = _parse_qty(row.get("Quantity", ""))
        price = _parse_price(row.get("Price", ""))

        if sym not in positions:
            positions[sym] = {
                "shares": 0.0,
                "last_txn_price": 0.0,
                "description": (row.get("Description") or sym).strip(),
                "cost_acc": 0.0,      # cumulative cost basis from actual buy Amounts (average-cost)
                "xfer_shares": 0.0,   # shares acquired with NO cost data (Security Transfer / journal in)
                "has_xfer": False,    # any no-cost transfer in/out → cost basis is partial/unknown
            }

        if price > 0:
            positions[sym]["last_txn_price"] = price

        # amount string from the CSV: "-$1,234.56" (cash out = purchase), "$1,234.56", or blank.
        # _parse_price strips the sign, so recover it from the leading '-'.
        amt_str = (row.get("Amount") or "").strip()
        amt = (-_parse_price(amt_str) if amt_str.startswith("-") else _parse_price(amt_str)) if amt_str else 0.0

        def _reduce_basis(p, sold_qty):
            sb = p["shares"]
            if sb > 0:
                frac = min(sold_qty, sb) / sb
                p["cost_acc"] *= (1 - frac)
                p["xfer_shares"] *= (1 - frac)

        # No-cost share movements (transfers/journals between accounts) → basis is unknown for those
        # shares. Flag the whole position partial; we never fabricate a cost for transferred-in shares.
        if action in ("Security Transfer", "Internal Transfer", "Journaled Shares"):
            positions[sym]["has_xfer"] = True
            positions[sym]["shares"] += qty            # qty is signed (negative = out)
            if qty > 0:
                positions[sym]["xfer_shares"] += qty
        elif action in BUY_ACTIONS and qty > 0:
            positions[sym]["shares"] += qty
            if amt < 0:                                   # cash outflow → real purchase cost
                positions[sym]["cost_acc"] += -amt
            else:                                         # split/other in → no cost in CSV
                positions[sym]["has_xfer"] = True
                positions[sym]["xfer_shares"] += qty
        elif action in SELL_ACTIONS and qty > 0:
            _reduce_basis(positions[sym], qty)            # average-cost reduction
            positions[sym]["shares"] -= qty
        elif action == "Journal" and qty > 0:
            if amt_str.startswith("-"):
                _reduce_basis(positions[sym], qty)
                positions[sym]["shares"] -= qty
            else:
                positions[sym]["shares"] += qty
                positions[sym]["xfer_shares"] += qty

    # Build holdings list
    holdings = []
    total_value    = 0.0
    total_day_chg  = 0.0
    total_cost     = 0.0

    for sym, pos in positions.items():
        shares = round(pos["shares"], 6)
        if shares < 0.001:
            continue  # Fully sold

        cache_price, cache_prev = _get_cached_price(sym, price_cache)
        # Use cache price if available, else last transaction price
        price = cache_price if cache_price > 0 else pos["last_txn_price"]
        prev  = cache_prev  if cache_price > 0 else price

        mv      = shares * price
        day_chg = shares * (price - prev)
        # Cost basis = summed actual buy Amounts (average-cost). If any shares were transferred in
        # without cost data (Security Transfer / journal in), the basis is partial → report it as
        # unknown (None) rather than a misleading understated number.
        basis_partial = pos.get("has_xfer", False) or pos.get("xfer_shares", 0.0) > 0.001
        acc_cost = round(pos.get("cost_acc", 0.0), 2)
        if basis_partial or acc_cost <= 0:
            cost_basis_out, gain_out, gain_pct_out = None, None, None
            cost = 0.0  # not added to total_cost (unknown)
        else:
            cost = acc_cost
            cost_basis_out = acc_cost
            gain_out = round(mv - acc_cost, 2)
            gain_pct_out = round((mv - acc_cost) / acc_cost * 100, 4) if acc_cost > 0 else None
        port_pct = 0.0  # Will be recalculated by portfolio_loader

        holdings.append({
            "symbol":          sym,
            "name":            pos["description"],
            "account":         account_key,
            "account_display": display_name,
            "account_type":    account_type,
            "broker":          "schwab",
            "shares":          shares,
            "price":           round(price, 4),
            "market_value":    round(mv, 2),
            "cost_basis":      cost_basis_out,
            "gain_loss":       gain_out,
            "gain_loss_pct":   gain_pct_out,
            "basis_partial":   basis_partial,
            "cost_basis_source": "transactions_sum",
            "day_change":      round(day_chg, 2),
            "day_change_pct":  round((price - prev) / prev * 100, 4) if prev > 0 else 0.0,
            "portfolio_pct":   0.0,
            "account_pct":     0.0,
            "asset_type":      "Equity",
            "is_etf":          len(sym) <= 4 and sym.isupper(),
            "is_fund":         False,
            "is_cash":         sym in {"SNSXX", "SWVXX", "VMFXX"},
            "reinvest_div":    False,
            "beta":            None,
            "sector_type":     None,
        })

        total_value   += mv
        total_day_chg += day_chg
        total_cost    += cost

    total_gain     = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost > 0 else 0.0

    account_summary = {
        "display_name":    display_name,
        "account_type":    account_type,
        "broker":          "schwab",
        "total_value":     round(total_value, 2),
        "total_cost":      round(total_cost, 2),
        "total_gain":      round(total_gain, 2),
        "total_gain_pct":  round(total_gain_pct, 4),
        "day_change":      round(total_day_chg, 2),
        "day_change_pct":  round(total_day_chg / total_value * 100, 4) if total_value > 0 else 0.0,
        "holding_count":   len(holdings),
        "loan_balance":    0,
        "reconstructed_from_transactions": True,
    }

    return holdings, account_summary
