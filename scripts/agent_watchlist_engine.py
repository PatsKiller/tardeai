#!/usr/bin/env python3
"""agent_watchlist_engine.py — Qualified intelligence + watchlist proposals + discovery summaries.

Three jobs:
1. Promote high-quality intel to qualified_intelligence (Q≥70, ai_validated)
2. Propose watchlist adds from qualified intel (symbols not yet tracked)
3. Generate daily "What I Discovered" summary

Usage:
    python3 scripts/agent_watchlist_engine.py --promote          # Promote high-Q intel
    python3 scripts/agent_watchlist_engine.py --propose          # Propose watchlist adds
    python3 scripts/agent_watchlist_engine.py --discovery [--telegram]  # Daily discovery summary
    python3 scripts/agent_watchlist_engine.py --all [--telegram]
    python3 scripts/agent_watchlist_engine.py --test
    python3 scripts/agent_watchlist_engine.py --status
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Advisory cloud-review cap (ADDITIVE — gated behind CLOUD_REVIEW=1)
_CLOUD_REVIEW_CAP = 5
_cloud_review_count = 0


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_tg(msg):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


# ── Job 1: Promote high-quality intel ────────────────────────────────

def promote_qualified_intel() -> dict:
    """5-level whiteboard curation pipeline. Local-first, multi-day, multi-source.

    Level 0: Raw — ingest from any source (news, YouTube, SEC, Finviz)
    Level 1: Scored — keyword + quality scoring (no external LLM)
    Level 2: Iterating — multi-day, cross-source aggregation (2+ sources = higher credibility)
    Level 3: Validated — local analysis + embedding similarity + due diligence
    Level 4: Promoted — dashboard-ready (appears in agent modals)
    Level 5: Synthesized — full agent debate + Alex review (Claude only)

    Promotion rules:
      L0→L1: auto (on ingest, scored by content_scoring.py)
      L1→L2: quality_score ≥ 50 AND days_on_board ≥ 1
      L2→L3: (days_on_board ≥ 2 AND sources_count ≥ 2) OR (days_on_board ≥ 3 AND quality_score ≥ 75)
      L3→L4: quality_score ≥ 75 AND credibility_score ≥ 0.6 AND symbol NOT NULL
      L4→L5: agent debate consensus ≥ 50% (run by proactive_intel_scan)
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ucur = conn.cursor()
    counts = {"L0_staged": 0, "L1_scored": 0, "L2_iterating": 0, "L3_validated": 0, "L4_promoted": 0}

    # ── L0: Stage new raw items to whiteboard ───────────────────────────
    # News (relevance ≥ 0.5 — wider net for whiteboard)
    cur.execute("""SELECT id, symbol, title, source, relevance_score, strategy_tags
        FROM news_articles WHERE relevance_score >= 0.5
          AND id NOT IN (SELECT source_id FROM intelligence_whiteboard WHERE source_type='news')
          AND id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='news')
        ORDER BY relevance_score DESC LIMIT 80""")
    for r in cur.fetchall():
        q = int(float(r["relevance_score"]) * 100)
        ucur.execute("""INSERT INTO intelligence_whiteboard
            (source_type, source_id, symbol, title, summary, quality_score, confidence, status, level)
            VALUES ('news', %s, %s, %s, %s, %s, %s, 'raw', 0) ON CONFLICT DO NOTHING""",
            (r["id"], r["symbol"], r["title"][:200], r["title"][:200], q, float(r["relevance_score"])))
        counts["L0_staged"] += 1

    # YouTube (Q ≥ 40 — wide net)
    cur.execute("""SELECT id, title, channel_name, quality_score, relevance_score, summary
        FROM youtube_transcripts WHERE quality_score >= 40
          AND id NOT IN (SELECT source_id FROM intelligence_whiteboard WHERE source_type='youtube')
          AND id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='youtube')
        ORDER BY quality_score DESC LIMIT 80""")
    for r in cur.fetchall():
        ucur.execute("""INSERT INTO intelligence_whiteboard
            (source_type, source_id, symbol, title, summary, quality_score, confidence, status, level)
            VALUES ('youtube', %s, NULL, %s, %s, %s, %s, 'raw', 0) ON CONFLICT DO NOTHING""",
            (r["id"], r["title"][:200], (r.get("summary") or r["title"])[:500],
             r["quality_score"], float(r["relevance_score"])))
        counts["L0_staged"] += 1

    # SEC Form 4 (always stage)
    cur.execute("""SELECT id, symbol, filer_name, transaction_type FROM sec_form4
        WHERE id NOT IN (SELECT source_id FROM intelligence_whiteboard WHERE source_type='sec_form4')
          AND id NOT IN (SELECT source_id FROM qualified_intelligence WHERE source_type='sec_form4')""")
    for r in cur.fetchall():
        ucur.execute("""INSERT INTO intelligence_whiteboard
            (source_type, source_id, symbol, title, quality_score, confidence, status, level)
            VALUES ('sec_form4', %s, %s, %s, 80, 0.8, 'raw', 0) ON CONFLICT DO NOTHING""",
            (r["id"], r["symbol"], f"Form 4: {r['filer_name']} {r['transaction_type']}"[:200]))
        counts["L0_staged"] += 1
    conn.commit()

    # ── Update days_on_board for everything ─────────────────────────────
    ucur.execute("UPDATE intelligence_whiteboard SET days_on_board = GREATEST(0, EXTRACT(DAY FROM NOW() - first_seen_at)::int)")
    conn.commit()

    # ── L0 → L1: Auto-score (quality_score already set on ingest) ──────
    ucur.execute("""UPDATE intelligence_whiteboard SET
        level = 1, status = 'scored', level_changed_at = NOW()
        WHERE level = 0 AND quality_score > 0""")
    counts["L1_scored"] = cur.connection.info.transaction_status  # placeholder
    conn.commit()
    cur.execute("SELECT count(*) FROM intelligence_whiteboard WHERE level = 1 AND status = 'scored'")
    counts["L1_scored"] = cur.fetchone()["count"]

    # ── L1 → L2: Quality ≥ 50 AND days ≥ 1 ─────────────────────────────
    # Also detect cross-source aggregation (same symbol from 2+ types)
    ucur.execute("""UPDATE intelligence_whiteboard wb SET
        sources_count = COALESCE(sub.cnt, 1),
        credibility_score = LEAST(1.0, COALESCE(sub.cnt, 1) * 0.3 + quality_score / 200.0)
        FROM (SELECT symbol, count(DISTINCT source_type) as cnt
              FROM intelligence_whiteboard WHERE symbol IS NOT NULL
              GROUP BY symbol) sub
        WHERE wb.symbol = sub.symbol""")

    ucur.execute("""UPDATE intelligence_whiteboard SET
        level = 2, status = 'iterating', level_changed_at = NOW(), last_iterated_at = NOW()
        WHERE level = 1 AND quality_score >= 50 AND days_on_board >= 1""")
    conn.commit()
    cur.execute("SELECT count(*) FROM intelligence_whiteboard WHERE level = 2")
    counts["L2_iterating"] = cur.fetchone()["count"]

    # ── L2 → L3: Multi-source + time gate ───────────────────────────────
    ucur.execute("""UPDATE intelligence_whiteboard SET
        level = 3, status = 'validated', level_changed_at = NOW()
        WHERE level = 2
          AND ((days_on_board >= 2 AND sources_count >= 2) OR (days_on_board >= 3 AND quality_score >= 75))""")
    conn.commit()
    cur.execute("SELECT count(*) FROM intelligence_whiteboard WHERE level = 3")
    counts["L3_validated"] = cur.fetchone()["count"]

    # ── L3 → L4: Promote to qualified_intelligence (dashboard) ──────────
    cur.execute("""SELECT DISTINCT ON (symbol) id, source_type, source_id, symbol, title, quality_score, confidence
        FROM intelligence_whiteboard
        WHERE level = 3 AND quality_score >= 75 AND credibility_score >= 0.6 AND symbol IS NOT NULL
          AND symbol NOT IN (SELECT symbol FROM qualified_intelligence WHERE symbol IS NOT NULL)
        ORDER BY symbol, quality_score DESC""")
    for r in cur.fetchall():
        # Look up strategy_focus from ticker_strategy_classifications
        strat = None
        if r.get("symbol"):
            scur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            scur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=true LIMIT 1", (r["symbol"],))
            srow = scur.fetchone()
            strat = srow["strategy_type"] if srow else "position_monitoring"
            scur.close()
        # Validation: strategy_focus must NOT be a YouTube channel name
        if strat:
            vcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            vcur.execute("SELECT 1 FROM youtube_channels WHERE channel_name=%s LIMIT 1", (strat,))
            if vcur.fetchone():
                strat = "position_monitoring"  # was incorrectly set to channel name
            vcur.close()
        ucur.execute("""INSERT INTO qualified_intelligence
            (source_type, source_table, source_id, symbol, title, quality_score, relevance_score, strategy_focus)
            VALUES (%s, 'intelligence_whiteboard', %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (r["source_type"], r["source_id"], r["symbol"], r["title"][:200],
             r["quality_score"], float(r["confidence"] or 0), strat))
        ucur.execute("UPDATE intelligence_whiteboard SET level=4, status='promoted', promoted_at=NOW(), promoted_by='curation_engine', level_changed_at=NOW() WHERE id=%s", (r["id"],))
        counts["L4_promoted"] += 1
    conn.commit()

    # ── Stats ───────────────────────────────────────────────────────────
    cur.execute("SELECT level, status, count(*) as cnt FROM intelligence_whiteboard GROUP BY level, status ORDER BY level, status")
    level_stats = {}
    for r in cur.fetchall():
        level_stats[f"L{r['level']}_{r['status']}"] = r["cnt"]
    conn.close()

    print(f"[whiteboard] Pipeline: staged={counts['L0_staged']} scored={counts['L1_scored']} iterating={counts['L2_iterating']} validated={counts['L3_validated']} promoted={counts['L4_promoted']}")
    print(f"[whiteboard] Levels: {level_stats}")
    return {"counts": counts, "levels": level_stats}


# ── Job 2: Propose watchlist adds ────────────────────────────────────

def propose_watchlist_adds() -> dict:
    """Find symbols in qualified intel that aren't on watchlist, propose additions."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Symbols in qualified intel but not on watchlist
    cur.execute("""
        SELECT qi.symbol, count(*) as mentions, avg(qi.quality_score) as avg_q,
               array_agg(DISTINCT qi.strategy_focus) as strategies,
               array_agg(qi.id) as intel_ids
        FROM qualified_intelligence qi
        WHERE qi.symbol != '' AND qi.symbol IS NOT NULL
          AND qi.symbol NOT IN (SELECT symbol FROM watchlist_items)
          AND qi.symbol NOT IN (SELECT symbol FROM watchlist_proposals WHERE status='proposed')
        GROUP BY qi.symbol
        HAVING count(*) >= 2
        ORDER BY avg(qi.quality_score) DESC
        LIMIT 10
    """)
    proposals = cur.fetchall()

    ucur = conn.cursor()
    proposed = 0
    for p in proposals:
        strat = [s for s in (p["strategies"] or []) if s]
        strategy = strat[0] if strat else "core_growth_compounder"
        ucur.execute("""INSERT INTO watchlist_proposals
            (symbol, action, strategy_type, reason, source_intel_ids, confidence, proposed_by)
            VALUES (%s, 'add', %s, %s, %s, %s, 'agent_watchlist_engine')
            ON CONFLICT DO NOTHING""",
            (p["symbol"], strategy,
             f"{p['mentions']} qualified intel mentions, avg Q:{float(p['avg_q']):.0f}",
             list(p["intel_ids"][:10]) if p.get("intel_ids") else [], float(p["avg_q"]) / 100))
        proposed += 1

    conn.commit()
    conn.close()
    print(f"[propose] Created {proposed} watchlist proposals")
    return {"proposed": proposed}


# ── Job 3: Daily discovery summary ───────────────────────────────────

def generate_discovery_summary(send_telegram: bool = False) -> dict:
    """Alex generates 'What I Discovered Today' from qualified intel."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Today's qualified intel
    cur.execute("""
        SELECT source_type, title, symbol, quality_score, retirement_relevance, strategy_focus
        FROM qualified_intelligence
        WHERE discovered_at > CURRENT_DATE
        ORDER BY quality_score DESC LIMIT 15
    """)
    items = cur.fetchall()

    # Pending proposals
    cur.execute("SELECT symbol, strategy_type, confidence FROM watchlist_proposals WHERE status='proposed'")
    proposals = cur.fetchall()

    conn.close()

    if not items and not proposals:
        print("[discovery] Nothing new today")
        return {"items": 0, "proposals": 0}

    # Build summary
    lines = [f"\U0001F4A1 *Alex: What I Discovered Today*", f"_{datetime.now().strftime('%B %d, %Y')}_", ""]

    if items:
        lines.append(f"*{len(items)} high-quality intelligence items:*")
        for item in items[:8]:
            src = item["source_type"][0].upper()
            q = item["quality_score"]
            sym = f" ({item['symbol']})" if item["symbol"] else ""
            rel = item.get("retirement_relevance", "")
            rel_badge = " \U0001F3AF" if rel == "high" else ""
            lines.append(f"  [{src}] Q:{q}{rel_badge} {item['title'][:55]}{sym}")

    if proposals:
        lines.append("")
        lines.append(f"*{len(proposals)} watchlist proposals (pending review):*")
        for p in proposals[:5]:
            lines.append(f"  {p['symbol']} ({p['strategy_type'].replace('_',' ')}) conf:{float(p['confidence']):.0%}")

    summary_text = "\n".join(lines)

    # Store in discovery log
    try:
        conn = _get_conn()
        cur = conn.cursor()
        symbols = list(set(i["symbol"] for i in items if i.get("symbol")))
        cur.execute("""INSERT INTO agent_discovery_log (discovery_type, title, summary, symbols_mentioned, intel_count)
            VALUES ('daily', %s, %s, %s, %s)""",
            (f"Daily Discovery — {datetime.now().strftime('%Y-%m-%d')}",
             summary_text[:2000], json.dumps(symbols[:20]), len(items)))
        conn.commit()
        conn.close()
    except Exception:
        pass

    if send_telegram:
        _send_tg(summary_text)

    print(f"[discovery] {len(items)} items, {len(proposals)} proposals")
    print(summary_text)
    return {"items": len(items), "proposals": len(proposals)}


# ── Improvement #5: Sector Correlation Detection ────────────────────
# When 3+ events in the same batch share a sector/strategy, it's likely
# a correlated macro move — not individual thesis breaks.
# Example: TDG, LHX, LMT, NOC all triggering = defense sector event.
# This fires a SECTOR_CORRELATION_ALERT so Maria investigates the macro cause.

STRATEGY_SECTORS = {
    "defense_thesis": "defense",
    "dividend_growth_compounder": "dividend growth",
    "high_yield_income_bdc": "high yield income",
    "core_growth_compounder": "core growth",
    "swing_trade": "swing trade",
    "day_scalp": "scalp",
    "retirement_planning": "retirement",
    "covered_call_income": "covered call",
    "bond_income": "bonds",
    "reit_income": "REIT",
}


def get_symbol_strategy(symbol: str) -> str:
    """Look up a symbol's strategy from watchlist or holdings."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT strategy_type FROM watchlist_strategy_cards
            WHERE symbol = %s ORDER BY created_at DESC LIMIT 1
        """, (symbol.upper(),))
        row = cur.fetchone()
        if not row:
            cur.execute("""
                SELECT strategy FROM watchlist_items
                WHERE symbol = %s LIMIT 1
            """, (symbol.upper(),))
            row = cur.fetchone()
        conn.close()
        return (row[0] or "unknown") if row else "unknown"
    except Exception:
        return "unknown"


def detect_sector_correlation(symbols: list) -> dict | None:
    """Check if 3+ symbols in a batch share the same sector/strategy.

    Returns a correlation alert dict if found, None otherwise.
    Called by agent_event_router after collecting a batch of events.

    Args:
        symbols: List of ticker symbols from the current event batch

    Returns:
        dict with sector, symbols, count, note — or None if no correlation
    """
    if len(symbols) < 3:
        return None

    from collections import Counter
    symbol_strategies = {}
    for sym in symbols:
        if sym:
            symbol_strategies[sym] = get_symbol_strategy(sym)

    # Count by sector
    sector_counts = Counter(s for s in symbol_strategies.values() if s != "unknown")
    for sector, count in sector_counts.most_common(1):
        if count >= 3:
            correlated_symbols = [s for s, strat in symbol_strategies.items() if strat == sector]
            sector_label = STRATEGY_SECTORS.get(sector, sector.replace("_", " "))
            return {
                "event_type": "SECTOR_CORRELATION_ALERT",
                "sector": sector,
                "sector_label": sector_label,
                "symbols": correlated_symbols,
                "count": count,
                "priority": "urgent",
                "agents_to_notify": ["Maria", "Risk"],
                "note": (
                    f"{count} of today's triggered events are {sector_label} sector "
                    f"({', '.join(correlated_symbols)}). "
                    f"This may be a correlated macro move — not individual thesis breaks. "
                    f"Maria: investigate the macro catalyst before individual analyses."
                ),
            }
    return None


def insert_sector_correlation_event(correlation: dict):
    """Insert a SECTOR_CORRELATION_ALERT into agent_event_queue."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        import json as _json
        cur.execute("""
            INSERT INTO agent_event_queue
                (event_type, symbol, trigger_data, agents_to_notify, priority, status)
            VALUES (%s, NULL, %s, %s, 'urgent', 'pending')
            ON CONFLICT DO NOTHING
        """, (
            "SECTOR_CORRELATION_ALERT",
            _json.dumps({
                "sector": correlation["sector"],
                "sector_label": correlation["sector_label"],
                "symbols": correlation["symbols"],
                "count": correlation["count"],
                "note": correlation["note"],
            }),
            correlation["agents_to_notify"],
        ))
        conn.commit()
        conn.close()
        print(f"  [sector] SECTOR_CORRELATION_ALERT: {correlation['sector_label']} "
              f"({correlation['count']} symbols: {', '.join(correlation['symbols'])})")
    except Exception as e:
        print(f"  [sector] Error inserting correlation alert: {e}")


# ── Job 3b: Multi-agent debate for high-confidence intel ─────────────

def run_agent_debate(symbol: str, trigger_title: str, trigger_id: int = 0,
                     trigger_source: str = "qualified_intelligence") -> dict:
    """Run Maria/Steph/Risk debate on a symbol. Two rounds when agents disagree.

    Round 1: Each agent gives their independent view (original behavior).
    Round 2: ONLY if max divergence > 0.30 — each agent responds to the
             highest-disagreement point from Round 1. This resolves LMT-style
             conflicts where Risk says HOLD and Steph says TRIM — Round 2 lets
             Risk see Steph's specific heat/stop-breach argument and potentially update.

    Improvement #3: Counter-argument round added May 2026.
    Cost: 3 extra LLM calls (~$0.001) only when agents meaningfully disagree.
    """
    try:
        from llm_router import get_llm_response
        from intel_query import get_portfolio_heat_context, get_market_session_context

        # Inject heat + session into debate context for better decisions
        heat_ctx = ""
        session_ctx = ""
        try:
            heat_ctx = get_portfolio_heat_context()
        except Exception:
            pass
        try:
            session_ctx = get_market_session_context()
        except Exception:
            pass

        # Confluence + pipeline context
        confluence_ctx = ""
        prospects_ctx = ""
        history_ctx = ""
        try:
            from agent_collab import get_confluence_context, get_prospects_context, get_symbol_history_context
            _conn = _get_conn()
            confluence_ctx = get_confluence_context(symbol, _conn, profile='swing')
            prospects_ctx = get_prospects_context(symbol, _conn)
            history_ctx = get_symbol_history_context(symbol, _conn)
            _conn.close()
        except Exception:
            pass

        context_block = ""
        ctx_parts = [x for x in [heat_ctx, session_ctx, confluence_ctx, prospects_ctx, history_ctx] if x]
        if ctx_parts:
            context_block = "\n" + "\n".join(ctx_parts) + "\n"

        # ── Round 1: Independent views ─────────────────────────────────
        round1_prompt = f"""/no_think You are moderating a debate between 3 portfolio agents about {symbol}.

TRIGGER: "{trigger_title}"
CLIENT: Age 58, SSDI $3,800/mo, MFS filing, $1.2M portfolio, $55K income target.{context_block}
Each agent gives their INDEPENDENT view (2-3 sentences, citing their specific mandate):

MARIA (Fundamentals & Research): What does news/SEC/fundamentals say? Catalyst quality?
STEPH (Allocation & Income): Does this fit income strategy? Stop vs income floor impact?
RISK (Technical Analysis): What do RSI/SMA/stop distance say? Price action verdict?

Then provide:
CONSENSUS: BUY/HOLD/SELL/TRIM/RESEARCH_MORE
CONFIDENCE: 0-100%
DIVERGENCE: 0-100% (0=all agree, 100=max disagreement)
SSDI_IMPACT: none/low/high

Keep total under 250 words."""

        r1 = get_llm_response("cio_synthesis", round1_prompt, max_tokens=500)
        round1_text = r1.get("response", "") if r1.get("success") else ""

        # Parse round 1 results
        r1_consensus = "HOLD"
        r1_confidence = 50
        r1_divergence = 0
        import re
        for line in round1_text.split("\n"):
            lu = line.upper().strip()
            if "CONSENSUS:" in lu:
                for rec in ("BUY", "SELL", "TRIM", "HOLD", "RESEARCH_MORE"):
                    if rec in lu:
                        r1_consensus = rec
                        break
            if "CONFIDENCE:" in lu:
                nums = re.findall(r'(\d+)', line)
                if nums:
                    r1_confidence = min(100, int(nums[0]))
            if "DIVERGENCE:" in lu:
                nums = re.findall(r'(\d+)', line)
                if nums:
                    r1_divergence = min(100, int(nums[0]))

        # ── Round 2: Counter-argument (only if divergence > 30%) ───────
        round2_text = ""
        rounds_run = 1
        final_consensus = r1_consensus
        final_confidence = r1_confidence

        if r1_divergence > 30 and round1_text:
            rounds_run = 2
            round2_prompt = f"""/no_think Round 2 counter-argument debate for {symbol}.

Round 1 produced disagreement (divergence: {r1_divergence}%):
{round1_text}

The agents disagreed. Now each agent RESPONDS to the strongest opposing argument:

MARIA: Do you update your Round 1 view given what Steph and Risk said?
STEPH: Do you update your Round 1 view given what Maria and Risk said?
RISK: Do you update your Round 1 view given what Maria and Steph said?

Each agent: one sentence only. State MAINTAIN or UPDATE + why.

Then provide FINAL:
CONSENSUS: BUY/HOLD/SELL/TRIM/RESEARCH_MORE
CONFIDENCE: 0-100%

Keep total under 150 words."""

            r2 = get_llm_response("cio_synthesis", round2_prompt, max_tokens=300)
            round2_text = r2.get("response", "") if r2.get("success") else ""

            # Parse round 2 — use final consensus if available
            if round2_text:
                for line in round2_text.split("\n"):
                    lu = line.upper().strip()
                    if "CONSENSUS:" in lu or "FINAL" in lu and "CONSENSUS" in lu:
                        for rec in ("BUY", "SELL", "TRIM", "HOLD", "RESEARCH_MORE"):
                            if rec in lu:
                                final_consensus = rec
                                break
                    if ("CONFIDENCE:" in lu or "FINAL" in lu and "CONFIDENCE" in lu):
                        nums = re.findall(r'(\d+)', line)
                        if nums:
                            final_confidence = min(100, int(nums[0]))

        # Build full transcript
        full_transcript = round1_text
        if round2_text:
            full_transcript += f"\n\n--- ROUND 2 (counter-argument, divergence={r1_divergence}%) ---\n{round2_text}"

        # Store in DB
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO agent_debate_log
            (symbol, trigger_source, trigger_id, participants, debate_transcript,
             consensus_score, consensus_recommendation, provider)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (symbol, trigger_source, trigger_id,
             ["Maria", "Steph", "Risk"],
             full_transcript[:2000],
             final_confidence / 100.0,
             final_consensus,
             r1.get("provider", "")))
        debate_id = cur.fetchone()[0]
        conn.commit()

        # Auto-escalate to Alex if consensus >= 50%
        if final_confidence >= 50:
            try:
                import uuid as _uuid
                cur.execute("""INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, payload, created_at)
                    VALUES (%s, %s, 'alex', 'full_analysis', %s, 'pending', 0, 'debate_escalation', %s, NOW())""",
                    (str(_uuid.uuid4()), symbol,
                     f"Debate escalation: {final_consensus} at {final_confidence}%",
                     json.dumps({"debate_id": debate_id, "consensus": final_consensus, "score": final_confidence / 100.0})))
                cur.execute("UPDATE agent_debate_log SET escalated_to_alex=true, status='escalated' WHERE id=%s", (debate_id,))
                conn.commit()
            except Exception:
                pass

        # ── ADVISORY: free-OAuth cloud models review the LOCAL LLM's debate ──
        # Additive + advisory only — never changes consensus/confidence/escalation.
        # Gated behind CLOUD_REVIEW=1; capped per run.
        cloud_verdict = None
        global _cloud_review_count
        if os.getenv("CLOUD_REVIEW") == "1" and _cloud_review_count < _CLOUD_REVIEW_CAP:
            try:
                import cloud_review
                if cloud_review.available():
                    _cloud_review_count += 1
                    cr = cloud_review.review(
                        "watchlist_pick_review",
                        local_output=(
                            f"Debate consensus: {final_consensus} at {final_confidence}% confidence.\n"
                            + full_transcript[:3000]),
                        context={
                            "symbol": symbol,
                            "trigger": str(trigger_title)[:160],
                            "consensus": final_consensus,
                            "confidence_pct": final_confidence,
                            "divergence_pct": r1_divergence,
                            "rounds": rounds_run,
                        },
                        symbol=symbol,
                        source="agent_watchlist_engine",
                    )
                    cloud_verdict = (cr.get("consensus") or {}).get("verdict")
                    if cloud_verdict:
                        # attach advisory verdict into the stored transcript field
                        try:
                            cur.execute(
                                "UPDATE agent_debate_log SET debate_transcript = LEFT(%s, 2000) WHERE id=%s",
                                (full_transcript + f"\n\n[cloud_review_verdict={cloud_verdict}]", debate_id))
                            conn.commit()
                        except Exception:
                            conn.rollback()
                        print(f"  [debate] {symbol}: cloud_review consensus={cloud_verdict}")
            except Exception as e:
                print(f"  [debate] {symbol}: cloud_review skipped — {e}")

        conn.close()

        print(f"  [debate] {symbol}: {final_consensus} ({final_confidence}%) "
              f"via {r1.get('provider','?')} "
              f"[{rounds_run} round(s), divergence={r1_divergence}%]")

        return {
            "symbol": symbol,
            "consensus": final_consensus,
            "consensus_recommendation": final_consensus,
            "confidence": final_confidence / 100.0,
            "consensus_score": final_confidence,
            "transcript": full_transcript,
            "rounds": rounds_run,
            "divergence": r1_divergence,
            "provider": r1.get("provider"),
            "cloud_review_verdict": cloud_verdict,
        }

    except Exception as e:
        print(f"  [debate] {symbol}: error — {e}")
        return {"symbol": symbol, "error": str(e)}


# ── Job 4: Rotation proposals (strategy-aware) ──────────────────────

ROTATION_RULES = {
    # NEVER auto-rotate income assets unless income floor threatened
    "dividend_growth_compounder": {"auto_rotate": False, "rule": "HOLD unless dividend cut or payout unsafe"},
    "dividend_growth_compounding": {"auto_rotate": False, "rule": "HOLD unless dividend cut or payout unsafe"},
    "high_yield_income_bdc": {"auto_rotate": False, "rule": "HOLD unless income floor threatened (>20% of portfolio income)"},
    "tactical_income": {"auto_rotate": False, "rule": "HOLD unless yield drops below 4%"},
    "reit_income": {"auto_rotate": False, "rule": "HOLD unless occupancy collapse"},
    "bond_income": {"auto_rotate": False, "rule": "HOLD unless duration mismatch"},
    # Swing/tactical CAN rotate
    "swing_trade": {"auto_rotate": True, "rule": "Rotate on RSI >75 or <25 + catalyst exhaustion"},
    "core_growth_compounder": {"auto_rotate": True, "rule": "Rotate if PE >40 AND growth decelerating"},
    # Retirement: Alex-specific
    "retirement_planning": {"auto_rotate": False, "rule": "Alex reviews: Roth ladder, tax bracket, SSDI impact"},
    "disability_retirement_planning": {"auto_rotate": False, "rule": "Alex reviews: Medicaid, IRMAA, MFS implications"},
}


def propose_rotations() -> dict:
    """Check positions against rotation rules. Account-specific, SSDI-aware proposals."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get latest agent results via canonical broker wrapper.
    from lib.data_broker.agent_results import get_agent_results
    agent_results = get_agent_results(
        lambda sql, params=None, fetch="all":
            (cur.execute(sql, params or []) or True)
            and [dict(r) for r in cur.fetchall()]
            if fetch == "all" else (
                cur.execute(sql, params or []) or True
                and next(iter([dict(r) for r in [cur.fetchone()] if r]), None)
            ),
        [],  # all symbols — the wrapper filters to SELL/TRIM/AVOID internally
    )
    # Reconstruct sell_candidates in the expected format (with strategy_type from classifications)
    sell_candidates = []
    for sym, results in agent_results.items():
        for r in results:
            if r.get("recommendation") in ("SELL", "TRIM", "AVOID") and (r.get("confidence") or 0) > 0.5:
                # Join with strategy_type
                cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE LIMIT 1", (sym,))
                st_row = cur.fetchone()
                strategy_type = (dict(st_row).get("strategy_type") if st_row else None) if isinstance(st_row, dict) else None
                sell_candidates.append({
                    "symbol": sym,
                    "agent": r.get("agent"),
                    "recommendation": r.get("recommendation"),
                    "confidence": r.get("confidence"),
                    "strategy_type": strategy_type,
                })

    # Load holdings for account-specific details
    holdings_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    holdings_map = {}
    try:
        import json as _j
        h = _j.loads(holdings_path.read_text())
        for pos in h.get("holdings", []):
            sym = pos.get("symbol", "")
            if sym:
                if sym not in holdings_map:
                    holdings_map[sym] = []
                aid = pos.get("account_id", pos.get("account", ""))
                acct_type = "Roth IRA" if "roth" in aid.lower() else "Rollover IRA" if "rollover" in aid.lower() or "ira" in aid.lower() else "401k" if "401k" in aid.lower() else "Taxable"
                holdings_map[sym].append({
                    "account": acct_type,
                    "shares": float(pos.get("shares", 0) or 0),
                    "value": float(pos.get("market_value", 0) or 0),
                })
    except Exception:
        pass

    # Load feedback history for confidence adjustment
    feedback_adj = {}
    try:
        cur.execute("""
            SELECT symbol, strategy_type,
                   SUM(CASE WHEN decision='approved' THEN 1 ELSE 0 END) as approved,
                   SUM(CASE WHEN decision='rejected' THEN 1 ELSE 0 END) as rejected,
                   SUM(confidence_adjustment) as total_adj
            FROM agent_feedback_log
            WHERE created_at > NOW() - INTERVAL '90 days'
            GROUP BY symbol, strategy_type
        """)
        for row in cur.fetchall():
            key = (row["symbol"], row["strategy_type"])
            feedback_adj[key] = {
                "approved": int(row["approved"] or 0),
                "rejected": int(row["rejected"] or 0),
                "adj": float(row["total_adj"] or 0),
            }
    except Exception:
        pass  # Table may not exist yet

    ucur = conn.cursor()
    rotations = 0

    for c in sell_candidates:
        strategy = c.get("strategy_type", "")
        rule = ROTATION_RULES.get(strategy, {"auto_rotate": False, "rule": "Unknown — manual review"})

        if not rule["auto_rotate"]:
            continue

        # Skip if already proposed
        cur.execute("SELECT id FROM watchlist_proposals WHERE symbol=%s AND status='proposed' AND action='rotate'", (c["symbol"],))
        if cur.fetchone():
            continue

        # Apply feedback-based confidence adjustment
        base_conf = float(c["confidence"])
        fb = feedback_adj.get((c["symbol"], strategy))
        adj_conf = base_conf
        feedback_note = ""
        if fb:
            adj_conf = max(0.1, min(1.0, base_conf + fb["adj"]))
            if fb["rejected"] > fb["approved"]:
                feedback_note = f" [feedback: {fb['rejected']} rejected, skewing down]"
            elif fb["approved"] > 0:
                feedback_note = f" [feedback: {fb['approved']} approved, confidence boosted]"

        # Account-specific proposals
        positions = holdings_map.get(c["symbol"], [{"account": "Unknown", "shares": 0, "value": 0}])
        review_date = (datetime.now() + __import__("datetime").timedelta(days=14)).date()

        # Load personal situation for MAGI/threshold checks (once)
        if not hasattr(propose_rotations, '_ps_loaded'):
            propose_rotations._ps_cache = {}
            try:
                ps_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "personal_situation.json"
                if ps_path.exists():
                    ps = json.loads(ps_path.read_text())
                    fields = ps.get("fields", {})
                    propose_rotations._ps_cache = {
                        "agi": float(fields.get("schedule_c_gross", {}).get("current", 20000))
                              + float(fields.get("ssdi_annual", {}).get("current", 45600)),
                        "roth_ytd": float(fields.get("roth_conversion_ytd_2026", {}).get("current", 35000)),
                        "bracket_ceiling": float(fields.get("next_bracket_ceiling", {}).get("current", 94300)),
                        "ssdi_annual": float(fields.get("ssdi_annual", {}).get("current", 45600)),
                    }
            except Exception:
                pass
            propose_rotations._ps_loaded = True

        ps = propose_rotations._ps_cache
        current_magi = ps.get("agi", 65600) + ps.get("roth_ytd", 35000)
        irmaa_threshold = 103000  # 2026 MFS IRMAA Tier 1 threshold
        medicaid_limit = 20124    # NY Medicaid income limit
        bracket_ceiling = ps.get("bracket_ceiling", 94300)  # 22% bracket top for MFS

        # FRED-aware macro context for rotation decisions
        macro_note = ""
        try:
            cur.execute("SELECT series_id, value FROM fred_economic_series WHERE series_id IN ('DFF','VIXCLS','T10Y2Y') ORDER BY observation_date DESC")
            fred = {r["series_id"]: float(r["value"]) for r in cur.fetchall()}
            vix = fred.get("VIXCLS", 20)
            fed_rate = fred.get("DFF", 4.0)
            spread = fred.get("T10Y2Y", 0.5)
            if vix > 25:
                macro_note = f" [MACRO: VIX {vix:.0f} elevated — consider holding]"
            elif spread < 0:
                macro_note = f" [MACRO: Yield curve inverted — recession risk]"
            elif fed_rate > 5:
                macro_note = f" [MACRO: Fed rate {fed_rate:.2f}% high — bonds competitive]"
        except Exception:
            pass

        for pos in positions:
            # SSDI-aware impact assessment with MAGI thresholds
            ssdi_impact = "none"
            income_impact = "none"
            irmaa_risk = False
            ssdi_warnings = []

            if pos["account"] in ("Rollover IRA", "401k"):
                ssdi_impact = "conversion_taxable"
                # IRMAA check: would this sale + current MAGI push past threshold?
                projected_magi = current_magi + pos["value"]
                irmaa_risk = projected_magi > irmaa_threshold
                # MFS bracket check: would this push AGI past 22% ceiling?
                if projected_magi > bracket_ceiling:
                    ssdi_warnings.append(f"MAGI ${projected_magi:,.0f} exceeds 22% ceiling ${bracket_ceiling:,.0f}")
                    income_impact = "bracket_jump"
                else:
                    income_impact = "taxable_event"
                # Medicaid 5-year lookback: flag if large distribution could affect eligibility
                if pos["value"] > 50000:
                    ssdi_warnings.append("Large IRA distribution may affect Medicaid 5-year lookback")
            elif pos["account"] == "Roth IRA":
                ssdi_impact = "none"
                income_impact = "none"
                # Roth distributions don't affect MAGI, SSDI, or Medicaid
            elif pos["account"] == "Taxable":
                ssdi_impact = "capital_gains"
                income_impact = "taxable_event"
                # Capital gains add to MAGI
                est_gain = pos["value"] * 0.5  # conservative 50% gain estimate
                if current_magi + est_gain > irmaa_threshold:
                    irmaa_risk = True
                    ssdi_warnings.append(f"Cap gains could push MAGI past IRMAA ${irmaa_threshold:,.0f}")

            # Build enhanced reason with warnings + macro context
            reason = f"{c['agent']}: {c['recommendation']} (conf:{base_conf:.0%}). {rule['rule']}{feedback_note}{macro_note}"
            if ssdi_warnings:
                reason += " | SSDI: " + "; ".join(ssdi_warnings)

            ucur.execute("""INSERT INTO watchlist_proposals
                (symbol, action, strategy_type, reason, confidence, proposed_by, status,
                 account_name, shares_to_sell, target_symbol, review_date,
                 ssdi_impact, income_impact, irmaa_risk)
                VALUES (%s, 'rotate', %s, %s, %s, 'rotation_engine', 'proposed',
                        %s, %s, 'cash', %s, %s, %s, %s)""",
                (c["symbol"], strategy, reason, adj_conf,
                 pos["account"], pos["shares"], review_date,
                 ssdi_impact, income_impact, irmaa_risk))
            rotations += 1
            risk_badge = " IRMAA!" if irmaa_risk else ""
            warn_str = f" WARN:{';'.join(ssdi_warnings)}" if ssdi_warnings else ""

            # Auto-execution check: conf≥90%, no SSDI/IRMAA risk, income_impact=none, Roth account
            auto_eligible = (adj_conf >= 0.90 and ssdi_impact == "none"
                             and not irmaa_risk and income_impact == "none"
                             and not ssdi_warnings)
            auto_tag = " [AUTO-ELIGIBLE]" if auto_eligible else ""

            # Check if auto-execute is enabled in intelligence rules
            if auto_eligible:
                try:
                    cur.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='auto_execute' AND rule_key='low_risk'")
                    ae_row = cur.fetchone()
                    ae_enabled = ae_row and ae_row.get("config", {}).get("enabled", False) if ae_row else False
                    if ae_enabled:
                        # Auto-approve: update status and generate trade instruction
                        ucur.execute("UPDATE watchlist_proposals SET status='approved', reviewed_by='auto_engine', reviewed_at=NOW() WHERE symbol=%s AND status='proposed' AND account_name=%s ORDER BY created_at DESC LIMIT 1",
                                     (c["symbol"], pos["account"]))
                        ucur.execute("""INSERT INTO trade_instructions
                            (symbol, action, account_name, shares, target_symbol,
                             estimated_tax_impact, ssdi_note, irmaa_note, execution_type, status, instruction_text)
                            VALUES (%s, 'sell', %s, %s, 'cash', 0, 'No SSDI impact', 'No IRMAA risk', 'auto_approved', 'pending', %s)""",
                            (c["symbol"], pos["account"], pos["shares"],
                             f"AUTO-APPROVED: Sell {pos['shares']:.0f} shares of {c['symbol']} in {pos['account']}. Conf:{adj_conf:.0%}. No risk flags."))
                        auto_tag = " [AUTO-APPROVED]"
                        print(f"  [auto] {c['symbol']} in {pos['account']}: auto-approved (conf:{adj_conf:.0%}, no risk)")
                except Exception:
                    pass

            print(f"  [rotate] {c['symbol']} in {pos['account']}: {pos['shares']:.0f} shares → cash.{risk_badge} SSDI:{ssdi_impact}{warn_str} conf:{adj_conf:.0%}{auto_tag}")

    conn.commit()
    conn.close()
    print(f"[rotate] {rotations} rotation proposals created")
    return {"rotations": rotations}


# ── Job 5: Weekly retirement health check ────────────────────────────

def weekly_health_check(send_telegram: bool = False) -> dict:
    """Deep weekly check: income gap, Roth progress, allocation drift, disability considerations."""
    if datetime.now().weekday() != 6 and "--force" not in sys.argv:
        print("[health] Not Sunday — skipping (use --force to override)")
        return {"skipped": True}

    try:
        from llm_router import get_llm_response
        from alex_retirement_advisor import get_tax_context

        tax = get_tax_context(2026)
        bracket = tax.get("current_bracket", 12)
        room = tax.get("bracket_room_22pct", 0)
        roth_ytd = tax.get("roth_conversions_ytd", 0)

        # Get recent metrics
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT count(*) FROM qualified_intelligence WHERE discovered_at > NOW() - INTERVAL '7 days'")
        intel_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM watchlist_proposals WHERE status='proposed'")
        proposals_count = cur.fetchone()["count"]
        cur.execute("SELECT count(*) FROM agent_handoffs WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '7 days'")
        escalations = cur.fetchone()["count"]
        # Feedback stats
        feedback_line = ""
        try:
            cur.execute("SELECT decision, count(*) as cnt FROM agent_feedback_log GROUP BY decision")
            fb = {r["decision"]: r["cnt"] for r in cur.fetchall()}
            if fb:
                feedback_line = f"- Human feedback: {fb.get('approved', 0)} approved, {fb.get('rejected', 0)} rejected (confidence adjusted accordingly)\n"
        except Exception:
            pass
        conn.close()

        # FRED macro context
        macro_context = ""
        try:
            from external_market_data_ingest import get_macro_context
            mc = get_macro_context()
            if mc:
                macro_context = f"\n{mc}\n"
        except Exception:
            pass

        # Income data
        income_line = "Income: $14,285/yr vs $55K target. Gap: $40,715."
        try:
            div_path = PROJECT_ROOT / "data" / "portfolios" / "state" / "dividend_calendar.json"
            if div_path.exists():
                dc = json.loads(div_path.read_text())
                annual = float(dc.get("total_annual", 14285))
                gap = 55000 - annual
                income_line = f"Income: ${annual:,.0f}/yr vs $55K target. Gap: ${gap:,.0f} ({annual/55000*100:.0f}% of target)."
        except Exception:
            pass

        prompt = f"""/no_think You are Alex, a disability-optimized retirement planner. Provide a weekly health check.

CLIENT: Age 58, SSDI $3,800/mo, MFS filing, Medicare Dec 2026, $1.2M portfolio.
{income_line}
Tax: {bracket}% bracket, ${room:,.0f} room, Roth YTD ${roth_ytd:,.0f}.
{macro_context}
THIS WEEK:
- {intel_count} qualified intelligence items discovered
- {proposals_count} watchlist proposals pending review
- {escalations} agent escalations
{feedback_line}
Provide weekly health check (under 300 words):
1. Income gap progress — are we on track? What's needed to close the $40K+ gap?
2. Roth conversion pace — ahead/behind schedule? How much more room in 22% bracket?
3. Tax bracket management — room remaining, optimal conversion timing?
4. SSDI/disability considerations — any macro changes affecting disability benefits?
5. Medicaid planning status — NY income limits, MAGI impact of conversions
6. Macro environment impact — how do current rates/inflation affect the retirement plan?
7. Top 3 specific actions for next week with dollar amounts
Be specific with numbers. Address disability implications. Reference macro data if relevant."""

        result = get_llm_response("cio_synthesis", prompt, max_tokens=500, high_impact=True)
        review = result.get("response", "Health check unavailable") if result.get("success") else "Health check failed"

        # Store
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""INSERT INTO agent_discovery_log (discovery_type, title, summary, intel_count, provider)
                VALUES ('weekly_health', %s, %s, %s, %s)""",
                (f"Weekly Health Check — {datetime.now().strftime('%Y-%m-%d')}",
                 review[:2000], intel_count, result.get("provider", "")))
            cur.execute("""INSERT INTO ai_reports (report_type, title, content, provider)
                VALUES ('weekly_health', %s, %s, %s)""",
                (f"Weekly Health Check — {datetime.now().strftime('%b %d, %Y')}",
                 review, result.get("provider", "")))
            conn.commit()
            conn.close()
        except Exception:
            pass

        if send_telegram:
            divider = "\u2501" * 24
            _send_tg(f"\U0001F3E5 *Alex Weekly Health Check*\n{divider}\n\n{review[:1800]}\n\n{divider}\n_via {result.get('provider','?')}_")

        print(f"[health] Weekly check complete via {result.get('provider', '?')}")
        return {"status": "completed", "provider": result.get("provider")}
    except Exception as e:
        print(f"[health] Error: {e}")
        return {"error": str(e)}


# ── Job 6: Weekly autonomy summary (Sunday 8 AM) ───────────────────

def weekly_autonomy_summary(send_telegram: bool = False) -> dict:
    """Generate and send weekly autonomy progress summary."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Gather metrics
    cur.execute("SELECT count(*) as cnt FROM watchlist_agent_results WHERE created_at > NOW() - INTERVAL '7 days'")
    analyses = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) as cnt FROM qualified_intelligence WHERE discovered_at > NOW() - INTERVAL '7 days'")
    intel = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) as cnt, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) as approved FROM watchlist_proposals WHERE created_at > NOW() - INTERVAL '7 days'")
    props = cur.fetchone()
    cur.execute("SELECT count(*) as cnt FROM agent_debate_log WHERE created_at > NOW() - INTERVAL '7 days'")
    debates = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) as cnt FROM content_embeddings WHERE embedding IS NOT NULL")
    embeddings = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) as cnt FROM agent_handoffs WHERE escalated=TRUE AND created_at > NOW() - INTERVAL '7 days'")
    escalations = cur.fetchone()["cnt"]

    # Lessons
    cur.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'")
    lr = cur.fetchone()
    lessons = ""
    if lr and lr.get("config"):
        cfg = lr["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        lessons = cfg.get("text", "")

    conn.close()

    divider = "\u2501" * 24
    msg = (f"\U0001F4CA *Weekly Autonomy Report*\n{divider}\n\n"
           f"*This Week:*\n"
           f"  Analyses: {analyses}\n"
           f"  Intel discovered: {intel}\n"
           f"  Proposals: {props['cnt']} ({props['approved'] or 0} approved)\n"
           f"  Debates: {debates}\n"
           f"  Escalations: {escalations}\n"
           f"  Embeddings indexed: {embeddings}\n\n"
           f"*Lessons Learned:*\n{lessons or '  (accumulating...)'}\n\n"
           f"{divider}")

    if send_telegram:
        _send_tg(msg)

    print(msg.replace('*', '').replace('\U0001F4CA ', ''))
    return {"analyses": analyses, "intel": intel, "proposals": props["cnt"], "debates": debates}


# ── Status ───────────────────────────────────────────────────────────

def show_status():
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT source_type, count(*) FROM qualified_intelligence GROUP BY source_type")
    print("Qualified Intelligence:")
    for r in cur.fetchall():
        print(f"  {r['source_type']}: {r['count']}")

    cur.execute("SELECT count(*) FROM qualified_intelligence")
    print(f"  Total: {cur.fetchone()['count']}")

    cur.execute("SELECT status, count(*) FROM watchlist_proposals GROUP BY status")
    print("\nWatchlist Proposals:")
    for r in cur.fetchall():
        print(f"  {r['status']}: {r['count']}")

    cur.execute("SELECT count(*) FROM agent_discovery_log")
    print(f"\nDiscovery Logs: {cur.fetchone()['count']}")
    conn.close()


def test():
    print("=== Agent Watchlist Engine Test ===\n")
    print("1. Promoting qualified intel...")
    r1 = promote_qualified_intel()
    print(f"   {r1}")

    print("\n2. Proposing watchlist adds...")
    r2 = propose_watchlist_adds()
    print(f"   {r2}")

    print("\n3. Proposing rotations...")
    r3 = propose_rotations()
    print(f"   {r3}")

    print("\n4. Generating discovery summary...")
    r4 = generate_discovery_summary()
    print(f"   {r4}")

    print("\n5. Status:")
    show_status()
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    with PipelineRun("agent_watchlist_engine") as _run:
        tg = "--telegram" in sys.argv
        if "--test" in sys.argv:
            test()
        elif "--promote" in sys.argv:
            promote_qualified_intel()
        elif "--propose" in sys.argv:
            propose_watchlist_adds()
        elif "--discovery" in sys.argv:
            generate_discovery_summary(send_telegram=tg)
        elif "--rotate" in sys.argv:
            propose_rotations()
        elif "--health" in sys.argv:
            weekly_health_check(send_telegram=tg)
        elif "--all" in sys.argv or "--daily" in sys.argv:
            promote_qualified_intel()
            propose_watchlist_adds()
            propose_rotations()
            generate_discovery_summary(send_telegram=tg)
        elif "--weekly" in sys.argv:
            promote_qualified_intel()
            propose_watchlist_adds()
            propose_rotations()
            generate_discovery_summary(send_telegram=tg)
            weekly_health_check(send_telegram=tg)
        elif "--autonomy-summary" in sys.argv:
            weekly_autonomy_summary(send_telegram=tg)
        elif "--status" in sys.argv:
            show_status()
        else:
            print("Usage:")
            print("  --test              Full test run")
            print("  --daily / --all     Promote + propose + rotate + discovery")
            print("  --weekly            Daily + weekly health check")
            print("  --promote           Promote high-Q intel only")
            print("  --propose           Propose watchlist adds only")
            print("  --rotate            Propose rotations only")
            print("  --discovery         Discovery summary only")
            print("  --health [--force]  Weekly retirement health check")
            print("  --autonomy-summary  Weekly autonomy progress report")
            print("  --status            Show current counts")
            print("  Add --telegram to send alerts")

