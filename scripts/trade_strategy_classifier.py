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
    payload = json.dumps({
        "model": model, "stream": False,
        "options": {"temperature": 0.3, "num_predict": 256, "num_gpu": 0},
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
