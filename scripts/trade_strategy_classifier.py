#!/usr/bin/env python3
"""trade_strategy_classifier.py — Classify unclassified trades using local LLM.

Reads trades without strategy_id from the unified trades view.
Uses local LLM to analyze trade characteristics and assign a strategy.
Updates the source table (trade_transactions paired trades or paper_trades).

Default: --dry-run (no DB writes).
--apply: writes strategy_id to strategy_backtest_trades and paired_trade_transactions.

Safety: local model only, no Grok, no broker/trade mutations, classification only.
"""
import argparse, json, logging, os, re, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [strategy-classifier] %(message)s")
log = logging.getLogger("strategy_classifier")

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_URL = OLLAMA_BASE.rstrip("/") + "/api/chat"


def _get_conn():
    from db_adapter import _get_conn as gc
    return gc()


def _call_ollama(prompt, model="gemma3:4b", timeout=180):
    num_gpu = int(os.environ.get("LOCAL_LLM_NUM_GPU", "0"))
    payload = json.dumps({
        "model": model, "stream": False,
        "options": {"temperature": 0.3, "num_predict": 256, "num_gpu": num_gpu},
        "messages": [
            {"role": "system", "content": "You are a trade strategy classifier. Return ONLY valid JSON. One strategy_id only."},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(OLLAMA_CHAT_URL, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "").strip()
        return text if text else None


def _parse_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _preflight_llm_health():
    """Run local LLM health checks. Returns (ok, details)."""
    checks = []

    # 1. Resolved model must be gemma3:4b
    model = os.environ.get("LOCAL_LLM_MODEL", "")
    safe = os.environ.get("LOCAL_LLM_SAFE_MODEL", "")
    checks.append(("LOCAL_LLM_MODEL=gemma3:4b", model == "gemma3:4b"))

    # 2. qwen3:14b must be in disabled list
    disabled = os.environ.get("DISABLED_LOCAL_LLM_MODELS", "")
    checks.append(("qwen3:14b_disabled", "qwen3:14b" in disabled))

    # 3. FORCE_LOCAL_LLM_CPU=true
    # CPU or GPU mode — just verify the setting is present
    num_gpu = os.environ.get("LOCAL_LLM_NUM_GPU", "")
    checks.append(("LOCAL_LLM_NUM_GPU_set", num_gpu != ""))

    # 4. LOCAL_LLM_MAX_CONCURRENT=1
    max_conc = os.environ.get("LOCAL_LLM_MAX_CONCURRENT", "")
    checks.append(("LOCAL_LLM_MAX_CONCURRENT=1", max_conc == "1"))

    # 5. Run health check script
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


def main():
    p = argparse.ArgumentParser(description="Trade Strategy Classifier")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--model", default="gemma3:4b")
    p.add_argument("--json-out", type=str)
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    alpaca = os.environ.get("ALPACA_MODE", "")
    if alpaca != "paper":
        log.error(f"ALPACA_MODE={alpaca}, must be paper. Aborting.")
        sys.exit(1)

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

    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get unclassified closed trades
    cur.execute("""
        SELECT trade_id, symbol, broker, account, entry_price, exit_price, pnl, pnl_pct,
               entry_date, exit_date,
               EXTRACT(DAY FROM (exit_date::timestamp - entry_date::timestamp)) as hold_days,
               source_table
        FROM trades
        WHERE (strategy_id IS NULL OR strategy_id = '' OR strategy_id = 'unknown')
          AND status = 'closed' AND entry_price > 0 AND exit_price > 0
        ORDER BY ABS(pnl) DESC
        LIMIT %s
    """, [args.limit])
    trades = [dict(r) for r in cur.fetchall()]

    if not trades:
        log.info("No unclassified trades found")
        conn.close()
        return

    log.info(f"Classifying {len(trades)} trades")

    prompt_template = (PROJECT_ROOT / "scripts" / "prompts" / "strategy_classifier_v1.md").read_text()
    results = []

    for t in trades:
        trade_json = json.dumps(t, default=str)
        prompt = prompt_template.replace("{trade_json}", trade_json)
        log.info(f"Classifying {t['symbol']} ({t['broker']}/{t['account']}) hold={t.get('hold_days','?')}d pnl={t.get('pnl','?')}")

        try:
            raw = _call_ollama(prompt, model=args.model)
            parsed = _parse_json(raw)
            if parsed and parsed.get("strategy_id"):
                result = {
                    "trade_id": t["trade_id"], "symbol": t["symbol"],
                    "broker": t["broker"], "account": t["account"],
                    "strategy_id": parsed["strategy_id"],
                    "confidence": parsed.get("confidence", 0),
                    "reasoning": parsed.get("reasoning", ""),
                    "source_table": t["source_table"],
                }
                log.info(f"  → {parsed['strategy_id']} (confidence={parsed.get('confidence',0)})")

                if args.apply:
                    # Update strategy_backtest_trades for this symbol
                    cur.execute("""UPDATE strategy_backtest_trades
                        SET strategy_id=%s WHERE symbol=%s AND (strategy_id IS NULL OR strategy_id='' OR strategy_id='unknown')""",
                        [parsed["strategy_id"], t["symbol"]])
                    updated = cur.rowcount
                    result["bt_rows_updated"] = updated
                    log.info(f"  Updated {updated} backtest trade rows for {t['symbol']}")

                results.append(result)
            else:
                log.warning(f"  → No valid classification returned")
                results.append({"trade_id": t["trade_id"], "symbol": t["symbol"], "error": "no_classification"})
        except Exception as e:
            log.warning(f"  → Error: {e}")
            results.append({"trade_id": t["trade_id"], "symbol": t["symbol"], "error": str(e)})

    if args.apply:
        conn.commit()

    conn.close()

    output = {"total": len(trades), "classified": len([r for r in results if r.get("strategy_id")]),
              "errors": len([r for r in results if r.get("error")]), "results": results}

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, default=str, indent=2))

    print(json.dumps(output, default=str, indent=2))
    log.info(f"Done. Classified {output['classified']}/{output['total']}")


if __name__ == "__main__":
    main()
