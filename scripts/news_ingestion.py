#!/usr/bin/env python3
"""news_ingestion.py — Ingest news for portfolio/watchlist symbols.

Sources: Yahoo RSS (free), Finnhub (if API key exists). Gracefully skips missing APIs.

Usage:
    python3 scripts/news_ingestion.py --priority [--json]
    python3 scripts/news_ingestion.py --full [--json]
"""
import json, os, sys, hashlib, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_symbols(priority_only: bool = False) -> list:
    """Get symbols to scan from DB classifications."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if priority_only:
        # Portfolio holdings + high-priority watchlist
        cur.execute("""
            SELECT DISTINCT tsc.symbol, tsc.strategy_type
            FROM ticker_strategy_classifications tsc
            WHERE tsc.active = TRUE AND tsc.symbol IN (
                SELECT DISTINCT symbol FROM watchlist_items WHERE status <> 'removed' AND source = 'portfolio'
            )
        """)
    else:
        cur.execute("SELECT symbol, strategy_type FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [(r["symbol"], r["strategy_type"]) for r in cur.fetchall()]
    conn.close()
    return symbols


def _fetch_yahoo_rss(symbol: str) -> list:
    """Fetch Yahoo Finance RSS feed for a symbol."""
    articles = []
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                desc = item.findtext("description", "")
                articles.append({
                    "title": title,
                    "summary": desc[:500] if desc else "",
                    "source": "yahoo_rss",
                    "source_url": link,
                    "published_at": pub,
                })
    except Exception as e:
        pass  # Gracefully skip
    return articles


def _fetch_finnhub(symbol: str, api_key: str) -> list:
    """Fetch Finnhub news if API key available."""
    articles = []
    try:
        from_date = datetime.now().strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={from_date}&token={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for item in data[:5]:  # Limit per symbol
                articles.append({
                    "title": item.get("headline", ""),
                    "summary": item.get("summary", "")[:500],
                    "source": "finnhub",
                    "source_url": item.get("url", ""),
                    "published_at": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat() if item.get("datetime") else None,
                })
    except Exception:
        pass
    return articles


def ingest(priority_only: bool = False) -> dict:
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    symbols = _get_symbols(priority_only)
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if not finnhub_key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("FINNHUB_API_KEY="): finnhub_key = line.split("=", 1)[1].strip()

    total_new = 0
    total_scanned = 0

    for sym, strategy_type in symbols[:30]:  # Limit to avoid rate limits
        articles = _fetch_yahoo_rss(sym)
        if finnhub_key:
            articles.extend(_fetch_finnhub(sym, finnhub_key))

        for a in articles:
            # Dedup by symbol + title hash
            title_hash = hashlib.sha256(f"{sym}:{a['title']}".encode()).hexdigest()[:24]
            cur.execute("SELECT id FROM news_articles WHERE symbol=%s AND title=%s LIMIT 1", (sym, a["title"][:500]))
            if cur.fetchone():
                continue

            # Score and tag
            from content_scoring import score_content, tag_content
            _scores = score_content(title=a["title"], text=a.get("summary", ""), source=a["source"], symbols=[sym])
            _tags = tag_content(text=a.get("summary", ""), title=a["title"])

            cur.execute("""
                INSERT INTO news_articles (symbol, strategy_type, title, summary, source, source_url, published_at,
                    relevance_score, strategy_tags, agent_tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (sym, strategy_type, a["title"][:500], a.get("summary", "")[:1000],
                  a["source"], a.get("source_url", "")[:500],
                  a.get("published_at"), _scores["relevance_score"],
                  json.dumps(_tags["strategy_tags"]), json.dumps(_tags["agent_tags"])))
            total_new += 1

        total_scanned += 1

    conn.commit()
    conn.close()

    result = {"scanned": total_scanned, "new_articles": total_new, "sources": ["yahoo_rss"] + (["finnhub"] if finnhub_key else [])}
    print(f"[news] Scanned {total_scanned} symbols, {total_new} new articles")
    return result


if __name__ == "__main__":
    priority = "--priority" in sys.argv
    result = ingest(priority_only=priority)
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
