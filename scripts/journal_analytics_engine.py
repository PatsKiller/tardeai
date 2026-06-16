#!/usr/bin/env python3
"""journal_analytics_engine.py — read-only analytics over the trade journal (2026-06-15).

Computes the TradeZella-style analytics the v3 Journal → Analytics tab was missing, ALL from data
already captured (schwab_round_trips for trade facts + timestamps, journal_trade_reviews for the
review enrichment). No new tables, no migration, pure SELECTs — read-only.

Sections (see run()):
  • time_analysis  — win rate / net P&L / count by day-of-week, hour-of-day, and trading session
  • equity_curve   — cumulative net-P&L series + max drawdown, Sharpe (per-trade), recovery factor
  • r_distribution — realized-R histogram + planned-vs-realized averages (from reviews)
  • setup_breakdown— win rate / P&L by setup_family, plus top mistake_tags and emotion correlation

  python3 scripts/journal_analytics_engine.py [--account schwab_taxable] [--days 180]
"""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _q(sql, params=None):
    from db_adapter import _execute
    return _execute(sql, params, "all") or []


def _session_of(hour: int) -> str:
    """Classify an ET entry hour into a trading session."""
    if hour < 9 or (hour == 9 and False):
        return "premarket"
    if hour < 11:
        return "open (9:30-11)"
    if hour < 14:
        return "midday (11-14)"
    if hour < 16:
        return "close (14-16)"
    return "after-hours"


def _trades(account=None, days=180):
    """Closed real round-trips with timestamps + review enrichment (left-joined). Read-only."""
    where = ["srt.exit_time IS NOT NULL", "srt.net_pnl IS NOT NULL",
             "srt.entry_time > now() - (%s || ' days')::interval"]
    params = [int(days)]
    if account:
        where.append("srt.account = %s"); params.append(account)
    sql = f"""
        SELECT srt.symbol, srt.account, srt.entry_time, srt.exit_time, srt.hold_minutes,
               srt.net_pnl, srt.pnl_pct, srt.strategy_tag, srt.entry_grade, srt.exit_grade,
               jtr.setup_family, jtr.realized_r, jtr.planned_r, jtr.market_regime,
               jtr.mistake_tags, jtr.strength_tags, jtr.emotion_before, jtr.emotion_during,
               jtr.confidence_before, jtr.stress_level, jtr.followed_plan
        FROM schwab_round_trips srt
        LEFT JOIN journal_trade_reviews jtr
          ON jtr.symbol = srt.symbol AND jtr.account = srt.account
         AND jtr.closed_date = srt.exit_time::date
        WHERE {' AND '.join(where)}
        ORDER BY srt.exit_time ASC
    """
    return _q(sql, params)


def _agg(rows):
    """(count, wins, net, win_rate) for a list of trades."""
    n = len(rows)
    wins = sum(1 for r in rows if (r.get("net_pnl") or 0) > 0)
    net = sum(float(r.get("net_pnl") or 0) for r in rows)
    return {"trades": n, "wins": wins, "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "net_pnl": round(net, 2)}


def time_analysis(trades):
    by_dow, by_hour, by_session = defaultdict(list), defaultdict(list), defaultdict(list)
    for t in trades:
        et = t.get("entry_time")
        if not et:
            continue
        by_dow[et.weekday()].append(t)
        by_hour[et.hour].append(t)
        by_session[_session_of(et.hour)].append(t)
    return {
        "by_day_of_week": [{"label": _DOW[d], "dow": d, **_agg(by_dow[d])} for d in range(7) if by_dow[d]],
        "by_hour": [{"label": f"{h:02d}:00", "hour": h, **_agg(by_hour[h])} for h in sorted(by_hour)],
        "by_session": [{"label": s, **_agg(by_session[s])}
                       for s in ("premarket", "open (9:30-11)", "midday (11-14)", "close (14-16)", "after-hours")
                       if by_session[s]],
    }


def equity_curve(trades):
    """Cumulative net-P&L curve + max drawdown, per-trade Sharpe, recovery factor."""
    cum, peak, max_dd, points = 0.0, 0.0, 0.0, []
    pnls = []
    for t in trades:
        p = float(t.get("net_pnl") or 0)
        pnls.append(p)
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        points.append({"date": str(t.get("exit_time"))[:10], "symbol": t.get("symbol"),
                       "pnl": round(p, 2), "cum_pnl": round(cum, 2)})
    net = round(cum, 2)
    # per-trade Sharpe: mean/std of trade P&L (not annualized — small samples)
    sharpe = 0.0
    if len(pnls) > 1:
        mean = sum(pnls) / len(pnls)
        var = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
        sd = var ** 0.5
        sharpe = round(mean / sd, 2) if sd else 0.0
    return {
        "points": points,
        "net_pnl": net,
        "max_drawdown": round(max_dd, 2),
        "recovery_factor": round(net / max_dd, 2) if max_dd > 0 else None,
        "sharpe_per_trade": sharpe,
        "trades": len(pnls),
    }


def r_distribution(trades):
    """Realized-R histogram + planned-vs-realized (only trades that have a review with R)."""
    buckets = {"<-1R": 0, "-1..0R": 0, "0..1R": 0, "1..2R": 0, "2..3R": 0, ">3R": 0}
    realized, planned = [], []
    for t in trades:
        rr = t.get("realized_r")
        if rr is None:
            continue
        rr = float(rr)
        realized.append(rr)
        if t.get("planned_r") is not None:
            planned.append(float(t["planned_r"]))
        if rr < -1: buckets["<-1R"] += 1
        elif rr < 0: buckets["-1..0R"] += 1
        elif rr < 1: buckets["0..1R"] += 1
        elif rr < 2: buckets["1..2R"] += 1
        elif rr < 3: buckets["2..3R"] += 1
        else: buckets[">3R"] += 1
    return {
        "histogram": [{"bucket": k, "count": v} for k, v in buckets.items()],
        "avg_realized_r": round(sum(realized) / len(realized), 2) if realized else None,
        "avg_planned_r": round(sum(planned) / len(planned), 2) if planned else None,
        "expectancy_r": round(sum(realized) / len(realized), 2) if realized else None,
        "sample": len(realized),
    }


def setup_breakdown(trades):
    """Win rate / P&L by strategy_tag (always populated) + setup_family / mistake / emotion overlays
    from reviews (sparse — only where the trade was manually reviewed)."""
    by_strategy = defaultdict(list)
    by_setup, by_emotion = defaultdict(list), defaultdict(list)
    mistake_counts = defaultdict(lambda: {"count": 0, "net_pnl": 0.0})
    for t in trades:
        by_strategy[t.get("strategy_tag") or "untagged"].append(t)
        if t.get("setup_family"):
            by_setup[t["setup_family"]].append(t)
        if t.get("emotion_during"):
            by_emotion[t["emotion_during"]].append(t)
        tags = t.get("mistake_tags") or []
        if isinstance(tags, str):
            try: tags = json.loads(tags)
            except Exception: tags = [tags]
        for tag in tags or []:
            mistake_counts[tag]["count"] += 1
            mistake_counts[tag]["net_pnl"] += float(t.get("net_pnl") or 0)
    return {
        "by_strategy": sorted([{"strategy": k, **_agg(v)} for k, v in by_strategy.items()],
                              key=lambda x: -x["net_pnl"]),
        "by_setup": sorted([{"setup": k, **_agg(v)} for k, v in by_setup.items()],
                           key=lambda x: -x["net_pnl"]),
        "by_emotion": sorted([{"emotion": k, **_agg(v)} for k, v in by_emotion.items()],
                             key=lambda x: -x["net_pnl"]),
        "top_mistakes": sorted([{"tag": k, "count": v["count"], "net_pnl": round(v["net_pnl"], 2)}
                                for k, v in mistake_counts.items()], key=lambda x: x["net_pnl"])[:8],
    }


def run(account=None, days=180):
    trades = _trades(account, days)
    return {
        "ok": True,
        "filters": {"account": account or "all", "days": days},
        "overall": _agg(trades),
        "time_analysis": time_analysis(trades),
        "equity_curve": equity_curve(trades),
        "r_distribution": r_distribution(trades),
        "setup_breakdown": setup_breakdown(trades),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    print(json.dumps(run(a.account, a.days), indent=2, default=str))


if __name__ == "__main__":
    main()
