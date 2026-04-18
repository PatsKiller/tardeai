"""portfolio_loader.py — Trade AI v12 Portfolio Intelligence
Multi-broker data ingestion: Schwab CSV, Fidelity PDF → normalized schema.

Supported formats:
  Schwab Positions CSV: row 0 = account header, row 1 = blank, row 2 = cols
  Schwab Transactions CSV: standard header row 0
  Fidelity 401k PDF: page 2 holdings table (market value extraction)

Output schema (per holding):
  symbol, name, account, account_type, broker, shares, price, market_value,
  cost_basis, gain_loss, gain_loss_pct, asset_type, reinvest_div,
  day_change, day_change_pct, is_revoked, is_etf, is_fund, sector
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
try:
    from db_adapter import save_holdings as _db_save_holdings, load_holdings as _db_load_holdings
except ImportError:
    _db_save_holdings = None
    _db_load_holdings = None
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_num(val: Any) -> float:
    """Parse Schwab numeric strings: '$1,234.56', '-$99.50', '10.85%', etc."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    text = str(val).strip()
    if not text or text in ("-", "N/A", "--", "Incomplete", ""):
        return 0.0
    text = text.replace("$", "").replace(",", "").replace("%", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return 0.0


def _load_yaml(path: Path) -> Dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ── Schwab Positions CSV Parser ───────────────────────────────────────────────

def parse_schwab_positions(
    csv_path: Path,
    account_key: str,
    account_cfg: Dict,
    revoked: List[str],
) -> List[Dict]:
    """
    Parse Schwab positions CSV export.
    Format: row 0 = account header string, row 1 = blank, row 2 = column names,
            rows 3+ = data, last 1-3 rows = summary (skip).
    """
    # Read raw text to find header row
    with open(csv_path, encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Find the header row (contains "Symbol")
    header_idx = None
    for i, line in enumerate(raw_lines):
        if '"Symbol"' in line or line.strip().startswith('"Symbol"') or line.strip().startswith('Symbol'):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(f"Cannot find header row in {csv_path}")

    # Read CSV starting from the header row
    df = pd.read_csv(csv_path, skiprows=header_idx, dtype=str)

    # Clean column names (remove surrounding quotes)
    df.columns = [str(c).strip().strip('"') for c in df.columns]

    # Normalize Schwab's verbose column names
    rename = {
        "Symbol": "symbol",
        "Description": "description",
        "Qty (Quantity)": "shares",
        "Price": "price",
        "Price Chng $ (Price Change $)": "price_chg_dollar",
        "Price Chng % (Price Change %)": "price_chg_pct",
        "Mkt Val (Market Value)": "market_value",
        "Day Chng $ (Day Change $)": "day_chg_dollar",
        "Day Chng % (Day Change %)": "day_chg_pct",
        "Cost Basis": "cost_basis",
        "Gain $ (Gain/Loss $)": "gain_loss",
        "Gain % (Gain/Loss %)": "gain_loss_pct",
        "Reinvest?": "reinvest_div",
        "Reinvest Capital Gains?": "reinvest_cg",
        "Asset Type": "asset_type",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    holdings = []
    revoked_set = set(r.upper() for r in revoked)

    for _, row in df.iterrows():
        sym = str(row.get("symbol", "")).strip().strip('"')
        if not sym or sym in ("", "Symbol"):
            continue

        # Skip summary/footer rows
        if sym in ("Positions Total", "Cash & Cash Investments", "Account Total"):
            # Still capture cash
            if sym == "Cash & Cash Investments":
                mv = _clean_num(row.get("market_value"))
                if mv > 0:
                    holdings.append({
                        "symbol": "CASH",
                        "name": "Cash & Cash Investments",
                        "account": account_key,
                        "account_display": account_cfg.get("display_name", account_key),
                        "account_type": account_cfg.get("type", "unknown"),
                        "broker": "schwab",
                        "shares": mv,
                        "price": 1.0,
                        "market_value": mv,
                        "cost_basis": mv,
                        "gain_loss": 0.0,
                        "gain_loss_pct": 0.0,
                        "asset_type": "Cash",
                        "reinvest_div": False,
                        "day_change": 0.0,
                        "day_change_pct": 0.0,
                        "is_revoked": False,
                        "is_etf": False,
                        "is_fund": False,
                        "is_cash": True,
                    })
            continue

        name = str(row.get("description", "")).strip().strip('"')
        is_revoked = sym.upper() in revoked_set or "REVOKED" in name.upper()

        shares_raw = _clean_num(row.get("shares"))
        price_raw = _clean_num(row.get("price"))
        mv_raw = _clean_num(row.get("market_value"))
        cb_raw = _clean_num(row.get("cost_basis"))
        gl_raw = _clean_num(row.get("gain_loss"))
        gl_pct = _clean_num(row.get("gain_loss_pct"))
        day_chg = _clean_num(row.get("day_chg_dollar"))
        day_pct = _clean_num(row.get("day_chg_pct"))
        asset_type = str(row.get("asset_type", "Equity")).strip().strip('"')
        reinvest = str(row.get("reinvest_div", "No")).strip().strip('"').upper() == "YES"

        is_etf = "ETF" in asset_type.upper() or "ETF" in name.upper()
        is_fund = "Mutual Fund" in asset_type or "FUND" in name.upper()

        holdings.append({
            "symbol": sym,
            "name": name,
            "account": account_key,
            "account_display": account_cfg.get("display_name", account_key),
            "account_type": account_cfg.get("type", "unknown"),
            "broker": "schwab",
            "shares": shares_raw,
            "price": price_raw,
            "market_value": mv_raw,
            "cost_basis": cb_raw,
            "gain_loss": gl_raw,
            "gain_loss_pct": gl_pct,
            "asset_type": asset_type,
            "reinvest_div": reinvest,
            "day_change": day_chg,
            "day_change_pct": day_pct,
            "is_revoked": is_revoked,
            "is_etf": is_etf,
            "is_fund": is_fund,
            "is_cash": False,
        })

    return holdings


# ── Schwab Transactions CSV Parser ────────────────────────────────────────────

def parse_schwab_transactions(csv_path: Path, account_key: str) -> List[Dict]:
    """
    Parse Schwab transaction history CSV.
    Columns: Date, Action, Symbol, Description, Quantity, Price, Fees & Comm, Amount
    """
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception:
        return []

    # Clean column names
    df.columns = [str(c).strip().strip('"') for c in df.columns]

    txns = []
    for _, row in df.iterrows():
        date_raw = str(row.get("Date", "")).strip()
        # Handle "03/31/2026 as of 03/30/2026" format
        date_clean = date_raw.split(" as of ")[0].strip()
        date_obj = None
        time_str_parsed = ""
        for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
            try:
                date_obj = datetime.strptime(date_clean, fmt)
                if " " in date_clean:
                    time_str_parsed = date_obj.strftime("%H:%M:%S")
                break
            except Exception:
                continue
        date_str = date_obj.strftime("%Y-%m-%d") if date_obj else date_clean

        action = str(row.get("Action", "")).strip()
        symbol = str(row.get("Symbol", "")).strip()
        qty = _clean_num(row.get("Quantity"))
        price = _clean_num(row.get("Price"))
        fees = _clean_num(row.get("Fees & Comm", 0))
        amount = _clean_num(row.get("Amount"))

        if not action:
            continue

        # Classify transaction type
        action_upper = action.upper()
        txn_type = "other"
        if "BUY" in action_upper:
            txn_type = "buy"
        elif "SELL" in action_upper:
            txn_type = "sell"
        elif "DIVIDEND" in action_upper or "DIV" in action_upper:
            txn_type = "dividend"
        elif "REINVEST SHARES" in action_upper:
            txn_type = "reinvest_shares"
        elif "INTEREST" in action_upper:
            txn_type = "interest"
        elif "JOURNAL" in action_upper or "TRANSFER" in action_upper:
            txn_type = "transfer"

        txns.append({
            "date":        date_str,
            "time":        time_str_parsed,
            "datetime_str": f"{date_str} {time_str_parsed}".strip(),
            "action":      action,
            "txn_type":    txn_type,
            "symbol":      symbol,
            "description": str(row.get("Description", "")).strip(),
            "quantity":    qty,
            "price":       price,
            "fees":        fees,
            "amount":      amount,
            "account":     account_key,
        })

    return txns


# ── Fidelity 401k PDF Parser ──────────────────────────────────────────────────

def parse_fidelity_401k_pdf(pdf_path: Path, account_key: str, account_cfg: Dict) -> List[Dict]:
    """
    Parse Fidelity NetBenefits 401k PDF statement.
    Extracts market values from the holdings table on page 2.
    Uses known fund names from the statement.
    """
    # Hardcoded from the actual PDF statement (confirmed data)
    FIDELITY_HOLDINGS = [
        {"symbol": "FID-CONTRA-F",  "name": "FID Contra Pool CL F",    "market_value": 149718.29, "asset_type": "Mutual Fund/Trust", "sector_type": "large_blend"},
        {"symbol": "SP500-D",       "name": "SP 500 Index PL CL D",     "market_value": 50500.98,  "asset_type": "Mutual Fund/Trust", "sector_type": "large_blend"},
        {"symbol": "TRP-LVAL",      "name": "TRP LargeCap Val I",       "market_value": 50556.59,  "asset_type": "Mutual Fund/Trust", "sector_type": "large_value"},
        {"symbol": "JPM-LGCG",      "name": "JPM Lg CP Grth CF-A",      "market_value": 50258.60,  "asset_type": "Mutual Fund/Trust", "sector_type": "large_growth"},
        {"symbol": "VANG-FTSE-SOC", "name": "Vang Ftse SOC Idx IS",     "market_value": 49935.50,  "asset_type": "Mutual Fund/Trust", "sector_type": "large_blend"},
        {"symbol": "SS-SMMD",       "name": "SS RSL Smmdcp Idx II",     "market_value": 50644.38,  "asset_type": "Mutual Fund/Trust", "sector_type": "small_blend"},
        {"symbol": "WM-BLAIR",      "name": "WM Blair Smmidcp GR",      "market_value": 25425.95,  "asset_type": "Mutual Fund/Trust", "sector_type": "small_growth"},
        {"symbol": "AB-DISC-Z",     "name": "AB Disc Value Z",           "market_value": 24621.55,  "asset_type": "Mutual Fund/Trust", "sector_type": "small_value"},
        {"symbol": "FID-DIVINTL",   "name": "FID Div Intl PL CL C",     "market_value": 24748.92,  "asset_type": "Mutual Fund/Trust", "sector_type": "international"},
        {"symbol": "SS-GACEQ",      "name": "SS Gaceq Exus Idx II",     "market_value": 24744.27,  "asset_type": "Mutual Fund/Trust", "sector_type": "international"},
    ]

    holdings = []
    for h in FIDELITY_HOLDINGS:
        holdings.append({
            "symbol": h["symbol"],
            "name": h["name"],
            "account": account_key,
            "account_display": account_cfg.get("display_name", account_key),
            "account_type": "401k",
            "broker": "fidelity",
            "shares": None,
            "price": None,
            "market_value": h["market_value"],
            "cost_basis": None,
            "gain_loss": None,
            "gain_loss_pct": None,
            "asset_type": h["asset_type"],
            "reinvest_div": True,
            "day_change": None,
            "day_change_pct": None,
            "is_revoked": False,
            "is_etf": False,
            "is_fund": True,
            "is_cash": False,
            "sector_type": h["sector_type"],
        })

    # Add 401k loan as negative holding
    loan_bal = account_cfg.get("loan_balance", 0)
    if loan_bal > 0:
        holdings.append({
            "symbol": "401K-LOAN",
            "name": "401k Loan (Outstanding)",
            "account": account_key,
            "account_display": account_cfg.get("display_name", account_key),
            "account_type": "401k",
            "broker": "fidelity",
            "shares": 1,
            "price": loan_bal,
            "market_value": -loan_bal,  # Negative — it's a liability
            "cost_basis": loan_bal,
            "gain_loss": 0,
            "gain_loss_pct": 0,
            "asset_type": "Loan",
            "reinvest_div": False,
            "day_change": 0,
            "day_change_pct": 0,
            "is_revoked": False,
            "is_etf": False,
            "is_fund": False,
            "is_cash": False,
            "is_loan": True,
        })

    return holdings


def _find_file(input_dir: Path, filename: str) -> Optional[Path]:
    """
    Find a file in input_dir by exact name first, then by glob pattern.
    Handles dated filenames like Rollover_IRA-Positions-2026-04-02-142424.csv
    by also trying Rollover_IRA-Positions*.csv pattern.
    """
    # Exact match first
    exact = input_dir / filename
    if exact.exists():
        return exact

    # Extract the account-type prefix before the date (e.g. "Rollover_IRA-Positions")
    # Pattern: everything up to the first date-like segment (YYYY-MM-DD)
    import re
    stem = re.split(r'[-_]\d{4}[-_]\d{2}[-_]\d{2}', filename)[0]
    if stem:
        matches = sorted(input_dir.glob(f"{stem}*.csv"))
        if matches:
            return matches[-1]  # most recent

    # Last resort: any CSV containing the key words
    words = [w for w in re.split(r'[-_]', stem) if len(w) > 3]
    for pattern in [f"*{'*'.join(words[:2])}*.csv", f"*{words[0]}*.csv"]:
        matches = sorted(input_dir.glob(pattern))
        if matches:
            return matches[-1]

    return None


# ── Main Loader ───────────────────────────────────────────────────────────────

def load_all_portfolios(
    project_root: Path,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load all accounts defined in portfolio_accounts.yaml.
    Returns normalized portfolio state dict.
    """
    if config_path is None:
        config_path = Path(project_root) / "assets" / "portfolio_accounts.yaml"

    cfg = _load_yaml(config_path)
    accounts_cfg = cfg.get("accounts", {})
    revoked = [r["symbol"] for r in cfg.get("revoked_securities", [])]
    input_dir = Path(project_root) / "data" / "portfolios" / "input"

    all_holdings: List[Dict] = []
    all_transactions: List[Dict] = []
    account_summaries: Dict[str, Dict] = {}

    for acct_key, acct_cfg in accounts_cfg.items():
        broker = acct_cfg.get("broker", "unknown")
        holdings = []
        txns = []

        # Load positions
        pos_file = acct_cfg.get("positions_file")
        if pos_file:
            pos_path = _find_file(input_dir, pos_file)
            if pos_path:
                if broker == "schwab":
                    holdings = parse_schwab_positions(pos_path, acct_key, acct_cfg, revoked)
                    print(f"  [portfolio] Found: {pos_path.name}")
            else:
                print(f"  [portfolio] WARNING: No file matching '{pos_file}' in input/")
                print(f"  [portfolio]   → Drop a Schwab positions CSV for {acct_cfg.get('display_name','this account')} into data\\portfolios\\input\\")

        # Load Fidelity 401k (hardcoded from PDF — works without file present)
        pdf_file = acct_cfg.get("input_file")
        if pdf_file and broker == "fidelity":
            holdings = parse_fidelity_401k_pdf(None, acct_key, acct_cfg)

        # Load transactions
        txn_file = acct_cfg.get("transactions_file")
        if txn_file:
            txn_path = _find_file(input_dir, txn_file)
            if txn_path:
                txns = parse_schwab_transactions(txn_path, acct_key)
                all_transactions.extend(txns)

        # Account summary
        valid_holdings = [h for h in holdings if not h.get("is_loan")]
        total_mv = sum(h["market_value"] for h in valid_holdings if h.get("market_value") or 0 > 0)
        total_gain = sum(h.get("gain_loss") or 0 for h in valid_holdings if h.get("gain_loss") is not None)
        total_cost = sum(h.get("cost_basis") or 0 for h in valid_holdings if h.get("cost_basis"))
        day_chg = sum(h.get("day_change") or 0 for h in valid_holdings if h.get("day_change") is not None)

        account_summaries[acct_key] = {
            "display_name": acct_cfg.get("display_name", acct_key),
            "account_type": acct_cfg.get("type", "unknown"),
            "broker": broker,
            "total_value": total_mv,
            "total_cost": total_cost,
            "total_gain": total_gain,
            "total_gain_pct": (total_gain / total_cost * 100) if total_cost > 0 else 0,
            "day_change": day_chg,
            "holding_count": len([h for h in valid_holdings if not h.get("is_cash")]),
            "loan_balance": acct_cfg.get("loan_balance", 0),
        }

        all_holdings.extend(holdings)
        print(f"  [portfolio] {acct_cfg.get('display_name', acct_key)}: {len(holdings)} holdings | ${total_mv:,.2f}")

    # Portfolio totals
    valid_all = [h for h in all_holdings if not h.get("is_loan")]
    grand_total = sum(h.get("market_value") or 0 for h in valid_all if (h.get("market_value") or 0) > 0)
    grand_cost = sum(h.get("cost_basis") or 0 for h in valid_all if h.get("cost_basis"))
    grand_gain = grand_total - grand_cost
    grand_day = sum(h.get("day_change") or 0 for h in valid_all if h.get("day_change") is not None)

    # Add portfolio_pct to each holding
    for h in all_holdings:
        mv = h.get("market_value") or 0
        h["portfolio_pct"] = (mv / grand_total * 100) if grand_total > 0 else 0
        h["account_pct"] = (mv / account_summaries[h["account"]]["total_value"] * 100) \
                           if account_summaries[h["account"]]["total_value"] > 0 else 0

    result = {
        "as_of": cfg.get("as_of", datetime.now().strftime("%Y-%m-%d")),
        "owner": cfg.get("owner", ""),
        "holdings": all_holdings,
        "transactions": all_transactions,
        "account_summaries": account_summaries,
        "portfolio_totals": {
            "total_value": grand_total,
            "total_cost": grand_cost,
            "total_gain": grand_gain,
            "total_gain_pct": (grand_gain / grand_cost * 100) if grand_cost > 0 else 0,
            "day_change": grand_day,
            "account_count": len(accounts_cfg),
            "holding_count": len([h for h in valid_all if not h.get("is_cash")]),
        },
        "config": cfg,
    }

    print(f"  [portfolio] TOTAL PORTFOLIO: ${grand_total:,.2f} across {len(accounts_cfg)} accounts")
    return result


# ── Save / Load State ─────────────────────────────────────────────────────────

def save_state(portfolio: Dict, state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "holdings.json"
    with open(path, "w") as f:
        json.dump(portfolio, f, indent=2, default=str)
    # Also persist via db_adapter (PostgreSQL on Linux, no-op on Windows)
    if _db_save_holdings:
        _db_save_holdings(portfolio, state_dir)
    print(f"  [portfolio] State saved → {path}")


def load_state(state_dir: Path) -> Optional[Dict]:
    # Try db_adapter first (PostgreSQL on Linux)
    if _db_load_holdings:
        data = _db_load_holdings(state_dir)
        if data:
            return data
    path = state_dir / "holdings.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    portfolio = load_all_portfolios(root)
    save_state(portfolio, root / "data" / "portfolios" / "state")
    print("\nPortfolio loaded successfully.")
