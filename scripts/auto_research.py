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


def _ensure_symbol_profiles(symbols: list) -> int:
    """Seed symbol_profiles rows so agent jobs pass the fail-closed ticker gate."""
    import subprocess
    syms = sorted({str(s or "").upper().strip() for s in symbols if str(s or "").strip()})
    if not syms:
        return 0
    conn = _get_conn()
    cur = conn.cursor()
    missing = []
    for sym in syms:
        cur.execute("SELECT 1 FROM symbol_profiles WHERE upper(symbol)=upper(%s) LIMIT 1", (sym,))
        if not cur.fetchone():
            missing.append(sym)
    conn.close()
    if not missing:
        return 0
    print(f"[auto-research] Building symbol_profiles for {len(missing)} symbol(s): {', '.join(missing)}")
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_symbol_profiles.py"),
         "--symbols", ",".join(missing), "--force"],
        cwd=str(PROJECT_ROOT), check=False, capture_output=True, text=True,
    )
    return len(missing)


def _queue_agent_reviews(symbol: str, note: str) -> int:
    """Queue maria/steph/risk when auto-research fires but agents never wrote results."""
    _ensure_symbol_profiles([symbol])
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
            VALUES (%s, %s, %s, 'full_analysis', 0, %s, 'queued', 'auto_research.py')
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


def _screener_find_candidates(all_time: bool = True, days: int = 14) -> list:
    """Collect historical screener-find symbols from every source (deduped, richest row wins)."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    found: dict[str, dict] = {}

    def _add(sym, reason="", strategy_type=None, brief="", at=None, source=""):
        sym = str(sym or "").upper().strip()
        if not sym or len(sym) > 5:
            return
        row = {
            "symbol": sym,
            "reason": (reason or "")[:500],
            "strategy_type": strategy_type,
            "brief_snippet": (brief or "")[:800],
            "auto_research_at": at,
            "source": source,
        }
        prev = found.get(sym)
        if not prev or (at and (not prev.get("auto_research_at") or at > prev["auto_research_at"])):
            found[sym] = row

    # 1. auto_research intelligence events (screener finds + new discoveries)
    time_clause = "" if all_time else f"AND created_at > NOW() - INTERVAL '{int(days)} days'"
    cur.execute(f"""
        SELECT DISTINCT ON (symbol) symbol, payload, created_at
        FROM portfolio_intelligence_events
        WHERE event_type = 'auto_research' {time_clause}
        ORDER BY symbol, created_at DESC
    """)
    for r in cur.fetchall():
        payload = r.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        reason = str(payload.get("reason") or "")
        trigger = str(payload.get("trigger_kind") or "")
        if "screener" not in reason.lower() and trigger != "new_discovery":
            continue
        st = None
        m = re.search(r"\(([^)]+)\)", reason)
        if m:
            st = m.group(1)
        brief = str(payload.get("research") or payload.get("research_preview") or "")
        _add(r["symbol"], reason or "auto_research", st, brief, r.get("created_at"), "event")

    # 2. user_research_topics from auto_research.py (telegram briefs)
    cur.execute("""
        SELECT topic, original_message, latest_findings, updated_at
        FROM user_research_topics
        WHERE source = 'auto_research.py'
    """)
    for r in cur.fetchall():
        m = re.search(r"Auto-research:\s*([A-Z]{1,5})", r.get("topic") or "")
        if not m:
            continue
        msg = str(r.get("original_message") or "")
        if "screener" not in msg.lower():
            continue
        st = None
        sm = re.search(r"\(([^)]+)\)", msg)
        if sm:
            st = sm.group(1)
        _add(m.group(1), msg, st, r.get("latest_findings") or "", r.get("updated_at"), "topic")

    # 3. telegram_outbox auto_research bodies (all historical nightly runs)
    cur.execute("""
        SELECT body, sent_at FROM telegram_outbox
        WHERE report_type = 'auto_research' AND ok = TRUE
        ORDER BY sent_at DESC
    """)
    for r in cur.fetchall():
        body = str(r.get("body") or "")
        for m in re.finditer(r"\*([A-Z]{1,5})\*\s*\(([^)]+)\)", body):
            sym, reason = m.group(1), m.group(2)
            if "screener" not in reason.lower() and "find" not in reason.lower():
                continue
            st = None
            sm = re.search(r"\(([^)]+)\)", reason)
            if sm:
                st = sm.group(1)
            _add(sym, f"New screener find: {sym} ({reason})", st, "", r.get("sent_at"), "outbox")

    # 4. incubator-active screener promotions (Finviz → watchlist bus)
    cur.execute("""
        SELECT wi.symbol, wi.trigger_source, wi.last_trigger_at,
               tsc.strategy_type
        FROM watchlist_items wi
        LEFT JOIN ticker_strategy_classifications tsc
               ON wi.symbol = tsc.symbol AND tsc.active = TRUE
        WHERE wi.source = 'ai_discovered'
          AND wi.status <> 'removed'
          AND wi.trigger_source ILIKE '%incubator_active%'
          AND wi.last_trigger_at > NOW() - INTERVAL '90 days'
    """)
    for r in cur.fetchall():
        reason = f"Incubator screener promotion: {r['symbol']}"
        if r.get("strategy_type"):
            reason += f" ({r['strategy_type']})"
        _add(r["symbol"], reason, r.get("strategy_type"), "",
             r.get("last_trigger_at"), "incubator")

    conn.close()
    return sorted(found.values(), key=lambda x: x.get("auto_research_at") or "", reverse=True)


def backfill_screener_finds(days: int = 14, all_time: bool = True) -> int:
    """Pin screener finds that still have buy-side CIO verdicts.

    Sources (all_time=True): auto_research events, research topics, telegram outbox,
    and incubator-active screener promotions (90d). Pins deactivate automatically when
    CIO drifts off buy-side.
    """
    candidates = _screener_find_candidates(all_time=all_time, days=days)
    print(f"[backfill] Evaluating {len(candidates)} historical screener-find candidate(s)")
    pinned, skipped = [], []
    for c in candidates:
        sym = c["symbol"]
        if _sync_screener_find_pin(
            sym,
            reason=c.get("reason") or "screener_find",
            strategy_type=c.get("strategy_type"),
            brief_snippet=c.get("brief_snippet") or "",
            auto_research_at=c.get("auto_research_at"),
        ):
            pinned.append(sym)
            print(f"[backfill] pinned {sym} ({c.get('source')})")
        else:
            skipped.append(sym)
            print(f"[backfill] skipped {sym} — CIO not buy-side ({c.get('source')})")
    print(f"[auto-research] Active pins: {len(pinned)} | skipped (non-buy-side): {len(skipped)}")
    if pinned:
        print(f"[auto-research] Pinned: {', '.join(sorted(set(pinned)))}")
    repair_screener_find_agents(pinned)
    return len(pinned)


def repair_screener_find_agents(symbols: list = None) -> int:
    """Ensure symbol_profiles + queue agent reviews for screener-find pins missing LLM results."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if symbols:
        syms = sorted({str(s).upper() for s in symbols})
    else:
        cur.execute("SELECT symbol FROM screener_find_pins WHERE active = true")
        syms = sorted(r["symbol"] for r in cur.fetchall())
    _ensure_symbol_profiles(syms)
    queued_total = 0
    for sym in syms:
        cur.execute(
            "SELECT COUNT(*) AS c FROM watchlist_agent_results "
            "WHERE symbol=%s AND created_at > NOW() - INTERVAL '30 days'",
            (sym,),
        )
        if (cur.fetchone() or {}).get("c", 0) > 0:
            continue
        n = _queue_agent_reviews(sym, f"Screener-find repair: {sym} — profile + agent backfill")
        queued_total += n
        if n:
            print(f"[repair] queued {n} agent job(s) for {sym}")
    conn.close()
    print(f"[auto-research] Agent repair queued {queued_total} job(s) across screener-find pins")
    return queued_total


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
    if "--repair-screener-agents" in sys.argv:
        repair_screener_find_agents()
    elif "--backfill-screener-finds" in sys.argv:
        _days = 14
        if "--days" in sys.argv:
            try:
                _days = int(sys.argv[sys.argv.index("--days") + 1])
            except (ValueError, IndexError):
                pass
        _all = "--days" not in sys.argv
        backfill_screener_finds(days=_days, all_time=_all)
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
        print("  --repair-screener-agents  Build profiles + queue agent jobs for active pins")
        print("  --backfill-screener-finds  Pin all historical buy-side screener finds")
        print("  --backfill-screener-finds --days N  Limit event scan to last N days")