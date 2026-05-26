# Source Export: scripts/sentiment_processor.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/sentiment_processor.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `6f63e2f9cc855339d1c1c343963d94fb4b1f15c9ffb717709a36c9596e10e23b` |
| **File Size** | 5717 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
sentiment_processor.py — Score unscored news/catalysts for sentiment.

Loads news_articles without a sentiment_score, applies a simple positive/negative
word-counting lexicon as a baseline, and stores results in sentiment_observations.

CLI: python3 scripts/sentiment_processor.py [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# ── Simple sentiment lexicon ─────────────────────────────────────────────────
POSITIVE_WORDS = {
    "beat", "beats", "exceeds", "strong", "growth", "upgrade", "raises",
    "bullish", "rally", "surge", "surges", "gain", "gains", "profit",
    "profitable", "record", "outperform", "buy", "breakout", "momentum",
    "accelerate", "dividend", "boost", "innovation", "partnership",
    "approval", "approved", "positive", "upside", "expanding", "recovery",
    "opportunity", "optimistic", "confident", "success", "successful",
    "higher", "increase", "increased", "improvement", "improved",
}

NEGATIVE_WORDS = {
    "miss", "misses", "disappoints", "weak", "decline", "downgrade",
    "lowers", "bearish", "crash", "plunge", "loss", "losses", "deficit",
    "underperform", "sell", "breakdown", "stall", "cut", "cuts",
    "warning", "warns", "risk", "negative", "downside", "shrinking",
    "recession", "layoffs", "lawsuit", "fraud", "investigation",
    "default", "delisting", "bankruptcy", "lower", "decrease",
    "deterioration", "concern", "uncertainty", "volatile",
}

RISK_KEYWORDS = [
    "sec investigation", "class action", "going concern", "restatement",
    "audit failure", "delisting", "bankruptcy", "default notice",
]

OPPORTUNITY_KEYWORDS = [
    "fda approval", "new contract", "earnings beat", "guidance raise",
    "insider buying", "analyst upgrade", "dividend increase",
]


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _score_text(text: str) -> tuple:
    """Return (sentiment_label, score, confidence, pos_phrases, neg_phrases, risk_kw, opp_kw)."""
    words = text.lower().split()
    text_lower = text.lower()

    pos_count = sum(1 for w in words if w.strip(".,;:!?()") in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w.strip(".,;:!?()") in NEGATIVE_WORDS)
    total = pos_count + neg_count

    if total == 0:
        return "neutral", 0.0, 0.2, [], [], [], []

    score = (pos_count - neg_count) / max(total, 1)
    confidence = min(0.9, 0.3 + (total / 20.0))

    pos_found = [w for w in words if w.strip(".,;:!?()") in POSITIVE_WORDS][:5]
    neg_found = [w for w in words if w.strip(".,;:!?()") in NEGATIVE_WORDS][:5]
    risk_found = [kw for kw in RISK_KEYWORDS if kw in text_lower]
    opp_found = [kw for kw in OPPORTUNITY_KEYWORDS if kw in text_lower]

    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    return label, round(score, 3), round(confidence, 3), pos_found, neg_found, risk_found, opp_found


def run(as_json: bool = False):
    conn = _get_conn()
    cur = conn.cursor()

    # Load news articles without sentiment_score
    cur.execute("""
        SELECT id, symbol, strategy_type, title, summary
        FROM news_articles
        WHERE sentiment_score IS NULL
        ORDER BY published_at DESC NULLS LAST
        LIMIT 500
    """)
    rows = cur.fetchall()

    scored = []
    for nid, symbol, strategy_type, title, summary in rows:
        text = f"{title} {summary or ''}"
        label, score, confidence, pos, neg, risk_kw, opp_kw = _score_text(text)

        # Update the news_article itself
        cur.execute("""
            UPDATE news_articles SET sentiment = %s, sentiment_score = %s WHERE id = %s
        """, (label, score, nid))

        # Insert into sentiment_observations
        cur.execute("""
            INSERT INTO sentiment_observations
                (symbol, strategy_type, source_type, source_id,
                 overall_sentiment, sentiment_score, confidence,
                 key_phrases, risk_keywords, opportunity_keywords,
                 model_used, raw_text_snippet)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            symbol, strategy_type, "news_article", nid,
            label, score, confidence,
            json.dumps(pos[:5] + neg[:5]),
            json.dumps(risk_kw),
            json.dumps(opp_kw),
            "lexicon_v1",
            text[:300],
        ))
        obs_id = cur.fetchone()[0]

        scored.append({
            "observation_id": obs_id,
            "news_id": nid,
            "symbol": symbol,
            "sentiment": label,
            "score": score,
            "confidence": confidence,
        })

    conn.commit()
    cur.close()
    conn.close()

    if as_json:
        print(json.dumps({"scored": len(scored), "observations": scored}, default=str))
    else:
        print(f"[sentiment_processor] Scored {len(scored)} articles.")
        for s in scored[:20]:
            print(f"  {s['symbol']:>8} | {s['sentiment']:<8} | score={s['score']:+.3f} | conf={s['confidence']:.2f}")
        if len(scored) > 20:
            print(f"  ... and {len(scored) - 20} more")


if __name__ == "__main__":
    run(as_json="--json" in sys.argv)
```
