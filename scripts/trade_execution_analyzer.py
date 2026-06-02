#!/usr/bin/env python3
"""trade_execution_analyzer.py — MFE/MAE + trailing optimization + entry quality.

Broker-agnostic: fetches bars from yfinance (default), polygon, or any
configured data provider. Never hardcodes to a specific broker.

Three analysis modes:
  --mfe          Compute MFE/MAE for all closed trades
  --optimize     Optimize trailing stop tiers per strategy family
  --entry        Score entry quality and correlate with outcomes
  --all          Run all three

Usage:
    .venv/bin/python scripts/trade_execution_analyzer.py --all
    .venv/bin/python scripts/trade_execution_analyzer.py --mfe --symbol ASPN
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [exec-analyzer] %(message)s")
log = logging.getLogger("exec-analyzer")


def _get_conn():
    from db_adapter import _get_conn as gc
    return gc()


# ── Broker-agnostic bar fetcher ──────────────────────────────────────────

def fetch_bars(symbol: str, start_date: str, end_date: str, timeframe: str = "1Day") -> list:
    """Fetch OHLCV bars from available data providers. Broker-agnostic.
    Returns list of dicts: [{timestamp, open, high, low, close, volume}, ...]
    """
    bars = _fetch_yfinance(symbol, start_date, end_date)
    if bars:
        return bars
    bars = _fetch_polygon(symbol, start_date, end_date)
    if bars:
        return bars
    bars = _fetch_alpaca_data_api(symbol, start_date, end_date, timeframe)
    if bars:
        return bars
    log.warning(f"No bar data available for {symbol} ({start_date} to {end_date})")
    return []


def _fetch_yfinance(symbol, start, end):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval="1d")
        if df.empty:
            return []
        return [{"timestamp": str(idx), "open": r["Open"], "high": r["High"],
                 "low": r["Low"], "close": r["Close"], "volume": r.get("Volume", 0)}
                for idx, r in df.iterrows()]
    except Exception as e:
        log.debug(f"yfinance failed for {symbol}: {e}")
        return []


def _fetch_polygon(symbol, start, end):
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        return []
    try:
        import requests
        resp = requests.get(
            f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}",
            params={"apiKey": api_key, "adjusted": "true", "sort": "asc", "limit": 120},
            timeout=15)
        if resp.ok:
            results = resp.json().get("results", [])
            return [{"timestamp": str(datetime.fromtimestamp(r["t"] / 1000)), "open": r["o"],
                     "high": r["h"], "low": r["l"], "close": r["c"], "volume": r.get("v", 0)}
                    for r in results]
    except Exception as e:
        log.debug(f"polygon failed for {symbol}: {e}")
    return []


def _fetch_alpaca_data_api(symbol, start, end, timeframe="1Day"):
    key = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        return []
    try:
        import requests
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            params={"start": start, "end": end, "timeframe": timeframe, "limit": 120},
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=15)
        if resp.ok:
            bars = resp.json().get("bars", [])
            return [{"timestamp": b["t"], "open": b["o"], "high": b["h"],
                     "low": b["l"], "close": b["c"], "volume": b.get("v", 0)}
                    for b in bars]
    except Exception as e:
        log.debug(f"alpaca data API failed for {symbol}: {e}")
    return []


# ── 1. MFE/MAE Analysis ─────────────────────────────────────────────────

def run_mfe_analysis(conn, symbol_filter=None):
    """Compute MFE/MAE for all closed trades missing analysis."""
    cur = conn.cursor()
    where = "AND t.symbol = %s" if symbol_filter else ""
    params = [symbol_filter] if symbol_filter else []
    cur.execute(f"""
        SELECT t.id, t.symbol, t.strategy_id, t.entry_price, t.exit_price,
               t.stop_loss, t.target_1, t.shares, t.entry_time, t.exit_time,
               t.pnl, t.r_multiple, t.exit_reason,
               t.planned_entry, t.score_at_entry, t.rvol_at_entry,
               t.catalyst_verified, t.intel_readiness, t.vix_at_entry
        FROM paper_trades t
        LEFT JOIN trade_mfe_analysis m ON t.id = m.trade_id
        WHERE t.status = 'closed' AND t.exit_price IS NOT NULL
        AND m.trade_id IS NULL {where}
        ORDER BY t.closed_at DESC
    """, params or None)
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not trades:
        log.info("No trades need MFE analysis")
        return {"analyzed": 0}

    log.info(f"Analyzing {len(trades)} trades for MFE/MAE")
    analyzed = 0

    for t in trades:
        entry = float(t["entry_price"] or 0)
        exit_px = float(t["exit_price"] or 0)
        stop = float(t["stop_loss"] or 0)
        target = float(t["target_1"] or 0)
        shares = int(t["shares"] or 0)
        risk_per_share = abs(entry - stop) if entry and stop else 1

        # Fetch bars
        entry_date = str(t["entry_time"])[:10] if t["entry_time"] else None
        exit_date = str(t["exit_time"])[:10] if t["exit_time"] else None
        if not entry_date or not exit_date:
            continue

        bars = fetch_bars(t["symbol"], entry_date, exit_date)
        if not bars:
            log.warning(f"  {t['symbol']}: no bar data, skipping")
            continue

        # Compute MFE/MAE
        mfe_price = entry
        mae_price = entry
        mfe_idx = 0
        mae_idx = 0
        mfe_time = None
        mae_time = None

        for i, bar in enumerate(bars):
            high = float(bar["high"])
            low = float(bar["low"])
            if high > mfe_price:
                mfe_price = high
                mfe_idx = i
                mfe_time = bar["timestamp"]
            if low < mae_price:
                mae_price = low
                mae_idx = i
                mae_time = bar["timestamp"]

        mfe_r = (mfe_price - entry) / risk_per_share if risk_per_share > 0 else 0
        mae_r = (mae_price - entry) / risk_per_share if risk_per_share > 0 else 0
        actual_r = float(t["r_multiple"] or 0)
        capture_ratio = actual_r / mfe_r if mfe_r > 0 else (1.0 if actual_r >= 0 else 0)
        money_left = (mfe_price - exit_px) * shares if mfe_price > exit_px else 0
        stop_nearly_hit = (mae_price - stop) / stop * 100 < 2 if stop > 0 else False
        stop_dist_at_mae = ((mae_price - stop) / stop * 100) if stop > 0 else None

        # Entry quality scoring
        slippage = abs(float(t["planned_entry"] or entry) - entry) / entry * 100 if entry > 0 else 0
        slippage_score = max(0, 25 - slippage * 5)
        setup_score = min(25, (float(t["score_at_entry"] or 0) / 55) * 25)
        context_score = max(0, 25 - abs(float(t["vix_at_entry"] or 17) - 17) * 1.5)
        catalyst_bonus = 12.5 if t.get("catalyst_verified") else 0
        intel_bonus = min(12.5, float(t.get("intel_readiness") or 0) / 100 * 12.5)
        timing_score = catalyst_bonus + intel_bonus
        entry_quality = round(slippage_score + setup_score + context_score + timing_score, 1)

        # Hold time
        hold_min = None
        if t["entry_time"] and t["exit_time"]:
            try:
                et = t["entry_time"] if hasattr(t["entry_time"], "timestamp") else datetime.fromisoformat(str(t["entry_time"]))
                xt = t["exit_time"] if hasattr(t["exit_time"], "timestamp") else datetime.fromisoformat(str(t["exit_time"]))
                hold_min = int((xt - et).total_seconds() / 60)
            except Exception:
                pass

        # Store
        cur.execute("""
            INSERT INTO trade_mfe_analysis
                (trade_id, symbol, strategy_id, mfe_price, mfe_r, mfe_time, mfe_bar_index,
                 mae_price, mae_r, mae_time, mae_bar_index,
                 capture_ratio, money_left, optimal_exit_price, optimal_exit_time,
                 stop_nearly_hit, stop_distance_at_mae, bars_analyzed, holding_period_min,
                 entry_quality_score, slippage_score, timing_score, setup_score, context_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trade_id) DO UPDATE SET
                mfe_price=EXCLUDED.mfe_price, mfe_r=EXCLUDED.mfe_r, mae_price=EXCLUDED.mae_price,
                mae_r=EXCLUDED.mae_r, capture_ratio=EXCLUDED.capture_ratio, money_left=EXCLUDED.money_left,
                entry_quality_score=EXCLUDED.entry_quality_score, created_at=NOW()
        """, [t["id"], t["symbol"], t["strategy_id"],
              mfe_price, round(mfe_r, 3), mfe_time, mfe_idx,
              mae_price, round(mae_r, 3), mae_time, mae_idx,
              round(capture_ratio, 3), round(money_left, 2), mfe_price, mfe_time,
              stop_nearly_hit, round(stop_dist_at_mae, 2) if stop_dist_at_mae else None,
              len(bars), hold_min,
              entry_quality, round(slippage_score, 1), round(timing_score, 1),
              round(setup_score, 1), round(context_score, 1)])

        # Update paper_trades MFE/MAE columns.
        # Phase 194 FIX: these columns are PERCENT excursion from entry (consistent with
        # paper_trade_monitor.py). Previously this wrote mfe_r (R-multiple) into the same column,
        # corrupting units. The R-multiple lives in trade_mfe_analysis.mfe_r; the dollar
        # profit-left-on-table in trade_mfe_analysis.money_left.
        mfe_pct = round((mfe_price - entry) / entry * 100, 3) if entry > 0 else None
        mae_pct = round((mae_price - entry) / entry * 100, 3) if entry > 0 else None
        cur.execute("""UPDATE paper_trades SET max_favorable_excursion=%s, max_adverse_excursion=%s WHERE id=%s""",
                    [mfe_pct, mae_pct, t["id"]])
        conn.commit()

        log.info(f"  {t['symbol']}: MFE {mfe_r:.2f}R MAE {mae_r:.2f}R capture {capture_ratio:.0%} "
                 f"left ${money_left:.0f} entry_q={entry_quality:.0f}")
        analyzed += 1

    return {"analyzed": analyzed}


# ── 2. Trailing Stop Optimizer ───────────────────────────────────────────

def run_trailing_optimization(conn):
    """Simulate different trailing tier thresholds on closed trades."""
    from strategy_trailing_policy import TRAILING_TIERS, get_strategy_family

    cur = conn.cursor()
    cur.execute("""SELECT id, symbol, strategy_id, entry_price, stop_loss, target_1,
                   exit_price, pnl, r_multiple, shares
                   FROM paper_trades WHERE status='closed' AND exit_price IS NOT NULL""")
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not trades:
        log.info("No closed trades for optimization")
        return {"optimized": 0}

    # Group by family
    families = {}
    for t in trades:
        family = get_strategy_family(t["strategy_id"] or "unknown")
        families.setdefault(family, []).append(t)

    # Test different breakeven thresholds
    test_thresholds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    results = []

    for family, family_trades in families.items():
        current_tiers = TRAILING_TIERS.get(family, {}).get("tiers", [])
        current_be = current_tiers[0][0] if current_tiers else 1.0

        log.info(f"\n{family}: {len(family_trades)} trades, current breakeven={current_be}R")
        best_threshold = current_be
        best_avg_r = 0
        detail = {}

        for threshold in test_thresholds:
            total_r = 0
            wins = 0
            for t in family_trades:
                entry = float(t["entry_price"] or 0)
                stop = float(t["stop_loss"] or 0)
                exit_px = float(t["exit_price"] or 0)
                risk = abs(entry - stop) if entry and stop else 1
                r = float(t["r_multiple"] or 0)

                # Simulate: if trade hit threshold R, stop moves to breakeven
                # If it then reverses below entry, exit at entry (0R) instead of actual
                if r >= threshold:
                    # Trade reached the threshold — at minimum breakeven
                    simulated_r = max(0, r)
                else:
                    simulated_r = r  # Didn't reach threshold, original exit

                total_r += simulated_r
                if simulated_r > 0:
                    wins += 1

            avg_r = total_r / len(family_trades) if family_trades else 0
            win_rate = wins / len(family_trades) * 100 if family_trades else 0
            detail[str(threshold)] = {"avg_r": round(avg_r, 3), "win_rate": round(win_rate, 1), "total_r": round(total_r, 2)}
            log.info(f"  BE={threshold}R: avg_r={avg_r:.3f} win_rate={win_rate:.0f}%")

            if avg_r > best_avg_r:
                best_avg_r = avg_r
                best_threshold = threshold

        current_avg_r = detail.get(str(current_be), {}).get("avg_r", 0)
        improvement = ((best_avg_r - current_avg_r) / abs(current_avg_r) * 100) if current_avg_r else 0

        confidence = "low" if len(family_trades) < 5 else "medium" if len(family_trades) < 15 else "high"

        result = {
            "family": family, "sample_size": len(family_trades),
            "current_breakeven": current_be, "optimized_breakeven": best_threshold,
            "current_avg_r": current_avg_r, "optimized_avg_r": round(best_avg_r, 3),
            "improvement_pct": round(improvement, 1), "confidence": confidence,
            "detail": detail,
        }
        results.append(result)

        # Store
        cur.execute("""INSERT INTO trailing_optimization_results
            (strategy_family, current_config, optimized_config, current_avg_r, optimized_avg_r,
             improvement_pct, sample_size, confidence, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [family, json.dumps({"breakeven": current_be}),
             json.dumps({"breakeven": best_threshold}),
             current_avg_r, round(best_avg_r, 3), round(improvement, 1),
             len(family_trades), confidence, json.dumps(detail)])
        conn.commit()

        log.info(f"  RECOMMENDATION: {family} breakeven {current_be}R → {best_threshold}R "
                 f"(+{improvement:.1f}% avg R, confidence={confidence})")

    return {"optimized": len(results), "results": results}


# ── 3. Entry Quality Correlation ─────────────────────────────────────────

def run_entry_quality_correlation(conn):
    """Correlate entry quality scores with trade outcomes."""
    cur = conn.cursor()
    cur.execute("""SELECT m.trade_id, m.symbol, m.strategy_id,
                   m.entry_quality_score, m.mfe_r, m.mae_r, m.capture_ratio,
                   t.r_multiple, t.pnl, t.outcome_verdict
                   FROM trade_mfe_analysis m
                   JOIN paper_trades t ON m.trade_id = t.id
                   WHERE m.entry_quality_score IS NOT NULL""")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        log.info("No entry quality data for correlation (run --mfe first)")
        return {"correlated": 0}

    # Simple correlation: split into good (>50) vs poor (<50) entries
    good = [r for r in rows if float(r.get("entry_quality_score") or 0) >= 50]
    poor = [r for r in rows if float(r.get("entry_quality_score") or 0) < 50]

    good_avg_r = sum(float(r["r_multiple"] or 0) for r in good) / len(good) if good else 0
    poor_avg_r = sum(float(r["r_multiple"] or 0) for r in poor) / len(poor) if poor else 0
    good_mfe = sum(float(r["mfe_r"] or 0) for r in good) / len(good) if good else 0
    poor_mfe = sum(float(r["mfe_r"] or 0) for r in poor) / len(poor) if poor else 0
    good_win = sum(1 for r in good if float(r["r_multiple"] or 0) > 0) / len(good) * 100 if good else 0
    poor_win = sum(1 for r in poor if float(r["r_multiple"] or 0) > 0) / len(poor) * 100 if poor else 0

    report = {
        "total_trades": len(rows),
        "good_entries": {"count": len(good), "avg_r": round(good_avg_r, 3), "avg_mfe": round(good_mfe, 3), "win_rate": round(good_win, 1)},
        "poor_entries": {"count": len(poor), "avg_r": round(poor_avg_r, 3), "avg_mfe": round(poor_mfe, 3), "win_rate": round(poor_win, 1)},
        "conclusion": "good entries outperform" if good_avg_r > poor_avg_r else "no significant difference",
    }

    log.info(f"\nEntry Quality Correlation ({len(rows)} trades):")
    log.info(f"  Good entries (score>=50): {len(good)} trades, avg R={good_avg_r:.3f}, MFE={good_mfe:.2f}R, win={good_win:.0f}%")
    log.info(f"  Poor entries (score<50):  {len(poor)} trades, avg R={poor_avg_r:.3f}, MFE={poor_mfe:.2f}R, win={poor_win:.0f}%")

    return report


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Trade Execution Analyzer — MFE/MAE + trailing optimization + entry quality")
    ap.add_argument("--mfe", action="store_true", help="Run MFE/MAE analysis")
    ap.add_argument("--optimize", action="store_true", help="Run trailing stop optimization")
    ap.add_argument("--entry", action="store_true", help="Run entry quality correlation")
    ap.add_argument("--all", action="store_true", help="Run all analyses")
    ap.add_argument("--symbol", type=str, help="Filter to specific symbol")
    args = ap.parse_args()

    if not any([args.mfe, args.optimize, args.entry, args.all]):
        args.all = True

    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        return

    if args.mfe or args.all:
        log.info("=== MFE/MAE Analysis ===")
        result = run_mfe_analysis(conn, symbol_filter=args.symbol)
        log.info(f"MFE analysis: {result}")

    if args.optimize or args.all:
        log.info("\n=== Trailing Stop Optimization ===")
        result = run_trailing_optimization(conn)
        log.info(f"Optimization: {json.dumps(result, indent=2, default=str)}")

    if args.entry or args.all:
        log.info("\n=== Entry Quality Correlation ===")
        result = run_entry_quality_correlation(conn)
        log.info(f"Correlation: {json.dumps(result, indent=2, default=str)}")

    conn.close()
    log.info("\nAll analyses complete.")


if __name__ == "__main__":
    main()
