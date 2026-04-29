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

    # YouTube transcripts
    cur.execute("""
        SELECT 'youtube' as source_type, title, LEFT(transcript_text, 200) as text_snippet,
               quality_score, relevance_score,
               strategy_tags, agent_tags, ingested_at as date, '' as symbol
        FROM youtube_transcripts
        WHERE agent_tags @> %s
          AND quality_score >= %s
          AND ingested_at > NOW() - INTERVAL '%s days'
        ORDER BY ingested_at DESC LIMIT %s
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

    # YouTube + social — keyword search in text
    for table, text_col, date_col, q_col, title_col in [
        ("youtube_transcripts", "transcript_text", "ingested_at", "quality_score", "title"),
        ("social_posts", "text", "ingested_at", "quality_score", "username"),
    ]:
        cur.execute(f"""
            SELECT '{table.split('_')[0]}' as source_type,
                   {title_col} as title, LEFT({text_col}, 200) as text_snippet,
                   {q_col} as quality_score, relevance_score,
                   strategy_tags, agent_tags, {date_col} as date
            FROM {table}
            WHERE ({text_col} ILIKE %s OR {title_col} ILIKE %s)
              AND {q_col} >= %s
              AND {date_col} > NOW() - INTERVAL '%s days'
            ORDER BY {date_col} DESC LIMIT %s
        """, (sym_pattern, sym_pattern, min_quality, days, limit))
        results.extend(cur.fetchall())

    conn.close()
    results.sort(key=lambda r: r.get("date") or "", reverse=True)
    return results[:limit]


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
            correct = "CORRECT" if (rec in ("BUY", "ADD") and chg7 > 0) or (rec in ("SELL", "TRIM") and chg7 < 0) or (rec == "HOLD" and abs(chg7) < 5) else "WRONG" if abs(chg7) > 2 else "NEUTRAL"
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

    if not items:
        return ""

    lines = [f"RECENT INTELLIGENCE ({len(items)} items, last {days} days):"]
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

        if total_chars + len(line) > max_chars:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)
