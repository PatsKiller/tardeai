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
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    """Semantic search across YouTube transcripts using TF-IDF similarity + keyword fallback.

    1. Keyword ILIKE match for candidate retrieval
    2. TF-IDF semantic re-ranking using content_embeddings
    Returns results ranked by semantic_score (TF-IDF similarity * quality_score).
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    pattern = f"%{query}%"
    # Candidate retrieval: keyword match (cast wider net)
    cur.execute("""
        SELECT yt.id, yt.title, yt.channel_name,
               COALESCE(yt.summary, LEFT(yt.cleaned_text, 300)) as text_snippet,
               yt.quality_score, yt.relevance_score, yt.strategy_tags, yt.sub_tags,
               yt.structured_json, yt.ingested_at as date,
               ce.tfidf_terms
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

    # Semantic re-ranking using TF-IDF similarity
    try:
        from content_scoring import semantic_similarity
        for c in candidates:
            terms = c.get("tfidf_terms") or {}
            if isinstance(terms, str):
                terms = json.loads(terms)
            sim = semantic_similarity(query, terms) if terms else 0.0
            c["semantic_score"] = round(sim * (c.get("quality_score", 50) / 100), 3)
        candidates.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
    except Exception:
        pass  # Fall back to quality-based ordering

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
                      days: int = 7) -> str:
    """Get a text summary of recent intel for LLM prompt injection.

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

    # Brave Search fallback — if we have few items, try web search
    if symbol and len(items) < 3:
        try:
            from web_research import search_web
            web_results = search_web(f"{symbol} stock analysis retirement dividend 2026", count=3)
            if web_results:
                web_lines = ["WEB RESEARCH (Brave Search):"]
                for wr in web_results[:3]:
                    web_lines.append(f"  {wr.get('title', '')[:60]} — {wr.get('description', '')[:80]}")
                extra_context.append("\n".join(web_lines))
        except Exception:
            pass  # Brave may be unavailable (402 / no key)

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
