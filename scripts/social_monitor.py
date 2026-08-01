#!/usr/bin/env python3
"""
DEPRECATED (Data Broker Phase 5): use scripts/social_ingest.py as the canonical
social_posts writer. This module remains for backward-compatible cron until removed.

social_monitor.py — Social media ingestion with unified scoring.

Ingests posts from X/Twitter, Reddit, StockTwits (when API keys are configured).
Scores every post using content_scoring.score_social_post() for quality, relevance,
sentiment, engagement velocity, and misinformation risk.

API keys needed (in .env):
  TWITTER_BEARER_TOKEN  — X/Twitter API v2 ($100/mo basic tier)
  REDDIT_CLIENT_ID      — Reddit API (free read access)
  REDDIT_CLIENT_SECRET
  STOCKTWITS_API_KEY    — StockTwits (free tier available)

Usage:
    python3 scripts/social_monitor.py --test
    python3 scripts/social_monitor.py --ingest          # ingest from all configured APIs
    python3 scripts/social_monitor.py --status           # show API status
    python3 scripts/social_monitor.py --manual "text" --username user --platform x
"""
import json, os, sys
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


def _get_env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        try:
            for line in (PROJECT_ROOT / ".env").read_text().splitlines():
                if line.startswith(f"{key}="):
                    val = line.split("=", 1)[1].strip()
        except Exception:
            pass
    return val


def _get_portfolio_symbols() -> list:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r[0] for r in cur.fetchall()]
        conn.close()
        return symbols
    except Exception:
        return []


SOCIAL_APIS = {
    "x": {"env_var": "TWITTER_BEARER_TOKEN", "label": "X/Twitter API v2"},
    "reddit": {"env_var": "REDDIT_CLIENT_ID", "label": "Reddit API"},
    "stocktwits": {"env_var": "STOCKTWITS_API_KEY", "label": "StockTwits API"},
}


def check_api_status() -> dict:
    """Check which social APIs are configured."""
    status = {}
    for name, cfg in SOCIAL_APIS.items():
        key = _get_env(cfg["env_var"])
        status[name] = {
            "configured": bool(key),
            "env_var": cfg["env_var"],
            "label": cfg["label"],
        }
    return status


def store_post(platform: str, post_id: str, text: str, username: str = "",
               display_name: str = "", post_date: datetime = None,
               url: str = "", followers: int = 0, verified: bool = False,
               likes: int = 0, retweets: int = 0, replies: int = 0,
               added_by: str = "ai") -> dict:
    """Score, tag, and store a social post. Returns scoring result."""
    from content_scoring import score_social_post, tag_content

    symbols = _get_portfolio_symbols()
    scores = score_social_post(
        text=text, username=username, platform=platform,
        followers=followers, verified=verified,
        likes=likes, retweets=retweets, replies=replies,
        post_date=post_date, symbols=symbols,
    )
    tags = tag_content(text=text, title="")

    import psycopg2
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO social_posts
                (platform, post_id, username, display_name, text, post_date, url,
                 followers, verified, likes, retweets, replies,
                 engagement_metrics, symbols_mentioned,
                 quality_score, relevance_score, validation_status,
                 matched_keywords, sentiment, sentiment_score, added_by,
                 strategy_tags, agent_tags)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (platform, post_id) DO NOTHING
        """, (
            platform, post_id, username, display_name, text[:2000],
            post_date or datetime.now(timezone.utc), url,
            followers, verified, likes, retweets, replies,
            json.dumps({"likes": likes, "retweets": retweets, "replies": replies}),
            json.dumps(scores["matched_keywords"]),
            scores["quality_score"], scores["relevance_score"],
            scores["validation_status"], json.dumps(scores["matched_keywords"]),
            scores["sentiment"], scores["sentiment_score"], added_by,
            json.dumps(tags["strategy_tags"]), json.dumps(tags["agent_tags"]),
        ))
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
    finally:
        conn.close()

    return scores


def ingest_x(symbols: list, max_per_symbol: int = 10) -> int:
    """Ingest from X/Twitter API. Returns count of new posts."""
    token = _get_env("TWITTER_BEARER_TOKEN")
    if not token:
        return 0

    # X API v2 search/recent endpoint
    import urllib.request
    count = 0
    for sym in symbols[:10]:  # rate limit protection
        query = f"${sym} lang:en -is:retweet"
        url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results={max_per_symbol}&tweet.fields=created_at,public_metrics,author_id"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                for tweet in data.get("data", []):
                    metrics = tweet.get("public_metrics", {})
                    store_post(
                        platform="x",
                        post_id=tweet["id"],
                        text=tweet.get("text", ""),
                        username=tweet.get("author_id", ""),
                        post_date=datetime.fromisoformat(tweet["created_at"].replace("Z", "+00:00")) if tweet.get("created_at") else None,
                        url=f"https://x.com/i/status/{tweet['id']}",
                        likes=metrics.get("like_count", 0),
                        retweets=metrics.get("retweet_count", 0),
                        replies=metrics.get("reply_count", 0),
                    )
                    count += 1
        except Exception as e:
            print(f"  [social] X API error for {sym}: {e}")
    return count


def ingest_stocktwits(symbols: list, max_per_symbol: int = 10) -> int:
    """Ingest from StockTwits API. Returns count of new posts."""
    key = _get_env("STOCKTWITS_API_KEY")
    if not key:
        return 0

    import urllib.request
    count = 0
    for sym in symbols[:10]:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json?access_token={key}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                for msg in data.get("messages", [])[:max_per_symbol]:
                    store_post(
                        platform="stocktwits",
                        post_id=str(msg["id"]),
                        text=msg.get("body", ""),
                        username=msg.get("user", {}).get("username", ""),
                        display_name=msg.get("user", {}).get("name", ""),
                        post_date=datetime.fromisoformat(msg["created_at"].replace("Z", "+00:00")) if msg.get("created_at") else None,
                        url=f"https://stocktwits.com/message/{msg['id']}",
                        followers=msg.get("user", {}).get("followers", 0),
                        likes=msg.get("likes", {}).get("total", 0),
                    )
                    count += 1
        except Exception as e:
            print(f"  [social] StockTwits error for {sym}: {e}")
    return count


def ingest_all() -> dict:
    """Run ingestion from all configured APIs."""
    symbols = _get_portfolio_symbols()
    results = {"symbols": len(symbols), "posts": {}}

    apis = check_api_status()
    for name, info in apis.items():
        if not info["configured"]:
            results["posts"][name] = {"status": "not_configured", "env_var": info["env_var"]}
            continue

        if name == "x":
            count = ingest_x(symbols)
        elif name == "stocktwits":
            count = ingest_stocktwits(symbols)
        else:
            count = 0  # Reddit not yet implemented
            results["posts"][name] = {"status": "not_implemented", "count": 0}
            continue

        results["posts"][name] = {"status": "ok", "count": count}

    return results


def test_pipeline():
    """Test scoring engine with sample social posts."""
    print("=== Social Media Scoring — Test ===\n")

    from content_scoring import score_social_post
    symbols = _get_portfolio_symbols()

    # API status
    print("API Status:")
    for name, info in check_api_status().items():
        status = "CONFIGURED" if info["configured"] else f"NOT SET ({info['env_var']})"
        print(f"  {info['label']:<25} {status}")

    # Test scoring with sample posts
    print("\nScoring Engine Test:")
    test_posts = [
        {
            "text": "$SCHD just raised its dividend again! 12th consecutive year of dividend growth. Great for retirement income portfolios. Yield now at 3.8%.",
            "username": "dividendgrowth", "followers": 50000, "verified": True,
            "likes": 450, "retweets": 120, "replies": 35,
        },
        {
            "text": "$V Visa earnings beat estimates, revenue up 10% YoY. Price target raised to $320 by multiple analysts. Upgrade to strong buy.",
            "username": "marketwatch", "followers": 500000, "verified": True,
            "likes": 1200, "retweets": 340, "replies": 89,
        },
        {
            "text": "🚀🚀🚀 $DOGE to the moon!! 1000x guaranteed returns!! Not financial advice but trust me bro this is the one!! Act now!!",
            "username": "cryptobro99", "followers": 200, "verified": False,
            "likes": 5, "retweets": 2, "replies": 1,
        },
        {
            "text": "Interesting day in the market. SPY holding steady above support.",
            "username": "randomtrader", "followers": 500, "verified": False,
            "likes": 12, "retweets": 3, "replies": 2,
        },
        {
            "text": "Roth conversion strategy: with the 22% bracket room, converting IRA positions during market dips is smart tax planning for early retirees. IRMAA lookback means plan 2 years ahead.",
            "username": "earlyretirementnow", "followers": 80000, "verified": True,
            "likes": 890, "retweets": 210, "replies": 67,
        },
    ]

    for post in test_posts:
        scores = score_social_post(
            text=post["text"],
            username=post["username"],
            platform="x",
            followers=post["followers"],
            verified=post["verified"],
            likes=post["likes"],
            retweets=post["retweets"],
            replies=post["replies"],
            post_date=datetime.now(timezone.utc),
            symbols=symbols,
        )
        q = scores["quality_score"]
        r = scores["relevance_score"]
        s = scores["sentiment"]
        v = scores["validation_status"]
        bd = scores["score_breakdown"]
        print(f"\n  @{post['username']:<22} Q:{q:3} R:{r:.2f} [{v:<14}] sent:{s}")
        print(f"    {post['text'][:80]}...")
        print(f"    breakdown: rel={bd['relevance']:.0f} rec={bd['recency']} eng={bd['engagement']} cred={bd['credibility']} sent={bd['sentiment']} misinfo={bd['misinfo']}")
        if scores["matched_keywords"]:
            print(f"    keywords: {', '.join(scores['matched_keywords'][:6])}")
        if scores["misinfo_flags"]:
            print(f"    MISINFO FLAGS: {scores['misinfo_flags']}")

    # Test manual storage
    print("\n\nManual Storage Test:")
    result = store_post(
        platform="x", post_id="test_001",
        text="$SCHD dividend growth is perfect for retirement income. Yield 3.8%, IRMAA-safe conversions.",
        username="test_user", post_date=datetime.now(timezone.utc),
        likes=100, retweets=20, replies=5,
        added_by="test",
    )
    print(f"  Stored test post: Q={result['quality_score']} R={result['relevance_score']} [{result['validation_status']}]")

    # Count stored posts
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*), count(DISTINCT platform) FROM social_posts")
    count, platforms = cur.fetchone()
    conn.close()
    print(f"\n  Total stored posts: {count} across {platforms} platform(s)")

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_pipeline()
    elif "--ingest" in sys.argv:
        result = ingest_all()
        print(json.dumps(result, indent=2, default=str))
    elif "--status" in sys.argv:
        for name, info in check_api_status().items():
            status = "CONFIGURED" if info["configured"] else f"NOT SET ({info['env_var']})"
            print(f"  {info['label']:<25} {status}")
    elif "--manual" in sys.argv:
        idx = sys.argv.index("--manual")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        username = ""
        platform = "x"
        for i, a in enumerate(sys.argv):
            if a == "--username" and i + 1 < len(sys.argv): username = sys.argv[i + 1]
            if a == "--platform" and i + 1 < len(sys.argv): platform = sys.argv[i + 1]
        import hashlib
        post_id = hashlib.sha256(f"{text}:{username}".encode()).hexdigest()[:16]
        result = store_post(platform=platform, post_id=post_id, text=text,
                           username=username, added_by="user")
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage:")
        print("  --test              Run scoring engine test")
        print("  --ingest            Ingest from all configured APIs")
        print("  --status            Show API configuration status")
        print('  --manual "text" --username user --platform x    Store a manual post')
