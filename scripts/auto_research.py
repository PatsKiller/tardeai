#!/usr/bin/env python3
"""auto_research.py — Auto-trigger deep research from agent findings.

When synthesis detects conflicts, low confidence, or high-impact recommendations,
this script queues deeper research using the LLM router and stores findings
back into the intelligence pipeline.

Triggers:
1. Agent conflict on a symbol → research both sides
2. High-impact recommendation (BUY/SELL on >5% position) → verify thesis
3. New screener discovery → initial research brief
4. Escalation event → gather more context

Usage:
    python3 scripts/auto_research.py --check [--telegram]
    python3 scripts/auto_research.py --research SYMBOL [--telegram]
"""
import json, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_tg(msg: str):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


def find_research_triggers() -> list:
    """Find symbols needing deeper research based on agent activity."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    triggers = []

    # 1. Agent conflicts (BUY vs SELL) — need research to resolve
    cur.execute("""
        WITH recent AS (
            SELECT DISTINCT ON (symbol, agent) symbol, agent, recommendation, confidence
            FROM watchlist_agent_results
            WHERE created_at > NOW() - INTERVAL '3 days'
            ORDER BY symbol, agent, created_at DESC
        )
        SELECT symbol, array_agg(agent || ':' || recommendation) as recs
        FROM recent GROUP BY symbol
        HAVING bool_or(recommendation IN ('BUY','ADD'))
           AND bool_or(recommendation IN ('SELL','TRIM'))
    """)
    for r in cur.fetchall():
        triggers.append({
            "symbol": r["symbol"],
            "reason": "agent_conflict",
            "detail": f"Agents disagree: {', '.join(r['recs'])}",
            "priority": 1,
        })

    # 2. High-impact pending decisions (proposed, high priority)
    cur.execute("""
        SELECT cd.symbol, cd.action, cd.priority
        FROM cio_decisions cd
        WHERE cd.status = 'proposed'
          AND cd.action IN ('BUY', 'SELL', 'TRIM')
          AND cd.priority IN ('critical', 'high')
        LIMIT 5
    """)
    for r in cur.fetchall():
        triggers.append({
            "symbol": r["symbol"],
            "reason": "high_impact_decision",
            "detail": f"Proposed {r['action']} on {r['symbol']} (>5% weight, priority: {r['priority']})",
            "priority": 2,
        })

    # 3. New discoveries not yet researched (from screener, no agent results yet)
    cur.execute("""
        SELECT wi.symbol, tsc.strategy_type
        FROM watchlist_items wi
        JOIN ticker_strategy_classifications tsc ON wi.symbol = tsc.symbol AND tsc.active=TRUE
        WHERE wi.source = 'ai_discovered'
          AND wi.updated_at > NOW() - INTERVAL '3 days'
          AND wi.symbol NOT IN (SELECT DISTINCT symbol FROM watchlist_agent_results)
        LIMIT 5
    """)
    for r in cur.fetchall():
        triggers.append({
            "symbol": r["symbol"],
            "reason": "new_discovery",
            "detail": f"New screener find: {r['symbol']} ({r['strategy_type']})",
            "priority": 3,
        })

    conn.close()
    return triggers


# reason -> guard trigger_source. Anything not mapped here (CLI --research, unknown) defaults to
# "manual" (T1, operator-initiated). The guard fails closed on a genuinely unknown source.
_REASON_SOURCE = {
    "agent_conflict": "auto_research_conflict",
    "high_impact_decision": "auto_research_high_impact",
    "new_discovery": "auto_research_discovery",
}


def _record_skip(symbol: str, reason: str, gd: dict):
    """Audit a guard-skipped research attempt so DEFER/BLOCK is never silent."""
    try:
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO portfolio_intelligence_events
                (symbol, event_type, severity, source, payload)
            VALUES (%s, 'auto_research_skipped', 'info', 'auto_research.py', %s)
        """, (symbol, json.dumps({
            "research_reason": reason,
            "trigger_source": gd.get("trigger_source"),
            "budget_tier": gd.get("tier"),
            "budget_decision": gd.get("decision"),
            "lane_used": gd.get("lane_used"),
            "guard_reason": gd.get("reason"),
        }, default=str)))
        conn.commit(); conn.close()
    except Exception:
        pass


def research_symbol(symbol: str, reason: str = "manual", trigger_source: str = "manual") -> dict:
    """Run deep research on a symbol using LLM + web search + available intel.

    Every LLM call is gated by the Hermes research budget guard and uses the free/local lane
    only — automated research can never fall back onto a paid lane. A non-ALLOW guard verdict
    skips the LLM call entirely and is recorded for audit.
    """
    from llm_router import get_llm_response, LOCAL_MODEL
    from hermes_research_budget_guard import decide, ALLOW
    from intel_query import get_intel_summary
    from agent_collab import get_agent_context
    from web_research import research_symbol_web

    # --- Budget guard FIRST: decide before spending any web/LLM effort. ---
    gd = decide(symbol=symbol, trigger_source=trigger_source, research_type="research",
                lane="local", model=LOCAL_MODEL, urgency="normal", has_active_trigger=True)
    if gd.get("decision") != ALLOW:
        _record_skip(symbol, reason, gd)
        return {"symbol": symbol, "skipped": True, "decision": gd.get("decision"),
                "trigger_source": trigger_source, "tier": gd.get("tier"),
                "reason": gd.get("reason")}

    # Gather all available context
    intel = get_intel_summary(symbol=symbol, min_quality=30, max_chars=500, days=14)
    agent_ctx = get_agent_context(symbol, requesting_agent="auto_research")

    # Live web research via Brave Search API
    web_ctx = research_symbol_web(symbol, focus="analysis dividend risk")
    if web_ctx:
        intel = f"{intel}\n\n{web_ctx}" if intel else web_ctx

    # Build research prompt
    prompt = f"""/no_think You are a senior research analyst. Conduct a focused research brief on {symbol}.

CONTEXT:
{intel}

{agent_ctx}

Research trigger: {reason}

Provide a concise research brief covering:
1. THESIS: Bull case and bear case (2-3 sentences each)
2. KEY QUESTION: The single most important unresolved question about this position
3. DATA NEEDED: What specific data would resolve the conflict or uncertainty
4. RECOMMENDATION: Based on available information, what's the highest-conviction next action
5. CONFIDENCE: How certain are you (0-100%) and why

Keep under 300 words. Be specific with numbers and dates."""

    # free_only=True: local lane only — paid fallback is structurally impossible.
    result = get_llm_response("cio_synthesis", prompt, max_tokens=600, free_only=True)

    if not result.get("success"):
        return {"error": "LLM failed", "symbol": symbol}

    research = result["response"]

    # Store as intelligence event (with full budget-guard provenance)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO portfolio_intelligence_events
            (symbol, event_type, severity, source, payload)
        VALUES (%s, 'auto_research', 'info', 'auto_research.py', %s)
    """, (symbol, json.dumps({
        "reason": reason,
        "research_reason": reason,
        "trigger_source": trigger_source,
        "budget_tier": gd.get("tier"),
        "budget_decision": gd.get("decision"),
        "lane_used": result.get("provider"),
        "research_expires_at": gd.get("expires_at"),
        "provider": result.get("provider"),
        "cost": result.get("cost_estimate", 0),
    }, default=str)))
    conn.commit()
    conn.close()

    # Also save as a research topic finding
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_research_topics (topic, findings, status, priority, updated_at)
            VALUES (%s, %s, 'active', 2, NOW())
            ON CONFLICT (topic) DO UPDATE SET findings = EXCLUDED.findings, updated_at = NOW()
        """, (f"Auto-research: {symbol} ({reason})", research[:2000]))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {
        "symbol": symbol,
        "reason": reason,
        "research": research,
        "provider": result.get("provider"),
        "cost": result.get("cost_estimate", 0),
    }


def run_check(send_telegram: bool = False):
    """Find triggers and auto-research the top priorities."""
    triggers = find_research_triggers()
    print(f"[auto-research] Found {len(triggers)} research triggers")

    if not triggers:
        return {"triggers": 0, "researched": 0}

    # Research top 3 by priority
    researched = 0
    results = []
    for t in sorted(triggers, key=lambda x: x["priority"])[:3]:
        print(f"  Researching: {t['symbol']} ({t['reason']})")
        src = _REASON_SOURCE.get(t["reason"], "manual")
        result = research_symbol(t["symbol"], t["detail"], trigger_source=src)
        if result.get("skipped"):
            print(f"    skipped: {result.get('decision')} ({result.get('reason')})")
            continue
        if not result.get("error"):
            researched += 1
            results.append(result)

    if send_telegram and results:
        lines = [f"\U0001F50D *Auto-Research Complete*", ""]
        for r in results:
            lines.append(f"*{r['symbol']}* ({r['reason'][:30]})")
            # First 150 chars of research
            lines.append(f"_{r['research'][:150]}..._")
            lines.append("")
        lines.append(f"_via {results[0].get('provider', '?')} \u2022 /v2/research_")
        _send_tg("\n".join(lines))

    print(f"[auto-research] Researched {researched}/{len(triggers)} triggers")
    return {"triggers": len(triggers), "researched": researched, "results": results}


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    if "--check" in sys.argv:
        run_check(send_telegram=tg)
    elif "--research" in sys.argv:
        idx = sys.argv.index("--research")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1].upper()
            result = research_symbol(symbol, "manual", trigger_source="manual")
            if result.get("research"):
                print(result["research"])
            elif result.get("skipped"):
                print(f"Skipped by budget guard: {result.get('decision')} — {result.get('reason')}")
            else:
                print(f"Error: {result.get('error')}")
        else:
            print("Usage: --research SYMBOL")
    else:
        print("Usage:")
        print("  --check [--telegram]    Find triggers and auto-research top 3")
        print("  --research SYMBOL       Deep research a specific symbol")
