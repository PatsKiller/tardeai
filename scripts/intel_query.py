"""intel_query.py — Query recent high-quality intelligence for agents.

Provides a unified interface for any agent to pull scored + tagged intel from
news_articles, youtube_transcripts, and social_posts.

Usage:
    from intel_query import get_intel_for_agent, get_intel_for_symbol, get_intel_summary

    # Get recent intel tagged to Alex
    items = get_intel_for_agent("Alex", min_quality=70, limit=10)

    # Get recent intel mentioning V
    items = get_intel_for_symbol("V", min_quality=50, limit=10)

    # Get a text summary for injection into LLM prompts
    summary = get_intel_summary(agent="Alex", symbol="V", max_chars=800)

Agent Improvements (v3.7):
    #4 — Portfolio heat injected into every prompt via get_portfolio_heat_context()
    #6 — Market session context injected via get_market_session_context()
    #2 — Cross-agent reasoning (not just verdict) via get_cross_agent_context()
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Improvement #6: Market Session Context ──────────────────────────────────
# Injected into every agent prompt so agents know if they're analyzing
# a pre-market gap, live market move, after-hours print, or overnight trigger.

def get_market_session_context() -> str:
    """Return current market session as a one-line context string for agent prompts.

    Agents need to know session because:
    - PRE-MARKET stop: may reverse at open — wait for confirmation
    - MARKET HOURS stop: confirmed move — act with conviction
    - AFTER-HOURS stop: illiquid, may gap opposite — hold until open
    - OVERNIGHT: triggered while market closed — confirm at open before acting
    """
    from datetime import datetime, timezone
    try:
        import pytz
        et = datetime.now(pytz.timezone("US/Eastern"))
    except ImportError:
        # Fallback if pytz not installed: use UTC offset -4 or -5
        import time as _time
        utc_now = datetime.now(timezone.utc)
        # EST = UTC-5, EDT = UTC-4 (rough: EDT Mar-Nov)
        month = utc_now.month
        offset_hours = -4 if 3 <= month <= 11 else -5
        from datetime import timedelta
        et = utc_now + timedelta(hours=offset_hours)

    h, m = et.hour, et.minute
    mins_since_midnight = h * 60 + m
    time_str = et.strftime("%I:%M %p ET") if hasattr(et, 'strftime') else f"{h:02d}:{m:02d} ET"

    # Market hours: 9:30 AM – 4:00 PM ET = minutes 570–960
    if 570 <= mins_since_midnight < 960:
        mins_to_close = 960 - mins_since_midnight
        return (f"MARKET SESSION: MARKET HOURS ({time_str}, {mins_to_close}min to close). "
                f"Live prices confirmed. Volume-backed moves. Act with normal conviction.")
    # Pre-market: 4:00 AM – 9:30 AM ET = minutes 240–570
    elif 240 <= mins_since_midnight < 570:
        mins_to_open = 570 - mins_since_midnight
        return (f"MARKET SESSION: PRE-MARKET ({time_str}, {mins_to_open}min to open). "
                f"Low liquidity — prices may gap at open. Bias toward waiting for "
                f"market-hours confirmation before acting on stop triggers.")
    # After-hours: 4:00 PM – 8:00 PM ET = minutes 960–1200
    elif 960 <= mins_since_midnight < 1200:
        return (f"MARKET SESSION: AFTER-HOURS ({time_str}). "
                f"Illiquid — stop triggers here may reverse at next open. "
                f"Do NOT recommend immediate action. Flag for morning review.")
    # Overnight: 8:00 PM – 4:00 AM ET = minutes 1200–1440 or 0–240
    else:
        return (f"MARKET SESSION: OVERNIGHT ({time_str}). "
                f"Market closed. Any price triggers are after-hours/futures data. "
                f"Flag for morning confirmation — do not act on overnight prices alone.")


# ── Improvement #4: Portfolio Heat Context ──────────────────────────────────
# Portfolio heat = sum(unrealized losses) / total_portfolio_value.
# Agents must know heat level because:
# - Heat >8%: CRITICAL — honor ALL stops, no new positions
# - Heat >5%: elevated — bias toward stops over holds on borderline cases
# - Heat >3%: moderate — normal stop discipline
# - Heat <3%: low — can hold borderline stops, consider adding on dips

def get_portfolio_heat_context() -> str:
    """Read current portfolio heat from risk_management.json and return as context string.

    This single injection changes agent behavior on borderline stop decisions.
    LMT (HOLD 50% vs TRIM 85%) would have resolved faster if Risk saw heat=6.2%.
    """
    risk_files = [
        PROJECT_ROOT / "data" / "portfolios" / "state" / "risk_management.json",
        PROJECT_ROOT / "data" / "risk_management.json",
    ]
    for rf in risk_files:
        if rf.exists():
            try:
                data = json.loads(rf.read_text())
                heat = float(data.get("portfolio_heat_pct",
                             data.get("heat_pct",
                             data.get("heat", 0))) or 0)
                protected_pct = data.get("protected_pct", data.get("coverage_pct", 0))

                if heat > 8:
                    level = "CRITICAL"
                    directive = ("HONOR ALL STOPS IMMEDIATELY. "
                                 "Do not hold borderline positions. "
                                 "No new position entries under any circumstances.")
                elif heat > 5:
                    level = "ELEVATED"
                    directive = ("Bias toward honoring stops over holding. "
                                 "When in doubt on a borderline stop, TRIM. "
                                 "Do not add to existing positions.")
                elif heat > 3:
                    level = "MODERATE"
                    directive = "Normal stop discipline applies. Review stops ≥2× ATR from entry."
                else:
                    level = "LOW"
                    directive = ("Normal analysis. Can hold borderline stops if thesis intact. "
                                 "May consider adding on dips for high-conviction positions.")

                protection_note = f" Portfolio coverage: {protected_pct:.0f}% protected." if protected_pct else ""
                return (f"PORTFOLIO HEAT: {heat:.1f}% [{level}].{protection_note} "
                        f"Directive: {directive}")
            except Exception:
                pass

    # Fallback: compute from canonical holdings.json. (The old DB fallback queried the retired
    # `holdings` table with columns it never had — it silently errored to "unavailable" forever.)
    try:
        hp = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        if hp.exists():
            hd = json.loads(hp.read_text())
            rows = [h for h in hd.get("holdings", [])
                    if not h.get("is_cash") and "401k" not in str(h.get("account", "")).lower()]
            total_mv = sum(float(h.get("market_value") or 0) for h in rows)
            losses = sum(abs(float(h.get("gain_loss") or 0)) for h in rows if float(h.get("gain_loss") or 0) < 0)
            if total_mv > 0:
                heat = losses / total_mv * 100
                level = "CRITICAL" if heat > 8 else "ELEVATED" if heat > 5 else "MODERATE" if heat > 3 else "LOW"
                return f"PORTFOLIO HEAT: {heat:.1f}% [{level}]. Use heat level to calibrate stop decisions."
    except Exception:
        pass

    return "PORTFOLIO HEAT: unavailable (use normal stop discipline)."


# ── Improvement #2: Cross-Agent Reasoning Context ───────────────────────────
# Previously agents only saw: "Steph: TRIM (85%)"
# Now agents see: "Steph (85%): TRIM — stop breach + elevated heat, income not at risk"
# This lets Risk respond to Steph's ACTUAL argument, not just the label.
# Fewer conflicts, higher consensus quality, better LMT-style decisions.

def get_cross_agent_context(symbol: str, exclude_agent: str = None,
                            hours: int = 48) -> str:
    """Get recent agent analyses for a symbol, including their reasoning.

    Returns formatted string showing what other agents said AND WHY,
    so the current agent can respond to their arguments not just their verdicts.

    Args:
        symbol: The ticker to look up
        exclude_agent: The current agent (don't show their own prior result)
        hours: How far back to look (default 48h — catches same-day analyses)
    """
    try:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT agent_name, recommendation, confidence_score,
                   summary, created_at
            FROM watchlist_agent_results
            WHERE symbol = %s
              AND created_at > NOW() - INTERVAL '%s hours'
              AND status = 'completed'
            ORDER BY created_at DESC
        """, (symbol.upper(), hours))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return ""

        seen = set()
        lines = [f"OTHER AGENT VIEWS ON {symbol} (read these before forming your own view):"]
        for r in rows:
            agent = r.get("agent_name", "?")
            if exclude_agent and agent.lower() == exclude_agent.lower():
                continue
            if agent in seen:
                continue
            seen.add(agent)

            rec = r.get("recommendation", "?")
            conf = int(float(r.get("confidence_score") or 0) * 100)
            # Include summary/reasoning — this is the key improvement over just the label
            reasoning = (r.get("summary") or "").strip()
            if reasoning and len(reasoning) > 200:
                reasoning = reasoning[:200].rsplit(" ", 1)[0] + "..."

            agent_display = agent.upper().replace("_AGENT", "").replace("RISK_AGENT", "RISK")
            line = f"  {agent_display} ({conf}%): {rec}"
            if reasoning:
                line += f" — {reasoning}"
            else:
                line += " — (no reasoning recorded)"
            lines.append(line)

        if len(lines) == 1:  # Only the header, no actual results
            return ""

        lines.append("Consider whether these views change your analysis. You may agree, disagree, or note a conflict.")
        return "\n".join(lines)

    except Exception:
        return ""


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def get_intel_for_agent(agent: str, min_quality: int = 70, limit: int = 10,
                        days: int = 7) -> list:
    """Get recent high-quality intel tagged to a specific agent.

    Returns list of dicts with: source_type, title, text_snippet, quality_score,
    relevance_score, strategy_tags, agent_tags, date.
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    results = []

    # News articles (relevance_score is 0-1.0, convert min_quality from 0-100)
    cur.execute("""
        SELECT 'news' as source_type, title, summary as text_snippet,
               (relevance_score * 100)::int as quality_score, relevance_score,
               strategy_tags, agent_tags, created_at as date, symbol
        FROM news_articles
        WHERE agent_tags @> %s
          AND relevance_score >= %s
          AND created_at > NOW() - INTERVAL '%s days'
        ORDER BY relevance_score DESC, created_at DESC LIMIT %s
    """, (json.dumps([agent]), min_quality / 100.0, days, limit))
    results.extend(cur.fetchall())

    # YouTube transcripts (prefer summary over raw text)
    cur.execute("""
        SELECT 'youtube' as source_type, title,
               COALESCE(summary, LEFT(cleaned_text, 200), LEFT(transcript_text, 200)) as text_snippet,
               quality_score, relevance_score,
               strategy_tags, agent_tags, sub_tags, structured_json,
               ingested_at as date, '' as symbol
        FROM youtube_transcripts
        WHERE agent_tags @> %s
          AND quality_score >= %s
          AND ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY quality_score DESC, ingested_at DESC LIMIT %s
    """, (json.dumps([agent]), min_quality, days, limit))
    results.extend(cur.fetchall())

    # Social posts
    cur.execute("""
        SELECT 'social' as source_type, username as title, text as text_snippet,
               quality_score, relevance_score,
               strategy_tags, agent_tags, ingested_at as date, '' as symbol
        FROM social_posts
        WHERE agent_tags @> %s
          AND quality_score >= %s
          AND ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY ingested_at DESC LIMIT %s
    """, (json.dumps([agent]), min_quality, days, limit))
    results.extend(cur.fetchall())

    conn.close()

    # Sort all by date descending
    results.sort(key=lambda r: r.get("date") or "", reverse=True)
    return results[:limit]


def get_intel_for_symbol(symbol: str, min_quality: int = 50, limit: int = 10,
                         days: int = 7) -> list:
    """Get recent intel mentioning a specific symbol."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    results = []
    sym_upper = symbol.upper()
    sym_pattern = f"%{sym_upper}%"

    # News articles — exact symbol match (relevance_score is 0-1, scale to 0-100)
    cur.execute("""
        SELECT 'news' as source_type, title, summary as text_snippet,
               (relevance_score * 100)::int as quality_score, relevance_score,
               strategy_tags, agent_tags, created_at as date
        FROM news_articles
        WHERE symbol = %s
          AND created_at > NOW() - INTERVAL '%s days'
        ORDER BY relevance_score DESC, created_at DESC LIMIT %s
    """, (sym_upper, days, limit))
    results.extend(cur.fetchall())

    # YouTube — semantic search across structured_json + text + title
    cur.execute("""
        SELECT 'youtube' as source_type, title,
               COALESCE(summary, LEFT(cleaned_text, 200), LEFT(transcript_text, 200)) as text_snippet,
               quality_score, relevance_score,
               strategy_tags, agent_tags, sub_tags, structured_json,
               ingested_at as date
        FROM youtube_transcripts
        WHERE (transcript_text ILIKE %s OR title ILIKE %s
               OR summary ILIKE %s
               OR structured_json::text ILIKE %s)
          AND quality_score >= %s
          AND ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY quality_score DESC, ingested_at DESC LIMIT %s
    """, (sym_pattern, sym_pattern, sym_pattern, sym_pattern, min_quality, days, limit))
    results.extend(cur.fetchall())

    # Social — keyword search in text
    cur.execute("""
        SELECT 'social' as source_type, username as title, LEFT(text, 200) as text_snippet,
               quality_score, relevance_score,
               strategy_tags, agent_tags, ingested_at as date
        FROM social_posts
        WHERE (text ILIKE %s OR username ILIKE %s)
          AND quality_score >= %s
          AND ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY ingested_at DESC LIMIT %s
    """, (sym_pattern, sym_pattern, min_quality, days, limit))
    results.extend(cur.fetchall())

    conn.close()
    results.sort(key=lambda r: r.get("date") or "", reverse=True)
    return results[:limit]


def search_transcripts(query: str, min_quality: int = 50, limit: int = 5,
                       days: int = 30) -> list:
    """Semantic search across YouTube transcripts using Ollama embeddings + TF-IDF fallback.

    1. Keyword ILIKE for candidate retrieval (cast wider net)
    2. Compute query embedding via nomic-embed-text
    3. Cosine similarity re-ranking against stored embeddings
    4. TF-IDF fallback for items without embeddings
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    pattern = f"%{query}%"
    cur.execute("""
        SELECT yt.id, yt.title, yt.channel_name,
               COALESCE(yt.summary, LEFT(yt.cleaned_text, 300)) as text_snippet,
               yt.quality_score, yt.relevance_score, yt.strategy_tags, yt.sub_tags,
               yt.structured_json, yt.ingested_at as date,
               ce.tfidf_terms, ce.embedding
        FROM youtube_transcripts yt
        LEFT JOIN content_embeddings ce ON ce.source_type='youtube' AND ce.source_id=yt.id
        WHERE (yt.title ILIKE %s
               OR yt.summary ILIKE %s
               OR yt.structured_json::text ILIKE %s
               OR yt.transcript_text ILIKE %s)
          AND yt.quality_score >= %s
          AND yt.ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY yt.quality_score DESC, yt.ingested_at DESC LIMIT %s
    """, (pattern, pattern, pattern, pattern, min_quality, days, limit * 3))
    candidates = cur.fetchall()
    conn.close()

    # Semantic re-ranking: embeddings first, TF-IDF fallback
    try:
        from content_scoring import semantic_similarity, _get_embedding, cosine_similarity
        query_vec = _get_embedding(query)

        for c in candidates:
            doc_vec = c.get("embedding")
            if isinstance(doc_vec, str):
                doc_vec = json.loads(doc_vec)
            terms = c.get("tfidf_terms") or {}
            if isinstance(terms, str):
                terms = json.loads(terms)

            if query_vec and doc_vec and len(doc_vec) > 0:
                sim = cosine_similarity(query_vec, doc_vec)
            elif terms:
                sim = semantic_similarity(query, doc_terms=terms)
            else:
                sim = 0.0
            c["semantic_score"] = round(sim * (c.get("quality_score", 50) / 100), 3)

        candidates.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
    except Exception:
        pass

    return candidates[:limit]


def get_outcome_feedback(symbol: str, limit: int = 3) -> str:
    """Get past decision outcomes for a symbol — feedback loop for agents.

    Returns text showing what was recommended before and what actually happened,
    so agents can learn from past accuracy.
    """
    import psycopg2.extras
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT recommendation, price_at_decision, price_7d, price_30d, created_at
            FROM decision_outcomes
            WHERE symbol = %s AND price_7d IS NOT NULL
            ORDER BY created_at DESC LIMIT %s
        """, (symbol, limit))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return ""
        lines = [f"PAST DECISION OUTCOMES FOR {symbol} (learn from these):"]
        for r in rows:
            p0 = float(r.get("price_at_decision") or 0)
            p7 = float(r.get("price_7d") or 0)
            p30 = float(r.get("price_30d") or 0)
            chg7 = ((p7 / p0) - 1) * 100 if p0 > 0 and p7 > 0 else 0
            chg30 = ((p30 / p0) - 1) * 100 if p0 > 0 and p30 > 0 else 0
            rec = r.get("recommendation", "?")
            dt = str(r.get("created_at", ""))[:10]
            correct = "CORRECT" if (rec in ("BUY", "ADD") and chg7 > 0) or (rec in ("SELL", "TRIM") and chg7 < 0) or (rec in ("HOLD", "REBALANCE_TRIM") and abs(chg7) < 10) else "WRONG" if abs(chg7) > 5 else "NEUTRAL"
            lines.append(f"  {dt}: Rec={rec} at ${p0:.2f} → 7d: {chg7:+.1f}% → 30d: {chg30:+.1f}% [{correct}]")
        return "\n".join(lines)
    except Exception:
        return ""


def get_intel_summary(agent: str = None, symbol: str = None,
                      min_quality: int = 60, max_chars: int = 800,
                      days: int = 7, source_hint: str = "routine") -> str:
    """Get a text summary of recent intel for LLM prompt injection.

    Smart routing logic (v2.48):
      source_hint="research" → Brave Search first, then DB
      source_hint="high_value" → Brave first for retirement/SSDI topics
      source_hint="routine" → DB only (Google News RSS + Yahoo RSS already ingested)
      Brave 402/error → graceful fallback to DB-only

    Returns a formatted string ready to insert into an agent prompt.
    """
    items = []
    if agent:
        items = get_intel_for_agent(agent, min_quality=min_quality, days=days, limit=8)
    if symbol:
        sym_items = get_intel_for_symbol(symbol, min_quality=min_quality, days=days, limit=5)
        # Merge, dedup by title
        seen_titles = {i.get("title", "") for i in items}
        for si in sym_items:
            if si.get("title", "") not in seen_titles:
                items.append(si)
                seen_titles.add(si.get("title", ""))

    # SEC + market data (always include if symbol provided)
    extra_context = []
    if symbol:
        try:
            from sec_data_ingest import get_sec_intel
            sec_text = get_sec_intel(symbol)
            if sec_text:
                extra_context.append(sec_text)
        except Exception:
            pass
        try:
            from external_market_data_ingest import get_yfinance_context
            yf_text = get_yfinance_context(symbol)
            if yf_text:
                extra_context.append(yf_text)
        except Exception:
            pass
    # Macro context (always include)
    try:
        from external_market_data_ingest import get_macro_context
        macro = get_macro_context()
        if macro:
            extra_context.append(macro)
    except Exception:
        pass

    # ── IMPROVEMENT #4: Portfolio heat context ──────────────────────────
    # Agents need live heat level to calibrate stop decisions.
    # At 6.2% heat, borderline holds become trims. Prevents LMT-style conflicts.
    try:
        heat_ctx = get_portfolio_heat_context()
        if heat_ctx:
            extra_context.append(heat_ctx)
    except Exception:
        pass

    # ── IMPROVEMENT #6: Market session context ──────────────────────────
    # Agents need to know if this is a pre-market trigger (may reverse),
    # confirmed market-hours move, or overnight trigger (wait for open).
    try:
        session_ctx = get_market_session_context()
        if session_ctx:
            extra_context.append(session_ctx)
    except Exception:
        pass

    # ── IMPROVEMENT #2: Cross-agent reasoning context ───────────────────
    # Show other agents' verdicts AND their reasoning, not just the label.
    # "Steph (85%): TRIM — stop breach + heat" lets Risk respond to the argument.
    if symbol:
        try:
            cross_ctx = get_cross_agent_context(symbol, exclude_agent=agent)
            if cross_ctx:
                extra_context.append(cross_ctx)
        except Exception:
            pass

    # Qualified intelligence highlights (top items across all sources)
    try:
        import psycopg2.extras as _pxe
        _conn = _get_conn()
        _cur = _conn.cursor(cursor_factory=_pxe.RealDictCursor)
        if symbol:
            _cur.execute("""SELECT source_type, title, quality_score, retirement_relevance
                FROM qualified_intelligence WHERE symbol=%s ORDER BY quality_score DESC LIMIT 3""", (symbol,))
        else:
            _cur.execute("""SELECT source_type, title, quality_score, retirement_relevance
                FROM qualified_intelligence WHERE retirement_relevance='high'
                ORDER BY discovered_at DESC LIMIT 3""")
        _qi = _cur.fetchall()
        _conn.close()
        if _qi:
            qi_lines = ["QUALIFIED INTELLIGENCE (high-confidence verified):"]
            for q in _qi:
                rel = " [RETIREMENT]" if q.get("retirement_relevance") == "high" else ""
                qi_lines.append(f"  [{q['source_type']}] Q:{q['quality_score']}{rel} {q['title'][:60]}")
            extra_context.append("\n".join(qi_lines))
    except Exception:
        pass

    # Outcome lessons (learning loop — top lessons from past decisions)
    try:
        import psycopg2.extras as _pxl
        _conn2 = _get_conn()
        _cur2 = _conn2.cursor(cursor_factory=_pxl.RealDictCursor)
        _cur2.execute("SELECT config FROM agent_intelligence_rules WHERE rule_type='outcome_lessons' AND rule_key='latest'")
        _lr = _cur2.fetchone()
        _conn2.close()
        if _lr and _lr.get("config"):
            cfg = _lr["config"]
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            lt = cfg.get("text", "")
            if lt:
                extra_context.append(f"OUTCOME LESSONS (learn from these):\n{lt}")
    except Exception:
        pass

    # Smart search routing with throttling (v2.49):
    #   Brave ONLY if: relevance≥85 OR retirement_relevance=high OR source_hint=research
    #   Budget: max 5 calls/day, 60-min cooldown, 24h per-symbol cache
    #   All other: DB only (Google/Yahoo RSS already ingested)
    use_brave = False
    brave_reason = ""

    if source_hint == "research":
        use_brave = True
        brave_reason = "user_research"
    elif source_hint == "high_value" and any(
        float(i.get("relevance_score", 0) or 0) >= 0.85 or
        str(i.get("retirement_relevance", "")) == "high"
        for i in items[:5]
    ):
        use_brave = True
        brave_reason = "high_relevance"
    elif symbol and len(items) < 3 and source_hint != "routine":
        use_brave = True
        brave_reason = "sparse_db_results"

    if use_brave and symbol:
        # Check throttle: daily budget (5/day), cooldown (60min), per-symbol cache (24h)
        brave_allowed = True
        try:
            _bconn = _get_conn()
            _bcur = _bconn.cursor()
            # Check daily count
            _bcur.execute("SELECT count(*) FROM content_embeddings WHERE source_type='brave_cache' AND created_at > CURRENT_DATE")
            daily_count = _bcur.fetchone()[0]
            if daily_count >= 5:
                brave_allowed = False
                brave_reason = f"daily_limit ({daily_count}/5)"
            # Check per-symbol 24h cache
            if brave_allowed:
                _bcur.execute("SELECT id FROM content_embeddings WHERE source_type='brave_cache' AND title=%s AND created_at > NOW() - INTERVAL '24 hours'",
                              (f"brave:{symbol}",))
                if _bcur.fetchone():
                    brave_allowed = False
                    brave_reason = f"cached_24h ({symbol})"
            # Check 60-min cooldown
            if brave_allowed:
                _bcur.execute("SELECT created_at FROM content_embeddings WHERE source_type='brave_cache' ORDER BY created_at DESC LIMIT 1")
                last = _bcur.fetchone()
                if last:
                    from datetime import datetime, timezone
                    age_min = (datetime.now(timezone.utc) - last[0].astimezone(timezone.utc)).total_seconds() / 60
                    if age_min < 60:
                        brave_allowed = False
                        brave_reason = f"cooldown ({int(age_min)}min < 60min)"
            _bconn.close()
        except Exception:
            pass

        # Full fallback chain: Brave → Finnhub supplement → DB (Google/Yahoo already ingested)
        web_found = False

        if brave_allowed:
            try:
                from web_research import search_web
                query_terms = f"{symbol} stock"
                if source_hint == "research":
                    query_terms += " retirement SSDI disability planning 2026"
                else:
                    query_terms += " analysis dividend retirement income"
                web_results = search_web(query_terms, count=3)
                if web_results:
                    web_lines = [f"WEB RESEARCH (Brave — {brave_reason}):"]
                    for wr in web_results[:3]:
                        web_lines.append(f"  {wr.get('title', '')[:60]} — {wr.get('description', '')[:80]}")
                    extra_context.append("\n".join(web_lines))
                    web_found = True
                    # Record cache entry
                    try:
                        _cc = _get_conn()
                        _cc.cursor().execute(
                            "INSERT INTO content_embeddings (source_type, source_id, title, tfidf_terms) VALUES ('brave_cache', 0, %s, '{}'::jsonb)",
                            (f"brave:{symbol}",))
                        _cc.commit(); _cc.close()
                    except Exception:
                        pass
            except Exception:
                print(f"  [search] Brave failed for {symbol} → Finnhub fallback")

        if not web_found:
            # Fallback: Finnhub-specific articles (higher quality than general RSS)
            if brave_reason:
                print(f"  [search] {symbol}: {brave_reason} → using Finnhub + DB")
            try:
                _fconn = _get_conn()
                _fcur = _fconn.cursor(cursor_factory=__import__('psycopg2.extras', fromlist=['RealDictCursor']).RealDictCursor)
                _fcur.execute("""
                    SELECT title, summary, (relevance_score * 100)::int as quality_score
                    FROM news_articles
                    WHERE source = 'finnhub' AND symbol = %s
                      AND created_at > NOW() - INTERVAL '14 days'
                    ORDER BY relevance_score DESC LIMIT 3
                """, (symbol.upper(),))
                fh_rows = _fcur.fetchall()
                _fconn.close()
                if fh_rows:
                    fh_lines = ["FINNHUB NEWS (supplemental):"]
                    for r in fh_rows:
                        fh_lines.append(f"  Q:{r.get('quality_score',0)} {r.get('title','')[:60]}")
                    extra_context.append("\n".join(fh_lines))
            except Exception:
                pass

    if not items and not extra_context:
        return ""

    lines = []
    for ctx in extra_context:
        lines.append(ctx)
    if items:
        lines.append(f"RECENT INTELLIGENCE ({len(items)} items, last {days} days):")
    total_chars = 0
    for item in items[:8]:
        src = item.get("source_type", "?")
        title = item.get("title", "")[:60]
        snippet = (item.get("text_snippet") or "")[:100].replace("\n", " ")
        q = item.get("quality_score", 0)
        strats = item.get("strategy_tags") or []
        if isinstance(strats, str):
            try:
                strats = json.loads(strats)
            except Exception:
                strats = []
        strat_str = ", ".join(s.replace("_", " ") for s in strats[:2]) if strats else ""

        line = f"  [{src}] Q:{q} {title}"
        if strat_str:
            line += f" ({strat_str})"
        if snippet:
            line += f" — {snippet}"

        # For YouTube: include structured key_points if available
        sj = item.get("structured_json")
        if sj and src == "youtube":
            if isinstance(sj, str):
                try: sj = json.loads(sj)
                except: sj = None
            if sj and sj.get("key_points"):
                for kp in sj["key_points"][:2]:
                    line += f"\n    • {kp[:80]}"
            if sj and sj.get("action_items"):
                for ai in sj["action_items"][:1]:
                    line += f"\n    → {ai[:80]}"

        if total_chars + len(line) > max_chars:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)
