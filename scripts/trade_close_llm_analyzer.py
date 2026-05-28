#!/usr/bin/env python3
"""trade_close_llm_analyzer.py v4.0 — Local LLM close-of-trade analysis.

Supports both paper_trades and strategy_backtest_trades via --source flag.

Default: --dry-run (no model call, no DB write).
--dry-run --allow-local-llm: calls local model, logs only.
--apply --confirm-llm-review-write: writes trade_llm_reviews row.

Safety: local model only, no Grok, no broker/trade mutations.
"""
import argparse, hashlib, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [llm-analyzer] %(message)s")
log = logging.getLogger("llm_analyzer")


def _get_conn():
    from db_adapter import _get_conn as gc
    return gc()


def _build_input(conn, paper_trade_id=None, symbol=None):
    """Build input snapshot for a closed trade."""
    if paper_trade_id:
        trade = conn.cursor()
        trade.execute("SELECT * FROM paper_trades WHERE id=%s", [paper_trade_id])
        cols = [d[0] for d in trade.description]
        row = trade.fetchone()
        trade_data = dict(zip(cols, row)) if row else None
    elif symbol:
        trade = conn.cursor()
        trade.execute("SELECT * FROM paper_trades WHERE symbol=%s AND (exit_time IS NOT NULL OR (exit_reason IS NOT NULL AND exit_reason!='')) ORDER BY id DESC LIMIT 1", [symbol])
        cols = [d[0] for d in trade.description]
        row = trade.fetchone()
        trade_data = dict(zip(cols, row)) if row else None
    else:
        return None

    if not trade_data:
        return None

    tid = trade_data.get("id")
    sym = trade_data.get("symbol")

    # Proposals
    cur = conn.cursor()
    cur.execute("SELECT id, strategy_id, signal_score, signal_decision FROM paper_trade_proposals WHERE symbol=%s ORDER BY created_at DESC LIMIT 3", [sym])
    proposals = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    # Stop audit
    cur.execute("SELECT event_type, payload, event_ts FROM lifecycle_events WHERE paper_trade_id=%s AND stage='stop_change' ORDER BY event_ts", [tid])
    stop_audit = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    # TCA
    cur.execute("SELECT * FROM paper_execution_quality WHERE paper_trade_id=%s LIMIT 1", [tid])
    tca_cols = [d[0] for d in cur.description] if cur.description else []
    tca_row = cur.fetchone()
    tca = dict(zip(tca_cols, tca_row)) if tca_row else None

    return {
        "trade": trade_data,
        "proposals": proposals,
        "stop_audit": stop_audit,
        "tca": tca,
        "symbol": sym,
        "paper_trade_id": tid,
    }


def _build_backtest_input(conn, backtest_trade_id=None, symbol=None, limit=1):
    """Build input snapshots from strategy_backtest_trades."""
    cur = conn.cursor()
    if backtest_trade_id:
        cur.execute("SELECT * FROM strategy_backtest_trades WHERE id=%s", [backtest_trade_id])
    elif symbol:
        cur.execute("SELECT * FROM strategy_backtest_trades WHERE symbol=%s ORDER BY id DESC LIMIT %s", [symbol, limit])
    else:
        # Batch mode: find unreviewed backtest trades
        cur.execute("""
            SELECT sbt.* FROM strategy_backtest_trades sbt
            LEFT JOIN trade_llm_reviews tlr
              ON tlr.backtest_trade_id = sbt.id AND tlr.source_table = 'strategy_backtest_trades'
            WHERE tlr.id IS NULL
            ORDER BY sbt.id
            LIMIT %s
        """, [limit])

    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    if not rows:
        return []

    snapshots = []
    for row in rows:
        trade_data = dict(zip(cols, row))
        tid = trade_data.get("id")
        sym = trade_data.get("symbol")
        strategy = trade_data.get("strategy_id", "")

        snapshots.append({
            "trade": trade_data,
            "proposals": [],
            "stop_audit": [],
            "tca": None,
            "symbol": sym,
            "backtest_trade_id": tid,
            "paper_trade_id": None,
            "source_table": "strategy_backtest_trades",
            "strategy_id": strategy,
        })

    return snapshots


def _hash_input(snapshot):
    return hashlib.sha256(json.dumps(snapshot, default=str, sort_keys=True).encode()).hexdigest()[:16]


def _write_review_row(conn, snapshot, input_hash, args, model_output=None, model_error=None):
    """Write a trade_llm_reviews row for --apply mode."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trade_llm_reviews
            (paper_trade_id, backtest_trade_id, source_table, symbol, review_stage,
             prompt_version, model_name, model_provider,
             input_snapshot_hash, output_payload, summary, status, error_message, created_at)
        VALUES (%s, %s, %s, %s, 'close_analysis',
                %s, %s, 'local',
                %s, %s, %s, %s, %s, now())
        RETURNING id
    """, [
        snapshot.get("paper_trade_id"),
        snapshot.get("backtest_trade_id"),
        snapshot.get("source_table", "paper_trades"),
        snapshot["symbol"],
        args.prompt_version,
        args.model_name,
        input_hash,
        json.dumps(model_output, default=str) if model_output else None,
        f"LLM review for {snapshot['symbol']}",
        "dry_run" if args.dry_run else "complete",
        model_error,
    ])
    row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def main():
    p = argparse.ArgumentParser(description="LLM Close-of-Trade Analyzer v4.0")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--allow-local-llm", action="store_true")
    p.add_argument("--confirm-llm-review-write", action="store_true")
    p.add_argument("--paper-trade-id", type=int)
    p.add_argument("--backtest-trade-id", type=int)
    p.add_argument("--source", choices=["paper", "backtest"], default="paper",
                   help="Trade source: paper (paper_trades) or backtest (strategy_backtest_trades)")
    p.add_argument("--symbol", type=str)
    p.add_argument("--limit", type=int, default=1)
    p.add_argument("--json-out", type=str)
    p.add_argument("--model-name", default="qwen3:14b")
    p.add_argument("--prompt-version", default="close_analysis_v1")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    # Safety gates
    alpaca = os.environ.get("ALPACA_MODE", "")
    disable = os.environ.get("LLM_DISABLE_LIVE_EXECUTION", "")
    if alpaca != "paper":
        log.error(f"ALPACA_MODE={alpaca}, must be paper. Aborting.")
        sys.exit(1)

    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        sys.exit(1)

    # Build snapshots based on source
    if args.source == "backtest":
        snapshots = _build_backtest_input(
            conn,
            backtest_trade_id=args.backtest_trade_id,
            symbol=args.symbol,
            limit=args.limit,
        )
    else:
        snap = _build_input(conn, paper_trade_id=args.paper_trade_id, symbol=args.symbol)
        snapshots = [snap] if snap else []

    if not snapshots:
        log.warning(f"No eligible {args.source} trades found")
        result = {"status": "no_eligible_trade", "source": args.source, "dry_run": args.dry_run}
        if args.json_out:
            Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json_out).write_text(json.dumps(result, default=str, indent=2))
        print(json.dumps(result, default=str, indent=2))
        conn.close()
        return

    log.info(f"Processing {len(snapshots)} {args.source} trade(s)")
    all_results = []

    for snapshot in snapshots:
        input_hash = _hash_input(snapshot)
        trade_id = snapshot.get("backtest_trade_id") or snapshot.get("paper_trade_id")
        log.info(f"Trade: {snapshot['symbol']} #{trade_id} source={args.source} hash={input_hash}")

        result = {
            "status": "dry_run",
            "source": args.source,
            "symbol": snapshot["symbol"],
            "paper_trade_id": snapshot.get("paper_trade_id"),
            "backtest_trade_id": snapshot.get("backtest_trade_id"),
            "input_snapshot_hash": input_hash,
            "model_called": False,
            "db_row_written": False,
            "prompt_version": args.prompt_version,
            "model_name": args.model_name,
            "safety": {
                "alpaca_mode": alpaca,
                "llm_disable": disable,
                "orders_placed": "NONE",
                "broker_writes": "NONE",
                "model_provider": "local" if args.allow_local_llm else "none",
            },
        }

        model_output = None
        model_error = None

        if args.allow_local_llm:
            log.info(f"Calling local LLM for {snapshot['symbol']}...")
            try:
                from local_llm import generate as query_local_llm
                prompt_path = PROJECT_ROOT / "scripts" / "prompts" / f"llm_backtesting_{args.prompt_version}.md"
                prompt_template = prompt_path.read_text() if prompt_path.exists() else "Analyze this trade: {trade_json}"
                prompt = prompt_template.replace("{trade_json}", json.dumps(snapshot["trade"], default=str))
                prompt = prompt.replace("{proposal_json}", json.dumps(snapshot.get("proposals", []), default=str))
                prompt = prompt.replace("{stop_audit_json}", json.dumps(snapshot.get("stop_audit", []), default=str))
                prompt = prompt.replace("{tca_json}", json.dumps(snapshot.get("tca"), default=str))
                prompt = prompt.replace("{trace_json}", "{}")

                response = query_local_llm(prompt, timeout=120, fallback=False, caller="trade_close_llm_analyzer", process_type="BACKTEST_REVIEW")
                result["model_called"] = True
                result["model_output_preview"] = str(response)[:500] if response else "empty"
                model_output = response
                result["status"] = "dry_run_with_model" if args.dry_run else "complete"
                log.info(f"Model response received ({len(str(response))} chars)")
            except Exception as e:
                result["model_called"] = True
                result["model_error"] = str(e)
                model_error = str(e)
                result["status"] = "model_error"
                log.warning(f"Model call failed: {e}")

        # Write DB row in --apply mode
        if args.apply and args.confirm_llm_review_write:
            try:
                row_id = _write_review_row(conn, snapshot, input_hash, args, model_output, model_error)
                result["db_row_written"] = True
                result["review_row_id"] = row_id
                result["status"] = "complete" if model_output else "partial_review"
                log.info(f"Review row #{row_id} written for {snapshot['symbol']}")
            except Exception as e:
                result["db_write_error"] = str(e)
                log.error(f"DB write failed: {e}")

        all_results.append(result)

    # Output
    output = all_results if len(all_results) > 1 else all_results[0]
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, default=str, indent=2))

    print(json.dumps(output, default=str, indent=2))
    log.info(f"Done. Processed {len(all_results)} trade(s), source={args.source}")
    conn.close()


if __name__ == "__main__":
    main()
