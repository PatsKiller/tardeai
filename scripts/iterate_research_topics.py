#!/usr/bin/env python3
"""iterate_research_topics.py — Re-research active user topics and send updates.

Acts as a full CIO research analyst across all asset classes (equities, ETFs,
bonds, options income, macro, crypto/commodities, retirement), grounded in
portfolio context. Finds new articles, updated advice, and actionable options
for each saved research interest.

Usage:
    python3 scripts/iterate_research_topics.py [--telegram] [--json]
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def iterate_topics(send_telegram: bool = False) -> list:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get active topics that haven't been researched in >24h (or never)
    cur.execute("""
        SELECT * FROM user_research_topics
        WHERE status = 'active'
        AND (last_researched_at IS NULL OR last_researched_at < NOW() - INTERVAL '24 hours')
        ORDER BY priority DESC, last_researched_at NULLS FIRST
        LIMIT 5
    """)
    topics = cur.fetchall()

    if not topics:
        print("[iterate] No topics due for research")
        conn.close()
        return []

    results = []
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

    for t in topics:
        topic = t["topic"]
        prev = t.get("latest_findings", "")
        count = t.get("research_count", 0)

        # Engine Room v1 provenance parity (WS-2): ground each iteration in
        # current web sources and persist them to sources_json — sourceless
        # briefs render as "wire". Mirrors auto_research._persist_research_topic.
        # Degrades gracefully (empty → sources_json untouched) when the search
        # budget is exhausted.
        web_block, web_sources = "", None
        try:
            from web_research import search_web
            _hits = search_web(topic, count=5, freshness="pm")
            if _hits:
                _lines = [f"CURRENT WEB CONTEXT ({len(_hits)} results):"]
                for _h in _hits[:6]:
                    _lines.append(f"  [{_h.get('age') or ''}] {(_h.get('title') or '')[:80]}")
                    if _h.get("description"):
                        _lines.append(f"    {_h['description'][:120]}")
                web_block = "\n".join(_lines)
                web_sources = [{"title": (_h.get("title") or "")[:120],
                                "url": _h.get("url"), "as_of": _h.get("age") or None}
                               for _h in _hits[:8]]
        except Exception as _e:
            print(f"[iterate] {topic}: web grounding unavailable: {_e}")

        prompt = f"""/no_think You are a CIO research analyst covering all asset classes
(equities, ETFs, bonds, covered-call/put-selling income, macro/Fed, international,
crypto/commodities, and retirement planning). Provide an updated research advisory.

ONGOING RESEARCH TOPIC: {topic}
{web_block}

PORTFOLIO CONTEXT:
- $1.2M across 4 accounts (Fidelity 401k, Schwab Rollover IRA, Schwab Roth IRA, Schwab Taxable)
- Income target: $55K/yr. Current: $14,342/yr. Gap: $40,658.
- Income generators at 9.2% (target 25-40%). Core compounders at 42%.
- Timeline: 4-8 years to retirement income goal.
- Mandate: multi-asset CIO book — growth/value/small-cap, broad+sector+thematic ETFs,
  bonds (agg/corp/muni/Treasury), options-income ETFs, hedges, macro, international.

This is research iteration #{count + 1}. {"Previous findings: " + prev[:300] + "..." if prev else "First research on this topic."}

Provide:
1. What's new or changed since last advisory (across relevant asset classes)
2. Specific actionable recommendations (symbols/ETFs/strategies when evidence-backed)
3. Account-specific placement advice (IRA vs Roth vs Taxable) when tax-relevant
4. Risk considerations and portfolio fit
5. Next steps to investigate

Keep it concise (3-4 paragraphs) and actionable."""

        try:
            from llm_router import get_llm_response
            result = get_llm_response("agent_narrative", prompt, max_tokens=600)

            if result.get("success"):
                response = result["response"]

                # Reports v3 WS-C: strip conversational preamble at WRITE time; preamble-only
                # output degrades to the honest "research pending" stub — filler never becomes
                # findings. (This writer previously bypassed the shared QA lint entirely.)
                from research_intelligence_qa_lint import clean_advisory
                response, _clean_meta = clean_advisory(response, iteration=count + 1)
                if _clean_meta.get("stripped") or _clean_meta.get("degraded"):
                    print(f"[iterate] {topic}: preamble stripped"
                          f"{' → degraded to pending stub' if _clean_meta.get('degraded') else ''}")

                # Update topic
                cur.execute("""
                    UPDATE user_research_topics
                    SET latest_findings = %s, latest_finding_at = now(),
                        research_count = research_count + 1, last_researched_at = now(),
                        sources_json = COALESCE(%s::jsonb, sources_json),
                        updated_at = now()
                    WHERE id = %s
                """, (response[:2000],
                      json.dumps(web_sources) if web_sources else None,
                      t["id"]))

                # Intelligence event
                cur.execute("""
                    INSERT INTO portfolio_intelligence_events
                        (event_type, severity, source, payload)
                    VALUES ('research_iteration', 'info', 'iterate_research_topics.py', %s)
                """, (json.dumps({"topic_id": t["id"], "topic": topic,
                                   "iteration": count + 1, "provider": result.get("provider")}, default=str),))

                results.append({
                    "topic_id": t["id"],
                    "topic": topic,
                    "iteration": count + 1,
                    "provider": result.get("provider"),
                    "cost": result.get("cost_estimate", 0),
                    "response_preview": response[:200],
                })

                # Send Telegram update if requested
                if send_telegram:
                    msg = f"*Research Update: {topic}*\n(Iteration #{count + 1})\n\n{response[:1200]}\n\n_via {result.get('provider')} (${result.get('cost_estimate', 0):.4f})_"
                    try:
                        from telegram_alert import send_telegram as _send
                        _send(msg)
                    except Exception:
                        pass

                print(f"  [{t['id']}] {topic[:40]}... → {result.get('provider')} (#{count + 1})")
        except Exception as e:
            print(f"  [{t['id']}] Error: {e}")

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    results = iterate_topics(send_telegram=tg)
    print(f"[iterate] Processed {len(results)} topics")
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
