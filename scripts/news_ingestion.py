#!/usr/bin/env python3
"""news_ingestion.py — Ingest news for portfolio/watchlist symbols.

Sources:
  - Yahoo RSS (free, always active)
  - Finnhub (if FINNHUB_API_KEY exists)
  - Benzinga RSS (free, always active — benzinga.com/feed)
  - Benzinga API (if BENZINGA_API_KEY exists — richer data, analyst ratings)

All sources dedup by symbol + title. Scored + tagged via content_scoring.
Feeds into: news_articles, catalyst_events, sentiment_observations.

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
    """Get symbols to scan from DB classifications + incubator ACTIVE symbols."""
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

    # Also include incubator ACTIVE symbols (top 50 by score to avoid overloading)
    existing = {s[0] for s in symbols}
    try:
        cur.execute("""
            SELECT DISTINCT symbol, COALESCE(strategy_id, 'screener') as strategy_type
            FROM incubator_universe
            WHERE status = 'ACTIVE' AND latest_score >= 35
            ORDER BY latest_score DESC
            LIMIT 50
        """)
        for r in cur.fetchall():
            if r["symbol"] not in existing:
                symbols.append((r["symbol"], r["strategy_type"]))
                existing.add(r["symbol"])
    except Exception:
        pass  # non-fatal — incubator table may not exist

    # Actionable/traded universe — ALWAYS cover symbols we actually trade/hold/watch so source attribution +
    # catalyst calibration have data (closes the news↔trade overlap gap). Prepended (priority-first) so the
    # per-run cap can never truncate them.
    try:
        conn.rollback()  # clear any aborted-transaction state from the optional incubator query above
        cur.execute("""
            SELECT DISTINCT u.symbol, COALESCE(tsc.strategy_type, 'traded') AS strategy_type FROM (
                SELECT symbol FROM paper_trades WHERE entry_time > now() - interval '30 days' AND symbol IS NOT NULL
                UNION SELECT symbol FROM paper_trade_proposals WHERE status IN ('PENDING','APPROVED') AND symbol IS NOT NULL
                UNION SELECT symbol FROM trade_ai_scans WHERE run_date >= CURRENT_DATE AND decision IN ('GO','WAIT') AND symbol IS NOT NULL
                UNION SELECT symbol FROM watchlist_items WHERE status = 'active' AND symbol IS NOT NULL
                -- operator directives are watch-grade regardless of lifecycle status (2026-06-12:
                -- directive symbols sat status='researched' -> zero news coverage on the watchlist)
                UNION SELECT symbol FROM watchlist_items
                      WHERE in_directive_watch = true AND status <> 'removed' AND symbol IS NOT NULL
            ) u LEFT JOIN ticker_strategy_classifications tsc ON tsc.symbol = u.symbol
        """)
        actionable = [(r["symbol"], r["strategy_type"]) for r in cur.fetchall()]
        act_syms = {a[0] for a in actionable}
        symbols = actionable + [s for s in symbols if s[0] not in act_syms]
    except Exception:
        pass  # non-fatal — fall back to base universe

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


def _fetch_google_news_rss(symbol: str) -> list:
    """Fetch Google News RSS — free, captures Benzinga + Seeking Alpha + Motley Fool + all sources."""
    articles = []
    try:
        import re
        query = urllib.parse.quote(f"{symbol} stock") if hasattr(urllib, 'parse') else symbol
        url = f"https://news.google.com/rss/search?q={symbol}+stock&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TradeAI/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub = item.findtext("pubDate", "")
                source_name = item.findtext("source", "")
                # Map source to our naming
                src_lower = source_name.lower()
                if "benzinga" in src_lower:
                    source_tag = "benzinga_rss"
                elif "seeking alpha" in src_lower:
                    source_tag = "seeking_alpha"
                elif "motley fool" in src_lower:
                    source_tag = "motley_fool"
                elif "barron" in src_lower:
                    source_tag = "barrons"
                elif "morningstar" in src_lower:
                    source_tag = "morningstar"
                elif "marketwatch" in src_lower:
                    source_tag = "marketwatch"
                else:
                    source_tag = f"google_news:{source_name[:30]}"
                articles.append({
                    "title": title,
                    "summary": f"[{source_name}] {title}",
                    "source": source_tag,
                    "source_url": link,
                    "published_at": pub,
                })
    except Exception:
        pass  # Gracefully skip
    return articles


def _fetch_benzinga_api(symbol: str, api_key: str) -> list:
    """Fetch Benzinga news via API — richer data with analyst ratings."""
    articles = []
    try:
        from_date = datetime.now().strftime("%Y-%m-%d")
        url = (f"https://api.benzinga.com/api/v2/news"
               f"?token={api_key}&tickers={symbol}&dateFrom={from_date}"
               f"&pageSize=5&displayOutput=full")
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for item in data[:5]:
                title = item.get("title", "")
                body = item.get("body", item.get("teaser", ""))
                # Clean HTML
                import re
                clean_body = re.sub(r'<[^>]+>', '', body or "")[:500]
                pub_str = item.get("created", item.get("updated", ""))
                articles.append({
                    "title": title,
                    "summary": clean_body,
                    "source": "benzinga_api",
                    "source_url": item.get("url", ""),
                    "published_at": pub_str,
                    "benzinga_channels": item.get("channels", []),
                    "benzinga_stocks": item.get("stocks", []),
                })
    except Exception:
        pass  # Gracefully skip if API key invalid or rate limited
    return articles


def _feed_downstream(conn, symbol: str, strategy_type: str, article: dict, scores: dict, tags: dict):
    """Feed article into catalyst_events, sentiment_observations, research_insights."""
    cur = conn.cursor()
    title = article.get("title", "")[:500]
    summary = article.get("summary", "")[:1000]
    source = article.get("source", "unknown")
    relevance = scores.get("relevance_score", 0)
    keywords = scores.get("matched_keywords", [])

    # Catalyst + sentiment — use savepoints to prevent transaction abort
    # NOTE (2026-06-04 repair): this INSERT previously used columns title/relevance_score
    # which do NOT exist on catalyst_events (headline/impact_score) — it failed silently on
    # every article (savepoint rollback + except:pass) and wrote 0 rows for ~5 weeks. Columns
    # corrected; classify the type (no generic-'news' quality loss) and dedup on (symbol,
    # headline) so this and the scheduled news_to_catalyst.py classifier can both run safely.
    if relevance > 0.3:
        try:
            from news_to_catalyst import _classify, _severity_from_weight
            ctype = _classify(title, summary)
            severity = _severity_from_weight(float(relevance))
        except Exception:
            ctype, severity = "news", "low"
        try:
            cur.execute("SAVEPOINT ds_cat")
            cur.execute("""INSERT INTO catalyst_events
                    (symbol, strategy_type, catalyst_type, headline, description,
                     severity, confidence, impact_score, source, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, headline) DO NOTHING""",
                (symbol, strategy_type, ctype, title, summary,
                 severity, round(float(relevance), 2), round(float(relevance) * 10, 1),
                 source, article.get("published_at")))
            cur.execute("RELEASE SAVEPOINT ds_cat")
        except Exception:
            try: cur.execute("ROLLBACK TO SAVEPOINT ds_cat")
            except Exception: pass

    try:
        from content_scoring import SENTIMENT_POSITIVE, SENTIMENT_NEGATIVE
        text_lower = f"{title} {summary}".lower()
        pos = sum(1 for s in SENTIMENT_POSITIVE if s in text_lower)
        neg = sum(1 for s in SENTIMENT_NEGATIVE if s in text_lower)
        sentiment = "positive" if pos > neg else "negative" if neg > pos else "neutral"
        # 2026-06-04 repair: columns were source/sentiment/score/raw_text which do NOT exist
        # (table has source_type/overall_sentiment/sentiment_score/raw_text_snippet) — silently
        # failing (savepoint rollback + except:pass) since the schema migration; frozen 2026-05-10.
        cur.execute("SAVEPOINT ds_sent")
        cur.execute("""INSERT INTO sentiment_observations
                (symbol, strategy_type, source_type, overall_sentiment, sentiment_score, raw_text_snippet)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (symbol, strategy_type, source, sentiment, relevance, title[:500]))
        cur.execute("RELEASE SAVEPOINT ds_sent")
    except Exception:
        try: cur.execute("ROLLBACK TO SAVEPOINT ds_sent")
        except Exception: pass


def ingest(priority_only: bool = False) -> dict:
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    symbols = _get_symbols(priority_only)
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if not finnhub_key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("FINNHUB_API_KEY="): finnhub_key = line.split("=", 1)[1].strip()

    # Benzinga API key (optional — RSS works without it)
    benzinga_key = os.environ.get("BENZINGA_API_KEY", "")
    if not benzinga_key:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("BENZINGA_API_KEY="): benzinga_key = line.split("=", 1)[1].strip()

    total_new = 0
    total_scanned = 0
    source_counts = {"yahoo_rss": 0, "finnhub": 0, "benzinga_rss": 0, "benzinga_api": 0}

    _news_max = int(os.environ.get("NEWS_INGEST_MAX", "60"))  # actionable-first; raised from 30 to cover traded universe
    for sym, strategy_type in symbols[:_news_max]:  # Limit to avoid rate limits
        articles = _fetch_yahoo_rss(sym)
        if finnhub_key:
            articles.extend(_fetch_finnhub(sym, finnhub_key))
        # Google News RSS — captures Benzinga + Seeking Alpha + Motley Fool + all sources
        articles.extend(_fetch_google_news_rss(sym))
        # Benzinga API — richer data if key exists
        if benzinga_key:
            articles.extend(_fetch_benzinga_api(sym, benzinga_key))

        for a in articles:
            src = a.get("source", "")
            try:
                from hermes_source_policy import should_ingest
                ok, why = should_ingest(src)
                if not ok:
                    continue
            except Exception:
                pass
            is_google = src.startswith("google_news:") or src in ("seeking_alpha", "motley_fool", "morningstar", "barrons", "marketwatch", "benzinga_rss")
            # Dedup: Google News sources dedup by URL only (titles overlap with Yahoo)
            # Yahoo/Finnhub dedup by symbol + title
            if is_google:
                if a.get("source_url"):
                    cur.execute("SELECT id FROM news_articles WHERE source_url=%s LIMIT 1", (a["source_url"][:500],))
                    if cur.fetchone():
                        continue
                else:
                    continue  # Skip Google News without URL
            else:
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

            # Feed downstream pipeline
            _feed_downstream(conn, sym, strategy_type, a, _scores, _tags)

            source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1
            total_new += 1

        total_scanned += 1

    conn.commit()
    conn.close()

    active_sources = [s for s, c in source_counts.items() if c > 0]
    result = {"scanned": total_scanned, "new_articles": total_new, "sources": active_sources, "by_source": {s: c for s, c in source_counts.items() if c > 0}}
    print(f"[news] Scanned {total_scanned} symbols, {total_new} new articles — sources: {', '.join(f'{s}:{c}' for s, c in source_counts.items() if c > 0)}")
    return result


if __name__ == "__main__":
    # Pipeline registry heartbeat
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('news_ingestion')
    except Exception:
        pass

    try:
        priority = "--priority" in sys.argv
        result = ingest(priority_only=priority)
        if "--json" in sys.argv:
            print(json.dumps(result, indent=2, default=str))
        try:
            if _run_id: run_complete(_run_id, rows_processed=result.get('new_articles', 0))
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
