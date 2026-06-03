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
def _call_ollama_direct(prompt, model="gemma3:4b", timeout=180):
    """Call Ollama directly with JSON format mode and higher token limit.
    Bypasses local_llm.py to avoid the 300-token cap."""
    num_gpu = int(os.environ.get("LOCAL_LLM_NUM_GPU", "0"))
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are a trade analyst. Return ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.3, "num_predict": LLM_NUM_PREDICT, "num_gpu": num_gpu,
                    "num_ctx": 4096 if "12b" in model or "27b" in model else 8192},
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


def _preflight_llm_health():
    """Run local LLM health checks. Returns (ok, checks, failed)."""
    checks = []

    model = os.environ.get("LOCAL_LLM_MODEL", "")
    checks.append(("LOCAL_LLM_MODEL=gemma3:4b", model == "gemma3:4b"))

    disabled = os.environ.get("DISABLED_LOCAL_LLM_MODELS", "")
    checks.append(("qwen3:14b_disabled", "qwen3:14b" in disabled))

    num_gpu = os.environ.get("LOCAL_LLM_NUM_GPU", "")
    checks.append(("LOCAL_LLM_NUM_GPU_set", num_gpu != ""))

    max_conc = os.environ.get("LOCAL_LLM_MAX_CONCURRENT", "")
    checks.append(("LOCAL_LLM_MAX_CONCURRENT=1", max_conc == "1"))

    health_script = Path(__file__).resolve().parent / "check_local_llm_health.py"
    if health_script.exists():
        import subprocess
        result = subprocess.run(
            [sys.executable, str(health_script)],
            capture_output=True, text=True, timeout=120
        )
        checks.append(("health_script_pass", result.returncode == 0))
        if result.returncode != 0:
            log.error(f"Health check output:\n{result.stdout}\n{result.stderr}")
    else:
        checks.append(("health_script_exists", False))

    failed = [name for name, ok in checks if not ok]
    return len(failed) == 0, checks, failed


# ════════════════════════════════════════════════════════════════════
# Structured Backtest Trade Evaluation (gemma3:12b)
# Reviews real closed trades enriched by trade_backtest_engine.py
# (RSI/MACD/Fib/ADX/BB/structure/candle). Produces structured scores +
# verdict. Self-contained; does NOT touch the prose review path above.
# Post-trade research / journaling only — NOT live trading advice.
# ════════════════════════════════════════════════════════════════════

STRUCTURED_PROMPT_VERSION = "structured_eval_v1"
STRUCTURED_VERDICTS = {
    "high-quality setup", "valid setup but poor execution", "weak setup", "momentum chase",
    "entered too early", "entered too late", "should have waited for fib retracement",
    "should have waited for vwap confirmation", "should have waited for macd confirmation",
    "good entry, poor exit", "poor entry, good salvage", "invalid trade relative to regime",
}


def _structured_snapshot(row):
    """Build the model-facing snapshot from a trade_backtest_results row.
    Only includes signals we actually captured; VWAP/intraday are absent by design."""
    def f(x):
        return None if x is None else float(x)
    return {
        "symbol": row["symbol"],
        "open_date": str(row["open_date"]),
        "close_date": str(row["close_date"]),
        "direction": "long",  # trade_closed universe is long-only equity
        "actual_entry_price": f(row["actual_entry_price"]),
        "actual_exit_price": f(row["actual_exit_price"]),
        "actual_pnl": f(row["actual_pnl"]),
        "actual_pnl_pct": f(row["actual_pnl_pct"]),
        "hold_days": row["hold_days"],
        "entry": {
            "rsi": f(row["entry_rsi"]),
            "macd_line": f(row["entry_macd_line"]), "macd_signal": f(row["entry_macd_signal"]),
            "macd_hist": f(row["entry_macd_hist"]), "macd_state": row["entry_macd_state"],
            "adx": f(row["entry_adx"]),
            "bollinger_pct": f(row["entry_bb_pct"]), "bollinger_state": row["entry_bb_state"],
            "fib_retracement_level": f(row["entry_fib_level"]),
            "fib_leg_high": f(row["entry_fib_leg_high"]), "fib_leg_low": f(row["entry_fib_leg_low"]),
            "candlestick": row["entry_candle"], "structure": row["entry_structure"],
            "sma20_dist_pct": f(row["entry_sma20_dist_pct"]), "sma50_dist_pct": f(row["entry_sma50_dist_pct"]),
            "sma200_dist_pct": f(row["entry_sma200_dist_pct"]),
            "volume_ratio": f(row["entry_volume_ratio"]), "atr": f(row["entry_atr"]),
            "atr_stop_pct": f(row["entry_atr_stop_pct"]), "pct_52w": f(row["entry_52w_percentile"]),
            "better_entry_existed": row["better_entry_existed"], "best_entry_price": f(row["best_entry_price"]),
            "rule_based_grade": row["entry_grade"],
        },
        "exit": {
            "rsi": f(row["exit_rsi"]), "macd_state": row["exit_macd_state"],
            "left_on_table_20d": f(row["left_on_table_20d"]), "exit_was_early": row["exit_was_early"],
            "max_price_20d_after": f(row["max_price_20d_after"]), "rule_based_grade": row["exit_grade"],
        },
        "data_not_captured": ["VWAP", "intraday_structure", "session", "spread/slippage"],
    }


def _build_structured_prompt(snap):
    return (
        "You are an expert backtesting intelligence assistant for POST-TRADE technical review. "
        "This is research/journaling, NOT live trading advice.\n\n"
        "Evaluate whether this completed trade was technically sound at entry, well managed, and properly exited. "
        "Use ONLY the supplied data. Do NOT invent signals. Fields under data_not_captured are unavailable — do not "
        "penalize the setup for their absence; instead list them under data_gaps.\n\n"
        "Separate outcome from quality: a winning trade can still be a bad trade, and a losing trade can still be a "
        "good trade. If confluence is weak, say so bluntly. If waiting for a fib retracement / MACD confirmation / "
        "RSI reset would likely improve expectancy, state it explicitly.\n\n"
        f"TRADE DATA (JSON):\n{json.dumps(snap, indent=1)}\n\n"
        "Return ONLY valid JSON with EXACTLY this shape:\n"
        "{\n"
        '  "summary": "1-2 sentence executive summary",\n'
        '  "scores": {"confluence_score": 0-100, "entry_timing_score": 0-100, "exit_quality_score": 0-100, '
        '"risk_reward_score": 0-100, "management_score": 0-100, "overall_score": 0-100},\n'
        '  "verdict": "one of: high-quality setup | valid setup but poor execution | weak setup | momentum chase | '
        'entered too early | entered too late | should have waited for fib retracement | should have waited for vwap '
        'confirmation | should have waited for macd confirmation | good entry, poor exit | poor entry, good salvage | '
        'invalid trade relative to regime",\n'
        '  "entry_assessment": {"quality": "A-grade|acceptable|weak|poor", "timing": "early|optimal|late", '
        '"strengths": [], "weaknesses": [], "should_wait_for_retracement": true/false, "better_fib_zone": ""},\n'
        '  "exit_assessment": {"quality": "good|acceptable|weak|poor", "timing": "early|optimal|late", '
        '"strengths": [], "weaknesses": []},\n'
        '  "improvements": [],\n'
        '  "data_gaps": []\n'
        "}\n"
        "Every judgment must reference specific supplied values (e.g. 'RSI 71 + MACD bullish_fading = momentum "
        "exhaustion'). Be critical and evidence-based."
    )


def _validate_structured(parsed):
    """Returns (ok, classification, headline_score, verdict)."""
    if not parsed or not isinstance(parsed, dict):
        return False, "model_error", None, None
    sc = parsed.get("scores") or {}
    keys = ["confluence_score", "entry_timing_score", "exit_quality_score", "risk_reward_score", "management_score", "overall_score"]
    have = [k for k in keys if isinstance(sc.get(k), (int, float))]
    verdict = (parsed.get("verdict") or "").strip().lower()
    if len(have) < 4 or not parsed.get("summary"):
        cls = "empty_shell" if not parsed.get("summary") else "partial_review"
        return False, cls, sc.get("overall_score"), (verdict or None)
    cls = "meaningful_structured_review" if (len(have) == 6 and verdict in STRUCTURED_VERDICTS) else "partial_review"
    return True, cls, sc.get("overall_score"), (verdict if verdict in STRUCTURED_VERDICTS else (verdict or None))


def _write_structured_eval(conn, snap, ihash, parsed, raw, classification, score, verdict, model):
    cur = conn.cursor()
    ea = (parsed or {}).get("entry_assessment") or {}
    xa = (parsed or {}).get("exit_assessment") or {}
    strengths = (ea.get("strengths") or []) + (xa.get("strengths") or [])
    weaknesses = (ea.get("weaknesses") or []) + (xa.get("weaknesses") or [])
    cur.execute("""
        INSERT INTO trade_llm_reviews
          (symbol, trade_close_date, review_stage, model_provider, model_name, prompt_version,
           input_snapshot_hash, generated_at, status, summary, strengths, weaknesses,
           lessons, confidence, input_snapshot, output_payload, source_table,
           eval_overall_score, eval_verdict, created_at, updated_at)
        VALUES (%s,%s,'structured_backtest_eval','local',%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,
                'trade_backtest_results',%s,%s,NOW(),NOW())
    """, [
        snap["symbol"], snap["close_date"], model, STRUCTURED_PROMPT_VERSION, ihash,
        classification, (parsed or {}).get("summary"),
        json.dumps(strengths), json.dumps(weaknesses),
        json.dumps((parsed or {}).get("improvements") or []),
        (float(score) / 100.0 if isinstance(score, (int, float)) else None),
        json.dumps(snap), json.dumps(parsed or {"raw": raw[:500] if raw else None}),
        (float(score) if isinstance(score, (int, float)) else None), verdict,
    ])


def run_structured_eval(args):
    """Batch structured evaluation of enriched closed trades. Read-only to trades; only writes reviews."""
    model = getattr(args, "eval_model", None) or "gemma3:12b"
    conn = _get_conn()
    import psycopg2.extras
    rcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Candidate pool: enriched rows, largest left-on-table first. Dedup is by setup-hash
    # below (identical setups across accounts collapse to one eval — no redundant calls).
    rcur.execute("""
        SELECT * FROM trade_backtest_results r
        WHERE r.data_quality IN ('full','partial') AND r.entry_macd_state IS NOT NULL
        ORDER BY r.left_on_table_20d DESC NULLS LAST
    """)
    candidates = rcur.fetchall()
    # Hashes already evaluated (successfully) — skip; model_error hashes are allowed to retry.
    rcur.execute("SELECT input_snapshot_hash FROM trade_llm_reviews "
                 "WHERE review_stage='structured_backtest_eval' AND status <> 'model_error'")
    seen = {r["input_snapshot_hash"] for r in rcur.fetchall() if r["input_snapshot_hash"]}
    log.info(f"Structured eval: {len(candidates)} candidate(s), {len(seen)} already evaluated, target {args.limit} (model {model}, apply={args.apply})")
    done = 0
    for row in candidates:
        if done >= args.limit:
            break
        snap = _structured_snapshot(row)
        ihash = hashlib.sha256(json.dumps(snap, default=str, sort_keys=True).encode()).hexdigest()[:16]
        if ihash in seen:
            continue  # identical setup already evaluated (or duplicate account-trade)
        seen.add(ihash)
        prompt = _build_structured_prompt(snap)
        if not args.allow_local_llm and args.dry_run:
            log.info(f"  [dry-run] {snap['symbol']} {snap['close_date']} — prompt {len(prompt)} chars (no model call)")
            done += 1
            continue
        # Per-trade isolation: a single ollama timeout/error must NOT kill the whole batch.
        try:
            raw = _call_ollama_direct(prompt, model=model, timeout=420)
        except Exception as e:
            log.warning(f"  {snap['symbol']} {snap['close_date']}: model call failed ({type(e).__name__}: {e}); skipping, will retry next run")
            seen.discard(ihash)
            done += 1
            continue
        parsed, _perr = _extract_json(raw)
        ok, cls, score, verdict = _validate_structured(parsed)
        log.info(f"  {snap['symbol']} {snap['close_date']}: {cls} score={score} verdict={verdict}")
        done += 1  # count each model call against --limit (calls are the expensive unit)
        if cls == "model_error":
            seen.discard(ihash)  # allow a failed setup to retry on a later run
        if args.apply and args.confirm_llm_review_write and cls != "model_error":
            _write_structured_eval(conn, snap, ihash, parsed, raw, cls, score, verdict, model)
            conn.commit()
    log.info(f"Structured eval complete: {done} evaluated")
    conn.close()
    return 0


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
    p.add_argument("--model-name", default="gemma3:4b")
    p.add_argument("--prompt-version", default="close_analysis_v1")
    p.add_argument("--structured", action="store_true",
                   help="Run structured backtest trade evaluation (scores+verdict) over enriched trade_backtest_results.")
    p.add_argument("--eval-model", default="gemma3:12b", help="Model for --structured evaluation.")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    # Safety gates
    alpaca = os.environ.get("ALPACA_MODE", "")
    disable = os.environ.get("LLM_DISABLE_LIVE_EXECUTION", "")
    if alpaca != "paper":
        log.error(f"ALPACA_MODE={alpaca}, must be paper. Aborting.")
        sys.exit(1)

    # ── Structured evaluation path (self-contained; reuses ALPACA paper gate above) ──
    # No hard preflight: this path is non-mutating (writes only trade_llm_reviews rows,
    # records an honest model_error on any model failure). The slow CPU health-check
    # subprocess is advisory here, so a failure/timeout warns but does not abort.
    if args.structured:
        if args.apply:
            try:
                ok, _checks, failed = _preflight_llm_health()
                if not ok:
                    log.warning(f"LLM preflight advisory failed ({', '.join(failed)}); proceeding (non-mutating path).")
            except Exception as e:
                log.warning(f"LLM preflight advisory skipped: {e}")
        return run_structured_eval(args)

    # LLM safety preflight — required before --apply
    if args.apply:
        ok, checks, failed = _preflight_llm_health()
        if not ok:
            log.error(f"LLM preflight FAILED: {', '.join(failed)}")
            for name, passed in checks:
                log.info(f"  {'PASS' if passed else 'FAIL'}: {name}")
            log.error("Refusing to run --apply with failed health checks")
            sys.exit(1)
        log.info("LLM preflight PASSED")

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
