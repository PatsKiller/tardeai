# Source Export: scripts/social_ingest.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/social_ingest.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `2c0ac5bb5dd9f5db9d9e61cf0d47b3a7395d16ea20af597f1bacd5db0d725128` |
| **File Size** | 19578 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""social_ingest.py — Ingest social sentiment from StockTwits (free, no auth).

Usage:
    python3 scripts/social_ingest.py --source stocktwits --symbols "SCHD,V,TDG,LHX,LMT,NOC,RTX"
    python3 scripts/social_ingest.py --source stocktwits --holdings   # uses holdings.json symbols
    python3 scripts/social_ingest.py --source reddit                  # r/dividends, r/investing
"""
import json, sys, time, hashlib
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_holdings_symbols():
    """Get portfolio symbols from holdings.json."""
    f = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    return [h["symbol"] for h in data.get("holdings", [])
            if h.get("symbol") and not h.get("is_cash") and not h.get("is_fund")]


def ingest_stocktwits(symbols: list) -> dict:
    """Fetch recent messages from StockTwits public API for given symbols."""
    import requests

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    errors = []

    for sym in symbols:
        try:
            url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
            r = requests.get(url, timeout=15, headers={"User-Agent": "TradeAI/1.0"})

            if r.status_code == 429:
                print(f"  [stocktwits] Rate limited — stopping. Got {total_inserted} posts so far.")
                break

            if r.status_code != 200:
                errors.append(f"{sym}: HTTP {r.status_code}")
                continue

            data = r.json()
            messages = data.get("messages", [])

            for msg in messages[:10]:
                post_id = str(msg.get("id", ""))
                if not post_id:
                    continue

                # Check dedup
                cur.execute("SELECT 1 FROM social_posts WHERE platform='stocktwits' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                # Parse sentiment
                sentiment_data = msg.get("entities", {}).get("sentiment", {})
                raw_sentiment = sentiment_data.get("basic", "neutral") if sentiment_data else "neutral"
                sentiment = raw_sentiment.lower() if raw_sentiment else "neutral"
                sentiment_score = 0.7 if sentiment == "bullish" else (-0.7 if sentiment == "bearish" else 0.0)

                # Quality score: based on likes + basic engagement
                likes = msg.get("likes", {}).get("total", 0) if isinstance(msg.get("likes"), dict) else 0
                quality = min(50 + likes * 5, 95)

                # Post date
                created = msg.get("created_at", "")
                try:
                    post_date = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    post_date = datetime.now(timezone.utc)

                user = msg.get("user", {})
                username = user.get("username", "")
                followers = user.get("followers", 0)

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('stocktwits', %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, 0.5,
                            %s, %s, 'social_ingest', '[]'::jsonb, '[]'::jsonb)
                """, (
                    post_id, username, user.get("name", username),
                    msg.get("body", "")[:2000], post_date,
                    f"https://stocktwits.com/{username}/message/{post_id}",
                    followers, likes, json.dumps([sym]),
                    quality, sentiment, sentiment_score
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(1)  # Rate limit: be polite

        except Exception as e:
            errors.append(f"{sym}: {e}")
            continue

    cur.close()
    conn.close()

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors}
    print(f"[stocktwits] Inserted: {total_inserted}, Skipped (dupes): {total_skipped}, Errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")
    return result


def ingest_reddit(subreddits: list = None) -> dict:
    """Fetch recent posts from Reddit via public JSON API (no auth needed)."""
    import requests

    if subreddits is None:
        subreddits = ["dividends", "investing", "retirement", "financialindependence"]

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    errors = []

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/new/.json?limit=25"
            r = requests.get(url, timeout=15, headers={"User-Agent": "TradeAI/1.0 (portfolio intelligence)"})

            if r.status_code == 429:
                print(f"  [reddit] Rate limited on r/{sub} — stopping.")
                break
            if r.status_code != 200:
                errors.append(f"r/{sub}: HTTP {r.status_code}")
                continue

            data = r.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                pd = post.get("data", {})
                post_id = pd.get("id", "")
                if not post_id:
                    continue

                cur.execute("SELECT 1 FROM social_posts WHERE platform='reddit' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                title = pd.get("title", "")
                body = pd.get("selftext", "")[:1500]
                text = f"{title}\n{body}".strip()

                post_date = datetime.fromtimestamp(pd.get("created_utc", 0), tz=timezone.utc)
                score = pd.get("score", 0)
                num_comments = pd.get("num_comments", 0)
                quality = min(40 + score + num_comments * 2, 95)

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, replies, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('reddit', %s, %s, %s, %s, %s, %s,
                            0, %s, %s, '[]'::jsonb, %s, 0.4,
                            'neutral', 0, 'social_ingest', %s, '[]'::jsonb)
                """, (
                    post_id, pd.get("author", ""), pd.get("author", ""),
                    text, post_date,
                    f"https://reddit.com{pd.get('permalink', '')}",
                    score, num_comments, quality,
                    json.dumps([f"retirement_{sub}" if sub in ("retirement", "financialindependence") else f"dividend_{sub}"])
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(2)  # Reddit asks for 1 req/sec

        except Exception as e:
            errors.append(f"r/{sub}: {e}")
            continue

    cur.close()
    conn.close()

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors}
    print(f"[reddit] Inserted: {total_inserted}, Skipped (dupes): {total_skipped}, Errors: {len(errors)}")
    return result


def _extract_tickers(text: str) -> list:
    """Extract $TICKER mentions and bare uppercase tickers from text."""
    import re
    # $TICKER format
    dollar_tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
    # Bare tickers in context (3-5 uppercase letters not common words)
    COMMON_WORDS = {'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER',
                    'WAS', 'ONE', 'OUR', 'OUT', 'HAS', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW',
                    'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'DID', 'GET', 'HAS', 'HIM', 'LET',
                    'SAY', 'SHE', 'TOO', 'USE', 'DAD', 'MOM', 'SON', 'AGO', 'ANY', 'BAD',
                    'BIG', 'END', 'FAR', 'FEW', 'GOT', 'HAD', 'HIGH', 'JUST', 'KEEP',
                    'THIS', 'THAT', 'WILL', 'WITH', 'FROM', 'HAVE', 'BEEN', 'COULD',
                    'WOULD', 'SHOULD', 'EACH', 'MAKE', 'LIKE', 'LONG', 'LOOK', 'MANY',
                    'MOST', 'MUCH', 'NEED', 'NEXT', 'ONLY', 'OVER', 'SAME', 'SOME',
                    'THAN', 'THEM', 'THEN', 'THEY', 'WANT', 'WELL', 'WHAT', 'WHEN',
                    'ALSO', 'BACK', 'BEEN', 'CALL', 'COME', 'DOWN', 'EVEN', 'FIND',
                    'FIRE', 'FIRST', 'GIVE', 'GOOD', 'HELP', 'HERE', 'KNOW', 'LAST',
                    'LEFT', 'LIFE', 'LIVE', 'MADE', 'MORE', 'MOVE', 'MUCH', 'MUST',
                    'NAME', 'PART', 'PLAN', 'PLAY', 'POST', 'REAL', 'SELL', 'SURE',
                    'TAKE', 'TELL', 'TURN', 'VERY', 'WORK', 'YEAR', 'YOLO', 'HOLD',
                    'EDIT', 'TLDR', 'HODL', 'FOMO', 'ROTH', 'SSDI'}
    bare = re.findall(r'\b([A-Z]{2,5})\b', text)
    bare_tickers = [t for t in bare if t not in COMMON_WORDS and len(t) >= 2]
    return list(set(dollar_tickers + bare_tickers))


# Strategy-based discovery lists for StockTwits trending
STRATEGY_DISCOVERY = {
    "dividend_growth": ["SCHD", "VYM", "DGRO", "VIG", "HDV", "DIVO", "JEPI", "JEPQ", "O", "MAIN"],
    "defense_aerospace": ["LMT", "NOC", "RTX", "LHX", "GD", "BA", "HII", "TDG", "LDOS", "BAH"],
    "growth_tech": ["NVDA", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "TSM", "AVGO", "AMD", "CRM"],
    "retirement_income": ["SCHD", "VZ", "T", "MO", "PM", "KO", "PEP", "JNJ", "PG", "MMM"],
    "sector_rotation": ["XLF", "XLE", "XLK", "XLV", "XLI", "XLU", "XLP", "XLB", "XLRE", "XLC"],
}


def ingest_stocktwits_discovery() -> dict:
    """Fetch trending symbols across strategies — discover what's hot, not just portfolio."""
    import requests

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    errors = []

    # 1. StockTwits trending endpoint
    try:
        r = requests.get("https://api.stocktwits.com/api/2/trending/symbols.json",
                         timeout=15, headers={"User-Agent": "TradeAI/1.0"})
        if r.status_code == 200:
            trending = r.json().get("symbols", [])
            trending_tickers = [s.get("symbol", "") for s in trending[:20]]
            print(f"  [discovery] StockTwits trending: {', '.join(trending_tickers[:10])}")
            result = ingest_stocktwits(trending_tickers[:10])
            total_inserted += result.get("inserted", 0)
        else:
            errors.append(f"trending: HTTP {r.status_code}")
    except Exception as e:
        errors.append(f"trending: {e}")

    # 2. Strategy-based discovery — pick 3 non-portfolio symbols per strategy
    holdings_syms = set(_get_holdings_symbols())
    for strategy, symbols in STRATEGY_DISCOVERY.items():
        discovery_syms = [s for s in symbols if s not in holdings_syms][:3]
        if discovery_syms:
            try:
                result = ingest_stocktwits(discovery_syms)
                total_inserted += result.get("inserted", 0)
                time.sleep(1)
            except Exception as e:
                errors.append(f"{strategy}: {e}")

    conn.close()
    print(f"[discovery] Total inserted: {total_inserted}, Errors: {len(errors)}")
    return {"inserted": total_inserted, "errors": errors}


def ingest_reddit_with_discovery(subreddits: list = None) -> dict:
    """Reddit ingest that also extracts ticker mentions for discovery routing."""
    import requests

    if subreddits is None:
        subreddits = ["dividends", "investing", "retirement", "financialindependence",
                      "stocks", "ValueInvesting"]

    conn = _get_conn()
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    discovered_tickers = {}
    errors = []

    # Map subreddits to strategies
    SUB_STRATEGY = {
        "dividends": "dividend_income",
        "investing": "general",
        "retirement": "retirement_ssdi_roth_tax",
        "financialindependence": "retirement_ssdi_roth_tax",
        "stocks": "growth_momentum",
        "ValueInvesting": "value_dividend",
    }

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot/.json?limit=25"
            r = requests.get(url, timeout=15, headers={"User-Agent": "TradeAI/1.0 (portfolio intelligence)"})

            if r.status_code == 429:
                print(f"  [reddit] Rate limited on r/{sub} — stopping.")
                break
            if r.status_code != 200:
                errors.append(f"r/{sub}: HTTP {r.status_code}")
                continue

            data = r.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                pd = post.get("data", {})
                post_id = pd.get("id", "")
                if not post_id:
                    continue

                cur.execute("SELECT 1 FROM social_posts WHERE platform='reddit' AND post_id=%s", (post_id,))
                if cur.fetchone():
                    total_skipped += 1
                    continue

                title = pd.get("title", "")
                body = pd.get("selftext", "")[:1500]
                text = f"{title}\n{body}".strip()

                # Extract tickers for discovery
                tickers = _extract_tickers(text)
                strategy = SUB_STRATEGY.get(sub, "general")
                for t in tickers:
                    if t not in discovered_tickers:
                        discovered_tickers[t] = {"count": 0, "strategies": set()}
                    discovered_tickers[t]["count"] += 1
                    discovered_tickers[t]["strategies"].add(strategy)

                post_date = datetime.fromtimestamp(pd.get("created_utc", 0), tz=timezone.utc)
                score = pd.get("score", 0)
                num_comments = pd.get("num_comments", 0)
                quality = min(40 + score + num_comments * 2, 95)

                # Sentiment from score + upvote ratio
                upvote_ratio = pd.get("upvote_ratio", 0.5)
                sentiment = "bullish" if upvote_ratio > 0.75 and score > 10 else ("bearish" if upvote_ratio < 0.4 else "neutral")
                sentiment_score = (upvote_ratio - 0.5) * 2  # -1 to 1 scale

                cur.execute("""
                    INSERT INTO social_posts
                        (platform, post_id, username, display_name, text, post_date, url,
                         followers, likes, replies, symbols_mentioned, quality_score, relevance_score,
                         sentiment, sentiment_score, added_by, strategy_tags, agent_tags)
                    VALUES ('reddit', %s, %s, %s, %s, %s, %s,
                            0, %s, %s, %s, %s, 0.5,
                            %s, %s, 'social_ingest', %s, '[]'::jsonb)
                """, (
                    post_id, pd.get("author", ""), pd.get("author", ""),
                    text, post_date,
                    f"https://reddit.com{pd.get('permalink', '')}",
                    score, num_comments, json.dumps(tickers[:10]),
                    quality, sentiment, round(sentiment_score, 3),
                    json.dumps([strategy])
                ))
                total_inserted += 1

            conn.commit()
            time.sleep(2)

        except Exception as e:
            errors.append(f"r/{sub}: {e}")
            continue

    cur.close()
    conn.close()

    # Report discovered tickers
    if discovered_tickers:
        top_mentions = sorted(discovered_tickers.items(), key=lambda x: x[1]["count"], reverse=True)[:15]
        print(f"[reddit-discovery] Top mentioned tickers:")
        for ticker, info in top_mentions:
            strategies = ", ".join(info["strategies"])
            print(f"  ${ticker}: {info['count']}x ({strategies})")

    result = {"inserted": total_inserted, "skipped": total_skipped, "errors": errors,
              "discovered_tickers": {k: {"count": v["count"], "strategies": list(v["strategies"])}
                                    for k, v in list(discovered_tickers.items())[:30]}}
    print(f"[reddit] Inserted: {total_inserted}, Skipped: {total_skipped}, Tickers found: {len(discovered_tickers)}")
    return result


if __name__ == "__main__":
    source = "stocktwits"
    symbols = []

    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source = sys.argv[idx + 1]

    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols")
        if idx + 1 < len(sys.argv):
            symbols = [s.strip() for s in sys.argv[idx + 1].split(",") if s.strip()]

    if "--holdings" in sys.argv:
        symbols = _get_holdings_symbols()

    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('social_ingest')
    except Exception:
        pass

    try:
        if source == "stocktwits":
            if "--discover" in sys.argv:
                print("[stocktwits] Running discovery mode (trending + strategy exploration)...")
                ingest_stocktwits_discovery()
            else:
                if not symbols:
                    symbols = _get_holdings_symbols()[:15]
                if not symbols:
                    symbols = ["SCHD", "V", "TDG", "LHX", "LMT", "NOC", "RTX"]
                print(f"[stocktwits] Ingesting for {len(symbols)} symbols: {', '.join(symbols[:10])}...")
                ingest_stocktwits(symbols)

        elif source == "reddit":
            if "--discover" in sys.argv:
                print("[reddit] Running discovery mode (hot + ticker extraction)...")
                ingest_reddit_with_discovery()
            else:
                print("[reddit] Ingesting new posts from retirement/dividend subs...")
                ingest_reddit()

        elif source == "all":
            print("=== FULL SOCIAL INGEST ===")
            print("\n[1/3] StockTwits: portfolio holdings...")
            ingest_stocktwits(_get_holdings_symbols()[:15])
            print("\n[2/3] StockTwits: discovery (trending + strategies)...")
            ingest_stocktwits_discovery()
            print("\n[3/3] Reddit: discovery mode (hot + ticker extraction)...")
            ingest_reddit_with_discovery()
            print("\n=== DONE ===")

        else:
            print(f"Unknown source: {source}. Use --source stocktwits|reddit|all [--discover] [--holdings]")

        try:
            if _run_id: run_complete(_run_id, rows_processed=0)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
```
