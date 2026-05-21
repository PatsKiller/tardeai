#!/usr/bin/env python3
"""backtest_analyzer.py — LLM-powered trade analysis + strategy pattern backtesting.

Three capabilities:
1. Entry/exit quality grading with LLM analysis (was entry early/late?)
2. Finviz chart context for visual pattern recognition
3. Strategy pattern backtesting against incubator symbols

No live trading. Read-only.
"""
import json, logging, os, sys, time, uuid, warnings
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [analyzer] %(message)s")
log = logging.getLogger(__name__)

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
OHLC_CACHE_PATH = STATE_DIR / "price_ohlc_cache.json"


# ── Finviz Chart ────────────────────────────────────────────────────────────

def get_finviz_chart_url(symbol: str, timeframe: str = "d") -> str:
    """Get Finviz chart URL. timeframe: d=daily, w=weekly, m=monthly."""
    return f"https://charts2.finviz.com/chart.ashx?t={symbol}&ty=c&ta=1&p={timeframe}&s=l"


def get_finviz_chart_urls(symbol: str) -> Dict[str, str]:
    """Get daily + weekly chart URLs for a symbol."""
    return {
        "daily": get_finviz_chart_url(symbol, "d"),
        "weekly": get_finviz_chart_url(symbol, "w"),
    }


# ── Technical Context Builder ───────────────────────────────────────────────

def build_technical_context(symbol: str, entry_date: str, entry_price: float,
                            ohlc: Dict) -> Dict:
    """Build technical context at the time of entry using OHLC data."""
    bars = ohlc.get(symbol, {})
    if not bars:
        return {"available": False, "reason": "no OHLC data"}

    dates = sorted(bars.keys())
    # Find entry position
    entry_idx = None
    for i, d in enumerate(dates):
        if d >= entry_date:
            entry_idx = i
            break
    if entry_idx is None or entry_idx < 20:
        return {"available": False, "reason": "insufficient history before entry"}

    # Pre-entry bars (20 days before)
    pre_bars = [(dates[j], bars[dates[j]]) for j in range(max(0, entry_idx - 20), entry_idx)]
    closes = [b["c"] for _, b in pre_bars]
    highs = [b["h"] for _, b in pre_bars]
    lows = [b["l"] for _, b in pre_bars]

    if len(closes) < 14:
        return {"available": False, "reason": "insufficient bars for indicators"}

    # RSI-14
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = round(100 - (100 / (1 + rs)), 1)

    # SMA 20 distance
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    sma20_dist = round((entry_price - sma20) / sma20 * 100, 2)

    # ATR-14
    atr_vals = []
    for i in range(1, min(15, len(pre_bars))):
        h = pre_bars[i][1]["h"]
        l = pre_bars[i][1]["l"]
        pc = pre_bars[i-1][1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        atr_vals.append(tr)
    atr = round(sum(atr_vals) / len(atr_vals), 4) if atr_vals else 0
    atr_pct = round(atr / entry_price * 100, 2) if entry_price > 0 else 0

    # Recent high/low (20 days)
    high_20d = max(highs) if highs else entry_price
    low_20d = min(lows) if lows else entry_price
    range_position = round((entry_price - low_20d) / (high_20d - low_20d) * 100, 1) if high_20d != low_20d else 50

    # Trend direction (SMA slope)
    if len(closes) >= 10:
        sma_recent = sum(closes[-5:]) / 5
        sma_older = sum(closes[-10:-5]) / 5
        trend = "uptrend" if sma_recent > sma_older * 1.01 else "downtrend" if sma_recent < sma_older * 0.99 else "sideways"
    else:
        trend = "unknown"

    # Volume context
    volumes = [b.get("v", 0) for _, b in pre_bars if b.get("v")]
    avg_volume = round(sum(volumes) / len(volumes)) if volumes else 0

    return {
        "available": True,
        "rsi_at_entry": rsi,
        "sma20_dist_pct": sma20_dist,
        "atr": atr,
        "atr_pct": atr_pct,
        "range_position_pct": range_position,
        "trend": trend,
        "high_20d": round(high_20d, 2),
        "low_20d": round(low_20d, 2),
        "avg_volume_20d": avg_volume,
        "entry_vs_20d_high_pct": round((entry_price - high_20d) / high_20d * 100, 2),
        "charts": get_finviz_chart_urls(symbol),
    }


# ── LLM Trade Analyzer ─────────────────────────────────────────────────────

def analyze_trade_with_llm(symbol: str, strategy: str, entry_price: float,
                            exit_price: float, stop: float, target: float,
                            entry_date: str, exit_date: str, exit_reason: str,
                            pnl: float, tech_context: Dict) -> Dict:
    """Ask LLM to analyze trade quality — was entry early/late? was thesis right?"""
    if not tech_context.get("available"):
        return {"analyzed": False, "reason": "no technical context"}

    rsi = tech_context.get("rsi_at_entry", "?")
    sma_dist = tech_context.get("sma20_dist_pct", "?")
    trend = tech_context.get("trend", "?")
    range_pos = tech_context.get("range_position_pct", "?")
    atr_pct = tech_context.get("atr_pct", "?")
    chart_url = tech_context.get("charts", {}).get("daily", "")

    prompt = f"""Analyze this trade and grade the entry timing:

TRADE: {symbol} ({strategy})
Entry: ${entry_price:.2f} on {entry_date}
Exit: ${exit_price:.2f} on {exit_date} ({exit_reason})
Stop: ${stop:.2f} | Target: ${target:.2f}
P&L: ${pnl:+.2f} per share

TECHNICAL CONTEXT AT ENTRY:
RSI: {rsi} | SMA20 distance: {sma_dist}% | Trend: {trend}
Range position: {range_pos}% (0=at 20d low, 100=at 20d high)
ATR: {atr_pct}% of price
Daily chart: {chart_url}

Respond in exactly this JSON format:
{{
  "entry_grade": "A/B/C/D/F",
  "entry_timing": "early/optimal/late/chased",
  "entry_reasoning": "one sentence why",
  "optimal_entry_price": 0.00,
  "optimal_entry_note": "where would have been better",
  "exit_grade": "A/B/C/D/F",
  "exit_reasoning": "one sentence on exit quality",
  "thesis_correct": true/false,
  "thesis_note": "was the setup thesis validated by price action",
  "improvement_suggestion": "one actionable improvement for next time"
}}"""

    try:
        from llm_router import get_llm_response
        result = get_llm_response(
            task_type="cio_synthesis",
            prompt=prompt,
            high_impact=False,
            max_tokens=500,
            local_timeout=30,
        )
        raw = result.get("response", "")
        model = result.get("model_used", "?")

        import re
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            parsed = json.loads(match.group())
            parsed["analyzed"] = True
            parsed["model"] = model
            return parsed
        return {"analyzed": False, "reason": "no JSON in LLM response", "model": model, "raw": raw[:200]}
    except Exception as e:
        return {"analyzed": False, "reason": str(e)[:200]}


# ── Strategy Pattern Backtester ─────────────────────────────────────────────

def backtest_strategy_on_incubator(strategy_id: str, max_days: int = 20,
                                    limit: int = 50) -> Dict:
    """Backtest a strategy pattern against incubator symbols using real OHLC.

    Finds incubator symbols classified for this strategy, replays the
    signal date forward with strategy-specific stop/target levels.
    """
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get incubator symbols for this strategy
    cur.execute("""SELECT symbol, baseline_score, latest_score, first_seen_at,
        catalyst, sector, industry, days_active
        FROM incubator_universe
        WHERE strategy_id = %s AND status != 'rolled_off'
        ORDER BY latest_score DESC NULLS LAST
        LIMIT %s""", [strategy_id, limit])
    candidates = [dict(r) for r in cur.fetchall()]

    if not candidates:
        conn.close()
        return {"strategy": strategy_id, "candidates": 0, "results": []}

    # Get strategy-specific stop/target from YAML
    stop_pct = 5.0
    target_pct = 8.0
    try:
        from strategy_rule_adapter import load_strategy_configs
        configs = load_strategy_configs()
        cfg = configs.get(strategy_id, {})
        stop_pct = cfg.get("stop_loss_pct", cfg.get("stop_pct", 5.0))
        target_pct = cfg.get("target_pct", cfg.get("take_profit_pct", 8.0))
    except Exception:
        pass

    # Fetch OHLC for all candidate symbols
    symbols = [c["symbol"] for c in candidates]
    from enterprise_backtester import fetch_ohlc_for_symbols, load_close_cache, replay_trade
    earliest = min(str(c.get("first_seen_at", "2026-01-01"))[:10] for c in candidates)
    ohlc = fetch_ohlc_for_symbols(symbols, earliest, date.today().isoformat())
    close_cache = load_close_cache()

    results = []
    for c in candidates:
        sym = c["symbol"]
        entry_date = str(c.get("first_seen_at", ""))[:10]
        if not entry_date or entry_date < "2020-01-01":
            continue

        # Use latest available price as entry
        bars = ohlc.get(sym, {})
        close_prices = close_cache.get(sym, {})
        all_dates = sorted(set(list(bars.keys()) + list(close_prices.keys())))
        entry_price = None
        for d in all_dates:
            if d >= entry_date:
                if d in bars:
                    entry_price = bars[d]["c"]
                elif d in close_prices:
                    entry_price = float(close_prices[d])
                break
        if not entry_price:
            continue

        stop = round(entry_price * (1 - stop_pct / 100), 2)
        target = round(entry_price * (1 + target_pct / 100), 2)

        result = replay_trade(sym, entry_price, entry_date, stop, target, max_days, ohlc, close_cache)
        result["strategy_id"] = strategy_id
        result["score"] = c.get("latest_score") or c.get("baseline_score")
        result["sector"] = c.get("sector")
        result["catalyst"] = bool(c.get("catalyst"))
        result["days_in_incubator"] = c.get("days_active")
        result["charts"] = get_finviz_chart_urls(sym)
        results.append(result)

    conn.close()

    # Aggregate
    completed = [r for r in results if r.get("status") == "completed"]
    wins = [r for r in completed if r["pnl"] > 0]
    n = len(completed)

    return {
        "strategy": strategy_id,
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "candidates": len(candidates),
        "replayed": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else 0,
        "avg_return_pct": round(sum(r["pnl_pct"] for r in completed) / n, 2) if n else 0,
        "avg_mae_pct": round(sum(r["mae_pct"] for r in completed) / n, 2) if n else 0,
        "avg_mfe_pct": round(sum(r["mfe_pct"] for r in completed) / n, 2) if n else 0,
        "by_exit": {r: sum(1 for x in completed if x["exit_reason"] == r)
                    for r in set(x["exit_reason"] for x in completed)} if completed else {},
        "results": results,
        "top_winners": sorted([r for r in completed if r["pnl"] > 0],
                               key=lambda x: -x["pnl_pct"])[:5],
        "worst_losers": sorted([r for r in completed if r["pnl"] < 0],
                                key=lambda x: x["pnl_pct"])[:5],
    }


# ── Full Analysis Pipeline ──────────────────────────────────────────────────

def run_full_analysis(replay_result: Dict, trade: Dict, ohlc: Dict) -> Dict:
    """Run full analysis pipeline: technical context + LLM grading + charts."""
    symbol = replay_result["symbol"]
    entry_date = replay_result["entry_date"]
    entry_price = replay_result["entry_price"]

    # Build technical context
    tech = build_technical_context(symbol, entry_date, entry_price, ohlc)

    # LLM analysis
    llm = analyze_trade_with_llm(
        symbol=symbol,
        strategy=trade.get("strategy_id", "unknown"),
        entry_price=entry_price,
        exit_price=replay_result["exit_price"],
        stop=replay_result["stop"],
        target=replay_result["target"],
        entry_date=entry_date,
        exit_date=replay_result.get("exit_date", "?"),
        exit_reason=replay_result.get("exit_reason", "?"),
        pnl=replay_result["pnl"],
        tech_context=tech,
    )

    return {
        "symbol": symbol,
        "replay": replay_result,
        "technical_context": tech,
        "llm_analysis": llm,
        "charts": get_finviz_chart_urls(symbol),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="LLM-powered trade analyzer + strategy backtester")
    p.add_argument("--analyze-trades", action="store_true", help="Analyze closed trades with LLM")
    p.add_argument("--backtest-strategy", type=str, help="Backtest strategy on incubator symbols")
    p.add_argument("--all-strategies", action="store_true", help="Backtest all strategies on incubator")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--days", type=int, default=20)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--output-json", type=str)
    args = p.parse_args()

    results = {}

    if args.analyze_trades:
        from enterprise_backtester import get_trades_from_db, fetch_ohlc_for_symbols, load_close_cache, load_ohlc_cache, replay_trade
        paper, real = get_trades_from_db()
        all_trades = paper[:args.limit]

        symbols = list(set(t["symbol"] for t in all_trades))
        ohlc = fetch_ohlc_for_symbols(symbols, "2026-01-01", date.today().isoformat())
        close_cache = load_close_cache()

        analyses = []
        for t in all_trades:
            entry_date = str(t.get("entry_time", ""))[:10]
            entry_price = float(t.get("entry_price") or 0)
            stop = float(t.get("stop_loss") or entry_price * 0.95)
            target = float(t.get("target_1") or entry_price * 1.08)
            if not entry_price or not entry_date:
                continue

            replay = replay_trade(t["symbol"], entry_price, entry_date, stop, target, args.days, ohlc, close_cache)
            analysis = run_full_analysis(replay, t, ohlc)
            analyses.append(analysis)

            if args.verbose:
                llm = analysis["llm_analysis"]
                grade = llm.get("entry_grade", "?") if llm.get("analyzed") else "N/A"
                timing = llm.get("entry_timing", "?") if llm.get("analyzed") else "N/A"
                print(f"  {t['symbol']:8s} entry={grade} timing={timing} P&L={replay.get('pnl',0):+.2f} chart={analysis['charts']['daily']}")

        results["trade_analyses"] = analyses
        log.info(f"Analyzed {len(analyses)} trades with LLM")

    if args.backtest_strategy:
        log.info(f"Backtesting {args.backtest_strategy} on incubator...")
        bt = backtest_strategy_on_incubator(args.backtest_strategy, max_days=args.days, limit=args.limit)
        results["strategy_backtest"] = bt
        if args.verbose:
            print(f"\n{args.backtest_strategy}: {bt['replayed']} trades, "
                  f"WR={bt['win_rate']}%, avg={bt['avg_return_pct']}%")
            for w in bt.get("top_winners", [])[:3]:
                print(f"  WIN  {w['symbol']:8s} +{w['pnl_pct']:.1f}% chart={w.get('charts',{}).get('daily','')}")
            for l in bt.get("worst_losers", [])[:3]:
                print(f"  LOSS {l['symbol']:8s} {l['pnl_pct']:.1f}% chart={l.get('charts',{}).get('daily','')}")

    if args.all_strategies:
        strategies = ['swing_breakout', 'swing_trade', 'recovery_watch', 'earnings_catalyst',
                      'speculative_growth', 'sector_rotation', 'dividend_growth_compounder',
                      'defense_thesis', 'core_growth_compounder']
        all_bt = {}
        for sid in strategies:
            log.info(f"Backtesting {sid}...")
            bt = backtest_strategy_on_incubator(sid, max_days=args.days, limit=args.limit)
            all_bt[sid] = bt
            if args.verbose and bt["replayed"] > 0:
                print(f"  {sid:30s} n={bt['replayed']:3d} WR={bt['win_rate']:5.1f}% avg={bt['avg_return_pct']:+.1f}%")
        results["all_strategy_backtests"] = all_bt

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(results, indent=2, default=str))

    return results


if __name__ == "__main__":
    main()
