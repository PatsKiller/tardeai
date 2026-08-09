"""
social_sentiment.py — Trade AI v12
Social sentiment analysis for GO/WAIT tickers.

Sources (all free, no API keys required):
  1. Reddit  — r/WallStreetBets, r/stocks, r/investing, r/options, r/pennystocks
  2. StockTwits — bullish/bearish ratio + message volume
  3. Composite score combining both sources

Public API:
    get_social_sentiment(ticker)             → dict
    get_social_sentiment_bulk(tickers, delay) → dict[str, dict]

Return schema per ticker:
    {
        "symbol":               str,
        "mention_count":        int,     # total mentions across all sources
        "bullish_count":        int,
        "bearish_count":        int,
        "sentiment_score":      float,   # 0.0–1.0  (0.5 = neutral)
        "sentiment_label":      str,     # Very Bullish / Bullish / Neutral / Bearish / Very Bearish
        "sentiment_emoji":      str,     # 🟢🟡🔴 etc.
        "wsb_mentions":         int,
        "stocktwits_messages":  int,
        "stocktwits_bullish_pct": float,
        "top_posts":            list[dict],   # up to 3 top posts
        "sources":              list[str],    # which sources returned data
        "error":                str | None,
    }
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 10
REQUEST_DELAY   = 0.3

_REDDIT_HEADERS = {
    "User-Agent": "TradeAI/12.0 (social sentiment scanner; contact@example.com)",
}

REDDIT_SUBS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "options",
    "pennystocks",
    "StockMarket",
]

# Subreddit weights for scoring (WSB mention = more signal)
SUB_WEIGHTS = {
    "wallstreetbets": 2.0,
    "options":        1.5,
    "pennystocks":    1.5,
    "stocks":         1.0,
    "StockMarket":    1.0,
    "investing":      0.8,
}

# Sentiment thresholds
VERY_BULLISH_THRESHOLD = 0.72
BULLISH_THRESHOLD      = 0.57
BEARISH_THRESHOLD      = 0.43
VERY_BEARISH_THRESHOLD = 0.28

# Internal cache (per-process, per-run)
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 900  # 15 minutes

_HEADERS = {
    "User-Agent": "TradeAI/12.0 (sentiment analysis; contact: tradeai@localhost)",
    "Accept": "application/json",
}


# ─────────────────────────────────────────────────────────────────────────────
# Reddit
# ─────────────────────────────────────────────────────────────────────────────

def _search_reddit(ticker: str) -> dict:
    """
    Search Reddit for ticker mentions across configured subreddits.
    Uses the public Reddit JSON API — no auth, no API key.

    Returns:
        mention_count, wsb_mentions, top_posts, sub_breakdown
    """
    ticker_upper = ticker.upper()
    # Search terms: exact ticker + common variants
    search_queries = [
        f"${ticker_upper}",   # $NVDA format
        ticker_upper,          # plain ticker
    ]

    all_posts: list[dict] = []
    wsb_mentions = 0
    sub_breakdown: dict[str, int] = {}

    for sub in REDDIT_SUBS:
        for query in search_queries[:1]:  # use $TICKER format for precision
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json"
                params = {
                    "q": query,
                    "sort": "new",
                    "restrict_sr": "true",
                    "limit": 10,
                    "t": "day",       # last 24 hours
                }
                resp = requests.get(
                    url, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT
                )
                time.sleep(REQUEST_DELAY)

                if resp.status_code == 429:
                    log.debug("[social] Reddit rate limit hit, backing off")
                    time.sleep(2.0)
                    continue
                if resp.status_code != 200:
                    continue

                data = resp.json()
                posts = data.get("data", {}).get("children", [])

                for post in posts:
                    p = post.get("data", {})
                    title     = p.get("title", "")
                    selftext  = p.get("selftext", "")
                    score     = p.get("score", 0)
                    comments  = p.get("num_comments", 0)
                    url_post  = p.get("url", "")
                    created   = p.get("created_utc", 0)
                    subreddit = p.get("subreddit", sub)
                    upvote_r  = p.get("upvote_ratio", 0.5)

                    # Verify ticker actually appears in content
                    content = (title + " " + selftext).upper()
                    if ticker_upper not in content and f"${ticker_upper}" not in content:
                        continue

                    all_posts.append({
                        "title":        title[:150],
                        "score":        score,
                        "comments":     comments,
                        "upvote_ratio": upvote_r,
                        "subreddit":    subreddit,
                        "url":          url_post,
                        "created_utc":  created,
                        "weight":       SUB_WEIGHTS.get(subreddit, 1.0),
                    })

                    if subreddit.lower() == "wallstreetbets":
                        wsb_mentions += 1

                    sub_breakdown[subreddit] = sub_breakdown.get(subreddit, 0) + 1

            except Exception as exc:
                log.debug("[social] Reddit %s/%s error: %s", sub, ticker, exc)
                continue

    # Deduplicate by title
    seen_titles: set[str] = set()
    unique_posts = []
    for p in all_posts:
        key = p["title"].lower()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique_posts.append(p)

    # Sort by weighted engagement (score * weight + comments)
    unique_posts.sort(
        key=lambda p: (p["score"] * p["weight"]) + p["comments"],
        reverse=True
    )

    return {
        "mention_count":  len(unique_posts),
        "wsb_mentions":   wsb_mentions,
        "top_posts":      unique_posts[:3],
        "sub_breakdown":  sub_breakdown,
        "posts_raw":      unique_posts,
    }


def _score_reddit_sentiment(posts: list[dict]) -> float:
    """
    Derive a 0–1 sentiment score from Reddit posts.
    Based on upvote_ratio weighted by post engagement.
    0.5 = neutral, >0.5 = bullish, <0.5 = bearish.
    """
    if not posts:
        return 0.5

    total_weight = 0.0
    weighted_sum = 0.0

    for p in posts:
        engagement = max(1, p.get("score", 1)) * p.get("weight", 1.0)
        upvote_r   = p.get("upvote_ratio", 0.5)
        # Map upvote_ratio (0–1) to sentiment proxy
        # High upvotes + popular ticker post → bullish signal
        sentiment_proxy = upvote_r
        weighted_sum  += sentiment_proxy * engagement
        total_weight  += engagement

    return weighted_sum / total_weight if total_weight > 0 else 0.5


# ─────────────────────────────────────────────────────────────────────────────
# StockTwits
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_stocktwits(ticker: str) -> dict:
    """
    Fetch StockTwits stream for a ticker.
    Public API, no authentication required.

    Returns bullish/bearish counts, message volume, and top messages.
    """
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        params = {"limit": 30}
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)

        if resp.status_code == 404:
            return {"error": "ticker_not_found", "messages": 0}
        if resp.status_code == 429:
            return {"error": "rate_limited", "messages": 0}
        if resp.status_code != 200:
            return {"error": f"http_{resp.status_code}", "messages": 0}

        data = resp.json()
        symbol_info = data.get("symbol", {})
        messages    = data.get("messages", [])

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        top_msgs: list[dict] = []

        for msg in messages:
            body      = msg.get("body", "")
            entities  = msg.get("entities", {})
            sentiment = msg.get("entities", {}).get("sentiment", {})
            sent_val  = (sentiment.get("basic") or "").lower() if sentiment else ""

            if sent_val == "bullish":
                bullish_count += 1
            elif sent_val == "bearish":
                bearish_count += 1
            else:
                neutral_count += 1

            likes   = (msg.get("likes") or {}).get("total", 0)
            reshares = msg.get("reshares_count", 0) or 0

            if len(top_msgs) < 3 and body:
                top_msgs.append({
                    "text":       body[:200],
                    "sentiment":  sent_val or "neutral",
                    "likes":      likes,
                    "reshares":   reshares,
                    "created_at": msg.get("created_at", ""),
                })

        total_tagged = bullish_count + bearish_count
        bullish_pct  = (bullish_count / total_tagged * 100) if total_tagged > 0 else 50.0

        # StockTwits also provides watch count + message count in symbol info
        watch_count  = symbol_info.get("watchlist_count", 0)

        return {
            "messages":         len(messages),
            "bullish_count":    bullish_count,
            "bearish_count":    bearish_count,
            "neutral_count":    neutral_count,
            "bullish_pct":      round(bullish_pct, 1),
            "watch_count":      watch_count,
            "top_msgs":         top_msgs,
            "error":            None,
        }

    except Exception as exc:
        log.debug("[social] StockTwits %s error: %s", ticker, exc)
        return {"error": str(exc), "messages": 0}


# ─────────────────────────────────────────────────────────────────────────────
# Composite scoring
# ─────────────────────────────────────────────────────────────────────────────

def _composite_score(reddit: dict, st: dict) -> float:
    """
    Combine Reddit and StockTwits signals into a single 0–1 score.

    Weights:
      - StockTwits bullish% → 50% weight (explicit sentiment labels)
      - Reddit upvote ratio → 30% weight
      - Mention volume boost → 20% weight (high activity = stronger signal)
    """
    scores   = []
    weights  = []

    # StockTwits: bullish_pct → 0–1 scale
    st_msgs = st.get("messages", 0)
    if st_msgs > 0 and st.get("error") is None:
        st_score = st.get("bullish_pct", 50.0) / 100.0
        # Weight by message count (more messages = higher confidence)
        st_weight = min(2.0, 0.5 + (st_msgs / 30.0))
        scores.append(st_score)
        weights.append(st_weight)

    # Reddit: upvote-ratio-based sentiment
    reddit_posts = reddit.get("posts_raw", [])
    if reddit_posts:
        reddit_score  = _score_reddit_sentiment(reddit_posts)
        reddit_weight = min(1.5, 0.3 + (len(reddit_posts) / 20.0))
        scores.append(reddit_score)
        weights.append(reddit_weight)

    # Volume boost: many mentions with positive signal = higher confidence
    total_mentions = reddit.get("mention_count", 0) + st_msgs
    if total_mentions >= 20 and scores:
        avg_so_far = sum(s * w for s, w in zip(scores, weights)) / sum(weights)
        if avg_so_far > 0.5:
            # Nudge bullish if high volume
            scores.append(min(1.0, avg_so_far + 0.05))
            weights.append(0.5)
        elif avg_so_far < 0.5:
            scores.append(max(0.0, avg_so_far - 0.05))
            weights.append(0.5)

    if not scores:
        return 0.5  # neutral default

    return sum(s * w for s, w in zip(scores, weights)) / sum(weights)


def _score_to_label(score: float) -> tuple[str, str]:
    """Convert 0–1 score to (label, emoji)."""
    if score >= VERY_BULLISH_THRESHOLD:
        return "Very Bullish", "🟢🟢"
    if score >= BULLISH_THRESHOLD:
        return "Bullish", "🟢"
    if score > BEARISH_THRESHOLD:
        return "Neutral", "🟡"
    if score > VERY_BEARISH_THRESHOLD:
        return "Bearish", "🔴"
    return "Very Bearish", "🔴🔴"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_social_sentiment(
    ticker: str,
    use_cache: bool = True,
) -> dict:
    """
    Fetch and score social sentiment for a single ticker.

    Sources: Reddit (r/WSB, r/stocks, r/investing, r/options, r/pennystocks)
             + StockTwits

    Returns a sentiment dict (see module docstring for schema).
    """
    ticker = ticker.upper().strip()

    # Cache check
    if use_cache and ticker in _cache:
        cached_ts, cached_result = _cache[ticker]
        if time.time() - cached_ts < CACHE_TTL:
            log.debug("[social] %s — cache hit", ticker)
            return cached_result

    reddit = _search_reddit(ticker)
    st     = _fetch_stocktwits(ticker)

    comp_score = _composite_score(reddit, st)
    label, emoji = _score_to_label(comp_score)

    # Combine top posts from both sources
    top_posts: list[dict] = []
    for p in reddit.get("top_posts", []):
        top_posts.append({
            "source":    f"r/{p['subreddit']}",
            "text":      p["title"],
            "score":     p["score"],
            "comments":  p["comments"],
            "url":       p.get("url", ""),
        })
    for m in st.get("top_msgs", []):
        top_posts.append({
            "source":    "StockTwits",
            "text":      m["text"],
            "likes":     m["likes"],
            "sentiment": m["sentiment"],
        })

    sources_used = []
    if reddit.get("mention_count", 0) > 0:
        sources_used.append("reddit")
    if st.get("messages", 0) > 0 and st.get("error") is None:
        sources_used.append("stocktwits")

    result = {
        "symbol":                  ticker,
        "mention_count":           reddit.get("mention_count", 0) + st.get("messages", 0),
        "bullish_count":           st.get("bullish_count", 0),
        "bearish_count":           st.get("bearish_count", 0),
        "sentiment_score":         round(comp_score, 3),
        "sentiment_label":         label,
        "sentiment_emoji":         emoji,
        "wsb_mentions":            reddit.get("wsb_mentions", 0),
        "reddit_mentions":         reddit.get("mention_count", 0),
        "reddit_sub_breakdown":    reddit.get("sub_breakdown", {}),
        "stocktwits_messages":     st.get("messages", 0),
        "stocktwits_bullish_pct":  st.get("bullish_pct", 50.0),
        "stocktwits_watch_count":  st.get("watch_count", 0),
        "top_posts":               top_posts[:5],
        "sources":                 sources_used,
        "error":                   st.get("error") if not sources_used else None,
        "scanned_at":              datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    _cache[ticker] = (time.time(), result)
    log.info(
        "[social] %s — %s %s | Reddit:%d  WSB:%d  ST:%d (%.0f%% bull)",
        ticker, label, emoji,
        reddit.get("mention_count", 0),
        reddit.get("wsb_mentions", 0),
        st.get("messages", 0),
        st.get("bullish_pct", 50.0),
    )
    return result


def get_social_sentiment_bulk(
    tickers: list[str],
    delay: float = 0.3,
    max_tickers: int = 20,
) -> dict[str, dict]:
    """
    Fetch social sentiment for a list of tickers.

    Parameters
    ----------
    tickers     : list of ticker symbols
    delay       : seconds between requests (be polite to Reddit/StockTwits)
    max_tickers : hard cap (keeps runtime reasonable — 20 tickers ≈ 40–60 seconds)

    Returns
    -------
    dict of ticker → sentiment result dict
    """
    results: dict[str, dict] = {}
    batch = [t.upper().strip() for t in tickers[:max_tickers]]

    log.info("[social] bulk sentiment — %d tickers", len(batch))

    for i, ticker in enumerate(batch):
        results[ticker] = get_social_sentiment(ticker)
        if delay > 0 and i < len(batch) - 1:
            time.sleep(delay)

    bullish = sum(1 for v in results.values()
                  if v.get("sentiment_label", "") in ("Bullish", "Very Bullish"))
    log.info("[social] bulk complete — %d/%d bullish sentiment", bullish, len(results))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Social Radar — Reverse Screener
# ─────────────────────────────────────────────────────────────────────────────

# Words that look like tickers but aren't
_RADAR_STOPWORDS: set[str] = {
    "THE","AND","FOR","NOT","BUT","HAS","ARE","WAS","OUT","GET","PUT","ALL",
    "ONE","TWO","NEW","OLD","NOW","OUR","ITS","CAN","HAD","HIM","HIS","HOW",
    "WHO","DID","FED","ATH","ATL","EPS","CEO","CFO","IPO","ETF","FDA","SEC",
    "IMO","TBH","EMA","SMA","RSI","SPY","QQQ","IWM","VIX","WSB","YOU","LOL",
    "WTF","DUE","AMC","AI","DD","TA","US","USD","GDP","CPI","EOD","EOM","EOY",
    "YOY","QOQ","MOM","RR","EOW","YOLO","FOMO","HODL","MOASS","JUST","ONLY",
    "ALSO","EVEN","WHEN","THEN","THAN","FROM","WITH","THAT","THIS","THEY",
    "THEM","WERE","BEEN","HAVE","WILL","WOULD","COULD","SHOULD","WHAT","SOME",
    "INTO","VERY","OVER","BACK","BEEN","BOTH","DOWN","EACH","DOES","FROM",
    "GOOD","HAVE","HERE","HIGH","LIKE","LONG","MADE","MAKE","MANY","MORE",
    "MOST","MOVE","MUCH","MUST","NEXT","ONCE","ONLY","OPEN","PART","PLAY",
    "SAID","SAME","SELL","SHOW","SIDE","SLOW","STOP","SURE","TAKE","THEY",
    "TIME","TRUE","TURN","TYPE","UPON","USED","VERY","WAIT","WELL","WENT",
    "WERE","WHAT","WHEN","WILL","WITH","YEAR","YOUR","NYSE","AMEX","FOMC",
    "AAPL","MSFT","NVDA","GOOG","AMZN","META","TSLA","NFLX",  # blue chips — ignore in radar
}

def scan_social_radar(
    screener_syms: list[str] | None = None,
    min_mentions: int = 3,
    max_results: int = 20,
) -> list[dict]:
    """
    Scan Reddit hot posts for stock tickers NOT in the current screener.
    Uses hot.json endpoint — broader than search, captures trending organic posts.

    Parameters
    ----------
    screener_syms : tickers already in screener (excluded from radar output)
    min_mentions  : minimum total weighted mentions to surface a ticker
                    (WSB dollar-mention counts as 3, WSB bare = 2, others = 1)
    max_results   : max tickers to return (sorted by wsb_mentions desc)

    Returns
    -------
    list of dicts: {symbol, mention_count, wsb_mentions, sub_breakdown,
                    top_post, top_post_score, weighted_score, scanned_at}
    """
    screener_set: set[str] = {s.upper().strip() for s in (screener_syms or [])}
    scan_time = datetime.now().strftime("%H:%M ET")

    # Subreddits to scan: (name, post_limit, mention_weight)
    SUBS: list[tuple[str, int, float]] = [
        ("wallstreetbets", 50, 2.5),
        ("options",        30, 2.0),
        ("pennystocks",    30, 1.5),
        ("stocks",         30, 1.0),
        ("StockMarket",    20, 1.0),
        ("investing",      15, 0.7),
    ]

    ticker_data: dict[str, dict] = {}

    for sub, limit, weight in SUBS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json"
            resp = requests.get(
                url,
                headers=_REDDIT_HEADERS,
                params={"limit": limit},
                timeout=REQUEST_TIMEOUT,
            )
            time.sleep(REQUEST_DELAY)

            if resp.status_code == 429:
                log.debug("[radar] r/%s rate limited", sub)
                time.sleep(3.0)
                continue
            if resp.status_code != 200:
                continue

            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                p         = post.get("data", {})
                title     = p.get("title", "")
                body      = p.get("selftext", "")[:500]
                post_score = p.get("score", 0)
                combined  = f"{title} {body}"

                # Extract $TICKER (high confidence, counts as double)
                dollar_tickers = set(re.findall(r'\$([A-Z]{1,5})\b', combined))
                # Extract ALLCAPS words (lower confidence)
                all_caps = set(re.findall(r'\b([A-Z]{2,5})\b', combined))
                # Filter stopwords from bare mentions
                bare_tickers = all_caps - _RADAR_STOPWORDS - dollar_tickers

                for sym in dollar_tickers | bare_tickers:
                    if sym in screener_set or sym in _RADAR_STOPWORDS:
                        continue

                    if sym not in ticker_data:
                        ticker_data[sym] = {
                            "symbol":        sym,
                            "mention_count": 0,
                            "wsb_mentions":  0,
                            "weighted_score": 0.0,
                            "sub_breakdown": {},
                            "top_post":      "",
                            "top_post_score": 0,
                        }
                    d = ticker_data[sym]

                    # Weighted count: dollar mention = 2, bare = 1, times sub weight
                    count_add = 2 if sym in dollar_tickers else 1
                    d["mention_count"]   += count_add
                    d["weighted_score"]  += count_add * weight
                    d["sub_breakdown"][sub] = d["sub_breakdown"].get(sub, 0) + count_add

                    if sub == "wallstreetbets":
                        d["wsb_mentions"] += count_add

                    if post_score > d["top_post_score"]:
                        d["top_post"]       = title[:100]
                        d["top_post_score"] = post_score

        except Exception as exc:
            log.debug("[radar] r/%s error: %s", sub, exc)
            continue

    # Filter and score
    # WSB high-karma post auto-qualifies even with 1 mention
    filtered = []
    for sym, d in ticker_data.items():
        effective = d["mention_count"]
        if d["wsb_mentions"] > 0 and d["top_post_score"] > 200:
            effective = max(effective, min_mentions)   # auto-qualify
        if effective >= min_mentions:
            d["scanned_at"] = scan_time
            filtered.append(d)

    # Sort: WSB mentions desc → weighted score desc
    filtered.sort(key=lambda x: (x["wsb_mentions"], x["weighted_score"]), reverse=True)

    log.info(
        "[radar] scan complete — %d tickers found (screener excluded: %d)",
        len(filtered[:max_results]), len(screener_set),
    )
    return filtered[:max_results]


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if "--radar" in sys.argv:
        print("\n=== Social Radar Test ===\n")
        exclude = [s for s in sys.argv[1:] if s != "--radar"]
        results = scan_social_radar(screener_syms=exclude, min_mentions=3)
        if not results:
            print("  No tickers found above threshold.")
        else:
            for r in results[:10]:
                subs = " ".join(f"{k[:3].upper()}:{v}" for k, v in r["sub_breakdown"].items())
                print(f"  {r['symbol']:<6}  {r['mention_count']:>3} mentions  WSB:{r['wsb_mentions']}  {subs}")
                if r["top_post"]:
                    print(f"         {r['top_post'][:70]}")
        print()
        sys.exit(0)

    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["NVDA", "TSLA", "GME"]
    print(f"\n=== Social Sentiment Test — {tickers} ===\n")

    for ticker in tickers:
        result = get_social_sentiment(ticker)
        print(f"  {result['sentiment_emoji']}  {ticker:<6}  {result['sentiment_label']:<14}"
              f"  score={result['sentiment_score']:.2f}"
              f"  Reddit:{result['reddit_mentions']}"
              f"  WSB:{result['wsb_mentions']}"
              f"  ST:{result['stocktwits_messages']}"
              f"  ST_bull:{result['stocktwits_bullish_pct']:.0f}%")
        if result["top_posts"]:
            p = result["top_posts"][0]
            print(f"     Top: [{p['source']}] {p['text'][:80]}")
        print()
