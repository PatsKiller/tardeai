#!/usr/bin/env python3
"""llm_intelligence_enrichment.py — Scheduled LLM enrichment for dashboard surfaces.

Uses the local LLM (via Ollama toll gate / free lanes) to generate intelligence
narratives for: portfolio risk, rebalance suggestions, recovery analysis,
morning brief synthesis, prospect narratives.

Results are stored in the `llm_intelligence_cache` table and served by API endpoints.

Quality gate (2026-07-26 Home trust hardening):
- Never overwrite a good cache row with garbage / truncated markdown.
- portfolio_risk unprotected count uses the same risk_management positions the
  Home risk gauges use (status NO STOP / missing stop), so briefing and gauges agree.

Usage:
    .venv/bin/python scripts/llm_intelligence_enrichment.py
    .venv/bin/python scripts/llm_intelligence_enrichment.py --dry-run
    .venv/bin/python scripts/llm_intelligence_enrichment.py --section portfolio_risk

Schedule: Cron at 7:20 AM weekdays (after pipeline, before morning brief)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from llm_content_quality import is_usable_llm_content, strip_think_tags

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    return psycopg2.connect(host="127.0.0.1", port=5432,
                            dbname="trade_ai", user="trade_ai", password=pw)


def _llm_generate(prompt: str, timeout: int = 120) -> str:
    """Call local LLM via toll-gated generate() — free/local lane preferred."""
    from local_llm import generate
    raw = generate(prompt, timeout=timeout, fallback=True, fast=False,
                   caller="llm_intelligence_enrichment", process_type="HOME_BRIEFING") or ""
    return strip_think_tags(raw)


def _save_cache(conn, section: str, content: str, metadata: dict = None) -> bool:
    """Store LLM output only when quality gate passes. Returns True if written."""
    ok, reason = is_usable_llm_content(section, content)
    if not ok:
        print(f"  [{section}] REJECTED write — {reason} (keeping last good cache)")
        return False
    cur = conn.cursor()
    meta = dict(metadata or {})
    meta["quality_gate"] = "pass"
    meta["content_chars"] = len(content)
    cur.execute("""
        INSERT INTO llm_intelligence_cache (section, content, metadata, generated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (section) DO UPDATE SET
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata,
            generated_at = NOW()
    """, (section, content, json.dumps(meta, default=str)))
    conn.commit()
    return True


def _unprotected_positions(rm: dict) -> list:
    """Align with Home risk gauges: positions without an active stop.

    risk_management.json historically uses status == 'NO STOP'; some writers
    also set has_stop=False. Count either so LLM briefing matches the gauge.
    """
    out = []
    for p in rm.get("positions", []) or []:
        status = str(p.get("status") or "").upper().replace("_", " ")
        has_stop = p.get("has_stop")
        if status in ("NO STOP", "NOSTOP", "UNPROTECTED") or has_stop is False:
            out.append(p)
    return out


# ── Section 1: Portfolio Risk Narrative ──────────────────────────────────

def generate_portfolio_risk(conn, dry_run=False) -> str:
    """Generate a portfolio risk assessment narrative."""
    h = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    rm = json.loads((STATE_DIR / "risk_management.json").read_text()) if (STATE_DIR / "risk_management.json").exists() else {}

    holdings = h.get("holdings", [])
    total = sum(p.get("market_value", 0) for p in holdings) or 1
    cash = sum(p.get("market_value", 0) for p in holdings if p.get("is_cash"))
    positions = [p for p in holdings if not p.get("is_cash") and p.get("market_value", 0) > 1000]
    top5 = sorted(positions, key=lambda p: p.get("market_value", 0), reverse=True)[:5]
    heat = rm.get("portfolio_heat_pct", 0)
    no_stop = _unprotected_positions(rm)
    triggered = [p for p in rm.get("positions", []) if str(p.get("status", "")).upper() == "TRIGGERED"]

    prompt = f"""/no_think
You are a portfolio risk analyst. Provide a 3-4 sentence risk assessment based on this data.
Be direct, specific, and actionable. No fluff. Do not use markdown headings or ## markers.

Portfolio: ${total:,.0f} across {len(positions)} positions. Cash: ${cash:,.0f} ({cash/total*100:.1f}%).
Heat: {heat:.1f}%. Positions without stops: {len(no_stop)}. Stops triggered: {len(triggered)}.
Top 5 by size: {', '.join(f'{p.get("symbol","?")} ${p.get("market_value",0):,.0f} ({p.get("market_value",0)/total*100:.1f}%)' for p in top5)}.
{f'Triggered: {", ".join(p.get("symbol","?") for p in triggered)}.' if triggered else ''}

Write a risk assessment paragraph. Focus on concentration risk, stop coverage, and immediate actions needed.
Use the exact unprotected count {len(no_stop)} when mentioning positions without stops."""

    if dry_run:
        print(f"[portfolio_risk] Prompt: {len(prompt)} chars; unprotected={len(no_stop)}")
        return ""

    result = _llm_generate(prompt)
    if result and _save_cache(conn, "portfolio_risk", result, {
        "positions": len(positions), "heat": heat, "unprotected": len(no_stop),
        "source": "risk_management.json+holdings.json",
    }):
        print(f"  [portfolio_risk] Generated ({len(result)} chars); unprotected={len(no_stop)}")
    return result or ""


# ── Section 2: Rebalance Suggestions ─────────────────────────────────────

def generate_rebalance_suggestions(conn, dry_run=False) -> str:
    """Generate rebalance suggestions from live portfolio state."""
    h = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    dc = json.loads((STATE_DIR / "dividend_calendar.json").read_text()) if (STATE_DIR / "dividend_calendar.json").exists() else {}

    holdings = h.get("holdings", [])
    total = sum(p.get("market_value", 0) for p in holdings) or 1
    positions = [p for p in holdings if not p.get("is_cash") and p.get("market_value", 0) > 500]

    sectors = {}
    for p in positions:
        s = p.get("sector", "Other")
        sectors[s] = sectors.get(s, 0) + p.get("market_value", 0)

    accounts = {}
    for p in holdings:
        a = p.get("account", "unknown")
        accounts[a] = accounts.get(a, 0) + p.get("market_value", 0)

    annual_income = dc.get("total_annual", 0)
    portfolio_yield = (annual_income / total * 100) if total else 0

    top_concentrated = sorted(positions, key=lambda p: p.get("market_value", 0), reverse=True)[:8]

    prompt = f"""/no_think
You are a portfolio rebalance advisor for a retired individual on SSDI.
Provide 3-5 specific, actionable rebalance suggestions. Be direct. No markdown headings.

Portfolio: ${total:,.0f}. Yield: {portfolio_yield:.2f}% (${annual_income:,.0f}/yr).
Accounts: {', '.join(f'{a}: ${v:,.0f}' for a, v in sorted(accounts.items(), key=lambda x: -x[1])[:4])}.
Top positions: {', '.join(f'{p.get("symbol","?")} ${p.get("market_value",0):,.0f} ({p.get("market_value",0)/total*100:.1f}%)' for p in top_concentrated)}.
Sectors: {', '.join(f'{s}: {v/total*100:.0f}%' for s, v in sorted(sectors.items(), key=lambda x: -x[1])[:5])}.

Constraints: SSDI income, Roth conversion strategy active, 401k loan outstanding.
Focus on: concentration risk, income adequacy, tax-efficient moves.
Format as numbered suggestions, each 1-2 sentences."""

    if dry_run:
        print(f"[rebalance] Prompt: {len(prompt)} chars")
        return ""

    result = _llm_generate(prompt, timeout=180)
    if result and _save_cache(conn, "rebalance_suggestions", result,
                              {"total": total, "yield_pct": portfolio_yield, "positions": len(positions)}):
        print(f"  [rebalance] Generated ({len(result)} chars)")
    return result or ""


# ── Section 3: Recovery Watch Analysis ───────────────────────────────────

def generate_recovery_analysis(conn, dry_run=False) -> str:
    """Generate recovery watch analysis for active items."""
    import psycopg2.extras
    cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur2.execute("""
        SELECT symbol, analyst_verdict, analyst_confidence, exit_type,
               patience_score, exit_price, stop_price
        FROM stopped_out_watch WHERE is_active = true
        ORDER BY analyst_confidence DESC NULLS LAST
    """)
    items = cur2.fetchall()

    if not items:
        return ""

    ts = json.loads((STATE_DIR / "technical_snapshot.json").read_text()) if (STATE_DIR / "technical_snapshot.json").exists() else {}

    lines = []
    for item in items:
        sym = item["symbol"]
        tech = ts.get(sym, {}) if isinstance(ts, dict) else {}
        lines.append(f"{sym}: verdict={item['analyst_verdict']}, conf={float(item.get('analyst_confidence',0))*100:.0f}%, "
                     f"exit_type={item.get('exit_type','?')}, patience={float(item.get('patience_score',0)):.2f}, "
                     f"RSI={tech.get('rsi','?')}, SMA200={tech.get('sma200_pct','?')}%")

    prompt = f"""/no_think
You are a recovery watch analyst. Analyze these {len(items)} positions and provide a 3-4 sentence summary.
Focus on: which are closest to re-entry, which should be abandoned, and overall recovery posture.
No markdown headings.

{chr(10).join(lines)}

Write a concise recovery watch assessment. Be specific about symbols."""

    if dry_run:
        print(f"[recovery] Prompt: {len(prompt)} chars")
        return ""

    result = _llm_generate(prompt)
    if result and _save_cache(conn, "recovery_analysis", result, {"items": len(items)}):
        print(f"  [recovery] Generated ({len(result)} chars)")
    return result or ""


# ── Section 4: Morning Brief Synthesis ───────────────────────────────────

def generate_morning_synthesis(conn, dry_run=False) -> str:
    """Generate a synthesized morning intelligence paragraph."""
    h = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total = sum(p.get("market_value", 0) for p in h.get("holdings", []))
    rm = json.loads((STATE_DIR / "risk_management.json").read_text()) if (STATE_DIR / "risk_management.json").exists() else {}
    heat = rm.get("portfolio_heat_pct", 0)

    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, title, sentiment FROM news_articles
        WHERE created_at > NOW() - INTERVAL '24 hours' AND symbol IS NOT NULL AND symbol != ''
        ORDER BY relevance_score DESC NULLS LAST LIMIT 8
    """)
    news = cur.fetchall()
    news_lines = [f"{r[0]}: {r[1][:60]} ({r[2] or 'neutral'})" for r in news]

    cur.execute("""
        SELECT symbol, mention_count, sentiment_score
        FROM social_sentiment_history
        WHERE observed_at > NOW() - INTERVAL '48 hours'
        ORDER BY mention_count DESC NULLS LAST LIMIT 5
    """)
    social = cur.fetchall()

    prompt = f"""/no_think
You are a portfolio intelligence briefing writer. Write a 3-4 sentence morning synthesis paragraph.
Combine portfolio status, news, and social signals into one cohesive briefing.
Use plain prose only — no markdown headings, no ## markers, no bullet lists.

Portfolio: ${total:,.0f}, heat {heat:.1f}%.
Recent news (24h): {chr(10).join(news_lines) if news_lines else 'No recent news.'}
Social activity: {', '.join(f'{r[0]} ({r[1]} mentions)' for r in social) if social else 'Limited social activity.'}

Write a professional morning briefing paragraph. No bullet points — flowing prose."""

    if dry_run:
        print(f"[morning] Prompt: {len(prompt)} chars")
        return ""

    result = _llm_generate(prompt)
    if result and _save_cache(conn, "morning_synthesis", result, {"news_count": len(news)}):
        print(f"  [morning] Generated ({len(result)} chars)")
    return result or ""


# ── Section 5: Top Prospect Narratives ───────────────────────────────────

def generate_prospect_narratives(conn, dry_run=False) -> str:
    """Generate brief thesis narratives for top-scored prospects."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (symbol)
            symbol, score, decision, price, catalyst, sector, industry
        FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '2 days'
          AND score >= 35 AND (disqualified = false OR disqualified IS NULL)
        ORDER BY symbol, scanned_at DESC
    """)
    prospects = cur.fetchall()
    if not prospects:
        return ""

    lines = [f"{r[0]}: score={r[1]}, ${r[3]}, {r[5] or '?'}/{r[6] or '?'}, catalyst={r[4][:80] if r[4] else 'none'}"
             for r in prospects[:8]]

    prompt = f"""/no_think
You are a trade analyst. For each prospect below, write a 1-sentence thesis (why it's interesting).
Be specific about the catalyst and setup quality. No markdown headings.

{chr(10).join(lines)}

Format: SYMBOL: thesis sentence"""

    if dry_run:
        print(f"[prospects] Prompt: {len(prompt)} chars, {len(prospects)} symbols")
        return ""

    result = _llm_generate(prompt)
    if result:
        narratives = {}
        for line in result.strip().split("\n"):
            if ":" in line:
                parts = line.split(":", 1)
                sym = parts[0].strip().upper()
                narrative = parts[1].strip() if len(parts) > 1 else ""
                if sym and narrative and len(sym) <= 6:
                    narratives[sym] = narrative
        payload = json.dumps(narratives)
        if narratives and _save_cache(conn, "prospect_narratives", payload,
                                      {"count": len(narratives)}):
            print(f"  [prospects] Generated {len(narratives)} narratives")
    return result or ""


# ── Main ─────────────────────────────────────────────────────────────────

def ensure_cache_table(conn):
    """Create the cache table if it doesn't exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS llm_intelligence_cache (
            section TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            metadata JSONB DEFAULT '{}',
            generated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="LLM Intelligence Enrichment")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--section", help="Run only one section")
    args = parser.parse_args()

    print(f"[llm_enrichment] Starting — {datetime.now().isoformat()}")

    conn = _get_conn()
    ensure_cache_table(conn)

    sections = {
        "portfolio_risk": generate_portfolio_risk,
        "rebalance_suggestions": generate_rebalance_suggestions,
        "recovery_analysis": generate_recovery_analysis,
        "morning_synthesis": generate_morning_synthesis,
        "prospect_narratives": generate_prospect_narratives,
    }

    if args.section:
        if args.section in sections:
            sections[args.section](conn, dry_run=args.dry_run)
        else:
            print(f"Unknown section: {args.section}. Available: {list(sections.keys())}")
    else:
        for name, fn in sections.items():
            try:
                print(f"  [{name}] Running...")
                fn(conn, dry_run=args.dry_run)
                time.sleep(2)
            except Exception as e:
                print(f"  [{name}] Error: {e}")

    conn.close()
    print(f"[llm_enrichment] Complete — {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
