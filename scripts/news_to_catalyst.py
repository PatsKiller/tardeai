#!/usr/bin/env python3
"""
news_to_catalyst.py — Process unprocessed news_articles into catalyst_events.

Loads news_articles where no linked catalyst_event exists (matched by title/symbol),
classifies catalyst_type via keyword matching, scores using catalyst_type_weights
from DB, and creates catalyst_events rows.

CLI: python3 scripts/news_to_catalyst.py [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# ── Catalyst keyword map ─────────────────────────────────────────────────────
# Each catalyst_type maps to keywords found in headlines/summaries.
CATALYST_KEYWORDS = {
    "earnings_beat":      ["beat expectations", "beats estimate", "tops estimate", "earnings beat",
                           "revenue beat", "profit beat", "exceeds expectations", "blowout quarter"],
    "earnings_miss":      ["misses estimate", "earnings miss", "revenue miss", "disappoints",
                           "falls short", "below expectations", "profit miss"],
    "guidance_raise":     ["raises guidance", "raises outlook", "ups forecast", "boosts guidance",
                           "raises full-year", "increases forecast"],
    "guidance_lower":     ["lowers guidance", "cuts outlook", "reduces forecast", "warns on",
                           "lowers full-year", "disappointing outlook"],
    "contract_win":       ["wins contract", "awarded contract", "new partnership", "strategic alliance",
                           "major deal", "billion-dollar contract", "new agreement"],
    "fda_approval":       ["fda approval", "fda clears", "fda grants", "regulatory approval",
                           "drug approved", "clearance granted"],
    "merger_acquisition": ["acquisition", "merger", "takeover", "buyout", "acquires",
                           "to acquire", "deal to buy", "merge with"],
    "insider_buy":        ["insider buy", "insider purchase", "director buys", "ceo buys",
                           "officer purchases", "insider buying"],
    "analyst_upgrade":    ["upgrade", "price target raised", "price target increase",
                           "initiates with buy", "outperform"],
    "short_squeeze":      ["short squeeze", "short interest", "heavily shorted", "days to cover"],
    "geopolitical":       ["tariff", "sanctions", "trade war", "geopolitical", "embargo",
                           "trade deal", "trade agreement"],
    "dividend_increase":  ["dividend increase", "dividend hike", "raises dividend",
                           "dividend boost", "special dividend"],
    "dividend_cut":       ["dividend cut", "suspends dividend", "eliminates dividend",
                           "dividend reduction", "dividend slash"],
    "stock_split":        ["stock split", "forward split", "reverse split"],
    "buyback":            ["buyback", "share repurchase", "repurchase program",
                           "buy back shares"],
    "ceo_change":         ["ceo change", "new ceo", "ceo resigns", "ceo steps down",
                           "executive shakeup", "names new chief"],
    "sector_rotation":    ["sector rotation", "money flowing into", "rotation out of",
                           "sector shift"],
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _classify(title: str, summary: str) -> str:
    """Return the best catalyst_type for a headline+summary, or 'other'."""
    text = f"{title} {summary or ''}".lower()
    for ctype, keywords in CATALYST_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return ctype
    return "other"


def _severity_from_weight(weight: float) -> str:
    if weight >= 0.85:
        return "high"
    if weight >= 0.55:
        return "medium"
    return "low"


def run(as_json: bool = False):
    conn = _get_conn()
    cur = conn.cursor()

    # Load catalyst_type_weights from DB
    cur.execute("SELECT catalyst_type, base_weight FROM catalyst_type_weights")
    weights = {row[0]: float(row[1]) for row in cur.fetchall()}

    # Find news articles with no linked catalyst event (by matching symbol + title)
    cur.execute("""
        SELECT n.id, n.symbol, n.strategy_type, n.title, n.summary,
               n.source, n.source_url, n.published_at
        FROM news_articles n
        LEFT JOIN catalyst_events ce
            ON ce.symbol = n.symbol AND ce.headline = n.title
        WHERE ce.id IS NULL
        ORDER BY n.published_at DESC NULLS LAST
        LIMIT 500
    """)
    rows = cur.fetchall()

    created = []
    for nid, symbol, strategy_type, title, summary, source, source_url, published_at in rows:
        ctype = _classify(title, summary)
        weight = weights.get(ctype, 0.3)
        severity = _severity_from_weight(weight)

        cur.execute("""
            INSERT INTO catalyst_events
                (symbol, strategy_type, catalyst_type, headline, description,
                 severity, confidence, impact_score, source, source_url, published_at,
                 raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, headline) DO NOTHING
            RETURNING id
        """, (
            symbol, strategy_type, ctype, title, summary,
            severity, round(weight, 2), round(weight * 10, 1),
            source or "news_to_catalyst", source_url, published_at,
            json.dumps({"news_article_id": nid, "classifier": "keyword_v1"})
        ))
        _row = cur.fetchone()
        if _row is None:
            continue  # (symbol, headline) already present (race with news_ingestion inline) — skip
        new_id = _row[0]
        created.append({
            "catalyst_id": new_id,
            "news_id": nid,
            "symbol": symbol,
            "catalyst_type": ctype,
            "severity": severity,
            "impact_score": round(weight * 10, 1),
        })

    conn.commit()
    cur.close()
    conn.close()

    if as_json:
        print(json.dumps({"created": len(created), "catalysts": created}, default=str))
    else:
        print(f"[news_to_catalyst] Created {len(created)} catalyst events from unprocessed news.")
        for c in created[:20]:
            print(f"  {c['symbol']:>8} | {c['catalyst_type']:<20} | sev={c['severity']:<6} | score={c['impact_score']}")
        if len(created) > 20:
            print(f"  ... and {len(created) - 20} more")


if __name__ == "__main__":
    run(as_json="--json" in sys.argv)
