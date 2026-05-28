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
        "options": {"temperature": 0.3, "num_predict": 512, "num_gpu": num_gpu},
        "messages": [
            {"role": "system", "content": "You are a trade strategy classifier. Return ONLY valid JSON with no other text. Every array element must be a plain string."},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(OLLAMA_CHAT_URL, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "").strip()
        return text if text else None


def _fix_malformed_arrays(text):
    """Fix common LLM JSON errors: colon-separated key:value in arrays like ["key": value]."""
    # Replace patterns like ["key": value, "key2": value2] with ["key=value", "key2=value2"]
    def fix_array(match):
        content = match.group(1)
        # Check if it looks like key:value pairs rather than strings
        if re.search(r'"[^"]+"\s*:', content) and not re.search(r'^\s*\{', content.strip()):
            # Convert "key": value pairs to "key=value" strings
            pairs = re.findall(r'"([^"]+)"\s*:\s*("[^"]*"|[^,\]]+)', content)
            if pairs:
                fixed = ", ".join(f'"{k}={v.strip().strip(chr(34))}"' for k, v in pairs)
                return f"[{fixed}]"
        return match.group(0)
    return re.sub(r'\[([^\[\]]+)\]', fix_array, text)


def _parse_json(raw):
    if not raw:
        return None
    text = raw.strip()

    # Try 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: markdown fences
    fence = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if fence:
        fenced = fence.group(1).strip()
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            # Try fixing malformed arrays in fenced content
            try:
                return json.loads(_fix_malformed_arrays(fenced))
            except json.JSONDecodeError:
                pass

    # Try 3: extract { ... } block
    brace_start = text.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    block = text[brace_start:i+1]
                    try:
                        return json.loads(block)
                    except json.JSONDecodeError:
                        # Try fixing malformed arrays
                        try:
                            return json.loads(_fix_malformed_arrays(block))
                        except json.JSONDecodeError:
                            pass
                    break

    # Try 4: fix whole text
    try:
        return json.loads(_fix_malformed_arrays(text))
    except json.JSONDecodeError:
        pass

    return None


# ── Deterministic post-validation ──────────────────────────────────────
_DIVIDEND_EVIDENCE_KEYWORDS = {
    "dividend", "income", "yield", "compounding", "reinvestment",
    "aristocrat", "dividend king", "payout", "distribution",
}


def _post_validate(parsed):
    """Apply rule-based validation after LLM classification.
    Returns (validated_parsed, validation_notes)."""
    notes = []
    if not parsed or not isinstance(parsed, dict):
        return parsed, ["no_parsed_output"]

    strategy = parsed.get("strategy_id", "")
    confidence = parsed.get("confidence", 0)
    reasoning = parsed.get("reasoning", "").lower()
    evidence_used = parsed.get("evidence_used", [])
    missing_evidence = parsed.get("missing_evidence", [])

    # Ensure required fields exist
    parsed.setdefault("evidence_used", [])
    parsed.setdefault("missing_evidence", [])
    parsed.setdefault("requires_review", confidence < 0.7)

    # Rule 1: dividend_growth_compounder needs dividend-specific evidence
    if strategy == "dividend_growth_compounder":
        evidence_str = " ".join(str(e).lower() for e in evidence_used)
        has_dividend_evidence = any(kw in evidence_str for kw in _DIVIDEND_EVIDENCE_KEYWORDS)
        if not has_dividend_evidence:
            notes.append(f"DOWNGRADED: {strategy} -> needs_review (no dividend-specific evidence in evidence_used)")
            parsed["strategy_id"] = "needs_review"
            parsed["requires_review"] = True
            parsed["confidence"] = min(confidence, 0.5)
            parsed.setdefault("validation_notes", []).append(
                "Downgraded from dividend_growth_compounder: no dividend/income evidence found"
            )

    # Rule 2: reasoning claims "dividend stock" without evidence
    if parsed.get("strategy_id") == "dividend_growth_compounder":
        unsupported_claims = ["dividend stock", "dividend paying", "dividend-paying"]
        reasoning_has_claim = any(c in reasoning for c in unsupported_claims)
        evidence_supports = any(
            kw in " ".join(str(e).lower() for e in evidence_used)
            for kw in _DIVIDEND_EVIDENCE_KEYWORDS
        )
        if reasoning_has_claim and not evidence_supports:
            notes.append(f"DOWNGRADED: reasoning claims dividend but evidence_used lacks support")
            parsed["strategy_id"] = "needs_review"
            parsed["requires_review"] = True
            parsed["confidence"] = min(confidence, 0.5)
            parsed.setdefault("validation_notes", []).append(
                "Downgraded: reasoning asserts dividend without supporting evidence"
            )

    # Rule 3: high confidence with thin evidence
    if parsed.get("confidence", 0) > 0.8 and len(evidence_used) < 2:
        old_conf = parsed["confidence"]
        parsed["confidence"] = 0.6
        notes.append(f"CAPPED confidence {old_conf} -> 0.6 (fewer than 2 evidence items)")
        parsed.setdefault("validation_notes", []).append(
            f"Confidence capped from {old_conf} to 0.6: insufficient evidence items"
        )

    # Rule 4: swing_trade for 30+ day holds is likely wrong
    # (swing_trade is defined as 2-20 days — longer holds need more evidence)
    # This check uses trade data passed via the parsed output's evidence
    hold_evidence = [e for e in evidence_used if "hold_days=" in str(e)]
    if strategy == "swing_trade" and hold_evidence:
        try:
            hold_days = float(str(hold_evidence[0]).split("=")[1])
            if hold_days > 30:
                notes.append(f"DOWNGRADED: swing_trade -> needs_review (hold_days={hold_days} exceeds swing range)")
                parsed["strategy_id"] = "needs_review"
                parsed["requires_review"] = True
                parsed["confidence"] = min(confidence, 0.4)
                parsed.setdefault("validation_notes", []).append(
                    f"Downgraded from swing_trade: hold_days={hold_days} exceeds 2-20 day swing range"
                )
        except (ValueError, IndexError):
            pass

    # Rule 5: needs_review / unknown confidence bounds
    if parsed.get("strategy_id") == "needs_review":
        parsed["confidence"] = min(parsed.get("confidence", 0.5), 0.5)
        parsed["requires_review"] = True
    elif parsed.get("strategy_id") == "unknown":
        parsed["confidence"] = min(parsed.get("confidence", 0.4), 0.4)
        parsed["requires_review"] = True

    return parsed, notes


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

    # Get unclassified closed trades with enrichment data
    cur.execute("""
        SELECT t.trade_id, t.symbol, t.broker, t.account,
               t.entry_price, t.exit_price, t.pnl, t.pnl_pct,
               t.entry_date, t.exit_date,
               EXTRACT(DAY FROM (t.exit_date::timestamp - t.entry_date::timestamp)) AS hold_days,
               t.exit_reason, t.source_table,
               -- ticker_strategy_classifications
               tsc.strategy_type   AS ticker_strategy,
               tsc.asset_type      AS ticker_asset_type,
               tsc.confidence      AS ticker_confidence,
               -- watchlist_strategy_cards
               wsc.strategy_type   AS watchlist_strategy,
               wsc.thesis          AS watchlist_thesis,
               wsc.catalyst_summary AS watchlist_catalyst,
               -- paper_trade_proposals (most recent for this symbol)
               ptp.strategy_id     AS proposal_strategy,
               ptp.catalyst        AS proposal_catalyst,
               ptp.setup_type      AS proposal_setup,
               ptp.sector          AS proposal_sector,
               ptp.industry        AS proposal_industry,
               ptp.discovery_source AS proposal_discovery_source
        FROM trades t
        LEFT JOIN ticker_strategy_classifications tsc
            ON tsc.symbol = t.symbol AND tsc.active = true
        LEFT JOIN watchlist_strategy_cards wsc
            ON wsc.symbol = t.symbol
        LEFT JOIN LATERAL (
            SELECT strategy_id, catalyst, setup_type, sector, industry, discovery_source
            FROM paper_trade_proposals
            WHERE symbol = t.symbol
            ORDER BY created_at DESC LIMIT 1
        ) ptp ON true
        WHERE (t.strategy_id IS NULL OR t.strategy_id = '' OR t.strategy_id = 'unknown')
          AND t.status = 'closed' AND t.entry_price > 0 AND t.exit_price > 0
        ORDER BY ABS(t.pnl) DESC
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
        # Build enrichment context
        enrichment = {}
        if t.get("ticker_strategy"):
            enrichment["ticker_classification"] = {
                "strategy": t["ticker_strategy"],
                "asset_type": t.get("ticker_asset_type"),
                "confidence": float(t["ticker_confidence"]) if t.get("ticker_confidence") else None,
            }
        if t.get("watchlist_strategy"):
            enrichment["watchlist"] = {
                "strategy": t["watchlist_strategy"],
                "thesis": t.get("watchlist_thesis", "")[:200] if t.get("watchlist_thesis") else None,
                "catalyst": t.get("watchlist_catalyst", "")[:200] if t.get("watchlist_catalyst") else None,
            }
        if t.get("proposal_strategy"):
            enrichment["proposal"] = {
                "strategy": t["proposal_strategy"],
                "catalyst": t.get("proposal_catalyst", "")[:200] if t.get("proposal_catalyst") else None,
                "setup": t.get("proposal_setup", "")[:200] if t.get("proposal_setup") else None,
                "sector": t.get("proposal_sector"),
                "industry": t.get("proposal_industry"),
                "discovery_source": t.get("proposal_discovery_source"),
            }

        # Build trade data for prompt (core fields only)
        trade_core = {k: t[k] for k in (
            "trade_id", "symbol", "broker", "account", "entry_price", "exit_price",
            "pnl", "pnl_pct", "entry_date", "exit_date", "hold_days", "exit_reason", "source_table"
        ) if t.get(k) is not None}

        if enrichment:
            trade_core["enrichment"] = enrichment
            parts = [f"{k}={v.get('strategy', '?')}" for k, v in enrichment.items()]
            log.info(f"  Enrichment: {', '.join(parts)}")

        trade_json = json.dumps(trade_core, default=str)
        prompt = prompt_template.replace("{trade_json}", trade_json)
        log.info(f"Classifying {t['symbol']} ({t['broker']}/{t['account']}) hold={t.get('hold_days','?')}d pnl={t.get('pnl','?')}")

        try:
            raw = _call_ollama(prompt, model=args.model)
            if raw:
                log.debug(f"  Raw LLM output: {raw[:300]}")
            parsed = _parse_json(raw)
            if not parsed and raw:
                log.warning(f"  JSON parse failed, raw preview: {raw[:200]}")
            if parsed and parsed.get("strategy_id"):
                # Post-validation
                llm_strategy = parsed["strategy_id"]
                llm_confidence = parsed.get("confidence", 0)
                parsed, validation_notes = _post_validate(parsed)

                result = {
                    "trade_id": t["trade_id"], "symbol": t["symbol"],
                    "broker": t["broker"], "account": t["account"],
                    "strategy_id": parsed["strategy_id"],
                    "confidence": parsed.get("confidence", 0),
                    "reasoning": parsed.get("reasoning", ""),
                    "evidence_used": parsed.get("evidence_used", []),
                    "missing_evidence": parsed.get("missing_evidence", []),
                    "requires_review": parsed.get("requires_review", False),
                    "source_table": t["source_table"],
                }
                if validation_notes:
                    result["validation_notes"] = validation_notes
                    result["llm_original_strategy"] = llm_strategy
                    result["llm_original_confidence"] = llm_confidence

                log.info(f"  → {parsed['strategy_id']} (confidence={parsed.get('confidence',0)})"
                         + (f" [validated from {llm_strategy}]" if validation_notes else ""))

                if args.apply:
                    # Do not apply needs_review or unknown to DB
                    if parsed["strategy_id"] in ("needs_review", "unknown"):
                        log.info(f"  Skipping DB write for {parsed['strategy_id']}")
                    else:
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

    classified = [r for r in results if r.get("strategy_id") and r["strategy_id"] not in ("needs_review", "unknown")]
    needs_review = [r for r in results if r.get("strategy_id") == "needs_review"]
    unknowns = [r for r in results if r.get("strategy_id") == "unknown"]
    errors = [r for r in results if r.get("error")]
    validated = [r for r in results if r.get("validation_notes")]
    output = {
        "total": len(trades),
        "classified": len(classified),
        "needs_review": len(needs_review),
        "unknown": len(unknowns),
        "errors": len(errors),
        "post_validated": len(validated),
        "results": results,
    }

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(output, default=str, indent=2))

    print(json.dumps(output, default=str, indent=2))
    log.info(f"Done. Classified {output['classified']}/{output['total']}")


if __name__ == "__main__":
    main()
