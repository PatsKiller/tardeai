#!/usr/bin/env python3
"""auto_research.py — Auto-trigger deep research from agent findings.

When synthesis detects conflicts, low confidence, or high-impact recommendations,
this script queues deeper research using the LLM router and stores findings
back into the intelligence pipeline.

Triggers:
1. Agent conflict on a symbol → research both sides
2. High-impact pending decision → verify thesis
3. New screener discovery → initial research brief
4. Escalation event → gather more context

Usage:
    python3 scripts/auto_research.py --check [--telegram]
    python3 scripts/auto_research.py --research SYMBOL [--telegram]
    python3 scripts/auto_research.py --backfill-outbox
"""
import json, re, sys, uuid
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
            "detail": f"Proposed {r['action']} on {r['symbol']} (priority: {r['priority']})",
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


def _sync_screener_find_pin(symbol: str, reason: str = "", strategy_type: str = None,
                            brief_snippet: str = "", auto_research_at=None) -> bool:
    """Keep buy-side screener finds pinned in the Watchlist Screener Finds lane."""
    try:
        from api_v2 import _sync_screener_find_pin as _api_sync
        return _api_sync(symbol, reason=reason, strategy_type=strategy_type,
                         brief_snippet=brief_snippet, auto_research_at=auto_research_at)
    except Exception as e:
        print(f"[auto-research] screener pin sync failed for {symbol}: {e}")
        return False


def _persist_research_topic(symbol: str, reason: str, research: str, strategy_type: str = None) -> None:
    """Write brief to user_research_topics for Intelligence → Research tab."""
    topic = f"Auto-research: {symbol}"
    snippet = (research or "")[:8000]
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, research_count FROM user_research_topics WHERE topic = %s LIMIT 1", (topic,))
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE user_research_topics SET
                source = 'auto_research.py', status = 'active', priority = 'normal',
                original_message = %s, strategy_type = COALESCE(%s, strategy_type),
                latest_findings = %s, latest_finding_at = NOW(), last_researched_at = NOW(),
                research_count = COALESCE(research_count, 0) + 1, updated_at = NOW()
            WHERE topic = %s
        """, (reason[:500], strategy_type, snippet, topic))
    else:
        cur.execute("""
            INSERT INTO user_research_topics (
                topic, source, status, priority, strategy_type, original_message,
                latest_findings, latest_finding_at, last_researched_at, research_count,
                created_at, updated_at
            ) VALUES (%s, 'auto_research.py', 'active', 'normal', %s, %s, %s, NOW(), NOW(), 1, NOW(), NOW())
        """, (topic, strategy_type, reason[:500], snippet))
    conn.commit()
    conn.close()


def _queue_agent_reviews(symbol: str, note: str) -> int:
    """Queue maria/steph/risk when auto-research fires but agents never wrote results."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM watchlist_agent_results WHERE symbol=%s AND created_at > NOW() - INTERVAL '7 days'",
        (symbol,),
    )
    if (cur.fetchone() or [0])[0] > 0:
        conn.close()
        return 0
    cur.execute("""
        SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE symbol=%s AND status IN ('queued', 'processing', 'pending')
          AND created_at > NOW() - INTERVAL '6 hours'
    """, (symbol,))
    if (cur.fetchone() or [0])[0] > 0:
        conn.close()
        return 0
    queued = 0
    for agent in ("maria", "steph", "risk_agent"):
        job_id = f"ar_{symbol.lower()}_{agent}_{uuid.uuid4().hex[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs
                (id, symbol, requested_agent, request_type, priority, note, status, submitted_from)
            VALUES (%s, %s, %s, 'full_analysis', 2, %s, 'queued', 'auto_research.py')
            ON CONFLICT DO NOTHING
        """, (job_id, symbol, agent, note[:240]))
        queued += cur.rowcount or 0
    conn.commit()
    conn.close()
    if queued:
        print(f"[auto-research] Queued {queued} agent review job(s) for {symbol}")
    return queued


def research_symbol(symbol: str, reason: str = "manual", trigger_kind: str = "manual") -> dict:
    """Run deep research on a symbol using LLM + web search + available intel."""
    from llm_router import get_llm_response
    from intel_query import get_intel_summary
    from agent_collab import get_agent_context
    from web_research import research_symbol_web

    intel = get_intel_summary(symbol=symbol, min_quality=30, max_chars=500, days=14)
    agent_ctx = get_agent_context(symbol, requesting_agent="auto_research")

    web_ctx = research_symbol_web(symbol, focus="analysis dividend risk")
    if web_ctx:
        intel = f"{intel}\n\n{web_ctx}" if intel else web_ctx

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

Keep under 300 words. Be specific with numbers and dates. Flag anything not present in CONTEXT as [unverified]."""

    # Screener discoveries: prefer local gemma; conflicts/decisions may use cloud.
    high_impact = trigger_kind in ("agent_conflict", "high_impact_decision")
    result = get_llm_response("cio_synthesis", prompt, max_tokens=600, high_impact=high_impact)

    if not result.get("success"):
        return {"error": "LLM failed", "symbol": symbol}

    research = result["response"]
    provider = result.get("provider")
    model_used = result.get("model_used")

    strategy_type = None
    m = re.search(r"\(([^)]+)\)\s*$", reason)
    if m:
        strategy_type = m.group(1)

    payload = {
        "reason": reason,
        "trigger_kind": trigger_kind,
        "provider": provider,
        "model_used": model_used,
        "cost": result.get("cost_estimate", 0),
        "research_preview": research[:500],
        "research": research[:8000],
        "pipeline": "trade_ai_auto_research",
        "hermes": False,
        "web_search_ok": bool(web_ctx),
    }

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO portfolio_intelligence_events
            (symbol, event_type, severity, source, payload)
        VALUES (%s, 'auto_research', 'info', 'auto_research.py', %s)
    """, (symbol, json.dumps(payload, default=str)))
    conn.commit()
    conn.close()

    try:
        _persist_research_topic(symbol, reason, research, strategy_type)
    except Exception as e:
        print(f"[auto-research] topic persist failed for {symbol}: {e}")

    if trigger_kind in ("new_discovery", "agent_conflict"):
        _queue_agent_reviews(symbol, f"Auto-research {trigger_kind}: {reason[:180]}")

    if trigger_kind in ("new_discovery", "manual") or "screener" in (reason or "").lower():
        _sync_screener_find_pin(symbol, reason=reason, strategy_type=strategy_type,
                                brief_snippet=research[:800])

    return {
        "symbol": symbol,
        "reason": reason,
        "trigger_kind": trigger_kind,
        "research": research,
        "provider": provider,
        "model_used": model_used,
        "cost": result.get("cost_estimate", 0),
        "queued_agents": True,
    }


def run_check(send_telegram: bool = False):
    """Find triggers and auto-research the top priorities."""
    triggers = find_research_triggers()
    print(f"[auto-research] Found {len(triggers)} research triggers")

    if not triggers:
        return {"triggers": 0, "researched": 0}

    researched = 0
    results = []
    for t in sorted(triggers, key=lambda x: x["priority"])[:3]:
        print(f"  Researching: {t['symbol']} ({t['reason']})")
        result = research_symbol(t["symbol"], t["detail"], t["reason"])
        if not result.get("error"):
            researched += 1
            results.append(result)

    if send_telegram and results:
        lines = ["\U0001F50D *Auto-Research Complete*", ""]
        for r in results:
            lines.append(f"*{r['symbol']}* ({r['reason'][:30]})")
            lines.append(f"_{r['research'][:150]}..._")
            lines.append("")
        prov = results[0].get("provider", "?")
        model = results[0].get("model_used") or ""
        lines.append(
            f"_via {prov}{(' · ' + model) if model else ''} · Trade AI auto_research (not Hermes) · "
            f"/v3/intelligence?tab=research · /v3/reports?super=intel&category=research_"
        )
        _send_tg("\n".join(lines))

    print(f"[auto-research] Researched {researched}/{len(triggers)} triggers")
    return {"triggers": len(triggers), "researched": researched, "results": results}


def backfill_screener_finds(days: int = 14) -> int:
    """Pin recent auto-research screener finds that still have buy-side CIO verdicts."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(f"""
        SELECT DISTINCT ON (symbol) symbol, payload, created_at
        FROM portfolio_intelligence_events
        WHERE event_type = 'auto_research'
          AND created_at > NOW() - INTERVAL '{int(days)} days'
        ORDER BY symbol, created_at DESC
    """)
    n = 0
    for r in cur.fetchall():
        sym = str(r["symbol"] or "").upper()
        payload = r.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        reason = str(payload.get("reason") or "auto_research")
        st = None
        m = re.search(r"\(([^)]+)\)\s*$", reason)
        if m:
            st = m.group(1)
        brief = str(payload.get("research") or payload.get("research_preview") or "")
        if _sync_screener_find_pin(sym, reason=reason, strategy_type=st,
                                   brief_snippet=brief, auto_research_at=r.get("created_at")):
            n += 1
            print(f"[backfill] pinned {sym} (buy-side CIO)")
        else:
            print(f"[backfill] skipped {sym} (CIO not buy-side)")
    conn.close()
    print(f"[auto-research] Screener-find pins active: {n}")
    return n


def backfill_from_outbox(limit: int = 5) -> int:
    """Re-hydrate user_research_topics from captured Telegram outbox bodies."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, body, sent_at FROM telegram_outbox
        WHERE report_type = 'auto_research' AND ok = TRUE
        ORDER BY sent_at DESC LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    n = 0
    for _id, body, sent_at in rows:
        if not body:
            continue
        for m in re.finditer(r"\*([A-Z]{1,5})\*\s*\(([^)]+)\)\s*\n(_(.+?)_\s*)?", body, re.DOTALL):
            sym, reason = m.group(1), m.group(2)
            chunk = (m.group(4) or "").strip().strip("_")
            if not chunk:
                continue
            full = chunk.replace("...", "")
            detail = f"New screener find: {sym}" if "screener" in reason.lower() else reason
            try:
                _persist_research_topic(sym, detail, full)
                n += 1
            except Exception as e:
                print(f"[backfill] {sym}: {e}")
    conn.close()
    print(f"[auto-research] Backfilled {n} topic(s) from telegram_outbox")
    return n


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    if "--backfill-screener-finds" in sys.argv:
        backfill_screener_finds()
    elif "--backfill-outbox" in sys.argv:
        backfill_from_outbox()
    elif "--check" in sys.argv:
        run_check(send_telegram=tg)
    elif "--research" in sys.argv:
        idx = sys.argv.index("--research")
        if idx + 1 < len(sys.argv):
            symbol = sys.argv[idx + 1].upper()
            result = research_symbol(symbol, "manual", "manual")
            if result.get("research"):
                print(result["research"])
            else:
                print(f"Error: {result.get('error')}")
        else:
            print("Usage: --research SYMBOL")
    else:
        print("Usage:")
        print("  --check [--telegram]    Find triggers and auto-research top 3")
        print("  --research SYMBOL       Deep research a specific symbol")
        print("  --backfill-outbox       Hydrate Intelligence tab from telegram_outbox")
        print("  --backfill-screener-finds  Pin buy-side screener finds into Watchlist lane")