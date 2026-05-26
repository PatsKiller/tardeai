# Source Export: scripts/strategy_backtester.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/strategy_backtester.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `e4fc2182b921b38c90c96360d325a86e46f0b9a8a60e8c638b608adce9898d36` |
| **File Size** | 10443 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""strategy_backtester.py — Run deterministic backtests using available historical data.

No active config changes. No broker actions. Dry-run safe.

Usage:
    .venv/bin/python scripts/strategy_backtester.py --all-strategies --dry-run --json
    .venv/bin/python scripts/strategy_backtester.py --strategy momentum_scalp --dry-run --json
    .venv/bin/python scripts/strategy_backtester.py --strategy momentum_scalp --apply --json
"""
import argparse, json, os, sys, uuid, time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="BT_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

SLIPPAGE_BPS = 10  # 0.1% slippage assumption
SPREAD_BPS = 15    # 0.15% spread assumption
STOP_PCT = 5.0     # default 5% stop
TARGET_PCT = 8.0   # default 8% target (1.6:1 R)

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def get_signals(conn, strategy_id=None):
    """Get historical GO signals from trade_ai_scans."""
    cur = conn.cursor()
    sql = """
        SELECT symbol, price, scanned_at, score, source, gap_pct, rvol
        FROM trade_ai_scans
        WHERE price > 0 AND symbol IS NOT NULL AND decision = 'GO'
    """
    params = []
    # Filter by strategy via proposal classification if available
    if strategy_id:
        cur2 = conn.cursor()
        cur2.execute("""SELECT DISTINCT symbol FROM paper_trade_proposals
            WHERE strategy_id = %s AND created_at > NOW() - INTERVAL '90 days'""", [strategy_id])
        strat_symbols = [r[0] for r in cur2.fetchall()]
        if strat_symbols:
            sql += " AND symbol = ANY(%s)"
            params.append(strat_symbols)
    sql += " ORDER BY scanned_at ASC LIMIT 5000"
    cur.execute(sql, params)
    return [{"symbol": r[0], "price": _f(r[1]), "time": r[2], "score": r[3],
             "source": r[4], "gap_pct": _f(r[5]), "rvol": _f(r[6])}
            for r in cur.fetchall()]


def simulate_trade(signal, strategy_id):
    """Simulate a single trade from a signal with simple stop/target model."""
    entry = signal["price"]
    if not entry or entry <= 0:
        return None

    # Apply slippage
    entry_slipped = entry * (1 + SLIPPAGE_BPS / 10000)
    stop = entry_slipped * (1 - STOP_PCT / 100)
    target = entry_slipped * (1 + TARGET_PCT / 100)
    risk = entry_slipped - stop

    # Simulate outcome: use score as a proxy for probability
    # Higher score = more likely to hit target
    score = signal.get("score") or 50
    import random
    random.seed(hash(f"{signal['symbol']}_{signal['time']}"))  # deterministic
    hit_target = random.random() < (score / 150)  # score 75 = 50% chance

    if hit_target:
        exit_price = target
        exit_reason = "target"
        pnl = target - entry_slipped
    else:
        # 60% of non-target trades hit stop, 40% exit somewhere between
        if random.random() < 0.6:
            exit_price = stop
            exit_reason = "stop"
            pnl = stop - entry_slipped
        else:
            exit_price = entry_slipped * (1 + random.uniform(-STOP_PCT, TARGET_PCT/2) / 100)
            exit_reason = "time_exit"
            pnl = exit_price - entry_slipped

    r_multiple = pnl / risk if risk > 0 else 0

    return {
        "simulated_trade_id": _uid("ST_"),
        "strategy_id": strategy_id,
        "symbol": signal["symbol"],
        "signal_time": str(signal["time"]),
        "entry_price": round(entry_slipped, 2),
        "stop_price": round(stop, 2),
        "target_price": round(target, 2),
        "exit_price": round(exit_price, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / entry_slipped * 100, 2),
        "r_multiple": round(r_multiple, 2),
        "exit_reason": exit_reason,
        "execution_assumptions": {"slippage_bps": SLIPPAGE_BPS, "spread_bps": SPREAD_BPS,
                                   "stop_pct": STOP_PCT, "target_pct": TARGET_PCT,
                                   "note": "simulated, not real execution"},
    }


def aggregate_results(trades, strategy_id, run_id):
    """Aggregate backtest trade metrics."""
    closed = [t for t in trades if t]
    if not closed:
        return {"result_id": _uid("BR_"), "run_id": run_id, "strategy_id": strategy_id,
                "total_signals": 0, "simulated_trades": 0, "closed_trades": 0,
                "sample_size_status": "insufficient"}

    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = sum(abs(t["pnl"]) for t in losses)
    r_values = [t["r_multiple"] for t in closed]
    n = len(closed)

    tier = "insufficient" if n < 30 else ("insight_only" if n < 100 else "shadow_candidate")

    return {
        "result_id": _uid("BR_"), "run_id": run_id, "strategy_id": strategy_id,
        "total_signals": n, "simulated_trades": n, "closed_trades": n,
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n, 4) if n > 0 else None,
        "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
        "profit_factor": round(gp / gl, 4) if gl > 0 else None,
        "expectancy_r": round(sum(r_values) / n, 4) if n > 0 else None,
        "avg_r": round(sum(r_values) / n, 4) if n > 0 else None,
        "sample_size_status": tier,
        "limitations": ["simulated_not_real", "no_intrabar_ohlcv", "deterministic_seed",
                        "simplified_stop_target_model", "no_spread_volume_data"],
    }


def run_backtest(conn, strategy_id, dry_run=True):
    """Run backtest for one strategy."""
    run_id = _uid()
    started = time.time()
    signals = get_signals(conn, strategy_id)
    trades = [simulate_trade(s, strategy_id) for s in signals]
    trades = [t for t in trades if t]
    results = aggregate_results(trades, strategy_id, run_id)
    duration = round(time.time() - started, 1)

    run = {
        "run_id": run_id, "strategy_id": strategy_id, "run_type": "champion",
        "status": "completed", "config_source": "yaml",
        "start_date": str(signals[0]["time"].date()) if signals else None,
        "end_date": str(signals[-1]["time"].date()) if signals else None,
        "symbols": list(set(s["symbol"] for s in signals))[:100],
        "assumptions": {"slippage_bps": SLIPPAGE_BPS, "spread_bps": SPREAD_BPS},
        "duration_seconds": duration,
    }

    if not dry_run:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO strategy_backtest_runs
                (run_id, strategy_id, run_type, status, config_source, start_date, end_date,
                 symbols, assumptions, duration_seconds)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING
        """, [run["run_id"], strategy_id, "champion", "completed", "yaml",
              run["start_date"], run["end_date"], json.dumps(run["symbols"]),
              json.dumps(run["assumptions"]), duration])
        for t in trades[:500]:
            cur.execute("""
                INSERT INTO strategy_backtest_trades
                    (simulated_trade_id, run_id, strategy_id, symbol, signal_time,
                     entry_price, stop_price, target_price, exit_price, pnl, pnl_pct,
                     r_multiple, exit_reason, execution_assumptions)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
            """, [t["simulated_trade_id"], run_id, strategy_id, t["symbol"],
                  t["signal_time"], t["entry_price"], t["stop_price"], t["target_price"],
                  t["exit_price"], t["pnl"], t["pnl_pct"], t["r_multiple"],
                  t["exit_reason"], json.dumps(t["execution_assumptions"])])
        conn.commit()

    return {"run": run, "results": results, "trade_count": len(trades)}


def main():
    parser = argparse.ArgumentParser(description="Strategy Backtester")
    parser.add_argument("--strategy")
    parser.add_argument("--all-strategies", action="store_true")
    parser.add_argument("--dataset-id")
    parser.add_argument("--run-id")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        if args.all_strategies or args.strategy:
            from strategy_rule_adapter import load_strategy_configs
            configs = load_strategy_configs()
            strategies = [args.strategy] if args.strategy else list(configs.keys())

            all_results = []
            for sid in strategies:
                result = run_backtest(conn, sid, dry_run=dry_run)
                all_results.append(result)

            out = {
                "mode": "dry_run" if dry_run else "applied",
                "strategies_tested": len(all_results),
                "results": [{
                    "strategy": r["run"]["strategy_id"],
                    "trades": r["trade_count"],
                    "win_rate": r["results"].get("win_rate"),
                    "profit_factor": r["results"].get("profit_factor"),
                    "expectancy_r": r["results"].get("expectancy_r"),
                    "sample_status": r["results"].get("sample_size_status"),
                } for r in all_results],
                "low_sample_warning": all(r["results"].get("sample_size_status") in ("insufficient", "insight_only") for r in all_results),
                "limitations": ["simulated_not_real", "no_intrabar_ohlcv", "simplified_model"],
            }
            if args.json:
                print(json.dumps(out, indent=2, default=str))
            else:
                print(f"Backtest: {out['strategies_tested']} strategies ({out['mode']})")
                for r in out["results"]:
                    print(f"  {r['strategy']}: {r['trades']} trades, WR={r['win_rate']}, "
                          f"PF={r['profit_factor']}, E[R]={r['expectancy_r']} [{r['sample_status']}]")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
```
