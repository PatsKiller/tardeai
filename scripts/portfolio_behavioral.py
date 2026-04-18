"""portfolio_behavioral.py — Trading Behavioral Analytics (numerical only)"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

def analyze_behavior(journal: Dict, state_dir: Path) -> Dict:
    trades = journal.get("closed_trades", [])
    if not trades:
        return {"has_data": False}

    # ── Win rate by day of week ───────────────────────────────────────────────
    by_dow: Dict[int, Dict] = {i: {"wins":0,"losses":0,"pnl":0.0,"count":0} for i in range(7)}
    for t in trades:
        try:
            d = datetime.strptime(t["close_date"][:10], "%Y-%m-%d")
            dow = d.weekday()
            by_dow[dow]["count"] += 1
            by_dow[dow]["pnl"]   += t.get("pnl",0)
            if t.get("pnl",0) > 0: by_dow[dow]["wins"] += 1
            else: by_dow[dow]["losses"] += 1
        except: pass

    dow_stats = []
    for i in range(5):  # Mon-Fri only
        d = by_dow[i]
        if d["count"] > 0:
            dow_stats.append({
                "day":      DAYS[i],
                "count":    d["count"],
                "win_rate": round(d["wins"]/d["count"]*100, 1),
                "avg_pnl":  round(d["pnl"]/d["count"], 2),
                "total_pnl":round(d["pnl"], 2),
            })
    best_day  = max(dow_stats, key=lambda x: x["avg_pnl"]) if dow_stats else None
    worst_day = min(dow_stats, key=lambda x: x["avg_pnl"]) if dow_stats else None

    # ── Win rate by hour of day ───────────────────────────────────────────────
    by_hour: Dict[int, Dict] = defaultdict(lambda: {"wins":0,"losses":0,"pnl":0.0,"count":0})
    for t in trades:
        m = t.get("close_min")
        if m is not None:
            h = m // 60
            by_hour[h]["count"] += 1
            by_hour[h]["pnl"]   += t.get("pnl",0)
            if t.get("pnl",0) > 0: by_hour[h]["wins"] += 1
            else: by_hour[h]["losses"] += 1

    hour_stats = []
    for h in sorted(by_hour.keys()):
        d = by_hour[h]
        if d["count"] >= 2:
            hour_stats.append({
                "hour":     h,
                "label":    f"{h:02d}:00",
                "count":    d["count"],
                "win_rate": round(d["wins"]/d["count"]*100, 1),
                "avg_pnl":  round(d["pnl"]/d["count"], 2),
                "total_pnl":round(d["pnl"], 2),
            })
    best_hour  = max(hour_stats, key=lambda x: x["avg_pnl"]) if hour_stats else None
    worst_hour = min(hour_stats, key=lambda x: x["avg_pnl"]) if hour_stats else None

    # ── Win rate by setup ─────────────────────────────────────────────────────
    by_setup: Dict[str, Dict] = defaultdict(lambda: {"wins":0,"total":0,"pnl":0.0})
    for t in trades:
        s = t.get("setup","") or "Untagged"
        by_setup[s]["total"] += 1
        by_setup[s]["pnl"]   += t.get("pnl",0)
        if t.get("pnl",0) > 0: by_setup[s]["wins"] += 1

    setup_stats = []
    for s, d in by_setup.items():
        if d["total"] >= 2:
            setup_stats.append({
                "setup":    s,
                "count":    d["total"],
                "win_rate": round(d["wins"]/d["total"]*100, 1),
                "avg_pnl":  round(d["pnl"]/d["total"], 2),
                "total_pnl":round(d["pnl"], 2),
            })
    setup_stats.sort(key=lambda x: -x["avg_pnl"])

    # ── Win rate by execution tag ─────────────────────────────────────────────
    by_exec: Dict[str, Dict] = defaultdict(lambda: {"wins":0,"total":0,"pnl":0.0})
    for t in trades:
        e = t.get("execution","") or "Untagged"
        by_exec[e]["total"] += 1
        by_exec[e]["pnl"]   += t.get("pnl",0)
        if t.get("pnl",0) > 0: by_exec[e]["wins"] += 1

    exec_stats = []
    for e, d in by_exec.items():
        if d["total"] >= 2:
            exec_stats.append({
                "execution":e,
                "count":    d["total"],
                "win_rate": round(d["wins"]/d["total"]*100, 1),
                "avg_pnl":  round(d["pnl"]/d["total"], 2),
                "total_pnl":round(d["pnl"], 2),
            })
    exec_stats.sort(key=lambda x: -x["avg_pnl"])

    # ── Post-loss behavior (revenge trading signal) ───────────────────────────
    sorted_trades = sorted(trades, key=lambda x: x.get("close_date",""))
    post_loss_wins = 0; post_loss_count = 0
    post_win_wins  = 0; post_win_count  = 0
    for i in range(1, len(sorted_trades)):
        prev = sorted_trades[i-1]
        curr = sorted_trades[i]
        if prev.get("pnl",0) < 0:
            post_loss_count += 1
            if curr.get("pnl",0) > 0: post_loss_wins += 1
        else:
            post_win_count  += 1
            if curr.get("pnl",0) > 0: post_win_wins  += 1

    revenge_signal = False
    post_loss_wr   = round(post_loss_wins/post_loss_count*100, 1) if post_loss_count else None
    post_win_wr    = round(post_win_wins/post_win_count*100, 1)   if post_win_count  else None
    overall_wr     = journal.get("stats",{}).get("win_rate",50)
    if post_loss_wr and post_loss_wr < overall_wr - 15:
        revenge_signal = True

    # ── Rolling 90-day improvement ────────────────────────────────────────────
    from datetime import timedelta
    today = datetime.now()
    periods = []
    for months_back in [1, 2, 3]:
        cutoff = (today - timedelta(days=months_back*30)).strftime("%Y-%m-%d")
        end    = (today - timedelta(days=(months_back-1)*30)).strftime("%Y-%m-%d")
        period_trades = [t for t in trades if cutoff <= t.get("close_date","")[:10] <= end]
        if period_trades:
            wins = sum(1 for t in period_trades if t.get("pnl",0)>0)
            periods.append({
                "label":    f"{months_back}mo ago",
                "count":    len(period_trades),
                "win_rate": round(wins/len(period_trades)*100, 1),
                "avg_pnl":  round(sum(t.get("pnl",0) for t in period_trades)/len(period_trades), 2),
            })

    improving = False
    if len(periods) >= 2:
        improving = periods[0]["win_rate"] > periods[1]["win_rate"]

    result = {
        "has_data":       True,
        "day_of_week":    dow_stats,
        "best_day":       best_day,
        "worst_day":      worst_day,
        "hour_of_day":    hour_stats,
        "best_hour":      best_hour,
        "worst_hour":     worst_hour,
        "by_setup":       setup_stats,
        "by_execution":   exec_stats,
        "post_loss_wr":   post_loss_wr,
        "post_win_wr":    post_win_wr,
        "revenge_signal": revenge_signal,
        "rolling_periods":periods,
        "improving":      improving,
        "sample_size":    len(trades),
    }
    (state_dir/"behavioral_analytics.json").write_text(json.dumps(result, indent=2, default=str))
    return result
