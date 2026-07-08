#!/usr/bin/env python3
"""paper_trade_closer.py — Close Alpaca paper trades with safety validation.

Requires explicit --close-paper flag. Validates ALPACA_MODE=paper before any action.
Runs reconciliation, TCA, and thesis review after close.

SAFETY: Paper trading ONLY. Live trading is permanently blocked.

Usage:
    .venv/bin/python scripts/paper_trade_closer.py --paper-trade-id 42 --dry-run
    .venv/bin/python scripts/paper_trade_closer.py --paper-trade-id 42 --close-paper --reason "target hit"
    .venv/bin/python scripts/paper_trade_closer.py --symbol AAPL --dry-run
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

import psycopg2
import psycopg2.extras

log = logging.getLogger("paper_trade_closer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _write_execution_event(conn, paper_trade_id, symbol, event_type, payload):
    """Write to paper_execution_events table."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_execution_events
                (paper_trade_id, symbol, event_type, event_source, payload, created_at)
            VALUES (%s, %s, %s, 'paper_trade_closer', %s, NOW())
        """, [paper_trade_id, symbol, event_type, json.dumps(payload, default=str)])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to write execution event: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def _close_alpaca_position(adapter, symbol):
    """Close a position in Alpaca paper. Returns API response or error."""
    try:
        import requests
        resp = requests.delete(
            f"{adapter.base_url}/v2/positions/{symbol}",
            headers=adapter.headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return {"status": "closed", "data": resp.json()}
        elif resp.status_code == 404:
            return {"status": "not_found", "message": f"No position for {symbol} in Alpaca"}
        else:
            return {"status": "error", "code": resp.status_code, "message": resp.text[:500]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _run_post_close(trade_id, symbol):
    """Run reconciliation + TCA + thesis review after close (non-blocking)."""
    post_close_results = {}

    # Reconciliation
    try:
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"),
             str(PROJECT_ROOT / "scripts/alpaca_paper_reconciler.py"), "--apply"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )
        post_close_results["reconciliation"] = "ok" if r.returncode == 0 else f"exit:{r.returncode}"
    except Exception as e:
        post_close_results["reconciliation"] = f"error: {str(e)[:100]}"

    # TCA (execution quality)
    try:
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"),
             str(PROJECT_ROOT / "scripts/paper_execution_quality_analyzer.py"),
             "--recent", "--apply"],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )
        post_close_results["tca"] = "ok" if r.returncode == 0 else f"exit:{r.returncode}"
    except Exception as e:
        post_close_results["tca"] = f"error: {str(e)[:100]}"

    # Thesis review (outcome comparison → trade_thesis_outcomes)
    try:
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"),
             str(PROJECT_ROOT / "scripts/post_trade_thesis_reviewer.py"), "--apply"],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT),
        )
        post_close_results["thesis_review"] = "ok" if r.returncode == 0 else f"exit:{r.returncode}"
    except Exception as e:
        post_close_results["thesis_review"] = f"error: {str(e)[:100]}"

    # Scored thesis review → trade_thesis_reviews (feeds journal-learning view). Separate from
    # the outcome reviewer above; this is the scored/lesson lane that had no scheduled runner.
    # Idempotent: get_reviewable skips trades that already have a review (NOT EXISTS), so this
    # only writes the just-closed trade (+ any un-reviewed backlog, bounded LIMIT 100).
    try:
        r = subprocess.run(
            [str(PROJECT_ROOT / ".venv/bin/python"),
             str(PROJECT_ROOT / "scripts/trade_thesis_review_engine.py"), "--apply", "--json"],
            capture_output=True, text=True, timeout=180, cwd=str(PROJECT_ROOT),
        )
        post_close_results["thesis_review_scored"] = "ok" if r.returncode == 0 else f"exit:{r.returncode}"
    except Exception as e:
        post_close_results["thesis_review_scored"] = f"error: {str(e)[:100]}"

    return post_close_results


def close_paper_trade(conn, paper_trade_id=None, symbol=None, reason="manual", dry_run=False):
    """Close a paper trade via Alpaca paper."""

    # Safety checks
    if LIVE_TRADING_ENABLED:
        return {"status": "blocked", "error": "LIVE_TRADING_ENABLED is true -- closer blocked"}
    if ALPACA_MODE != "paper":
        return {"status": "blocked", "error": f"ALPACA_MODE={ALPACA_MODE}, must be 'paper'"}

    cur = conn.cursor()

    # Find the trade
    if paper_trade_id:
        cur.execute("""
            SELECT * FROM paper_trades WHERE id = %s AND status IN ('open', 'pending', 'submitted')
        """, [paper_trade_id])
    elif symbol:
        cur.execute("""
            SELECT * FROM paper_trades
            WHERE symbol = %s AND status IN ('open', 'pending', 'submitted')
              AND account = 'ALPACA_PAPER'
            ORDER BY created_at DESC LIMIT 1
        """, [symbol.upper()])
    else:
        return {"status": "error", "error": "Specify --paper-trade-id or --symbol"}

    trade = cur.fetchone()
    if not trade:
        return {"status": "error", "error": f"No open paper trade found for {'#' + str(paper_trade_id) if paper_trade_id else symbol}"}

    trade_id = trade["id"]
    sym = trade["symbol"]
    entry_price = float(trade.get("entry_price") or trade.get("planned_entry") or 0)
    shares = int(trade.get("shares") or 0)
    stop_loss = float(trade.get("stop_loss") or 0)

    if dry_run:
        log.info(f"[dry-run] Would close paper trade #{trade_id} ({sym})")
        return {
            "status": "dry_run",
            "paper_trade_id": trade_id,
            "symbol": sym,
            "entry_price": entry_price,
            "shares": shares,
            "reason": reason,
            "message": f"Would close {sym} #{trade_id} -- use --close-paper to execute",
        }

    # Load adapter and close position
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        adapter = AlpacaPaperAdapter()
    except Exception as e:
        return {"status": "error", "error": f"Failed to load adapter: {e}"}

    _write_execution_event(conn, trade_id, sym, "CLOSE_INITIATED", {
        "reason": reason,
        "entry_price": entry_price,
        "shares": shares,
    })

    # Close in Alpaca
    close_result = {"status": "skipped", "message": "Adapter not enabled"}
    if adapter.enabled:
        close_result = _close_alpaca_position(adapter, sym)
        log.info(f"Alpaca close result for {sym}: {close_result['status']}")

    # Get exit price from close result or current price
    exit_price = 0
    if close_result.get("data"):
        # The close position API doesn't return a price directly, check positions
        try:
            price_data = close_result["data"]
            if isinstance(price_data, dict):
                exit_price = float(price_data.get("current_price", 0))
        except Exception:
            pass

    if exit_price == 0:
        # Try to get from current_price on the trade
        exit_price = float(trade.get("current_price") or 0)

    # Compute PnL
    now = datetime.now(timezone.utc)
    pnl = round((exit_price - entry_price) * shares, 2) if exit_price > 0 and entry_price > 0 else None
    pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2) if exit_price > 0 and entry_price > 0 else None
    risk_per_share = abs(entry_price - stop_loss) if stop_loss > 0 else 0
    r_multiple = round((exit_price - entry_price) / risk_per_share, 2) if risk_per_share > 0 and exit_price > 0 else None

    entry_time = trade.get("entry_time") or trade.get("created_at")
    hold_time_min = round((now - entry_time).total_seconds() / 60, 1) if entry_time else None

    from trade_outcome_helpers import classify_verdict
    verdict = classify_verdict(pnl)

    # Update paper_trades
    cur.execute("""
        UPDATE paper_trades SET
            exit_price = %s,
            exit_time = %s,
            exit_reason = %s,
            pnl = %s,
            pnl_pct = %s,
            hold_time_min = %s,
            outcome_verdict = %s,
            status = 'closed',
            lifecycle_state = 'closed',
            closed_at = %s,
            closed_via = 'paper_trade_closer',
            updated_at = %s
        WHERE id = %s
    """, [exit_price if exit_price > 0 else None, now, reason, pnl, pnl_pct,
          hold_time_min, verdict, now, now, trade_id])
    conn.commit()

    _write_execution_event(conn, trade_id, sym, "TRADE_CLOSED", {
        "exit_price": exit_price,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
        "verdict": verdict,
        "reason": reason,
        "alpaca_close_result": close_result.get("status"),
    })

    # Run post-close pipeline
    post_close = _run_post_close(trade_id, sym)

    # Trigger agent curation hooks for journal entry generation
    try:
        from agent_curation_hooks import on_paper_trade_closed
        on_paper_trade_closed(conn, trade_id)
        log.info(f"[{sym}] Post-trade analysis hooks triggered")
    except Exception as _hook_err:
        log.warning(f"[{sym}] Post-trade hooks failed (non-fatal): {_hook_err}")

    return {
        "status": "closed",
        "paper_trade_id": trade_id,
        "symbol": sym,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "shares": shares,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
        "verdict": verdict,
        "hold_time_min": hold_time_min,
        "reason": reason,
        "alpaca_close": close_result.get("status"),
        "post_close": post_close,
    }


def main():
    parser = argparse.ArgumentParser(description="Paper trade closer")
    parser.add_argument("--paper-trade-id", type=int, help="Trade ID to close")
    parser.add_argument("--symbol", type=str, help="Symbol to close")
    parser.add_argument("--dry-run", action="store_true", help="Preview without closing")
    parser.add_argument("--close-paper", action="store_true",
                        help="Required flag to actually close a paper trade")
    parser.add_argument("--reason", type=str, default="manual", help="Close reason")
    args = parser.parse_args()

    if not args.paper_trade_id and not args.symbol:
        parser.error("Specify --paper-trade-id or --symbol")

    if not args.dry_run and not args.close_paper:
        parser.error("Use --close-paper to confirm paper trade close, or --dry-run to preview")

    conn = get_db()
    try:
        result = close_paper_trade(
            conn,
            paper_trade_id=args.paper_trade_id,
            symbol=args.symbol,
            reason=args.reason,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
