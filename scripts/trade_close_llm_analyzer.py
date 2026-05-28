#!/usr/bin/env python3
"""trade_close_llm_analyzer.py v4.1 — Local LLM close-of-trade analysis.

Supports both paper_trades and strategy_backtest_trades via --source flag.

Default: --dry-run (no model call, no DB write).
--dry-run --allow-local-llm: calls local model, logs only.
--apply --confirm-llm-review-write: writes trade_llm_reviews row.

v4.1 changes (close_analysis_v2):
- Direct Ollama call with num_predict=2048, format=json
- JSON parser: extracts from fences, validates keys, fills defaults
- Quality classifier: meaningful_structured_review / partial_review / empty_shell / model_error
- Structured DB writes: maps parsed JSON to assessment columns

Safety: local model only, no Grok, no broker/trade mutations.
"""
import argparse, hashlib, json, logging, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [llm-analyzer] %(message)s")
log = logging.getLogger("llm_analyzer")

# Ollama direct call config
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = OLLAMA_BASE.rstrip("/") + "/api/chat"
LLM_NUM_PREDICT = 2048

# Required keys for a meaningful review
REQUIRED_KEYS = {"summary", "thesis_assessment", "execution_assessment", "stop_assessment"}
OPTIONAL_KEYS = {
    "tca_assessment": None, "post_close_assessment": None, "backtest_comparison": None,
    "strengths": [], "weaknesses": [], "lessons": [], "confidence": 0.0,
    "data_quality_gaps": [], "facts": [], "inferences": [],
    "safety": {"analysis_only": True, "orders_recommended": False, "broker_actions": False, "strategy_changes": False},
}


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

    cur = conn.cursor()
    cur.execute("SELECT id, strategy_id, signal_score, signal_decision FROM paper_trade_proposals WHERE symbol=%s ORDER BY created_at DESC LIMIT 3", [sym])
    proposals = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    cur.execute("SELECT event_type, payload, event_ts FROM lifecycle_events WHERE paper_trade_id=%s AND stage='stop_change' ORDER BY event_ts", [tid])
    stop_audit = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    cur.execute("SELECT * FROM paper_execution_quality WHERE paper_trade_id=%s LIMIT 1", [tid])
    tca_cols = [d[0] for d in cur.description] if cur.description else []
    tca_row = cur.fetchone()
    tca = dict(zip(tca_cols, tca_row)) if tca_row else None

    return {
        "trade": trade_data, "proposals": proposals, "stop_audit": stop_audit,
        "tca": tca, "symbol": sym, "paper_trade_id": tid,
    }


def _build_backtest_input(conn, backtest_trade_id=None, symbol=None, limit=1):
    """Build input snapshots from strategy_backtest_trades."""
    cur = conn.cursor()
    if backtest_trade_id:
        cur.execute("SELECT * FROM strategy_backtest_trades WHERE id=%s", [backtest_trade_id])
    elif symbol:
        cur.execute("SELECT * FROM strategy_backtest_trades WHERE symbol=%s ORDER BY id DESC LIMIT %s", [symbol, limit])
    else:
        cur.execute("""
            SELECT sbt.* FROM strategy_backtest_trades sbt
            LEFT JOIN trade_llm_reviews tlr
              ON tlr.backtest_trade_id = sbt.id AND tlr.source_table = 'strategy_backtest_trades'
            WHERE tlr.id IS NULL
            ORDER BY sbt.id LIMIT %s
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
            "trade": trade_data, "proposals": [], "stop_audit": [], "tca": None,
            "symbol": sym, "backtest_trade_id": tid, "paper_trade_id": None,
            "source_table": "strategy_backtest_trades", "strategy_id": strategy,
        })
    return snapshots


def _hash_input(snapshot):
    return hashlib.sha256(json.dumps(snapshot, default=str, sort_keys=True).encode()).hexdigest()[:16]


# ── JSON Parser ──────────────────────────────────────────────────────
def _extract_json(raw_text):
    """Extract JSON object from model response. Handles pure JSON, markdown fences, and surrounding prose."""
    if not raw_text or not raw_text.strip():
        return None, "empty_response"

    text = raw_text.strip()

    # Try 1: pure JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, None
    except json.JSONDecodeError:
        pass

    # Try 2: markdown fences ```json ... ``` or ``` ... ```
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if fence_match:
        try:
            obj = json.loads(fence_match.group(1).strip())
            if isinstance(obj, dict):
                return obj, None
        except json.JSONDecodeError:
            pass

    # Try 3: find first { ... } block
    brace_start = text.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[brace_start:i+1])
                        if isinstance(obj, dict):
                            return obj, None
                    except json.JSONDecodeError:
                        break

    return None, "json_parse_failed"


def _validate_and_fill(parsed):
    """Validate required keys, fill optional defaults. Returns (filled_dict, missing_required)."""
    if not parsed or not isinstance(parsed, dict):
        return None, list(REQUIRED_KEYS)

    missing = [k for k in REQUIRED_KEYS if not parsed.get(k)]

    # Fill optional keys with defaults
    for key, default in OPTIONAL_KEYS.items():
        if key not in parsed or parsed[key] is None:
            parsed[key] = default if not isinstance(default, (list, dict)) else (default.copy() if isinstance(default, dict) else list(default))

    return parsed, missing


def _classify_quality(parsed, missing_required, parse_error):
    """Classify review quality."""
    if parse_error:
        return "model_error" if parse_error == "empty_response" else "empty_shell"
    if not parsed:
        return "empty_shell"
    if len(missing_required) == 0:
        has_lessons = bool(parsed.get("lessons"))
        has_two_assessments = sum(1 for k in ["thesis_assessment", "execution_assessment", "stop_assessment", "tca_assessment"]
                                  if parsed.get(k)) >= 2
        if has_lessons and has_two_assessments:
            return "meaningful_structured_review"
        return "partial_review"
    if len(missing_required) <= 2:
        return "partial_review"
    return "missing_data"


# ── Direct Ollama Call ───────────────────────────────────────────────
def _call_ollama_direct(prompt, model="qwen3:14b", timeout=180):
    """Call Ollama directly with JSON format mode and higher token limit.
    Bypasses local_llm.py to avoid the 300-token cap."""
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are a trade analyst. Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.3, "num_predict": LLM_NUM_PREDICT, "num_gpu": 0},
    }).encode()

    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "").strip()
        duration = round(data.get("total_duration", 0) / 1e9, 1)
        tokens = data.get("eval_count", 0)
        log.info(f"Ollama direct: {duration}s, {tokens} tokens, {len(text)} chars")
        return text if text else None


# ── DB Writer ────────────────────────────────────────────────────────
def _write_review_row(conn, snapshot, input_hash, args, parsed_output, raw_output, classification, model_error=None):
    """Write a trade_llm_reviews row with structured field mapping."""
    cur = conn.cursor()

    summary = (parsed_output or {}).get("summary", f"LLM review for {snapshot['symbol']}")
    status_map = {
        "meaningful_structured_review": "complete",
        "partial_review": "partial",
        "missing_data": "missing_data",
        "empty_shell": "error",
        "model_error": "error",
    }
    status = status_map.get(classification, "error")

    cur.execute("""
        INSERT INTO trade_llm_reviews
            (paper_trade_id, backtest_trade_id, source_table, symbol, review_stage,
             prompt_version, model_name, model_provider,
             input_snapshot_hash, output_payload, summary, status,
             thesis_assessment, execution_assessment, stop_assessment, tca_assessment,
             post_close_assessment, backtest_comparison,
             strengths, weaknesses, lessons, confidence, data_quality_gaps,
             error_message, created_at)
        VALUES (%s, %s, %s, %s, 'close_analysis',
                %s, %s, 'local',
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, now())
        RETURNING id
    """, [
        snapshot.get("paper_trade_id"),
        snapshot.get("backtest_trade_id"),
        snapshot.get("source_table", "paper_trades"),
        snapshot["symbol"],
        args.prompt_version,
        args.model_name,
        input_hash,
        json.dumps(parsed_output or raw_output, default=str) if (parsed_output or raw_output) else None,
        summary,
        status,
        (parsed_output or {}).get("thesis_assessment"),
        (parsed_output or {}).get("execution_assessment"),
        (parsed_output or {}).get("stop_assessment"),
        (parsed_output or {}).get("tca_assessment"),
        (parsed_output or {}).get("post_close_assessment"),
        (parsed_output or {}).get("backtest_comparison"),
        json.dumps((parsed_output or {}).get("strengths", [])),
        json.dumps((parsed_output or {}).get("weaknesses", [])),
        json.dumps((parsed_output or {}).get("lessons", [])),
        (parsed_output or {}).get("confidence"),
        json.dumps((parsed_output or {}).get("data_quality_gaps", [])),
        model_error,
    ])
    row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def main():
    p = argparse.ArgumentParser(description="LLM Close-of-Trade Analyzer v4.1")
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
            conn, backtest_trade_id=args.backtest_trade_id,
            symbol=args.symbol, limit=args.limit,
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

        raw_output = None
        parsed_output = None
        classification = None
        model_error = None

        if args.allow_local_llm:
            log.info(f"Calling local LLM for {snapshot['symbol']}...")
            try:
                # Build prompt
                prompt_path = PROJECT_ROOT / "scripts" / "prompts" / f"llm_backtesting_{args.prompt_version}.md"
                prompt_template = prompt_path.read_text() if prompt_path.exists() else "Analyze this trade and return JSON: {trade_json}"
                prompt = prompt_template.replace("{trade_json}", json.dumps(snapshot["trade"], default=str))
                prompt = prompt.replace("{proposal_json}", json.dumps(snapshot.get("proposals", []), default=str))
                prompt = prompt.replace("{stop_audit_json}", json.dumps(snapshot.get("stop_audit", []), default=str))
                prompt = prompt.replace("{tca_json}", json.dumps(snapshot.get("tca"), default=str))
                prompt = prompt.replace("{trace_json}", "{}")

                # Direct Ollama call with JSON format mode and 2048 tokens
                raw_output = _call_ollama_direct(prompt, model=args.model_name, timeout=180)
                result["model_called"] = True

                if raw_output:
                    parsed_output, parse_error = _extract_json(raw_output)
                    if parsed_output:
                        parsed_output, missing = _validate_and_fill(parsed_output)
                        classification = _classify_quality(parsed_output, missing, None)
                        if missing:
                            log.warning(f"Missing required keys: {missing}")
                    else:
                        classification = _classify_quality(None, [], parse_error)
                        model_error = parse_error
                        log.warning(f"JSON parse failed: {parse_error}")
                else:
                    classification = "model_error"
                    model_error = "empty_response"
                    log.warning("Model returned empty response")

                result["model_output_preview"] = str(raw_output)[:500] if raw_output else "empty"
                result["classification"] = classification
                result["parsed_fields"] = list((parsed_output or {}).keys())
                result["status"] = f"dry_run_with_model_{classification}" if args.dry_run else classification
                log.info(f"Classification: {classification}")

            except Exception as e:
                result["model_called"] = True
                result["model_error"] = str(e)
                model_error = str(e)
                classification = "model_error"
                result["classification"] = classification
                result["status"] = "model_error"
                log.warning(f"Model call failed: {e}")

        # Write DB row in --apply mode
        if args.apply and args.confirm_llm_review_write:
            try:
                row_id = _write_review_row(conn, snapshot, input_hash, args, parsed_output, raw_output, classification, model_error)
                result["db_row_written"] = True
                result["review_row_id"] = row_id
                log.info(f"Review row #{row_id} written for {snapshot['symbol']} ({classification})")
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
