# Source Export: scripts/signal_fusion.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/signal_fusion.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `8bcdb2ea2f479731e5aae9d75d500f7a1c5951535650a2167482d19e97f0ae18` |
| **File Size** | 10655 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""signal_fusion.py — Fuse catalyst, news, social, sentiment into unified signal scores.

Strategy-aware weighting. Classification-first.

Usage:
    python3 scripts/signal_fusion.py --full [--json]
    python3 scripts/signal_fusion.py --symbol SCHD [--json]
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Strategy-aware fusion weights
_STRATEGY_FUSION = {
    "dividend_growth_compounder": {"catalyst": 0.40, "news": 0.35, "social": 0.10, "sentiment": 0.15},
    "covered_call_income":        {"catalyst": 0.35, "news": 0.35, "social": 0.10, "sentiment": 0.20},
    "high_yield_income_bdc":      {"catalyst": 0.40, "news": 0.30, "social": 0.10, "sentiment": 0.20},
    "bond_income":                {"catalyst": 0.30, "news": 0.40, "social": 0.05, "sentiment": 0.25},
    "core_growth_compounder":     {"catalyst": 0.35, "news": 0.30, "social": 0.15, "sentiment": 0.20},
    "defense_thesis":             {"catalyst": 0.45, "news": 0.35, "social": 0.05, "sentiment": 0.15},
    "speculative_growth":         {"catalyst": 0.30, "news": 0.20, "social": 0.30, "sentiment": 0.20},
    "swing_trade":                {"catalyst": 0.25, "news": 0.20, "social": 0.30, "sentiment": 0.25},
}
_DEFAULT_WEIGHTS = {"catalyst": 0.35, "news": 0.30, "social": 0.20, "sentiment": 0.15}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def fuse_signals(symbol: str, window_hours: int = 24) -> dict:
    """Compute fused signal for a symbol from recent catalysts, news, social, sentiment."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sym = symbol.upper()
    cutoff = datetime.now() - timedelta(hours=window_hours)

    # Classification
    cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
    cls = cur.fetchone()
    strategy_type = cls["strategy_type"] if cls else None
    weights = _STRATEGY_FUSION.get(strategy_type, _DEFAULT_WEIGHTS)

    # Recent catalysts
    cur.execute("SELECT catalyst_type, confidence, impact_score, severity FROM catalyst_events WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 5", (sym, cutoff))
    catalysts = cur.fetchall()
    catalyst_score = 0
    if catalysts:
        scores = [float(c.get("confidence", 0.5) or 0.5) * float(c.get("impact_score", 0.5) or 0.5) for c in catalysts]
        catalyst_score = min(1.0, sum(scores) / len(scores))

    # Recent news
    cur.execute("SELECT relevance_score, sentiment_score FROM news_articles WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 10", (sym, cutoff))
    news = cur.fetchall()
    news_score = 0
    if news:
        scores = [float(n.get("relevance_score", 0.5) or 0.5) for n in news]
        news_score = min(1.0, sum(scores) / len(scores))

    # Recent social (may be empty if no social monitoring)
    cur.execute("SELECT sentiment_score, engagement_score FROM social_mentions WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 10", (sym, cutoff))
    social = cur.fetchall()
    social_score = 0
    if social:
        scores = [float(s.get("engagement_score", 0.5) or 0.5) for s in social]
        social_score = min(1.0, sum(scores) / len(scores))

    # Sentiment from catalyst analysis
    cur.execute("SELECT overall_sentiment, confidence FROM catalyst_sentiment_analysis WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 3", (sym, cutoff))
    sentiments = cur.fetchall()
    sentiment_score = 0.5  # neutral default
    if sentiments:
        # Map sentiment to score
        sent_map = {"very_positive": 0.9, "positive": 0.7, "neutral": 0.5, "negative": 0.3, "very_negative": 0.1}
        scores = [sent_map.get(s.get("overall_sentiment", "neutral"), 0.5) for s in sentiments]
        sentiment_score = sum(scores) / len(scores)

    # Research insights (structured thesis data)
    cur.execute("""
        SELECT thesis_type, confidence, time_horizon, structured_thesis, id
        FROM research_insights WHERE symbol=%s AND created_at > %s AND active=TRUE
        ORDER BY created_at DESC LIMIT 5
    """, (sym, cutoff))
    research = cur.fetchall()
    research_score = 0
    research_insight_ids = []
    if research:
        # Score: bullish insights increase, bearish decrease, confidence-weighted
        thesis_map = {"bullish": 0.8, "neutral": 0.5, "bearish": 0.2, "mixed": 0.4}
        r_scores = [thesis_map.get(r.get("thesis_type", "neutral"), 0.5) * float(r.get("confidence", 0.5) or 0.5) for r in research]
        research_score = min(1.0, sum(r_scores) / len(r_scores))
        research_insight_ids = [r["id"] for r in research if r.get("id")]

    # Multi-source confirmation: research + news/catalyst alignment boosts confidence
    confirmation_bonus = 0
    if research_score > 0.5 and (catalyst_score > 0.5 or news_score > 0.5):
        confirmation_bonus = 0.05  # Small boost for multi-source alignment
    elif research_score < 0.3 and (catalyst_score > 0.5 or news_score > 0.5):
        confirmation_bonus = -0.03  # Research contradicts other sources

    # Fuse with research (reweight: research gets ~10% from social which is often empty)
    r_weight = min(0.15, weights.get("social", 0.20))  # Take from social weight
    s_weight = max(0.05, weights.get("social", 0.20) - r_weight)
    fused = (
        weights["catalyst"] * catalyst_score +
        weights["news"] * news_score +
        s_weight * social_score +
        weights["sentiment"] * sentiment_score +
        r_weight * research_score +
        confirmation_bonus
    )
    fused = round(max(0, min(1.0, fused)), 3)

    # Signal decay: reduce score for older signals
    # (cutoff already handles window, but we could age-weight within window)

    # Contradiction detection
    contradictions = []
    if news_score > 0.6 and social_score < 0.3:
        contradictions.append("positive_news_negative_social")
    if social_score > 0.7 and news_score < 0.3:
        contradictions.append("high_social_no_news_retail_risk")
    if catalyst_score > 0.7 and sentiment_score < 0.3:
        contradictions.append("strong_catalyst_negative_sentiment")
    if research_score > 0.6 and catalyst_score < 0.3:
        contradictions.append("positive_research_no_catalyst")
    if research_score < 0.3 and catalyst_score > 0.6:
        contradictions.append("negative_research_positive_catalyst")

    # Severity
    severity = "low"
    if fused > 0.7: severity = "high"
    elif fused > 0.5: severity = "medium"
    if any(c.get("severity") == "critical" for c in catalysts): severity = "critical"

    # Persist
    cur.execute("""
        INSERT INTO fused_signals (symbol, strategy_type, fused_score, catalyst_score, news_score,
                                   social_score, sentiment_score, research_score, research_insight_ids,
                                   severity, confidence, contradictions, reason_codes, human_review)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (sym, strategy_type, fused, catalyst_score, news_score, social_score, sentiment_score,
          research_score, research_insight_ids if research_insight_ids else None,
          severity, fused,
          json.dumps(contradictions), [], len(contradictions) > 0))

    # Intelligence event for high-severity signals
    if severity in ("high", "critical"):
        cur.execute("""
            INSERT INTO portfolio_intelligence_events (symbol, strategy_type, event_type, severity, source, payload)
            VALUES (%s, %s, 'fused_signal', %s, 'signal_fusion.py', %s)
        """, (sym, strategy_type, severity,
              json.dumps({"fused_score": fused, "catalyst_score": catalyst_score,
                          "news_score": news_score, "contradictions": contradictions}, default=str)))

    conn.commit()
    conn.close()

    return {
        "symbol": sym,
        "strategy_type": strategy_type,
        "fused_score": fused,
        "catalyst_score": catalyst_score,
        "news_score": news_score,
        "social_score": social_score,
        "sentiment_score": sentiment_score,
        "severity": severity,
        "contradictions": contradictions,
        "human_review": len(contradictions) > 0,
        "research_score": research_score,
        "research_insight_ids": research_insight_ids,
        "confirmation_bonus": confirmation_bonus,
        "input_counts": {"catalysts": len(catalysts), "news": len(news), "social": len(social), "sentiments": len(sentiments), "research": len(research)},
    }


def fuse_all(priority_only: bool = False) -> list:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if priority_only:
        cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE AND symbol IN (SELECT DISTINCT symbol FROM watchlist_items WHERE source='portfolio' AND status<>'removed')")
    else:
        cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()

    results = []
    for sym in symbols:
        try:
            results.append(fuse_signals(sym))
        except Exception as e:
            print(f"  [fusion] {sym}: error — {e}")
    return results


if __name__ == "__main__":
    if "--symbol" in sys.argv:
        sym = sys.argv[sys.argv.index("--symbol") + 1].upper()
        r = fuse_signals(sym)
        if "--json" in sys.argv:
            print(json.dumps(r, indent=2, default=str))
        else:
            print(f"  {r['symbol']}: fused={r['fused_score']:.3f} cat={r['catalyst_score']:.2f} news={r['news_score']:.2f} social={r['social_score']:.2f} sent={r['sentiment_score']:.2f} [{r['severity']}]")
    elif "--full" in sys.argv:
        results = fuse_all()
        print(f"[fusion] Fused {len(results)} symbols")
        high = [r for r in results if r["severity"] in ("high", "critical")]
        if high:
            print(f"  High/critical signals: {[r['symbol'] for r in high]}")
        if "--json" in sys.argv:
            print(json.dumps(results, indent=2, default=str))
    else:
        print("Usage: --symbol SCHD [--json] | --full [--json]")
```
