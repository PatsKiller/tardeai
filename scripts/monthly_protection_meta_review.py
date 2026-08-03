#!/usr/bin/env python3
"""monthly_protection_meta_review.py — monthly Claude ("fable 5") arbitration of LLM protection advice.

Operator requirement (2026-06-12): "once a month have fable 5 review what other LLMs recommended and
weigh in." Gathers the month's protection_advisory rows (gemma local + grok external, per symbol),
sends ONE curated meta-prompt to Claude (Anthropic — the only metered call, monthly by design),
and stores:
  • monthly_llm_meta_reviews — the full arbitration record (input snapshot + output payload)
  • hermes_external_research — one per-symbol verdict row (lane='claude') so the CLAUDE badge and
    tooltip light up on the Portfolio cards.

ADVISORY ONLY. Never places/modifies/proposes an order.

  python3 scripts/monthly_protection_meta_review.py [--days 31] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PROMPT_VERSION = "protection_meta_review_v1"

META_PROMPT_V1 = """You are the senior risk reviewer ("monthly meta-review"). Below are protective
stop / trailing-stop recommendations that OTHER models (local gemma, grok) produced this month for
real portfolio holdings, with the technical inputs they saw.

Your job, per symbol: (1) judge whether the recommendations are sound for the stated volatility
(ATR) and swing structure; (2) where models disagree, arbitrate and say which is better and why;
(3) give YOUR verdict stop/trail. Also list any cross-cutting patterns (systematic biases: stops
too tight vs ATR, ignoring analyst context, etc).

RULES: protection advice only — never what to buy/sell. STRICT JSON only:
{{"per_symbol": {{"<SYM>": {{"verdict_stop": <number|null>, "verdict_trail_type": "PERCENT"|"VALUE"|null,
  "verdict_trail_offset": <number|null>, "agrees_with": "<model or 'neither'>",
  "note": "<max 30 words>"}}}}, "patterns": ["<finding>", ...], "overall_quality": "<max 40 words>"}}

THIS MONTH'S RECOMMENDATIONS:
{body}"""


def _claude_DEPRECATED(prompt: str) -> str | None:
    """Deprecated — migrated to llm_lane.generate(lane='deepseek-v4')."""
    import os
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                break
    if not key:
        return None
    try:
        import anthropic
        from local_llm import FALLBACK_ANTHROPIC
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(model=FALLBACK_ANTHROPIC, max_tokens=8000,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"  anthropic error: {str(e)[:160]}")
        return None


def _claude(prompt: str) -> str | None:
    """Monthly protection meta-review using DeepSeek v4 (CIO-level adjudication).
    Replaces direct Anthropic call; DeepSeek v4 has ample token budget for multi-symbol arbitration."""
    try:
        from llm_lane import generate
        return generate(prompt, lane="deepseek-v4", timeout=180)
    except Exception as e:
        print(f"  deepseek-v4 error: {str(e)[:160]}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=31)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol, model_used, summary, thesis, evidence_json, confidence_score, created_at
                   FROM hermes_research_intelligence
                   WHERE research_type='protection_advisory' AND created_at > NOW() - %s * INTERVAL '1 day'
                   ORDER BY symbol, created_at DESC""", (a.days,))
    rows = cur.fetchall()
    if not rows:
        print(json.dumps({"status": "no_input", "note": "no protection_advisory rows in window — run "
                          "holding_protection_advisor.py first"}))
        return
    by_sym: dict = {}
    for sym, model, summary, thesis, ev, conf, at in rows:
        ev = ev if isinstance(ev, dict) else json.loads(ev or "{}")
        # latest rec per (symbol, model); inputs compressed to the decision-relevant numbers so a
        # FULL-portfolio review (39 symbols x 2 lanes) fits without mid-JSON truncation (2026-06-12)
        inp = ev.get("inputs") or {}
        by_sym.setdefault(sym, {})
        if model not in by_sym[sym]:
            by_sym[sym][model] = {"rec": ev.get("recommendation"), "why": (summary or "")[:140],
                                  # floor-clamp flag: True when the stop was widened to the family floor
                                  # (was too tight) — Claude should sanity-check the widening explicitly.
                                  "floored": bool(ev.get("floored")) or ((ev.get("recommendation") or {}).get("_floored_from_pct") is not None),
                                  "conf": float(conf or 0),
                                  "px": round(float(inp.get("price") or 0), 2),
                                  "atr": round(float(inp.get("atr") or 0), 2),
                                  "swing_low": round(float(inp.get("swing_low") or 0), 2),
                                  "pnl_pct": round(float(inp.get("pnl_pct") or 0), 1), "at": str(at)[:10]}
    body = json.dumps(by_sym, separators=(",", ":"), default=str)
    if len(body) > 60000:        # hard guard — never send a broken-JSON prompt
        body = json.dumps({k: by_sym[k] for k in sorted(by_sym)[:45]}, separators=(",", ":"), default=str)
    prompt = META_PROMPT_V1.format(body=body)
    snap_hash = hashlib.sha256(body.encode()).hexdigest()[:32]
    month = dt.date.today().replace(day=1).isoformat()

    if a.dry_run:
        print(f"DRY-RUN: {len(by_sym)} symbols, {len(rows)} recs, prompt {len(prompt)} chars, month {month}")
        return

    MODEL_NAME = "deepseek-v4-pro"
    out = _claude(prompt)
    parsed = None
    if out:
        m = re.search(r"\{.*\}", out, re.S)
        try:
            parsed = json.loads(m.group(0)) if m else None
        except Exception:
            parsed = None
    status = "completed" if parsed else ("empty_response" if not out else "parse_failed")
    cur.execute("""INSERT INTO monthly_llm_meta_reviews
                     (review_month, model_provider, model_name, prompt_version, generated_at, status,
                      trade_count, reviewed_trade_count, patterns, recommendations,
                      input_snapshot_hash, input_snapshot, output_payload, error_message)
                   VALUES (%s,'deepseek',%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (month, MODEL_NAME, PROMPT_VERSION, status, len(rows), len(by_sym),
                 json.dumps((parsed or {}).get("patterns") or []),
                 json.dumps((parsed or {}).get("per_symbol") or {}),
                 snap_hash, json.dumps(by_sym, default=str),               # json column: never truncate mid-token
                 json.dumps(parsed if parsed else {"raw_response": (out or "")[:50000]}),
                 None if parsed else "no/invalid JSON from model"))
    conn.commit()
    if parsed:
        for sym, v in (parsed.get("per_symbol") or {}).items():
            cur.execute("""INSERT INTO hermes_external_research
                             (lane, trigger_reason, priority, symbol, question, model, status,
                              recommendation, evidence_json, confidence, advisory_only)
                           VALUES ('deepseek','monthly_protection_meta_review','normal',%s,
                              'arbitrate this month''s stop/trail recommendations',%s,'sent',%s,%s,NULL,TRUE)""",
                        (sym.upper(), MODEL_NAME,
                         (f"verdict: stop {v.get('verdict_stop')} · trail "
                          f"{v.get('verdict_trail_offset')}{'%' if v.get('verdict_trail_type') == 'PERCENT' else '$'} "
                          f"· agrees with {v.get('agrees_with')} — {v.get('note', '')}")[:400],
                         json.dumps(v)))
        conn.commit()
    print(json.dumps({"status": status, "month": month, "symbols": len(by_sym), "input_recs": len(rows),
                      "patterns": (parsed or {}).get("patterns"),
                      "note": "advisory only; per-symbol verdicts feed the CLAUDE badge"}, default=str))


if __name__ == "__main__":
    main()
