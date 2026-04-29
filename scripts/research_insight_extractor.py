#!/usr/bin/env python3
"""research_insight_extractor.py — Extract structured insights from research sources.

Converts free-text research (news articles, transcripts, notes) into structured
decision-ready data with strategy_type, thesis, time_horizon, confidence.

Usage:
    python3 scripts/research_insight_extractor.py --from-news [--json]
    python3 scripts/research_insight_extractor.py --from-text "DGRO is a great dividend growth ETF for long-term income" --symbol DGRO [--json]
    python3 scripts/research_insight_extractor.py --from-catalysts [--json]
"""
import json, os, re, sys, hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Thesis detection keywords
_BULLISH = {"buy", "add", "accumulate", "upgrade", "outperform", "bullish", "upside",
            "growth", "opportunity", "breakout", "undervalued", "strong", "dividend raise",
            "dividend increase", "beat expectations", "guidance raise", "contract win"}
_BEARISH = {"sell", "trim", "avoid", "downgrade", "underperform", "bearish", "downside",
            "risk", "overvalued", "breakdown", "dividend cut", "miss", "guidance lower",
            "debt concern", "default risk", "recession"}
_INCOME = {"dividend", "yield", "income", "distribution", "payout", "coupon", "DRIP",
           "ex-div", "covered call", "premium", "monthly income"}
_HORIZON_SHORT = {"this week", "short-term", "swing", "day trade", "near-term", "immediate"}
_HORIZON_LONG = {"long-term", "retirement", "compound", "decade", "5-year", "10-year", "lifetime"}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def extract_insight(text: str, symbol: str = None, source_type: str = "manual",
                    source_reference: str = None) -> dict:
    """Extract structured insight from free text. Classification-first."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    text_lower = text.lower()
    words = set(text_lower.split())

    # Detect symbols mentioned
    symbols_found = []
    if symbol:
        symbols_found.append(symbol.upper())
    # Also scan for ticker patterns
    cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    known = {r["symbol"] for r in cur.fetchall()}
    for w in re.findall(r'\b[A-Z]{2,5}\b', text):
        if w in known and w not in symbols_found:
            symbols_found.append(w)

    # Get strategy_type from classification
    strategy_type = None
    if symbols_found:
        cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE",
                    (symbols_found[0],))
        r = cur.fetchone()
        if r:
            strategy_type = r["strategy_type"]

    # Detect thesis type
    bull_score = sum(1 for kw in _BULLISH if kw in text_lower)
    bear_score = sum(1 for kw in _BEARISH if kw in text_lower)
    thesis_type = "neutral"
    if bull_score > bear_score + 1:
        thesis_type = "bullish"
    elif bear_score > bull_score + 1:
        thesis_type = "bearish"
    elif bull_score > 0 and bear_score > 0:
        thesis_type = "mixed"

    # Detect time horizon
    time_horizon = "medium"
    if any(kw in text_lower for kw in _HORIZON_SHORT):
        time_horizon = "short"
    elif any(kw in text_lower for kw in _HORIZON_LONG):
        time_horizon = "long"

    # Confidence from text signals
    confidence = 0.5
    if bull_score + bear_score >= 4:
        confidence = 0.7
    if bull_score + bear_score >= 6:
        confidence = 0.8

    # Income relevance
    income_words = sum(1 for kw in _INCOME if kw in text_lower)
    yield_thesis = None
    if income_words >= 2:
        yield_thesis = f"{income_words} income-related signals detected"

    # Key arguments extraction (simple: first 3 sentences)
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 20]
    key_args = [{"text": s[:200]} for s in sentences[:3]]

    # Contradiction flags
    contradictions = []
    if bull_score > 0 and bear_score > 0:
        contradictions.append({"type": "mixed_signals", "detail": f"bullish:{bull_score} bearish:{bear_score}"})

    # Structured thesis
    structured = f"{thesis_type.upper()} ({time_horizon}-term)"
    if symbols_found:
        structured = f"{symbols_found[0]}: {structured}"
    if yield_thesis:
        structured += f" — income-relevant"

    # Price target extraction
    price_target = None
    pt_match = re.search(r'(?:target|price target|PT)[:\s]*\$?(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if pt_match:
        price_target = float(pt_match.group(1))

    insight = {
        "symbol": symbols_found[0] if symbols_found else None,
        "strategy_type": strategy_type,
        "source_type": source_type,
        "source_reference": source_reference,
        "thesis_type": thesis_type,
        "time_horizon": time_horizon,
        "confidence": confidence,
        "headline": text[:100],
        "structured_thesis": structured,
        "supporting_entities": symbols_found,
        "key_arguments": key_args,
        "contradiction_flags": contradictions,
        "price_target": price_target,
        "yield_thesis": yield_thesis,
        "risk_factors": [],
        "raw_text": text[:2000],
        "extraction_model": "keyword_v1",
        "extraction_confidence": confidence,
    }

    # Store in DB
    cur.execute("""
        INSERT INTO research_insights
            (symbol, strategy_type, source_type, source_reference, thesis_type, time_horizon,
             confidence, headline, structured_thesis, supporting_entities, key_arguments,
             contradiction_flags, price_target, yield_thesis, risk_factors, raw_text,
             extraction_model, extraction_confidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (insight["symbol"], insight["strategy_type"], source_type, source_reference,
          thesis_type, time_horizon, confidence, insight["headline"][:200],
          structured, symbols_found, json.dumps(key_args, default=str),
          json.dumps(contradictions, default=str), price_target, yield_thesis,
          json.dumps([], default=str), text[:2000], "keyword_v1", confidence))
    row = cur.fetchone()
    insight["id"] = row["id"] if row else None

    conn.commit()
    conn.close()
    return insight


def extract_from_news(limit: int = 100) -> list:
    """Extract insights from recent news articles that don't have linked insights yet."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT na.id, na.symbol, na.title, na.summary, na.source, na.strategy_type
        FROM news_articles na
        WHERE na.relevance_score >= 0.4
        AND NOT EXISTS (SELECT 1 FROM research_insights ri WHERE ri.source_reference = 'news:' || na.id::text)
        ORDER BY na.created_at DESC LIMIT %s
    """, (limit,))
    articles = cur.fetchall()
    conn.close()

    results = []
    for a in articles:
        text = f"{a.get('title', '')}. {a.get('summary', '')}"
        if len(text.strip()) < 20:
            continue
        try:
            r = extract_insight(text, symbol=a.get("symbol"), source_type="news",
                                source_reference=f"news:{a['id']}")
            results.append(r)
        except Exception as e:
            pass
    return results


def extract_from_catalysts(limit: int = 100) -> list:
    """Extract insights from catalyst events."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT ce.id, ce.symbol, ce.headline, ce.description, ce.catalyst_type, ce.strategy_type
        FROM catalyst_events ce
        WHERE ce.confidence >= 0.3
        AND NOT EXISTS (SELECT 1 FROM research_insights ri WHERE ri.source_reference = 'catalyst:' || ce.id::text)
        ORDER BY ce.created_at DESC LIMIT %s
    """, (limit,))
    catalysts = cur.fetchall()
    conn.close()

    results = []
    for c in catalysts:
        text = f"{c.get('headline', '')}. {c.get('description', '')}"
        if len(text.strip()) < 20:
            continue
        try:
            r = extract_insight(text, symbol=c.get("symbol"), source_type="catalyst",
                                source_reference=f"catalyst:{c['id']}")
            results.append(r)
        except Exception as e:
            pass
    return results


if __name__ == "__main__":
    if "--from-text" in sys.argv:
        idx = sys.argv.index("--from-text")
        text = sys.argv[idx + 1]
        sym = sys.argv[sys.argv.index("--symbol") + 1].upper() if "--symbol" in sys.argv else None
        r = extract_insight(text, symbol=sym)
        print(f"  {r['symbol'] or '?':>6} {r['thesis_type']:>8} {r['time_horizon']:>6} conf={r['confidence']:.1f} — {r['structured_thesis']}")
    elif "--from-news" in sys.argv:
        results = extract_from_news()
        print(f"[research] Extracted {len(results)} insights from news")
        if "--json" in sys.argv:
            print(json.dumps(results[:5], indent=2, default=str))
    elif "--from-catalysts" in sys.argv:
        results = extract_from_catalysts()
        print(f"[research] Extracted {len(results)} insights from catalysts")
    else:
        # Default: extract from both
        n = extract_from_news()
        c = extract_from_catalysts()
        print(f"[research] Extracted {len(n)} from news, {len(c)} from catalysts ({len(n)+len(c)} total)")
        if "--json" in sys.argv:
            print(json.dumps({"news": len(n), "catalysts": len(c)}, indent=2))
