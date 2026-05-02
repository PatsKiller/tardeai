"""_news_strategy_classifier.py — Keyword-based strategy classification for news articles.

Used by:
  - POST /api/v2/admin/backfill-news-strategy (one-time backfill)
  - aegis_overnight.py Phase 1.5 (nightly after ingestion)
"""
import os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Strategy patterns — ordered by specificity (most specific first)
STRATEGY_KEYWORDS = {
    # Most specific first — first match wins
    "ssdi": ["ssdi", "social security disability", "disability insurance", "sga ",
             "trial work period", "substantial gainful activity"],
    "disability_retirement": ["disability", "medicaid", "medicare advantage", "dual eligible",
                              "able account", "spend down", "disability benefit",
                              "disability income", "disability planning"],
    "trust_estate": ["special needs trust", "pooled trust", "estate planning", "irrevocable trust",
                     "probate", "elder law", "beneficiary designation", "inheritance"],
    "roth_conversion": ["roth conversion", "backdoor roth", "mega backdoor", "roth ladder",
                        "convert to roth", "roth rollover", "roth ira conversion"],
    "tax_planning": ["tax bracket", "capital gains tax", "tax loss harvest", "tax efficiency",
                     "irmaa", "magi", "tax strategy", "estimated tax", "tax bill"],
    "rollover_ira": ["rollover ira", "ira rollover", "traditional to roth", "ira transfer"],
    "401k_rollover": ["401k rollover", "401k to ira", "401k distribution",
                      "401k loan", "401k withdrawal", "401(k)"],
    "retirement_planning": ["retirement income", "retirement planning", "social security",
                            "required minimum", "rmd ", "retire early", "fire movement",
                            "pension", "retirement age", "golden years"],
    "dividend_income": ["dividend growth", "dividend income", "high yield", "dividend stock",
                        "yield on cost", "dividend aristocrat", "income investing", "ex-dividend",
                        "dividend cut", "dividend increase", "schd"],
    "high_yield_income_bdc": ["bdc", "business development company", "closed-end fund", "cef ",
                              "preferred stock", "mlp ", "covered call etf", "jepi", "jepq"],
    "bond_income": ["bond", "treasury", "fixed income", "corporate bond", "municipal bond",
                    "bond fund", "bnd ", "tips ", "i bond"],
    "macro_fed": ["federal reserve", "fed meeting", "interest rate", "inflation",
                  "yield curve", "economic outlook", "gdp ", "unemployment rate", "cpi "],
    "etf_indexing": ["index fund", "expense ratio", "passive investing", "total market",
                     "vanguard", "low cost fund", "s&p 500 index"],
}

RETIREMENT_RELEVANCE_KEYWORDS = {
    "high": ["retirement", "ira", "401k", "roth", "rmd", "pension", "social security",
             "ssdi", "medicare", "medicaid", "disability", "irmaa", "special needs trust"],
    "medium": ["dividend", "income", "yield", "tax", "estate", "beneficiary", "rebalance"],
}


def classify_strategy(title: str) -> tuple:
    """Classify a news article title into strategy_type + retirement_relevance.
    Returns (strategy_type, retirement_relevance). Never returns None for strategy_type.
    """
    t = (title or "").lower()

    # Strategy — first match wins (ordered by specificity)
    strategy = "investment_general"
    for strat, keywords in STRATEGY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            strategy = strat
            break

    # Retirement relevance
    relevance = "low"
    for level, keywords in RETIREMENT_RELEVANCE_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            relevance = level
            break

    return strategy, relevance


def classify_and_update_all() -> int:
    """Backfill all news_articles with missing strategy_type. Returns count updated."""
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all articles (backfill everything, even already-tagged — ensures consistency)
    cur.execute("SELECT id, title, strategy_type FROM news_articles")
    rows = cur.fetchall()

    updated = 0
    wcur = conn.cursor()
    for r in rows:
        strat, relevance = classify_strategy(r["title"])
        wcur.execute("UPDATE news_articles SET strategy_type = %s, retirement_relevance = %s WHERE id = %s",
                     (strat, relevance, r["id"]))
        updated += 1

    conn.commit()
    conn.close()
    print(f"[news-strategy] Backfill complete: {updated}/{len(rows)} articles updated")
    return updated


def classify_and_update_batch(article_ids: list) -> int:
    """Classify a specific batch of article IDs. Called by aegis_overnight after ingestion."""
    if not article_ids:
        return 0
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, title FROM news_articles WHERE id = ANY(%s)", (article_ids,))
    rows = cur.fetchall()

    wcur = conn.cursor()
    for r in rows:
        strat, relevance = classify_strategy(r["title"])
        wcur.execute("UPDATE news_articles SET strategy_type = %s, retirement_relevance = %s WHERE id = %s",
                     (strat, relevance, r["id"]))

    conn.commit()
    conn.close()
    return len(rows)


def classify_recent_untagged() -> int:
    """Classify any news_articles from the last 48h that have no strategy_type."""
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT id, title FROM news_articles
                   WHERE (strategy_type IS NULL OR strategy_type = '')
                     AND created_at > NOW() - INTERVAL '48 hours'""")
    rows = cur.fetchall()

    wcur = conn.cursor()
    updated = 0
    for r in rows:
        strat, relevance = classify_strategy(r["title"])
        wcur.execute("UPDATE news_articles SET strategy_type = %s, retirement_relevance = %s WHERE id = %s",
                     (strat, relevance, r["id"]))
        updated += 1

    conn.commit()
    conn.close()
    if updated:
        print(f"[news-strategy] Classified {updated} recent untagged articles")
    return updated
