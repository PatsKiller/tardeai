"""portfolio_performance.py — Trade AI v12 Portfolio Intelligence
Snapshot-based period performance tracking.
Saves portfolio snapshot on every run. After snapshots accumulate,
computes day/week/month/quarter/year performance by portfolio, account, sector.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Load .env before db_adapter import so USE_DB evaluates correctly
# (systemd does NOT inherit shell environment)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    from db_adapter import save_snapshot as _db_save_snapshot, load_snapshots as _db_load_snapshots
except ImportError:
    _db_save_snapshot = None
    _db_load_snapshots = None
from typing import Any, Dict, List, Optional, Tuple


SNAPSHOT_DIR_NAME = "snapshots"


# ── Snapshot Management ───────────────────────────────────────────────────────

def save_snapshot(portfolio: Dict, analysis: Dict, state_dir: Path) -> None:
    """Save today's portfolio snapshot for future period comparisons."""
    snap_dir = Path(state_dir) / SNAPSHOT_DIR_NAME
    snap_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    snap_path = snap_dir / f"{date_str}.json"

    totals = portfolio.get("portfolio_totals", {})
    account_summaries = portfolio.get("account_summaries", {})
    sector_pct = analysis.get("sector_pct", {})
    holdings = portfolio.get("holdings", [])

    # Compute LIVE account totals from actual holdings market_value
    # (account_summaries.total_value may be stale from last import)
    live_account_totals: Dict = {}
    live_account_day_change: Dict = {}
    for h in holdings:
        acct = h.get("account", "unknown")
        live_account_totals[acct] = live_account_totals.get(acct, 0) + (h.get("market_value") or 0)
        live_account_day_change[acct] = live_account_day_change.get(acct, 0) + (h.get("day_change") or 0)
    live_total = sum(live_account_totals.values())

    # Snapshot is lightweight — just the key metrics
    snapshot = {
        "date": date_str,
        "total_value": live_total if live_total > 0 else totals.get("total_value", 0),
        "total_gain": totals.get("total_gain", 0),
        "day_change": sum(live_account_day_change.values()) if live_account_day_change else totals.get("day_change", 0),
        "accounts": {
            k: {
                "value": live_account_totals.get(k, v.get("total_value", 0)),
                "gain": v.get("total_gain", 0),
                "day_change": live_account_day_change.get(k, v.get("day_change", 0)),
            }
            for k, v in account_summaries.items()
        },
        "sector_pct": sector_pct,
        "holdings": {
            h.get("symbol", "") + ":" + h.get("account", ""): {
                "symbol": h.get("symbol"),
                "account": h.get("account"),
                "account_display": h.get("account_display"),
                "market_value": h.get("market_value"),
                "price": h.get("price"),
                "shares": h.get("shares"),
                "day_change": h.get("day_change"),
                "day_change_pct": h.get("day_change_pct"),
                "portfolio_pct": h.get("portfolio_pct"),
            }
            for h in holdings
            if (h.get("market_value") or 0) > 100 and not h.get("is_loan")
        },
    }

    # Guard: total drift + per-holding reconciliation jumps
    _prev_snap = None
    _prev_files = sorted(snap_dir.glob("*.json"), key=lambda f: f.name, reverse=True)
    for _pf in _prev_files[:5]:
        if _pf.name == snap_path.name:
            continue
        try:
            _prev_snap = json.load(open(_pf))
            break
        except Exception:
            continue
    try:
        from portfolio_snapshot_sanity import snapshot_total_write_ok
        _snap_ok, _reason = snapshot_total_write_ok(snapshot, _prev_snap)
        if not _snap_ok:
            print(f"  [snapshot] ⛔ REJECTED: {_reason}")
    except ImportError:
        _snap_ok = True
        _total_val = snapshot.get("total_value", 0) or 0
        if _prev_snap:
            _pv = float(_prev_snap.get("total_value", 0))
            if _pv > 0 and _total_val > 0:
                _drift = abs(_total_val - _pv) / _pv * 100
                if _drift > 25:
                    print(f"  [snapshot] ⛔ REJECTED: ${_total_val:,.0f} vs prev ${_pv:,.0f} ({_drift:.1f}% drift > 25%)")
                    _snap_ok = False

    if _snap_ok:
        with open(snap_path, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)
        # Also persist via db_adapter (PostgreSQL on Linux)
        if _db_save_snapshot:
            _db_save_snapshot(snapshot, snap_dir.parent)
    else:
        print(f"  [snapshot] Snapshot NOT written — sanity check failed")


def load_snapshot(state_dir: Path, date_str: str) -> Optional[Dict]:
    """Load a specific date's snapshot."""
    snap_path = Path(state_dir) / SNAPSHOT_DIR_NAME / f"{date_str}.json"
    if snap_path.exists():
        with open(snap_path) as f:
            return json.load(f)
    return None


def find_nearest_snapshot(state_dir: Path, target_date: datetime) -> Optional[Tuple[str, Dict]]:
    """Find the snapshot nearest to target_date (within 5 days)."""
    snap_dir = Path(state_dir) / SNAPSHOT_DIR_NAME
    if not snap_dir.exists():
        return None
    for delta in range(0, 6):
        for sign in [1, -1]:
            check_date = target_date + timedelta(days=delta * sign)
            date_str = check_date.strftime("%Y-%m-%d")
            snap = load_snapshot(state_dir, date_str)
            if snap:
                return date_str, snap
    return None


def list_snapshots(state_dir: Path) -> List[str]:
    """List all available snapshot dates, newest first."""
    snap_dir = Path(state_dir) / SNAPSHOT_DIR_NAME
    if not snap_dir.exists():
        return []
    return sorted(
        [f.stem for f in snap_dir.glob("*.json")],
        reverse=True
    )


# ── Period Return Calculation ─────────────────────────────────────────────────

def _pct_change(current: float, prior: float) -> Optional[float]:
    if prior and prior != 0:
        return round((current - prior) / abs(prior) * 100, 2)
    return None


def _dollar_change(current: float, prior: float) -> float:
    return round(current - prior, 2)


def compute_period_returns(
    current_portfolio: Dict,
    current_analysis: Dict,
    state_dir: Path,
) -> Dict[str, Any]:
    """
    Compute portfolio performance for multiple periods by comparing snapshots.
    Returns period performance for portfolio, accounts, and sectors.
    """
    now = datetime.now()
    current_total = current_portfolio.get("portfolio_totals", {}).get("total_value", 0)
    current_accounts = current_portfolio.get("account_summaries", {})
    current_sectors = current_analysis.get("sector_pct", {})

    # Define periods to compute
    periods = {
        "1D":  now - timedelta(days=1),
        "1W":  now - timedelta(weeks=1),
        "1M":  now - timedelta(days=30),
        "3M":  now - timedelta(days=91),
        "6M":  now - timedelta(days=182),
        "YTD": datetime(now.year, 1, 1),
        "1Y":  now - timedelta(days=365),
    }

    portfolio_returns = {}
    account_returns = defaultdict(dict)
    snapshots_available = []

    for period_name, target_date in periods.items():
        result = find_nearest_snapshot(state_dir, target_date)
        if result:
            snap_date, snap = result
            snapshots_available.append(snap_date)
            prior_total = snap.get("total_value", 0)
            if prior_total > 0:
                portfolio_returns[period_name] = {
                    "pct": _pct_change(current_total, prior_total),
                    "dollar": _dollar_change(current_total, prior_total),
                    "prior_date": snap_date,
                    "prior_value": prior_total,
                }

            # Account-level returns
            prior_accounts = snap.get("accounts", {})
            for acct_key, acct_data in current_accounts.items():
                prior_acct = prior_accounts.get(acct_key, {})
                prior_val = prior_acct.get("value", 0)
                curr_val = acct_data.get("total_value", 0)
                if prior_val > 0 and curr_val > 0:
                    account_returns[acct_key][period_name] = {
                        "pct": _pct_change(curr_val, prior_val),
                        "dollar": _dollar_change(curr_val, prior_val),
                    }
        else:
            portfolio_returns[period_name] = {
                "pct": None, "dollar": None,
                "note": f"No snapshot near {target_date.strftime('%Y-%m-%d')} — will populate over time"
            }

    # Holdings-level period performance (compare to oldest snapshot for key positions)
    holdings_performance = compute_holdings_period_performance(
        current_portfolio.get("holdings", []), state_dir
    )

    # Sector performance (compare current sector % to prior)
    sector_performance = {}
    latest_snap = find_nearest_snapshot(state_dir, now - timedelta(days=30))
    if latest_snap:
        _, prior_snap = latest_snap
        prior_sectors = prior_snap.get("sector_pct", {})
        for sector, curr_pct in current_sectors.items():
            prior_pct = prior_sectors.get(sector, curr_pct)
            if prior_pct:
                sector_performance[sector] = {
                    "current_pct": curr_pct,
                    "prior_pct": prior_pct,
                    "change_pp": round(curr_pct - prior_pct, 2),
                }

    # All-time performance (from cost basis — always available)
    totals = current_portfolio.get("portfolio_totals", {})
    all_time = {
        "dollar": totals.get("total_gain", 0),
        "pct": totals.get("total_gain_pct", 0),
        "note": "Since inception (vs cost basis)",
    }

    # Today's P&L (from day_change in holdings)
    day_pnl = totals.get("day_change", 0)

    snapshots_count = len(list_snapshots(state_dir))

    return {
        "portfolio_returns": portfolio_returns,
        "account_returns": dict(account_returns),
        "holdings_performance": holdings_performance,
        "sector_performance": sector_performance,
        "all_time": all_time,
        "day_pnl": day_pnl,
        "snapshots_available": snapshots_count,
        "note": (
            f"{snapshots_count} daily snapshots accumulated. "
            "Period returns become available as snapshots accumulate over time."
            if snapshots_count < 7
            else f"{snapshots_count} snapshots — period returns available."
        ),
    }


def compute_holdings_period_performance(
    holdings: List[Dict],
    state_dir: Path,
    lookback_days: int = 30,
) -> List[Dict]:
    """Compare current holding values to prior snapshot for individual positions."""
    now = datetime.now()
    result = find_nearest_snapshot(state_dir, now - timedelta(days=lookback_days))
    if not result:
        return []

    snap_date, prior_snap = result
    prior_holdings = prior_snap.get("holdings", {})
    performance = []

    for h in holdings:
        sym = h.get("symbol", "")
        acct = h.get("account", "")
        key = f"{sym}:{acct}"
        curr_mv = h.get("market_value") or 0
        if curr_mv <= 0 or h.get("is_loan") or h.get("is_cash"):
            continue

        prior = prior_holdings.get(key, {})
        prior_mv = prior.get("market_value") or 0

        if prior_mv > 0:
            chg_pct = _pct_change(curr_mv, prior_mv)
            chg_dollar = _dollar_change(curr_mv, prior_mv)
            performance.append({
                "symbol": sym,
                "account_display": h.get("account_display", ""),
                "current_value": curr_mv,
                "prior_value": prior_mv,
                "change_dollar": chg_dollar,
                "change_pct": chg_pct,
                "period": f"{lookback_days}D",
                "prior_date": snap_date,
            })

    performance.sort(key=lambda x: -(x.get("change_dollar") or 0))
    return performance


# ── Main Entry Point ──────────────────────────────────────────────────────────

def track_performance(
    portfolio: Dict,
    analysis: Dict,
    state_dir: Path,
) -> Dict[str, Any]:
    """Save snapshot and compute period returns."""
    print("  [perf] Saving portfolio snapshot...")
    save_snapshot(portfolio, analysis, state_dir)

    print("  [perf] Computing period returns...")
    perf = compute_period_returns(portfolio, analysis, state_dir)

    snap_count = perf.get("snapshots_available", 0)
    available = [p for p, v in perf.get("portfolio_returns", {}).items()
                 if v.get("pct") is not None]
    print(f"  [perf] ✅ {snap_count} snapshots | periods available: {', '.join(available) if available else 'accumulating...'}")

    return perf
