#!/usr/bin/env python3
"""proposal_backtest_engine.py — Local evidence backtest for paper proposals.

Estimates historical performance based on local Trade AI data:
strategy_signals, trade_ai_scans, paper_trades, trade_closed,
agent_recommendation_outcomes, pattern_library.

Usage:
    .venv/bin/python scripts/proposal_backtest_engine.py --proposal-id 2
    .venv/bin/python scripts/proposal_backtest_engine.py --all-pending
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("backtest_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _safe_float(v, default=None):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def backtest_proposal(conn, proposal_id):
    """Run local evidence backtest for a single proposal."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT id, symbol, strategy_id, setup_type, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, catalyst_confidence,
               critic_verdict, sector
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"error": f"Proposal {proposal_id} not found"}
    prop = dict(zip(cols, row))
    symbol = prop['symbol']
    strategy_id = prop.get('strategy_id') or ''

    # ── 1. Same symbol history ──────────────────────────────────────────
    symbol_history = {"prior_scans": 0, "go_count": 0, "wait_count": 0, "aplus_count": 0,
                      "paper_trades": 0, "paper_wins": 0, "paper_pnl": 0.0,
                      "real_trades": 0, "real_wins": 0, "real_pnl": 0.0,
                      "last_result": None}

    cur.execute("SELECT COUNT(*) FROM trade_ai_scans WHERE symbol = %s", [symbol])
    symbol_history["prior_scans"] = cur.fetchone()[0] or 0

    cur.execute("SELECT decision, COUNT(*) FROM trade_ai_scans WHERE symbol = %s GROUP BY decision", [symbol])
    for dec, cnt in cur.fetchall():
        if dec == 'GO': symbol_history["go_count"] = cnt
        elif dec == 'WAIT': symbol_history["wait_count"] = cnt
        elif dec in ('A+', 'A_PLUS'): symbol_history["aplus_count"] = cnt

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(pnl), 0)
        FROM paper_trades WHERE symbol = %s AND status = 'closed'
    """, [symbol])
    r = cur.fetchone()
    symbol_history["paper_trades"] = r[0] or 0
    symbol_history["paper_wins"] = r[1] or 0
    symbol_history["paper_pnl"] = round(float(r[2] or 0), 2)

    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(pnl), 0)
        FROM trade_closed WHERE symbol = %s
    """, [symbol])
    r = cur.fetchone()
    symbol_history["real_trades"] = r[0] or 0
    symbol_history["real_wins"] = r[1] or 0
    symbol_history["real_pnl"] = round(float(r[2] or 0), 2)

    # Last paper result
    cur.execute("""
        SELECT pnl, outcome_verdict FROM paper_trades
        WHERE symbol = %s AND status = 'closed'
        ORDER BY closed_at DESC LIMIT 1
    """, [symbol])
    last = cur.fetchone()
    if last:
        symbol_history["last_result"] = f"PnL ${float(last[0]):.2f} ({last[1]})"

    # ── 2. Same strategy history ────────────────────────────────────────
    strategy_history = {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                        "profit_factor": None, "expectancy": None, "sample_size": 0}

    if strategy_id:
        cur.execute("""
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0),
                   COALESCE(AVG(pnl), 0),
                   COALESCE(AVG(r_multiple), 0)
            FROM paper_trades WHERE strategy_id = %s AND status = 'closed'
        """, [strategy_id])
        r = cur.fetchone()
        strategy_history["trades"] = r[0] or 0
        strategy_history["wins"] = r[1] or 0
        strategy_history["losses"] = r[2] or 0
        strategy_history["sample_size"] = r[0] or 0
        total_gains = float(r[3] or 0)
        total_losses = float(r[4] or 0)
        avg_pnl = float(r[5] or 0)
        avg_r = float(r[6] or 0)
        if strategy_history["trades"] > 0:
            strategy_history["win_rate"] = round(strategy_history["wins"] / strategy_history["trades"], 3)
            strategy_history["profit_factor"] = round(total_gains / total_losses, 2) if total_losses > 0 else None
            strategy_history["expectancy"] = round(avg_pnl, 2)
            strategy_history["avg_r"] = round(avg_r, 2)

    # ── 3. Similar setup history (broader match) ────────────────────────
    similar_count = 0
    similar_wins = 0
    similar_pnl = 0.0
    similar_r = 0.0

    # Match by strategy + similar RVOL/float/gap buckets from scans
    rvol = _safe_float(prop.get('rvol'), 0)
    float_m = _safe_float(prop.get('float_m'), 0)
    gap_pct = _safe_float(prop.get('gap_pct'), 0)

    # RVOL bucket: within 50% range
    rvol_lo = rvol * 0.5 if rvol else 0
    rvol_hi = rvol * 2.0 if rvol else 100

    # Float bucket: within 3x range
    float_lo = float_m * 0.3 if float_m else 0
    float_hi = float_m * 3.0 if float_m else 1000

    try:
        cur.execute("""
            SELECT pt.pnl, pt.r_multiple
            FROM paper_trades pt
            WHERE pt.status = 'closed'
              AND pt.strategy_id = %s
              AND pt.rvol_at_entry BETWEEN %s AND %s
              AND pt.float_m_at_entry BETWEEN %s AND %s
        """, [strategy_id, rvol_lo, rvol_hi, float_lo, float_hi])
        for pnl, r_mult in cur.fetchall():
            similar_count += 1
            if pnl and float(pnl) > 0:
                similar_wins += 1
            similar_pnl += float(pnl or 0)
            similar_r += float(r_mult or 0)
    except Exception as e:
        log.debug(f"Similar setup query failed: {e}")
        try: conn.rollback()
        except: pass

    # ── 4. Pattern library ──────────────────────────────────────────────
    patterns = {"proven": [], "killed": [], "watch": []}
    try:
        cur.execute("""
            SELECT pattern_name, status, pattern_description
            FROM pattern_library
            WHERE (symbol = %s OR strategy_id = %s)
              AND status IN ('PROVEN', 'KILLED', 'WATCH')
            ORDER BY created_at DESC LIMIT 10
        """, [symbol, strategy_id])
        for name, status, desc in cur.fetchall():
            entry = f"{name}: {(desc or '')[:80]}"
            if status == 'PROVEN': patterns["proven"].append(entry)
            elif status == 'KILLED': patterns["killed"].append(entry)
            elif status == 'WATCH': patterns["watch"].append(entry)
    except Exception:
        pass

    # ── 5. Agent recommendation outcomes ────────────────────────────────
    agent_outcomes = 0
    agent_correct = 0
    try:
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN verdict = 'CORRECT' THEN 1 ELSE 0 END), 0)
            FROM agent_recommendation_outcomes
            WHERE symbol = %s OR strategy_type = %s
        """, [symbol, strategy_id])
        r = cur.fetchone()
        agent_outcomes = r[0] or 0
        agent_correct = r[1] or 0
    except Exception:
        pass

    # ── Aggregate ───────────────────────────────────────────────────────
    total_samples = (symbol_history["paper_trades"] + symbol_history["real_trades"] +
                     similar_count + strategy_history["trades"])
    # Deduplicated approximate
    sample_size = max(similar_count, strategy_history["trades"],
                      symbol_history["paper_trades"] + symbol_history["real_trades"])

    if sample_size >= 30:
        backtest_quality = "SUFFICIENT"
    elif sample_size >= 10:
        backtest_quality = "LIMITED"
    elif sample_size >= 1:
        backtest_quality = "INSUFFICIENT"
    else:
        backtest_quality = "NO_DATA"

    # Aggregate win rate
    total_closed = similar_count if similar_count > 0 else strategy_history["trades"]
    total_w = similar_wins if similar_count > 0 else strategy_history["wins"]
    win_rate = round(total_w / total_closed, 3) if total_closed > 0 else None

    # Profit factor from strategy
    profit_factor = strategy_history.get("profit_factor")

    # Expectancy
    expectancy = strategy_history.get("expectancy")

    # Avg R
    avg_r = None
    if similar_count > 0 and similar_r:
        avg_r = round(similar_r / similar_count, 2)
    elif strategy_history.get("avg_r"):
        avg_r = strategy_history["avg_r"]

    # Similar setup summary
    similar_summary = f"{similar_count} similar setups found "
    if similar_count > 0:
        sim_wr = round(similar_wins / similar_count * 100, 1)
        similar_summary += f"(win rate {sim_wr}%, total PnL ${similar_pnl:.2f})"
    else:
        similar_summary += "— no close matches in local data"

    # Repeat pattern
    repeat_detected = len(patterns["proven"]) > 0 or len(patterns["killed"]) > 0
    repeat_desc = None
    if patterns["proven"]:
        repeat_desc = f"PROVEN: {patterns['proven'][0]}"
    elif patterns["killed"]:
        repeat_desc = f"KILLED: {patterns['killed'][0]}"

    # Limitations
    limitations = []
    if sample_size < 30:
        limitations.append(f"Only {sample_size} local samples")
    if symbol_history["paper_trades"] == 0:
        limitations.append(f"No closed paper trades for {symbol} yet")
    if symbol_history["real_trades"] == 0:
        limitations.append(f"No closed real trades for {symbol}")
    if similar_count < 5:
        limitations.append(f"Only {similar_count} similar setup matches")
    if backtest_quality == "NO_DATA":
        limitations.append("No historical trade data available for comparison")

    result = {
        "proposal_id": proposal_id,
        "symbol": symbol,
        "strategy_id": strategy_id,
        "sample_size": sample_size,
        "symbol_sample_size": symbol_history["paper_trades"] + symbol_history["real_trades"],
        "strategy_sample_size": strategy_history["trades"],
        "pattern_sample_size": len(patterns["proven"]) + len(patterns["killed"]) + len(patterns["watch"]),
        "backtest_quality": backtest_quality,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "avg_r": avg_r,
        "median_hold_minutes": None,  # TODO: compute when we have enough data
        "similar_setup_summary": similar_summary,
        "repeat_pattern_detected": repeat_detected,
        "repeat_pattern_description": repeat_desc,
        "limitations": limitations,
        "symbol_history": symbol_history,
        "strategy_history": strategy_history,
        "patterns": patterns,
        "agent_outcomes": {"total": agent_outcomes, "correct": agent_correct},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Upsert into proposal_backtest_snapshots
    try:
        conn.rollback()  # clear any prior aborted transaction
        cur.execute("""
            INSERT INTO proposal_backtest_snapshots
                (proposal_id, symbol, strategy_id, setup_type,
                 sample_size, symbol_sample_size, strategy_sample_size, pattern_sample_size,
                 win_rate, profit_factor, expectancy, avg_r,
                 similar_setup_summary, repeat_pattern_detected, repeat_pattern_description,
                 backtest_quality, limitations, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (proposal_id) DO UPDATE SET
                sample_size = EXCLUDED.sample_size,
                symbol_sample_size = EXCLUDED.symbol_sample_size,
                strategy_sample_size = EXCLUDED.strategy_sample_size,
                pattern_sample_size = EXCLUDED.pattern_sample_size,
                win_rate = EXCLUDED.win_rate,
                profit_factor = EXCLUDED.profit_factor,
                expectancy = EXCLUDED.expectancy,
                avg_r = EXCLUDED.avg_r,
                similar_setup_summary = EXCLUDED.similar_setup_summary,
                repeat_pattern_detected = EXCLUDED.repeat_pattern_detected,
                repeat_pattern_description = EXCLUDED.repeat_pattern_description,
                backtest_quality = EXCLUDED.backtest_quality,
                limitations = EXCLUDED.limitations,
                payload = EXCLUDED.payload
        """, [
            proposal_id, symbol, strategy_id, prop.get('setup_type'),
            sample_size, result["symbol_sample_size"], strategy_history["trades"],
            result["pattern_sample_size"],
            win_rate, profit_factor, expectancy, avg_r,
            similar_summary, repeat_detected, repeat_desc,
            backtest_quality, json.dumps(limitations),
            json.dumps(result, default=str),
        ])

        # Update proposal
        cur.execute("""
            UPDATE paper_trade_proposals
            SET backtest_status = %s,
                backtest_summary = %s,
                stock_history_summary = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [
            backtest_quality,
            json.dumps({"quality": backtest_quality, "sample_size": sample_size,
                         "win_rate": win_rate, "profit_factor": profit_factor,
                         "expectancy": expectancy, "avg_r": avg_r,
                         "similar_summary": similar_summary,
                         "repeat_pattern": repeat_detected,
                         "limitations": limitations}, default=str),
            json.dumps(symbol_history, default=str),
            proposal_id,
        ])
        conn.commit()
        log.info(f"  {symbol} (#{proposal_id}): backtest={backtest_quality} samples={sample_size} wr={win_rate}")
    except Exception as e:
        log.warning(f"Failed to persist backtest for {proposal_id}: {e}")
        conn.rollback()

    return result


def _write_strategy_backtest_result(conn, result):
    """Session 23C: Also write to strategy_backtest_results table."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO strategy_backtest_results
                (strategy_id, symbol, setup_type, sector, timeframe,
                 sample_size, wins, losses, win_rate, avg_r, expectancy_r,
                 profit_factor, confidence_level, sample_warning, parameters)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [
            result.get("strategy_id"), result.get("symbol"),
            result.get("setup_type"), result.get("sector"),
            result.get("timeframe", "mixed"),
            result.get("sample_size", 0),
            result.get("wins", 0), result.get("losses", 0),
            result.get("win_rate"), result.get("avg_r"),
            result.get("expectancy"), result.get("profit_factor"),
            result.get("backtest_quality"),
            "Backtest sample insufficient — learning mode only" if (result.get("sample_size") or 0) < 20 else None,
            json.dumps({"limitations": result.get("limitations", [])}, default=str),
        ])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to write strategy_backtest_results: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Proposal backtest engine")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--all-pending", action="store_true")
    parser.add_argument("--pending", action="store_true", help="Alias for --all-pending")
    parser.add_argument("--strategy", type=str, help="Filter by strategy_id")
    parser.add_argument("--apply", action="store_true", help="Write to DB")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.all_pending or args.pending:
            cur = conn.cursor()
            # Active proposals = PENDING and APPROVED_FOR_PAPER_TEST. The old filter was PENDING-only, so
            # proposals that moved to approved/paper-test (the ones actually shown + executed) never got a
            # backtest snapshot — proposal_backtest_snapshots went 34d stale and the card's Backtest field
            # stayed blank. Cover both active statuses.
            _ACTIVE = ('PENDING', 'APPROVED_FOR_PAPER_TEST')
            if args.strategy:
                cur.execute("""SELECT id FROM paper_trade_proposals
                             WHERE status = ANY(%s) AND strategy_id=%s
                             ORDER BY created_at DESC""", [list(_ACTIVE), args.strategy])
            else:
                cur.execute("SELECT id FROM paper_trade_proposals WHERE status = ANY(%s) ORDER BY created_at DESC",
                            [list(_ACTIVE)])
            results = []
            for (pid,) in cur.fetchall():
                result = backtest_proposal(conn, pid)
                if result.get('error'):
                    log.error(f"  #{pid}: {result['error']}")
                else:
                    _write_strategy_backtest_result(conn, result)
                    results.append({"proposal_id": pid, "symbol": result.get("symbol"),
                                    "quality": result.get("backtest_quality"),
                                    "samples": result.get("sample_size")})
            print(json.dumps({"processed": len(results), "results": results}, indent=2, default=str))
        elif args.proposal_id:
            result = backtest_proposal(conn, args.proposal_id)
            _write_strategy_backtest_result(conn, result)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Usage: --proposal-id N or --pending --apply or --strategy swing_breakout --pending --apply")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
