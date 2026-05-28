#!/usr/bin/env python3
"""enterprise_backtester.py — Real price-replay backtesting engine.

Replays actual daily OHLC bars against historical signals and proposals.
No probability simulation. Deterministic results from real price data.

Modes:
  --replay-trades     Replay trades we actually took (journal ground truth comparison)
  --replay-proposals  Replay proposals we generated but didn't trade
  --strategy X        Filter to one strategy
  --exclude-scalps    Skip momentum_scalp unless actually traded (default: on)
  --days N            Max hold period before timeout exit (default: 20)
  --apply             Write results to DB

No live trading. No broker calls. Read-only on market data.
"""
import argparse, json, logging, os, sys, time, uuid, warnings
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [backtester] %(message)s")
log = logging.getLogger(__name__)

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
OHLC_CACHE_PATH = STATE_DIR / "price_ohlc_cache.json"
CLOSE_CACHE_PATH = STATE_DIR / "price_cache.json"

SCALP_STRATEGIES = {"momentum_scalp", "gap_and_go", "social_scalp"}


# ── Data Loaders ────────────────────────────────────────────────────────────

def load_ohlc_cache() -> Dict:
    """Load OHLC cache. Falls back to close-only with degraded confidence."""
    if OHLC_CACHE_PATH.exists():
        return json.loads(OHLC_CACHE_PATH.read_text())
    return {}


def load_close_cache() -> Dict:
    """Load close-only price cache."""
    if CLOSE_CACHE_PATH.exists():
        raw = json.loads(CLOSE_CACHE_PATH.read_text())
        # Remove meta keys
        return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}
    return {}


def fetch_ohlc_for_symbols(symbols: List[str], start: str, end: str) -> Dict:
    """Fetch OHLC from yfinance and cache. Returns {symbol: {date: {o,h,l,c,v}}}."""
    import yfinance as yf
    warnings.simplefilter("ignore")

    ohlc = load_ohlc_cache()
    missing = [s for s in symbols if s not in ohlc or not ohlc[s]]

    if missing:
        log.info(f"Fetching OHLC for {len(missing)} symbols...")
        for sym in missing:
            try:
                hist = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True, threads=False)
                if hist.empty:
                    continue
                # Flatten MultiIndex
                if hasattr(hist.columns, "levels"):
                    hist.columns = [c[0] for c in hist.columns]
                bars = {}
                for idx, row in hist.iterrows():
                    d = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
                    bars[d] = {
                        "o": round(float(row.get("Open", row.get("Close", 0))), 4),
                        "h": round(float(row.get("High", row.get("Close", 0))), 4),
                        "l": round(float(row.get("Low", row.get("Close", 0))), 4),
                        "c": round(float(row.get("Close", 0)), 4),
                        "v": int(row.get("Volume", 0)),
                    }
                ohlc[sym] = bars
                time.sleep(0.3)
            except Exception as e:
                log.warning(f"OHLC fetch failed for {sym}: {e}")

        # Persist cache
        OHLC_CACHE_PATH.write_text(json.dumps(ohlc, separators=(",", ":")))
        log.info(f"OHLC cache updated: {len(ohlc)} symbols")

    return ohlc


def get_trades_from_db() -> List[Dict]:
    """Get all closed trades from unified trades view (all brokers, all accounts)."""
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Unified trades view: paper_trades (Alpaca) + paired trade_transactions (Schwab, all brokers)
    cur.execute("""SELECT trade_id as id, symbol, strategy_id, broker, account,
        entry_price, exit_price, stop_loss, target_price as target_1,
        shares, pnl, pnl_pct, exit_reason, entry_date as entry_time,
        exit_date as closed_at, source_table
        FROM trades
        WHERE status='closed' AND entry_price > 0 AND exit_price > 0""")
    all_trades = [dict(r) for r in cur.fetchall()]

    conn.close()
    return all_trades


def get_proposals_from_db(exclude_scalps=True) -> List[Dict]:
    """Get proposals that were NOT traded (missed opportunities)."""
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    exclude = ""
    if exclude_scalps:
        exclude = "AND strategy_id NOT IN ('momentum_scalp','gap_and_go','social_scalp')"

    cur.execute(f"""SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
        proposed_target1, proposed_shares, proposed_rr, status, created_at
        FROM paper_trade_proposals
        WHERE proposed_entry > 0 AND proposed_stop > 0 AND proposed_target1 > 0
        AND paper_trade_id IS NULL
        {exclude}
        ORDER BY created_at""")
    proposals = [dict(r) for r in cur.fetchall()]
    conn.close()
    return proposals


# ── Replay Engine ───────────────────────────────────────────────────────────

def replay_trade(symbol: str, entry_price: float, entry_date: str,
                 stop: float, target: float, max_days: int,
                 ohlc: Dict, close_cache: Dict) -> Dict:
    """Replay a single trade against real price bars.

    Returns dict with exit_price, exit_date, exit_reason, pnl, mae, mfe, hold_days.
    """
    bars = ohlc.get(symbol, {})
    close_prices = close_cache.get(symbol, {})
    ohlc_available = bool(bars)

    # Use whichever source has data
    if not bars and not close_prices:
        return {"status": "no_data", "symbol": symbol, "reason": "no price data available"}

    # Get sorted dates after entry
    all_dates = sorted(set(list(bars.keys()) + list(close_prices.keys())))
    # Find entry date or next available
    entry_idx = None
    date_adjusted = False
    for i, d in enumerate(all_dates):
        if d >= entry_date:
            entry_idx = i
            if d != entry_date:
                date_adjusted = True
            break
    if entry_idx is None:
        return {"status": "no_data", "symbol": symbol, "reason": f"no bars after {entry_date}"}

    # Replay bars
    mae = 0.0  # max adverse excursion (worst drawdown from entry)
    mfe = 0.0  # max favorable excursion (best profit from entry)
    exit_price = None
    exit_date = None
    exit_reason = None

    for day_offset in range(max_days):
        bar_idx = entry_idx + day_offset + 1  # start from day AFTER entry
        if bar_idx >= len(all_dates):
            break

        d = all_dates[bar_idx]

        # Get bar data
        if d in bars:
            bar = bars[d]
            high = bar["h"]
            low = bar["l"]
            close = bar["c"]
            data_quality = "ohlc"
        elif d in close_prices:
            close = float(close_prices[d])
            high = close
            low = close
            data_quality = "close_only"
        else:
            continue

        # Track MAE/MFE
        adverse = (low - entry_price) / entry_price * 100
        favorable = (high - entry_price) / entry_price * 100
        mae = min(mae, adverse)
        mfe = max(mfe, favorable)

        # Check stop hit (low <= stop)
        stop_hit = low <= stop
        # Check target hit (high >= target)
        target_hit = high >= target

        if stop_hit and target_hit:
            # Both hit same day — worst case: stop hit first
            exit_price = stop
            exit_date = d
            exit_reason = "stop_ambiguous_day"
            break
        elif stop_hit:
            exit_price = stop
            exit_date = d
            exit_reason = "stop_hit"
            break
        elif target_hit:
            exit_price = target
            exit_date = d
            exit_reason = "target_hit"
            break

    # Timeout — exit at last available close
    if exit_price is None:
        last_bar_idx = min(entry_idx + max_days, len(all_dates) - 1)
        d = all_dates[last_bar_idx]
        if d in bars:
            exit_price = bars[d]["c"]
        elif d in close_prices:
            exit_price = float(close_prices[d])
        else:
            exit_price = entry_price  # fallback
        exit_date = d
        exit_reason = "timeout"

    pnl = exit_price - entry_price
    pnl_pct = (pnl / entry_price * 100) if entry_price > 0 else 0
    hold_days = len([d for d in all_dates if entry_date < d <= (exit_date or entry_date)])

    return {
        "status": "completed",
        "symbol": symbol,
        "entry_price": round(entry_price, 4),
        "entry_date": entry_date,
        "exit_price": round(exit_price, 4),
        "exit_date": exit_date,
        "exit_reason": exit_reason,
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 2),
        "mae_pct": round(mae, 2),
        "mfe_pct": round(mfe, 2),
        "hold_days": hold_days,
        "stop": round(stop, 4),
        "target": round(target, 4),
        "date_adjusted": date_adjusted,
        "ohlc_available": ohlc_available,
    }


# ── Comparison Engine ───────────────────────────────────────────────────────

def compare_replay_to_actual(replay: Dict, actual: Dict) -> Dict:
    """Compare replay result to actual closed trade."""
    if replay["status"] != "completed":
        return {"matched": False, "reason": replay.get("reason", "replay failed")}

    actual_pnl = float(actual.get("pnl") or 0)
    replay_pnl = replay["pnl"] * float(actual.get("shares") or 1)
    actual_exit = float(actual.get("exit_price") or 0)

    actual_win = actual_pnl > 0
    replay_win = replay["pnl"] > 0

    return {
        "matched": True,
        "symbol": replay["symbol"],
        "actual_pnl": round(actual_pnl, 2),
        "replay_pnl": round(replay_pnl, 2),
        "pnl_delta": round(replay_pnl - actual_pnl, 2),
        "actual_exit": actual_exit,
        "replay_exit": replay["exit_price"],
        "exit_delta": round(replay["exit_price"] - actual_exit, 2),
        "actual_win": actual_win,
        "replay_win": replay_win,
        "outcome_match": actual_win == replay_win,
        "replay_exit_reason": replay["exit_reason"],
        "actual_exit_reason": actual.get("exit_reason", "?"),
    }


# ── Aggregation ─────────────────────────────────────────────────────────────

def aggregate_results(results: List[Dict], label: str) -> Dict:
    """Aggregate replay results into summary stats."""
    completed = [r for r in results if r.get("status") == "completed"]
    if not completed:
        return {"label": label, "count": 0, "coverage_pct": 0}

    wins = [r for r in completed if r["pnl"] > 0]
    losses = [r for r in completed if r["pnl"] <= 0]
    pnls = [r["pnl_pct"] for r in completed]
    maes = [r["mae_pct"] for r in completed]
    mfes = [r["mfe_pct"] for r in completed]
    holds = [r["hold_days"] for r in completed]

    n = len(completed)
    gp = sum(r["pnl_pct"] for r in wins)
    gl = sum(abs(r["pnl_pct"]) for r in losses) or 1

    return {
        "label": label,
        "count": n,
        "total_signals": len(results),
        "coverage_pct": round(n / len(results) * 100, 1) if results else 0,
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_return_pct": round(sum(pnls) / n, 2),
        "profit_factor": round(gp / gl, 2),
        "avg_mae_pct": round(sum(maes) / n, 2),
        "avg_mfe_pct": round(sum(mfes) / n, 2),
        "avg_hold_days": round(sum(holds) / n, 1),
        "max_win_pct": round(max(pnls), 2),
        "max_loss_pct": round(min(pnls), 2),
        "by_exit_reason": {r: sum(1 for x in completed if x["exit_reason"] == r)
                          for r in set(x["exit_reason"] for x in completed)},
        "ohlc_coverage": round(sum(1 for r in completed if r["ohlc_available"]) / n * 100, 1),
    }


# ── DB Writer ───────────────────────────────────────────────────────────────

def save_results_to_db(results: List[Dict], run_id: str, mode: str):
    """Save replay results to strategy_backtest_runs + trades."""
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()

    completed = [r for r in results if r.get("status") == "completed"]
    if not completed:
        conn.close()
        return

    strategies = set(r.get("strategy_id") or "unknown" for r in completed)
    symbols = list(set(r["symbol"] for r in completed))
    dates = [r["entry_date"] for r in completed if r.get("entry_date")]

    cur.execute("""INSERT INTO strategy_backtest_runs
        (run_id, strategy_id, run_type, status, config_source, start_date, end_date,
         symbols, assumptions, duration_seconds)
        VALUES (%s, %s, %s, 'completed', 'price_replay', %s, %s, %s, %s, 0)
        ON CONFLICT (run_id) DO NOTHING""",
        [run_id, ",".join(strategies), f"replay_{mode}",
         min(dates) if dates else None, max(dates) if dates else None,
         json.dumps(symbols[:100]), json.dumps({"engine": "enterprise_backtester", "mode": mode})])

    for r in completed:
        tid = f"ER_{run_id[:8]}_{r['symbol']}_{r['entry_date']}"
        cur.execute("""INSERT INTO strategy_backtest_trades
            (simulated_trade_id, run_id, strategy_id, symbol, signal_time,
             entry_price, stop_price, target_price, exit_price, pnl, pnl_pct,
             r_multiple, exit_reason, execution_assumptions, broker, account)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING""",
            [tid, run_id, r.get("strategy_id", "unknown"), r["symbol"],
             r["entry_date"], r["entry_price"], r["stop"], r["target"],
             r["exit_price"], r["pnl"], r["pnl_pct"],
             round(r["pnl"] / (r["entry_price"] - r["stop"]), 2) if r["entry_price"] != r["stop"] else 0,
             r["exit_reason"],
             json.dumps({"mae_pct": r["mae_pct"], "mfe_pct": r["mfe_pct"],
                         "hold_days": r["hold_days"], "ohlc": r["ohlc_available"]}),
             r.get("broker", ""), r.get("account", "")])

    conn.commit()
    conn.close()
    log.info(f"Saved {len(completed)} replay results to DB (run {run_id})")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Enterprise price-replay backtester")
    p.add_argument("--replay-trades", action="store_true", help="Replay actual closed trades")
    p.add_argument("--replay-proposals", action="store_true", help="Replay untaken proposals")
    p.add_argument("--strategy", type=str, help="Filter to one strategy")
    p.add_argument("--account", type=str, help="Filter to one account label (e.g. schwab_rollover_ira)")
    p.add_argument("--broker", type=str, help="Filter to one broker (e.g. schwab, alpaca)")
    p.add_argument("--exclude-scalps", action="store_true", default=True,
                   help="Skip scalp strategies unless traded (default: on)")
    p.add_argument("--include-scalps", action="store_true", help="Include scalp strategies")
    p.add_argument("--days", type=int, default=20, help="Max hold period (default: 20)")
    p.add_argument("--apply", action="store_true", help="Write results to DB")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.include_scalps:
        args.exclude_scalps = False

    run_id = f"ER_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    log.info(f"Enterprise backtest run {run_id}")

    # Load price data
    close_cache = load_close_cache()
    ohlc = load_ohlc_cache()

    all_results = []
    comparisons = []

    if args.replay_trades:
        all_trades = get_trades_from_db()
        trades = [{"id": t["id"], "symbol": t["symbol"],
            "strategy_id": t.get("strategy_id") or "unknown",
            "entry_price": float(t["entry_price"]), "exit_price": float(t["exit_price"]),
            "stop_loss": float(t.get("stop_loss") or 0), "target_1": float(t.get("target_1") or 0),
            "shares": float(t.get("shares") or 1), "pnl": float(t.get("pnl") or 0),
            "exit_reason": t.get("exit_reason", "?"),
            "entry_time": t.get("entry_time"), "closed_at": t.get("closed_at"),
            "account": t.get("account", ""), "broker": t.get("broker", ""),
            "source": t.get("source_table", "trades")} for t in all_trades]

        if args.strategy:
            trades = [t for t in trades if t.get("strategy_id") == args.strategy]
        if args.account:
            trades = [t for t in trades if (t.get("account") or "").lower() == args.account.lower()]
            log.info(f"Account filter '{args.account}': {len(trades)} trades")
        if args.broker:
            trades = [t for t in trades if (t.get("broker") or "").lower() == args.broker.lower()]
            log.info(f"Broker filter '{args.broker}': {len(trades)} trades")
        if args.exclude_scalps:
            # Keep scalps only if actually traded
            trades = [t for t in trades if t.get("strategy_id") not in SCALP_STRATEGIES
                      or t.get("source") == "real" or t.get("pnl")]

        # Collect symbols needing OHLC
        symbols = list(set(t["symbol"] for t in trades))
        if symbols:
            earliest = min(str(t.get("entry_time", "2026-01-01"))[:10] for t in trades)
            ohlc = fetch_ohlc_for_symbols(symbols, earliest, date.today().isoformat())

        log.info(f"Replaying {len(trades)} actual trades...")
        for t in trades:
            entry_date = str(t.get("entry_time", ""))[:10]
            entry_price = float(t.get("entry_price") or 0)
            stop = float(t.get("stop_loss") or entry_price * 0.95)
            target = float(t.get("target_1") or entry_price * 1.08)

            if not entry_price or not entry_date:
                continue

            result = replay_trade(t["symbol"], entry_price, entry_date,
                                  stop, target, args.days, ohlc, close_cache)
            result["strategy_id"] = t.get("strategy_id", "unknown")
            result["trade_id"] = t.get("id")
            result["source"] = t.get("source", "paper")
            all_results.append(result)

            # Compare to actual
            if result["status"] == "completed":
                comp = compare_replay_to_actual(result, t)
                comparisons.append(comp)

    if args.replay_proposals:
        proposals = get_proposals_from_db(exclude_scalps=args.exclude_scalps)
        if args.strategy:
            proposals = [p for p in proposals if p.get("strategy_id") == args.strategy]

        symbols = list(set(p["symbol"] for p in proposals))
        if symbols:
            earliest = min(str(p.get("created_at", "2026-01-01"))[:10] for p in proposals)
            ohlc = fetch_ohlc_for_symbols(symbols, earliest, date.today().isoformat())

        log.info(f"Replaying {len(proposals)} untaken proposals...")
        for p in proposals:
            entry_date = str(p.get("created_at", ""))[:10]
            result = replay_trade(p["symbol"], float(p["proposed_entry"]), entry_date,
                                  float(p["proposed_stop"]), float(p["proposed_target1"]),
                                  args.days, ohlc, close_cache)
            result["strategy_id"] = p.get("strategy_id", "unknown")
            result["proposal_id"] = p.get("id")
            result["proposal_status"] = p.get("status")
            all_results.append(result)

    # Aggregate
    summary = aggregate_results(all_results, "all")

    # Per-strategy
    strategies = set(r.get("strategy_id", "unknown") for r in all_results if r.get("status") == "completed")
    per_strategy = {}
    for sid in sorted(strategies, key=lambda x: x or ""):
        strat_results = [r for r in all_results if r.get("strategy_id") == sid]
        per_strategy[sid] = aggregate_results(strat_results, sid)

    # Comparison summary
    comp_summary = {}
    if comparisons:
        matched = [c for c in comparisons if c["matched"]]
        if matched:
            comp_summary = {
                "matched_trades": len(matched),
                "outcome_match_rate": round(sum(1 for c in matched if c["outcome_match"]) / len(matched) * 100, 1),
                "avg_pnl_delta": round(sum(c["pnl_delta"] for c in matched) / len(matched), 2),
                "replay_optimistic": sum(1 for c in matched if c["replay_pnl"] > c["actual_pnl"]),
                "replay_pessimistic": sum(1 for c in matched if c["replay_pnl"] < c["actual_pnl"]),
            }

    # Save to DB
    if args.apply and all_results:
        mode = "trades" if args.replay_trades else "proposals"
        save_results_to_db(all_results, run_id, mode)

    # Output
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "enterprise_price_replay",
        "total_signals": len(all_results),
        "completed": sum(1 for r in all_results if r.get("status") == "completed"),
        "no_data": sum(1 for r in all_results if r.get("status") == "no_data"),
        "summary": summary,
        "per_strategy": per_strategy,
        "comparison": comp_summary,
        "config": {"max_days": args.days, "exclude_scalps": args.exclude_scalps},
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"ENTERPRISE BACKTEST: {report['completed']}/{report['total_signals']} completed")
        print(f"{'='*60}")
        if summary.get("count"):
            print(f"  Win rate:      {summary['win_rate']}%")
            print(f"  Avg return:    {summary['avg_return_pct']}%")
            print(f"  Profit factor: {summary['profit_factor']}")
            print(f"  Avg MAE:       {summary['avg_mae_pct']}%")
            print(f"  Avg MFE:       {summary['avg_mfe_pct']}%")
            print(f"  Avg hold:      {summary['avg_hold_days']} days")
            print(f"  OHLC coverage: {summary['ohlc_coverage']}%")
        print(f"\nPer strategy:")
        for sid, s in per_strategy.items():
            print(f"  {(sid or 'unknown'):25s} n={s['count']:3d} WR={s['win_rate']:5.1f}% PF={s['profit_factor']:5.2f} MAE={s['avg_mae_pct']:+.1f}% MFE={s['avg_mfe_pct']:+.1f}%")
        if comp_summary:
            print(f"\nReplay vs Actual comparison:")
            print(f"  Matched: {comp_summary['matched_trades']} trades")
            print(f"  Outcome match: {comp_summary['outcome_match_rate']}%")
            print(f"  Avg P&L delta: ${comp_summary['avg_pnl_delta']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Enterprise Backtest Report\n",
              f"Run: {run_id} | {report['completed']}/{report['total_signals']} completed\n"]
        if summary.get("count"):
            md += [f"| Metric | Value |", f"|--------|-------|",
                   f"| Win Rate | {summary['win_rate']}% |",
                   f"| Avg Return | {summary['avg_return_pct']}% |",
                   f"| Profit Factor | {summary['profit_factor']} |",
                   f"| Avg MAE | {summary['avg_mae_pct']}% |",
                   f"| Avg MFE | {summary['avg_mfe_pct']}% |",
                   f"| OHLC Coverage | {summary['ohlc_coverage']}% |"]
        Path(args.output_md).write_text("\n".join(md))

    return report


if __name__ == "__main__":
    main()
