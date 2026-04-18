#!/usr/bin/env python3
"""
portfolio_trade_analysis.py — Trade Performance Analysis Module
Trade AI v12 | Stage 4d of Portfolio Intelligence pipeline

Called automatically by portfolio_orchestrator.py when a new
transactions CSV is detected in data/portfolios/input/.

Also embedded in the Trade Journal tab of the dashboard via cache.

CACHE: data/portfolios/state/trade_analysis_cache.json
  Keyed by file mtime — no re-run if CSV unchanged.

STANDALONE TEST:
  python scripts/portfolio_trade_analysis.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Time blocks ────────────────────────────────────────────────────────────────
TIME_BLOCKS = [
    ("09:30-10:30", time(9,30),  time(10,30)),
    ("10:30-11:30", time(10,30), time(11,30)),
    ("11:30-12:30", time(11,30), time(12,30)),
    ("12:30-13:30", time(12,30), time(13,30)),
    ("13:30-14:30", time(13,30), time(14,30)),
    ("14:30-16:00", time(14,30), time(16,0)),
]
DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

COL_ALIASES = {
    "symbol":      ["symbol","ticker","stock","instrument"],
    "entry_date":  ["entry date","entrydate","open date","date","trade date"],
    "entry_time":  ["entry time","entrytime","open time","time"],
    "entry_price": ["entry price","entryprice","open price","buy price","avg entry"],
    "exit_price":  ["exit price","exitprice","close price","sell price","avg exit"],
    "shares":      ["shares","qty","quantity","size"],
    "pnl":         ["p&l","pnl","profit","profit/loss","net p&l","realized p&l","gain/loss"],
    "setup_type":  ["setup type","setuptype","setup","strategy","pattern"],
}

# ── Parsers ────────────────────────────────────────────────────────────────────

def _sf(v):
    try: return float(str(v or "").replace("$","").replace(",","").strip())
    except: return None

def _st(v):
    if not v: return None
    for fmt in ["%H:%M:%S","%H:%M","%I:%M %p"]:
        try: return datetime.strptime(str(v).strip(), fmt).time()
        except: pass
    return None

def _sd(v):
    if not v: return None
    for fmt in ["%Y-%m-%d","%m/%d/%Y","%m/%d/%y","%d/%m/%Y"]:
        try: return datetime.strptime(str(v).strip(), fmt)
        except: pass
    return None

def _map_cols(headers):
    low = {h.lower().strip(): h for h in headers}
    m = {}
    for canon, aliases in COL_ALIASES.items():
        for a in aliases:
            if a in low: m[canon] = low[a]; break
    return m

def _tblock(t):
    if not t: return "Unknown"
    for lbl, s, e in TIME_BLOCKS:
        if s <= t < e: return lbl
    return "Outside Hours"

# ── Load ───────────────────────────────────────────────────────────────────────

def load_trades_csv(filepath: str) -> Tuple[List[Dict], List[str]]:
    """Load trades from CSV. Returns (trades, warnings)."""
    import csv
    path = Path(filepath)
    if not path.exists():
        return [], [f"File not found: {filepath}"]
    trades, warnings, skipped = [], [], 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], ["CSV has no headers"]
        col = _map_cols(list(reader.fieldnames))
        if "pnl" not in col:
            return [], [f"No P&L column found. Headers: {list(reader.fieldnames)}"]
        for row in reader:
            pnl = _sf(row.get(col.get("pnl",""), ""))
            if pnl is None: skipped += 1; continue
            entry_dt = _sd(row.get(col.get("entry_date",""), ""))
            entry_t  = _st(row.get(col.get("entry_time",""), ""))
            trades.append({
                "symbol":     str(row.get(col.get("symbol",""),"") or "?").upper().strip(),
                "entry_date": entry_dt,
                "entry_time": entry_t,
                "entry_price":_sf(row.get(col.get("entry_price",""), "")),
                "exit_price": _sf(row.get(col.get("exit_price",""), "")),
                "shares":     _sf(row.get(col.get("shares",""), "")),
                "pnl":        pnl,
                "setup_type": str(row.get(col.get("setup_type",""),"")).strip() or "Unclassified",
                "day_of_week":DAYS[entry_dt.weekday()] if entry_dt else "Unknown",
                "time_block": _tblock(entry_t),
                "is_winner":  pnl > 0,
                "is_loser":   pnl < 0,
            })
    if skipped: warnings.append(f"Skipped {skipped} rows with missing P&L")
    if not any(t["entry_time"] for t in trades):
        warnings.append("No entry times — time-of-day analysis limited")
    if all(t["setup_type"] == "Unclassified" for t in trades):
        warnings.append("No Setup Type column — add it for setup analysis")
    return trades, warnings

# ── Analysis ───────────────────────────────────────────────────────────────────

def _stats_group(group):
    pnl = [t["pnl"] for t in group]
    wins = [t["pnl"] for t in group if t["is_winner"]]
    loss = [t["pnl"] for t in group if t["is_loser"]]
    n = len(group)
    return {
        "trades":   n,
        "winners":  len(wins),
        "losers":   len(loss),
        "win_rate": len(wins)/n if n else 0,
        "total_pnl":sum(pnl),
        "avg_pnl":  sum(pnl)/n if n else 0,
        "avg_win":  sum(wins)/len(wins) if wins else 0,
        "avg_loss": sum(loss)/len(loss) if loss else 0,
        "best":     max(pnl) if pnl else 0,
        "worst":    min(pnl) if pnl else 0,
    }

def compute_stats(trades):
    if not trades: return {}
    wins  = [t["pnl"] for t in trades if t["is_winner"]]
    loss  = [t["pnl"] for t in trades if t["is_loser"]]
    all_p = [t["pnl"] for t in trades]
    wr = len(wins)/len(trades)
    aw = sum(wins)/len(wins) if wins else 0
    al = sum(loss)/len(loss) if loss else 0
    gw = sum(wins)
    gl = abs(sum(loss))
    return {
        "total_trades": len(trades),
        "winners":      len(wins),
        "losers":       len(loss),
        "win_rate":     wr,
        "avg_win":      aw,
        "avg_loss":     al,
        "expectancy":   wr*aw + (1-wr)*al,
        "profit_factor":gw/gl if gl > 0 else 0,
        "total_pnl":    sum(all_p),
        "avg_pnl":      sum(all_p)/len(trades),
        "largest_win":  max(wins) if wins else 0,
        "largest_loss": min(loss) if loss else 0,
    }

def group_by(trades, key):
    grps = defaultdict(list)
    for t in trades: grps[t[key]].append(t)
    return {k: _stats_group(v) for k, v in sorted(grps.items())}

def detect_patterns(trades, by_setup, by_time, by_day):
    patterns, recs = [], []
    stats = compute_stats(trades)
    if not stats: return patterns, recs

    # Best/worst setup
    valid_setups = {k:v for k,v in by_setup.items()
                    if k != "Unclassified" and v["trades"] >= 2}
    if valid_setups:
        best_s = max(valid_setups, key=lambda k: valid_setups[k]["total_pnl"])
        worst_s = min(valid_setups, key=lambda k: valid_setups[k]["total_pnl"])
        bs, ws = valid_setups[best_s], valid_setups[worst_s]
        patterns.append(f"BEST SETUP: {best_s} — ${bs['total_pnl']:+,.0f} total, {bs['win_rate']*100:.0f}% WR")
        if valid_setups[worst_s]["total_pnl"] < 0:
            patterns.append(f"WORST SETUP: {worst_s} — ${ws['total_pnl']:+,.0f} total, {ws['win_rate']*100:.0f}% WR")
            recs.append(f"STOP trading {worst_s} ({ws['trades']} trades, {ws['win_rate']*100:.0f}% WR, ${ws['total_pnl']:+,.0f}). Eliminate from playbook.")
        recs.append(f"DOUBLE DOWN on {best_s} — {bs['trades']} trades, {bs['win_rate']*100:.0f}% WR, ${bs['total_pnl']:+,.0f}. This is your A+ setup.")

    # Best/worst time
    valid_times = {k:v for k,v in by_time.items()
                   if k not in ("Unknown","Outside Hours") and v["trades"] >= 2}
    if valid_times:
        best_t  = max(valid_times, key=lambda k: valid_times[k]["total_pnl"])
        worst_t = min(valid_times, key=lambda k: valid_times[k]["total_pnl"])
        bt, wt  = valid_times[best_t], valid_times[worst_t]
        patterns.append(f"BEST HOUR: {best_t} — ${bt['total_pnl']:+,.0f}, {bt['win_rate']*100:.0f}% WR")
        if valid_times[worst_t]["total_pnl"] < 0:
            patterns.append(f"WORST HOUR: {worst_t} — ${wt['total_pnl']:+,.0f}, {wt['win_rate']*100:.0f}% WR")
            recs.append(f"STOP TRADING {worst_t} — consistent losses. Log off this window.")

    # Consecutive loss streak
    streak = max_streak = 0
    for t in sorted(trades, key=lambda x: (x.get("entry_date") or datetime.min,
                                            x.get("entry_time") or time.min)):
        if t["is_loser"]: streak += 1; max_streak = max(max_streak, streak)
        else: streak = 0
    if max_streak >= 3:
        patterns.append(f"RISK FLAG: Max consecutive loss streak = {max_streak}. Implement 3-loss daily stop rule.")

    # Profit factor
    pf = stats["profit_factor"]
    if pf >= 1.5:
        patterns.append(f"EDGE CONFIRMED: Profit factor {pf:.2f}x, expectancy ${stats['expectancy']:+,.2f}/trade")
        recs.append(f"Profit factor {pf:.2f}x is solid. Keep above 1.5x as you scale size.")
    elif pf >= 1.0:
        recs.append(f"Profit factor {pf:.2f}x is marginal. Target 1.5x. Let winners run longer.")
    else:
        patterns.append(f"NO EDGE: Profit factor {pf:.2f}x — losing overall")
        recs.append(f"Profit factor < 1.0. Cut size 50% and identify what is broken.")

    return patterns, recs

# ── Main entry point for orchestrator ─────────────────────────────────────────

def run_analysis(portfolio: Dict, state_dir: Path) -> Dict:
    """
    Main entry point — called by portfolio_orchestrator.py as Stage 4d.
    Detects new/changed CSV, runs analysis, caches result.
    Returns analysis dict (or cached result if unchanged).
    """
    input_dir  = state_dir.parent.parent / "input"
    cache_path = state_dir / "trade_analysis_cache.json"

    # Find most recent transactions or trades CSV
    candidates = (
        sorted(input_dir.glob("*Transactions*.csv")) +
        sorted(input_dir.parent.parent.parent.glob("trades*.csv")) +
        sorted(input_dir.parent.parent.parent.glob("trade_log*.csv"))
    )

    if not candidates:
        return {"status": "no_csv", "error": "No trades CSV found in input/"}

    trades_file = str(candidates[-1])
    file_mtime  = os.path.getmtime(trades_file)

    # Return cache if file unchanged
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            if cache.get("src") == trades_file and cache.get("mt") == file_mtime:
                cache["status"] = "cached"
                return cache
        except Exception:
            pass

    # Run fresh analysis
    trades, warnings = load_trades_csv(trades_file)
    if not trades:
        return {"status": "no_trades", "warnings": warnings,
                "src": trades_file, "mt": file_mtime}

    stats    = compute_stats(trades)
    by_setup = group_by(trades, "setup_type")
    by_time  = group_by(trades, "time_block")
    by_day_raw = group_by(trades, "day_of_week")
    by_day   = {d: by_day_raw[d] for d in DAYS if d in by_day_raw}
    patterns, recs = detect_patterns(trades, by_setup, by_time, by_day)

    result = {
        "status":   "ok",
        "src":      trades_file,
        "src_name": Path(trades_file).name,
        "mt":       file_mtime,
        "as_of":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warnings": warnings,
        "trades_count": len(trades),
        "stats":    stats,
        "by_setup": by_setup,
        "by_time":  {k: by_time[k] for k in
                     ["09:30-10:30","10:30-11:30","11:30-12:30",
                      "12:30-13:30","13:30-14:30","14:30-16:00"]
                     if k in by_time},
        "by_day":   by_day,
        "patterns": patterns,
        "recommendations": recs,
    }

    # Save cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2, default=str))
    return result

# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = Path(__file__).parent.parent
    state_dir = root / "data" / "portfolios" / "state"
    result = run_analysis({}, state_dir)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("by_setup","by_time","by_day")}, indent=2, default=str))
    print(f"\nStatus: {result['status']}")
    if result.get("patterns"):
        print("\nPatterns:")
        for p in result["patterns"]: print(f"  {p}")
    if result.get("recommendations"):
        print("\nRecommendations:")
        for i,r in enumerate(result["recommendations"],1): print(f"  [{i}] {r}")
