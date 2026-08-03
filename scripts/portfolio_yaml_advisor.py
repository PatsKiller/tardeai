"""portfolio_yaml_advisor.py — YAML Config Advisor v1.0
=======================================================
Reads current holdings + portfolio_accounts.yaml and calls Claude Opus
to produce structured suggestions for YAML target_allocation changes.

Key safety principles:
  1. Reads LIVE holdings first — no stale data
  2. Marks any position touched in last 90 days as DO_NOT_TOUCH
  3. All suggestions require explicit human approval before writing
  4. Verbose logging of every Opus decision for full auditability
  5. Never suggests changing financial amounts — only % targets and notes

Output:
  data/portfolios/state/yaml_advisor_output.json   — structured suggestions
  logs/yaml_advisor_YYYYMMDD_HHMMSS.log            — verbose audit log

Usage:
  python scripts/portfolio_yaml_advisor.py
  (called by run_portfolio_monthly.bat after AI analysis stage)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ── Setup ──────────────────────────────────────────────────────────────────────

def _load_env(root: Path) -> None:
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _setup_logging(logs_dir: Path) -> logging.Logger:
    """Verbose logging to both file and console."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"yaml_advisor_{ts}.log"
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log = logging.getLogger("yaml_advisor")
    log.info("=" * 70)
    log.info("  YAML Config Advisor v1.0")
    log.info(f"  Log file: {log_path}")
    log.info("=" * 70)
    return log, log_path


# ── Data loaders ───────────────────────────────────────────────────────────────

def load_yaml_config(root: Path) -> Dict:
    yaml_path = root / "assets" / "portfolio_accounts.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_holdings(root: Path) -> Dict:
    path = root / "data" / "portfolios" / "state" / "holdings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_transactions(holdings: Dict) -> List[Dict]:
    """Extract all transactions from holdings.json."""
    return holdings.get("transactions", [])


def classify_bucket(symbol: str, sector_type: Optional[str],
                    account: str, name: str = "") -> str:
    """Mirrors classifyBucket() from the dashboard JS — single source of truth."""
    sym = symbol.upper()
    sec = (sector_type or "").lower()

    if sym == "CASH":                              return "Cash"
    if sym in ("BND","AGG","AMANX"):               return "Bonds"
    if sym in ("VXUS","EFA","VEA"):                return "International Equity"
    if sym in ("CSWC","PFLT"):                     return "BDC Income"
    if sym in ("SCHD","DIV","JEPI"):               return "Income ETF/Dividend"
    if sym in ("NEE","XLU"):                       return "Utilities"
    if sym in ("LMT","LHX","RTX","NOC","BAH",
               "AVAV","CACI","KTOS","GD","LDOS",
               "KBR","DRS","TDG","RKLB","IRDM",
               "ARKQ","ITA"):                      return "Defense"
    if sym == "V":
        acct = account.lower()
        return "US Equity" if ("rollover" in acct or "roth" in acct) else "Financials"
    if sym == "PFE":                               return "Healthcare"
    if sym == "FID-CONTRA-F":                      return "US Large Blend"
    if sym == "SP500-D":                           return "US Large Blend"
    if sym == "JPM-LGCG":                          return "US Large Growth"
    if sym == "TRP-LVAL":                          return "US Large Value"
    if sym == "AB-DISC-Z":                         return "US Large Value"
    if sym in ("WM-BLAIR","SS-SMMD"):              return "US Small"
    if sym in ("VANG-FTSE-SOC","FID-DIVINTL",
               "SS-GACEQ"):                        return "International Equity"
    if sym == "FCNTX":                             return "US Large Blend"
    if sym in ("ARKG","SCHG","QQQ"):               return "US Large Growth"
    if sym in ("XLB",):                            return "Materials"
    if sym in ("XLI",):                            return "Industrials"
    if "large_blend"  in sec:                      return "US Large Blend"
    if "large_growth" in sec:                      return "US Large Growth"
    if "large_value"  in sec:                      return "US Large Value"
    if "small"        in sec:                      return "US Small"
    if "international" in sec:                     return "International Equity"
    return "Other"


# ── Ground truth builder ───────────────────────────────────────────────────────

def build_ground_truth(holdings: Dict, transactions: List[Dict],
                       log: logging.Logger) -> Dict:
    """
    Build the verified current state snapshot.
    This is what Opus receives as its factual baseline.
    """
    log.info("─" * 50)
    log.info("STAGE 1: Building ground truth from live holdings")

    totals   = holdings.get("portfolio_totals", {})
    accounts = holdings.get("account_summaries", {})
    all_pos  = holdings.get("holdings", [])
    total_mv = totals.get("total_value", 1)

    log.info(f"  Portfolio total:  ${total_mv:,.0f}")
    log.info(f"  Holdings as_of:  {holdings.get('as_of', 'unknown')}")
    log.info(f"  Accounts:        {list(accounts.keys())}")

    # ── Per-account actual allocation ──────────────────────────────────────────
    acct_actual: Dict[str, Dict] = {}
    for acct_key, ac in accounts.items():
        positions = [
            x for x in all_pos
            if x.get("account") == acct_key
            and not x.get("is_loan")
            and not x.get("is_revoked")
            and (x.get("market_value") or 0) > 0
        ]
        acct_total = ac.get("total_value", 1)
        bucket_map: Dict[str, float] = {}
        pos_detail = []

        for p in positions:
            sym    = p.get("symbol", "")
            sec    = p.get("sector_type") or p.get("sector") or ""
            name   = p.get("name", "")
            mv     = p.get("market_value", 0)
            is_cash = p.get("is_cash", False)
            bucket = "Cash" if is_cash else classify_bucket(sym, sec, acct_key, name)
            bucket_map[bucket] = bucket_map.get(bucket, 0) + mv
            pos_detail.append({
                "symbol": sym,
                "name": name[:30],
                "market_value": round(mv),
                "bucket": bucket,
                "pct_of_account": round(mv / acct_total * 100, 2),
                "pct_of_portfolio": round(mv / total_mv * 100, 2),
            })

        bucket_pcts = {
            b: {
                "mv": round(v),
                "pct_of_account": round(v / acct_total * 100, 1),
            }
            for b, v in sorted(bucket_map.items(), key=lambda x: -x[1])
        }

        acct_actual[acct_key] = {
            "display_name":  ac.get("display_name", acct_key),
            "total_value":   round(acct_total),
            "pct_of_portfolio": round(acct_total / total_mv * 100, 1),
            "bucket_actual": bucket_pcts,
            "positions":     sorted(pos_detail, key=lambda x: -x["market_value"]),
        }
        log.info(f"\n  [{acct_key}] ${acct_total:,.0f}")
        for b, d in bucket_pcts.items():
            log.info(f"    {b:<28} {d['pct_of_account']:>5.1f}%  ${d['mv']:>10,.0f}")

    # ── 90-day trade history — DO NOT TOUCH list ────────────────────────────────
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    recent: List[Dict] = []
    for t in transactions:
        if t.get("txn_type") in ("buy", "sell") and t.get("date", "") >= cutoff:
            recent.append({
                "date":     t["date"],
                "action":   t.get("action", ""),
                "symbol":   t.get("symbol", ""),
                "quantity": t.get("quantity", 0),
                "amount":   t.get("amount", 0),
                "account":  t.get("account", ""),
            })

    recent.sort(key=lambda x: x["date"], reverse=True)
    do_not_touch = sorted({t["symbol"] for t in recent if t["symbol"] not in ("nan", "")})

    log.info(f"\n  Recent trades (last 90 days): {len(recent)}")
    for t in recent[:20]:
        log.info(f"    {t['date']}  {t['action']:<20} {t['symbol']:<10} qty:{t['quantity']}")
    log.info(f"\n  DO NOT TOUCH symbols: {do_not_touch}")

    return {
        "as_of":            holdings.get("as_of", ""),
        "total_portfolio":  round(total_mv),
        "accounts":         acct_actual,
        "recent_trades":    recent,
        "do_not_touch":     do_not_touch,
    }


# ── Opus prompt builder ────────────────────────────────────────────────────────

def build_opus_prompt(yaml_config: Dict, ground_truth: Dict,
                      log: logging.Logger) -> str:
    """
    Build the structured prompt for Claude Opus.
    Injects both the YAML and the verified current state side by side.
    """
    log.info("─" * 50)
    log.info("STAGE 2: Building Opus prompt")

    yaml_text = yaml.dump(yaml_config, default_flow_style=False, sort_keys=False)
    # Compact the ground truth — send summary of trades, not full raw list
    # This keeps prompt under ~20K chars to avoid Opus response issues
    compact_gt = dict(ground_truth)
    trades = ground_truth.get("recent_trades", [])
    # Summarize trades: count per symbol with most recent date
    trade_summary = {}
    for t in trades:
        sym = t.get("symbol","")
        if sym and sym not in ("nan",""):
            if sym not in trade_summary:
                trade_summary[sym] = {"buys":0,"sells":0,"last_date":t["date"]}
            if t.get("action","").lower() == "buy":
                trade_summary[sym]["buys"] += 1
            else:
                trade_summary[sym]["sells"] += 1
    compact_gt["recent_trades_summary"] = trade_summary
    compact_gt["recent_trades"] = trades[:10]  # Only show 10 most recent for context
    compact_gt["recent_trade_count"] = len(trades)
    truth_text = json.dumps(compact_gt, indent=2)

    prompt = f"""You are a portfolio configuration advisor reviewing a personal investor's 
portfolio configuration YAML file against their actual current holdings.

PERSONAL CONTEXT:
- Owner: John Whiting, age 58.6 (DOB 08/21/1967)
- Income: SSDI ~$3,800/mo + Schedule C ~$20K/yr gross
- Private disability income continues until age 68.5 (requires biannual recertification)
- Can invest without withdrawals until age 68.5+
- Golden Roth Conversion Window: ages 68.5–73 (disability stops, RMDs not yet required)
- FRA (Social Security): age 67
- Goal: maximize Roth IRA, minimize future RMDs, grow dividend income

CURRENT portfolio_accounts.yaml (THIS IS WHAT NEEDS REVIEWING):
```yaml
{yaml_text}
```

VERIFIED CURRENT STATE (live holdings as of {ground_truth['as_of']}):
```json
{truth_text}
```

DO NOT TOUCH — symbols with trades in last 90 days (these were intentional):
{ground_truth['do_not_touch']}

YOUR TASK:
Review the YAML target_allocation values against the verified current state.
Identify where the YAML targets are misaligned with current reality or the owner's strategy.

STRICT RULES:
1. NEVER suggest undoing trades from the DO_NOT_TOUCH list
2. NEVER suggest changing dollar amounts — only allocation percentages and notes fields
3. NEVER suggest more than 5 changes in a single review
4. Each suggestion must reference the specific YAML field path (e.g. accounts.schwab_rollover_ira.target_allocation.us_equity)
5. If current allocation is close to target (within 5%), do NOT flag it
6. Consider the personal context — age 58.6, Golden Window at 68.5, disability income stable

Respond ONLY in this exact JSON format — no preamble, no markdown:
{{
  "review_date": "{datetime.now().strftime('%Y-%m-%d')}",
  "observations": [
    {{
      "type": "info",
      "account": "account_key or 'portfolio'",
      "message": "factual observation about current state",
      "data": {{"key": "value"}}
    }}
  ],
  "suggestions": [
    {{
      "id": "sug_001",
      "type": "update_target | add_bucket | remove_bucket | update_notes",
      "account": "yaml account key",
      "yaml_path": "full.yaml.path.to.field",
      "current_value": "current value in yaml",
      "suggested_value": "proposed new value",
      "rationale": "clear 1-2 sentence reason grounded in current holdings data",
      "confidence": "high | medium | low",
      "recent_trade_conflict": false,
      "do_not_apply_if": "any condition that would make this suggestion wrong"
    }}
  ],
  "do_not_touch_confirmed": [
    {{
      "symbol": "SYM",
      "reason": "traded on DATE — intentional, not flagging"
    }}
  ],
  "yaml_health_score": 0-100,
  "yaml_health_notes": "overall 1-2 sentence summary"
}}"""

    log.info(f"  Prompt length: {len(prompt):,} chars")
    return prompt


# ── Opus call ──────────────────────────────────────────────────────────────────

def call_opus(prompt: str, log: logging.Logger) -> Optional[Dict]:
    """YAML portfolio advisor cascade:
    Try 1: DeepSeek v4 via llm_lane.generate() (CIO-level reasoning)
    Try 2: LLM router (Grok → local qwen3)
    Try 3: Direct local LLM (last resort)
    Returns parsed JSON dict or None."""
    import re
    log.info("─" * 50)
    log.info("STAGE 3: Calling LLM for rebalance analysis")

    raw_text = None
    model_used = "unknown"

    # Try 1: DeepSeek v4 via llm_lane (replaces Claude Opus — CIO-level reasoning)
    try:
        from llm_lane import generate
        log.info("  Trying: DeepSeek v4 via llm_lane")
        raw_text = generate(prompt, lane="deepseek-v4", timeout=180)
        if raw_text:
            model_used = "deepseek-v4-pro"
            log.info(f"  DeepSeek v4 response: {len(raw_text):,} chars")
    except Exception as e:
        log.warning(f"  DeepSeek v4 failed: {e}")

    # Try 2: LLM router (Grok → local qwen3)
    if not raw_text:
        log.info("  Falling back to LLM router (Grok/local)")
        try:
            from llm_router import get_llm_response
            result = get_llm_response(
                task_type="cio_synthesis",
                prompt=prompt,
                high_impact=True,
                max_tokens=4000,
                local_timeout=120,
            )
            raw_text = result.get("response", "")
            model_used = result.get("model_used", "router_fallback")
            log.info(f"  Router response: {len(raw_text):,} chars via {model_used}")
            if result.get("fallback_reason"):
                log.info(f"  Fallback reason: {result['fallback_reason']}")
        except Exception as e:
            log.error(f"  LLM router also failed: {e}")

    # Try 3: Direct local LLM (last resort)
    if not raw_text:
        log.info("  Last resort: direct local LLM (qwen3:14b)")
        try:
            from local_llm_config import get_local_llm_model, get_local_llm_base_url
            import urllib.request
            url = get_local_llm_base_url().rstrip("/") + "/api/chat"
            payload = json.dumps({
                "model": get_local_llm_model(),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }).encode()
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            resp = urllib.request.urlopen(req, timeout=180)
            data = json.loads(resp.read())
            raw_text = data.get("message", {}).get("content", "")
            model_used = get_local_llm_model()
            log.info(f"  Local LLM response: {len(raw_text):,} chars via {model_used}")
        except Exception as e:
            log.error(f"  Local LLM failed: {e}")
            return None

    if not raw_text:
        log.error("  All LLM providers failed — no rebalance analysis generated")
        return None

    log.info(f"  Final model: {model_used}")

    # Parse JSON
    json_match = re.search(r"\{[\s\S]*\}", raw_text)
    if not json_match:
        log.error(f"  Could not extract JSON from {model_used} response ({len(raw_text)} chars)")
        return None

    try:
        result = json.loads(json_match.group())
        result["_model_used"] = model_used
        log.info(f"  Parsed: {len(result.get('suggestions', []))} suggestion(s) from {model_used}")
        return result
    except json.JSONDecodeError as e:
        log.error(f"  JSON parse error: {e}")
        return None


# ── Diff logger ────────────────────────────────────────────────────────────────

def log_suggestion_diffs(suggestions: List[Dict], yaml_config: Dict,
                          log: logging.Logger) -> None:
    """
    Verbose diff log — exactly what Opus wants to change and why.
    This is the fallback audit trail.
    """
    log.info("─" * 50)
    log.info("STAGE 4: Suggestion diff log (verbose)")
    log.info(f"  Total suggestions: {len(suggestions)}")

    for i, sug in enumerate(suggestions, 1):
        log.info(f"\n  [{i}] {sug.get('id', f'sug_{i:03d}')} — {sug.get('type', '?')}")
        log.info(f"      Account:   {sug.get('account', '?')}")
        log.info(f"      YAML path: {sug.get('yaml_path', '?')}")
        log.info(f"      CURRENT:   {sug.get('current_value', '?')!r}")
        log.info(f"      PROPOSED:  {sug.get('suggested_value', '?')!r}")
        log.info(f"      Rationale: {sug.get('rationale', '?')}")
        log.info(f"      Confidence:{sug.get('confidence', '?')}")
        log.info(f"      Trade conflict: {sug.get('recent_trade_conflict', False)}")
        if sug.get("do_not_apply_if"):
            log.info(f"      ⚠ Guard:   {sug['do_not_apply_if']}")

        # Show the exact YAML diff
        path_parts = sug.get("yaml_path", "").split(".")
        try:
            node = yaml_config
            for part in path_parts:
                node = node[part]
            log.info(f"      YAML confirmed current: {node!r}")
        except (KeyError, TypeError):
            log.warning(f"      ⚠ Could not traverse yaml_path: {sug.get('yaml_path')}")


# ── Save output ────────────────────────────────────────────────────────────────

def save_output(result: Dict, ground_truth: Dict, log_path: Path,
                state_dir: Path, log: logging.Logger) -> Path:
    """Save full advisor output JSON for the dashboard to read."""
    output = {
        "generated_at":  datetime.now().isoformat(),
        "log_file":      str(log_path),
        "ground_truth_summary": {
            "as_of":           ground_truth["as_of"],
            "total_portfolio": ground_truth["total_portfolio"],
            "do_not_touch":    ground_truth["do_not_touch"],
            "recent_trade_count": len(ground_truth["recent_trades"]),
        },
        "opus_output":   result,
        "status":        "pending_review",  # dashboard sets to 'applied'/'dismissed'
    }

    out_path = state_dir / "yaml_advisor_output.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    log.info(f"  Output saved: {out_path}")
    return out_path


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    root      = Path(__file__).parent.parent.resolve()
    state_dir = root / "data" / "portfolios" / "state"
    logs_dir  = root / "logs"

    _load_env(root)
    log, log_path = _setup_logging(logs_dir)

    log.info(f"Project root: {root}")

    # Stage 1 — Load data
    log.info("Loading YAML config...")
    yaml_config = load_yaml_config(root)

    log.info("Loading live holdings...")
    holdings = load_holdings(root)
    transactions = load_transactions(holdings)
    log.info(f"  {len(transactions)} transactions loaded")

    # Stage 2 — Build ground truth
    ground_truth = build_ground_truth(holdings, transactions, log)

    # Stage 3 — Build prompt
    prompt = build_opus_prompt(yaml_config, ground_truth, log)

    # Stage 4 — Call Opus
    result = call_opus(prompt, log)

    if not result:
        log.error("Opus call failed — writing empty output for dashboard")
        result = {
            "review_date": datetime.now().strftime("%Y-%m-%d"),
            "observations": [],
            "suggestions": [],
            "do_not_touch_confirmed": [],
            "yaml_health_score": 0,
            "yaml_health_notes": "Advisor failed — check logs",
            "error": "Opus call returned no result",
        }

    # Stage 5 — Log diffs
    log_suggestion_diffs(result.get("suggestions", []), yaml_config, log)

    # Stage 6 — Save output
    out_path = save_output(result, ground_truth, log_path, state_dir, log)

    log.info("─" * 50)
    log.info("YAML ADVISOR COMPLETE")
    log.info(f"  Suggestions:  {len(result.get('suggestions', []))}")
    log.info(f"  Health score: {result.get('yaml_health_score', '?')}/100")
    log.info(f"  Output:       {out_path}")
    log.info(f"  Log:          {log_path}")
    log.info("  Next: open Command Center → AI Analyst → YAML Config Review")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
