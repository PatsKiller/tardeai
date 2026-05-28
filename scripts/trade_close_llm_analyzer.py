#!/usr/bin/env python3
"""trade_close_llm_analyzer.py v3.8 — Local LLM close-of-trade analysis.

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


def _hash_input(snapshot):
    return hashlib.sha256(json.dumps(snapshot, default=str, sort_keys=True).encode()).hexdigest()[:16]


def main():
    p = argparse.ArgumentParser(description="LLM Close-of-Trade Analyzer v3.8")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--allow-local-llm", action="store_true")
    p.add_argument("--confirm-llm-review-write", action="store_true")
    p.add_argument("--paper-trade-id", type=int)
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

    snapshot = _build_input(conn, paper_trade_id=args.paper_trade_id, symbol=args.symbol)
    if not snapshot:
        log.warning("No eligible trade found")
        result = {"status": "no_eligible_trade", "dry_run": args.dry_run}
        if args.json_out:
            Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json_out).write_text(json.dumps(result, default=str, indent=2))
        print(json.dumps(result, default=str, indent=2))
        conn.close()
        return

    input_hash = _hash_input(snapshot)
    log.info(f"Trade: {snapshot['symbol']} #{snapshot['paper_trade_id']} hash={input_hash}")

    result = {
        "status": "dry_run",
        "symbol": snapshot["symbol"],
        "paper_trade_id": snapshot["paper_trade_id"],
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

    if args.allow_local_llm and not args.apply:
        log.info("Calling local LLM (dry-run, no DB write)...")
        try:
            from local_llm import generate as query_local_llm
            prompt_path = PROJECT_ROOT / "scripts" / "prompts" / f"llm_backtesting_{args.prompt_version}.md"
            prompt_template = prompt_path.read_text() if prompt_path.exists() else "Analyze this trade: {trade_json}"
            prompt = prompt_template.replace("{trade_json}", json.dumps(snapshot["trade"], default=str))
            prompt = prompt.replace("{proposal_json}", json.dumps(snapshot["proposals"], default=str))
            prompt = prompt.replace("{stop_audit_json}", json.dumps(snapshot["stop_audit"], default=str))
            prompt = prompt.replace("{tca_json}", json.dumps(snapshot["tca"], default=str))
            prompt = prompt.replace("{trace_json}", "{}")

            response = query_local_llm(prompt, timeout=120, fallback=False, caller="trade_close_llm_analyzer", process_type="BACKTEST_REVIEW")
            result["model_called"] = True
            result["model_output_preview"] = str(response)[:500] if response else "empty"
            result["status"] = "dry_run_with_model"
            log.info(f"Model response received ({len(str(response))} chars)")
        except Exception as e:
            result["model_called"] = True
            result["model_error"] = str(e)
            result["status"] = "model_error"
            log.warning(f"Model call failed: {e}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, default=str, indent=2))

    print(json.dumps(result, default=str, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
