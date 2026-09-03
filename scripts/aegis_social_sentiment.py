"""
aegis_social_sentiment.py — Aegis Tier 1C: Social sentiment ingestion for tracked symbols.

Sources:
- Reddit public JSON API (r/wallstreetbets, r/stocks, r/investing, r/options)
- Brave Search API (finance-scoped social/community discovery)

All outputs marked model='aegis', source='aegis:social'.
Sentiment is SIGNAL only — never dominates recommendations alone.

Entry point: main()
"""

from __future__ import annotations
import json
import os
import re
import sys
import time
import requests
from datetime import date, datetime
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

AGENT = "aegis"
RUN_ID = f"aegis-social-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

# Reddit subreddits to scan
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options"]
# Bullish/bearish keyword lists
BULLISH_WORDS = {
    "bull",
    "bullish",
    "moon",
    "buy",
    "calls",
    "long",
    "breakout",
    "undervalued",
    "rocket",
    "squeeze",
    "upside",
    "load",
}
BEARISH_WORDS = {"bear", "bearish", "puts", "short", "crash", "overvalued", "dump", "sell", "downside", "tank", "fade"}


def _db_write(sql, params=None):
    try:
        from db_adapter import _get_conn
        import psycopg2.extras

        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"  [aegis-social] DB write error: {e}")
        return False


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB

        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


# ── Reddit public JSON API ───────────────────────────────────────────────


def fetch_reddit_mentions(symbols: list[str]) -> dict[str, dict]:
    """Scan Reddit subreddits for symbol mentions using public JSON API."""
    results: dict[str, dict] = {sym: {"mentions": [], "source": "reddit"} for sym in symbols}
    sym_set = set(s.upper() for s in symbols)
    # Build ticker pattern: match $TICKER or standalone TICKER (3+ chars)
    ticker_pattern = re.compile(r"\$([A-Z]{2,5})\b|(?<!\w)([A-Z]{3,5})(?!\w)")

    for sub in SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=50"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Aegis/1.0 portfolio-intelligence"})
            if resp.status_code != 200:
                print(f"  [reddit] r/{sub} returned {resp.status_code}")
                continue
            data = resp.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                pd = post.get("data", {})
                title = pd.get("title", "")
                selftext = (pd.get("selftext") or "")[:500]
                text = f"{title} {selftext}"
                score = pd.get("score", 0)
                ups = pd.get("ups", 0)

                # Find ticker mentions
                matches = ticker_pattern.findall(text)
                found_tickers = set()
                for m in matches:
                    ticker = (m[0] or m[1]).upper()
                    if ticker in sym_set:
                        found_tickers.add(ticker)

                for ticker in found_tickers:
                    text_lower = text.lower()
                    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
                    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)
                    results[ticker]["mentions"].append(
                        {
                            "subreddit": sub,
                            "title": title[:100],
                            "score": score,
                            "bull_signals": bull,
                            "bear_signals": bear,
                        }
                    )

            time.sleep(1.5)  # Rate limit between subreddits
        except Exception as e:
            print(f"  [reddit] r/{sub} error: {e}")

    return results


# ── StockTwits symbol stream (working replacement for Reddit 403) ─────────


def fetch_stocktwits_mentions(symbols: list[str], max_symbols: int = 50) -> dict[str, dict]:
    """Scan StockTwits symbol streams for per-symbol sentiment (no key, real-time).

    The Reddit public JSON API started returning 403 (2026-08-17) which left the desk
    with no social signal. StockTwits is the working fallback — its per-message
    sentiment entities give bull/bear directly, matching the shape Reddit used to.
    """
    results: dict[str, dict] = {sym: {"mentions": [], "source": "stocktwits"} for sym in symbols}
    for sym in symbols[:max_symbols]:
        try:
            url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            data = resp.json()
            messages = data.get("messages", [])
            for m in messages:
                body = (m.get("body") or "").strip()[:200]
                if not body:
                    continue
                senti = ((m.get("entities") or {}).get("sentiment") or {}).get("basic") or ""
                results[sym]["mentions"].append(
                    {
                        "channel": "stocktwits",
                        "title": body[:100],
                        "score": int((m.get("likes") or {}).get("total", 0) or 0),
                        "bull_signals": 1 if senti == "Bullish" else 0,
                        "bear_signals": 1 if senti == "Bearish" else 0,
                    }
                )
            time.sleep(0.3)  # politeness — per-symbol
        except Exception as e:
            print(f"  [stocktwits] {sym} error: {e}")

    return results


# ── Brave Search API ─────────────────────────────────────────────────────


def fetch_brave_social(symbols: list[str], max_queries: int = 10) -> dict[str, dict]:
    """Optional Brave discovery for social mentions.

    Default OFF (Wave 3 2026-09-01). Reddit + StockTwits are the durable social
    feeds; a search API is not a social feed and was exhausting the Brave daily
    budget (10×2×21 ≈ 420/mo) under F1/F2 bounds that already zeroed news/
    catalyst. Set AEGIS_BRAVE_ENABLED=1 to re-enable. Consumer named:
    aegis overnight / social store — do not delete this function.
    """
    import os

    if os.getenv("AEGIS_BRAVE_ENABLED", "0").lower() not in ("1", "true", "yes"):
        print("  [brave] retired default — reddit+stocktwits only; set AEGIS_BRAVE_ENABLED=1 to re-enable")
        return {}

    results: dict[str, dict] = {}
    try:
        from scripts.lib import brave_research_router as _router
    except ImportError:
        try:
            from lib import brave_research_router as _router  # type: ignore
        except ImportError:
            print("  [brave] research router unavailable — DENY (never fail open)")
            return {}

    for sym in symbols[:max_queries]:
        # Routed, not check-then-call. The previous shape called `check()`
        # (read-only) and only `record()`ed *after* the request, so two
        # concurrent runs could both observe the last unit as available and both
        # spend it. The router consumes atomically via `try_consume`, so the
        # decision and the count are one operation.
        outcome = _router.search(
            f"{sym} stock sentiment reddit OR stocktwits",
            purpose=_router.Purpose.SOCIAL_LEAD_DISCOVERY,
            priority=_router.Priority.WATCHLIST,
            caller="aegis_social_sentiment",
            count=5,
            freshness="pd",
        )
        if outcome.status in (
            _router.Status.DENIED_BUDGET,
            _router.Status.DENIED_RESERVE,
            _router.Status.DENIED_PURPOSE_QUOTA,
            _router.Status.BUDGET_UNAVAILABLE,
        ):
            print(f"  [brave] {outcome.status.value} — stopping at {sym}: {outcome.degradation_note()}")
            break
        if outcome.degraded:
            # Carry the reason rather than dropping the symbol silently: an
            # unavailable provider must not read downstream as "no chatter".
            results[sym] = {
                "mentions": [],
                "source": "brave",
                "available": False,
                "degraded_reason": outcome.status.value,
                "degraded_note": outcome.degradation_note(),
            }
            continue

        mentions = [
            {
                "title": r.title[:100],
                "url": r.url,
                "description": r.description[:150],
                # A search hit pointing AT a Reddit/StockTwits page is a pointer to
                # a discussion, not the discussion. It is never native sentiment.
                "source": "brave_discovery",
                "attribution": r.attribution,
            }
            for r in outcome.results[:3]
        ]
        if mentions:
            results[sym] = {
                "mentions": mentions,
                "source": "brave",
                "available": True,
                "attribution": _router.ATTRIBUTION,
            }
        else:
            results[sym] = {
                "mentions": [],
                "source": "brave",
                "available": True,
                "degraded_reason": "EMPTY",
                "degraded_note": outcome.degradation_note(),
            }

    return results


# ── Sentiment normalization ──────────────────────────────────────────────


def normalize_sentiment(symbol: str, reddit_data: dict, brave_data: dict, stocktwits_data: dict | None = None) -> dict:
    """Normalize raw social data into a structured sentiment record."""
    r_mentions = reddit_data.get("mentions", [])
    b_mentions = brave_data.get("mentions", []) if brave_data else []
    st_mentions = (stocktwits_data or {}).get("mentions", []) if stocktwits_data else []
    social_mentions = r_mentions + st_mentions

    mention_count = len(social_mentions) + len(b_mentions)
    if mention_count == 0:
        return None

    # Count polarity from Reddit + StockTwits (both carry bull/bear signals)
    bullish = sum(m.get("bull_signals", 0) for m in social_mentions)
    bearish = sum(m.get("bear_signals", 0) for m in social_mentions)
    total_signals = bullish + bearish
    if total_signals > 0:
        sentiment_score = round((bullish - bearish) / total_signals, 2)
    else:
        sentiment_score = 0.0

    bullish_count = sum(1 for m in social_mentions if m.get("bull_signals", 0) > m.get("bear_signals", 0))
    bearish_count = sum(1 for m in social_mentions if m.get("bear_signals", 0) > m.get("bull_signals", 0))
    neutral_count = mention_count - bullish_count - bearish_count

    # Theme extraction from titles
    all_titles = [m.get("title", "") for m in social_mentions + b_mentions]
    words = Counter()
    for t in all_titles:
        for w in re.findall(r"\b[a-z]{4,}\b", t.lower()):
            if w not in ("this", "that", "with", "from", "what", "have", "been", "will", "your", "just", "about"):
                words[w] += 1
    themes = [w for w, c in words.most_common(5) if c >= 2]

    # Top posts summary
    top = sorted(social_mentions, key=lambda m: m.get("score", 0), reverse=True)[:3]
    summary_parts = []
    for m in top:
        label = m.get("channel") or f"r/{m.get('subreddit', '?')}"
        summary_parts.append(f"{label}: {m.get('title', '')[:60]} (score:{m.get('score', 0)})")
    for m in b_mentions[:2]:
        summary_parts.append(f"[brave] {m.get('title', '')[:60]}")
    summary = " | ".join(summary_parts)[:500]

    # Spike detection: >5 mentions for a single symbol is unusual
    unusual_spike = mention_count >= 5

    # Confidence: social is always lower trust
    confidence = min(0.30 + (mention_count * 0.03), 0.60)

    return {
        "mention_count": mention_count,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "sentiment_score": sentiment_score,
        "volume_zscore": None,  # Would need historical baseline
        "unusual_spike": unusual_spike,
        "theme_tags": themes,
        "top_posts_summary": summary,
        "confidence": round(confidence, 2),
    }


def persist_sentiment(symbol: str, sentiment: dict, source_family: str):
    """Write sentiment record to social_sentiment_history."""
    return _db_write(
        """INSERT INTO social_sentiment_history
           (run_id, symbol, source_family, source_name, mention_count,
            bullish_count, bearish_count, neutral_count, sentiment_score,
            volume_zscore, unusual_spike, theme_tags, top_posts_summary,
            confidence, provenance)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (run_id, symbol, source_family) DO UPDATE SET
            mention_count=EXCLUDED.mention_count, sentiment_score=EXCLUDED.sentiment_score,
            top_posts_summary=EXCLUDED.top_posts_summary, confidence=EXCLUDED.confidence,
            observed_at=NOW()""",
        (
            RUN_ID,
            symbol,
            source_family,
            "reddit+stocktwits+brave",
            sentiment["mention_count"],
            sentiment["bullish_count"],
            sentiment["bearish_count"],
            sentiment["neutral_count"],
            sentiment["sentiment_score"],
            sentiment["volume_zscore"],
            sentiment["unusual_spike"],
            sentiment["theme_tags"],
            sentiment["top_posts_summary"],
            sentiment["confidence"],
            json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:social"}, default=str),
        ),
    )


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    print(f"[aegis-social] Sentiment ingestion starting — {RUN_ID}")

    # Resolve universe (reuse from nightly ingestion)
    from aegis_nightly_ingestion import resolve_universe

    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    print(f"  Universe: {len(symbols)} symbols")

    # D1: Reddit scan (best-effort — public JSON API is 403 since 2026-08-17)
    reddit_data = fetch_reddit_mentions(symbols)
    reddit_hits = sum(1 for v in reddit_data.values() if v.get("mentions"))
    print(f"  Reddit: {reddit_hits} symbols with mentions")

    # D1: StockTwits scan (working primary social source)
    stocktwits_data = fetch_stocktwits_mentions(symbols, max_symbols=50)
    stocktwits_hits = sum(1 for v in stocktwits_data.values() if v.get("mentions"))
    print(f"  StockTwits: {stocktwits_hits} symbols with mentions")

    # D1: Brave discovery (top 10 by priority: recovery > watchlist > holdings)
    priority_syms = sorted(
        symbols,
        key=lambda s: (
            0
            if any("recovery" in u["reasons"] for u in universe if u["symbol"] == s)
            else 1
            if any("watchlist" in u["reasons"] for u in universe if u["symbol"] == s)
            else 2
        ),
    )
    brave_data = fetch_brave_social(priority_syms, max_queries=10)
    print(f"  Brave: {len(brave_data)} symbols discovered")

    # D3: Normalize + persist
    written = 0
    for sym in symbols:
        sentiment = normalize_sentiment(
            sym,
            reddit_data.get(sym, {}),
            brave_data.get(sym, {}),
            stocktwits_data.get(sym, {}),
        )
        if sentiment:
            if persist_sentiment(sym, sentiment, "social"):
                written += 1

    print(f"  Persisted: {written} sentiment records")
    print(f"[aegis-social] Complete — {datetime.now().isoformat()}")
    return {
        "universe": len(symbols),
        "reddit_hits": reddit_hits,
        "stocktwits_hits": stocktwits_hits,
        "brave_hits": len(brave_data),
        "written": written,
        "run_id": RUN_ID,
    }


if __name__ == "__main__":
    main()
