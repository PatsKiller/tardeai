#!/usr/bin/env python3
"""hermes_social_sentiment.py — Hermes social/forum sentiment lane.

Hermes contributes to social_sentiment_history (the same table aegis_social_sentiment
writes) via SearXNG forum/social searches. This gives the desk a REDUNDANT social source
so a Reddit 403 / StockTwits outage no longer starves social sentiment (auto-fix).

Sources:
- SearXNG site:reddit.com <sym> stock   (forum threads — confirmed working)
- SearXNG <sym> stock sentiment reddit  (general fallback)

Writes: social_sentiment_history (source_family='hermes', source_name='hermes_searxng').
Liveness: report_source('hermes_social', ...) so the health agent can track it and the
auto-remediation ladder can re-run it on a stale finding.

Usage:
    python3 scripts/hermes_social_sentiment.py --dry-run
    python3 scripts/hermes_social_sentiment.py --apply --max-symbols 25
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")

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

RUN_ID = f"hermes-social-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

BULLISH_WORDS = {"bull", "bullish", "moon", "buy", "calls", "long", "breakout",
                 "undervalued", "rocket", "squeeze", "upside", "load"}
BEARISH_WORDS = {"bear", "bearish", "puts", "short", "crash", "overvalued",
                 "dump", "sell", "downside", "tank", "fade"}


def _db_write(sql, params=None) -> bool:
    try:
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"  [hermes-social] DB write error: {e}")
        return False


def resolve_universe() -> list[str]:
    """Tracked symbols. Reuse aegis universe; fall back to a small watchlist-safe set."""
    try:
        from aegis_nightly_ingestion import resolve_universe as _ru
        return [u["symbol"] for u in _ru()]
    except Exception as e:
        print(f"  [hermes-social] universe fallback ({e})")
    # Fallback: no DB — return an empty list so the caller can decide.
    return []


def _searxng(query: str, categories: str = "general") -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "format": "json", "categories": categories})
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}?{params}", method="GET",
                                     headers={"User-Agent": "HermesSocial/1.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
        return data.get("results", [])
    except Exception as e:
        print(f"  [hermes-social] searxng error: {e}")
        return []


FORUM_DOMAIN_HINTS = ("reddit.com", "stocktwits.com", "wallstreetbets", "seekingalpha.com")


def search_forum(symbol: str, limit: int = 6) -> list[dict]:
    """Search forums for a symbol, prioritizing actual forum/community domains.

    SearXNG's general engines honor `site:` inconsistently, so we collect across a few
    targeted queries and rank forum-domain results (Reddit/StockTwits/etc.) ahead of the
    generic quote pages the engines otherwise surface first.
    """
    queries = [
        f"site:reddit.com {symbol} stock",
        f"site:stocktwits.com {symbol}",
        f"{symbol} stock sentiment reddit",
    ]
    seen_urls = set()
    forum = []
    general = []
    for q in queries:
        for r in _searxng(q):
            url = r.get("url", "")
            title = (r.get("title") or "").strip()
            if not title or url in seen_urls:
                continue
            seen_urls.add(url)
            item = {
                "title": title[:140],
                "url": url,
                "snippet": (r.get("content") or "")[:200],
                "engine": r.get("engine", ""),
            }
            if any(h in url for h in FORUM_DOMAIN_HINTS):
                forum.append(item)
            else:
                general.append(item)
        time.sleep(0.4)
    return (forum + general)[:limit]


def classify(text: str) -> tuple[int, int]:
    """Return (bull, bear) keyword counts for a text."""
    tl = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in tl)
    bear = sum(1 for w in BEARISH_WORDS if w in tl)
    return bull, bear


def normalize(symbol: str, mentions: list[dict]) -> dict | None:
    if not mentions:
        return None
    mention_count = len(mentions)
    bullish = 0
    bearish = 0
    bull_posts = 0
    bear_posts = 0
    words = Counter()
    titles = []
    for m in mentions:
        title = m.get("title", "")
        text = f"{title} {m.get('snippet', '')}"
        b, s = classify(text)
        bullish += b
        bearish += s
        if b > s:
            bull_posts += 1
        elif s > b:
            bear_posts += 1
        titles.append(title[:60])
        for w in re.findall(r"\b[a-z]{4,}\b", title.lower()):
            if w not in ("this", "that", "with", "from", "what", "have", "been", "will",
                         "your", "just", "about", "stock", "reddit", "tesla"):
                words[w] += 1

    total = bullish + bearish
    sentiment_score = round((bullish - bearish) / total, 2) if total else 0.0
    themes = [w for w, c in words.most_common(5) if c >= 2]
    summary = " | ".join(titles[:3])[:500]

    return {
        "mention_count": mention_count,
        "bullish_count": bull_posts,
        "bearish_count": bear_posts,
        "sentiment_score": sentiment_score,
        "theme_tags": themes,
        "top_posts_summary": summary,
        "confidence": min(0.30 + mention_count * 0.03, 0.60),
    }


def persist(symbol: str, sentiment: dict) -> bool:
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
        (RUN_ID, symbol, "hermes", "hermes_searxng", sentiment["mention_count"],
         sentiment["bullish_count"], sentiment["bearish_count"],
         sentiment["mention_count"] - sentiment["bullish_count"] - sentiment["bearish_count"],
         sentiment["sentiment_score"], None, sentiment["mention_count"] >= 5,
         sentiment["theme_tags"], sentiment["top_posts_summary"],
         sentiment["confidence"],
         json.dumps({"run_id": RUN_ID, "agent": "hermes", "source": "hermes:searxng_social"}, default=str))
    )


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=25)
    args = ap.parse_args()

    print(f"[hermes-social] starting — {RUN_ID}")
    symbols = resolve_universe()
    if not symbols:
        print("  [hermes-social] empty universe — nothing to do")
        return {"universe": 0, "written": 0, "dry_run": not args.apply}

    symbols = symbols[:args.max_symbols]
    print(f"  Universe: {len(symbols)} symbols (capped at {args.max_symbols})")

    written = 0
    hits = 0
    for sym in symbols:
        mentions = search_forum(sym)
        if mentions:
            hits += 1
            sentiment = normalize(sym, mentions)
            if sentiment:
                if args.apply:
                    if persist(sym, sentiment):
                        written += 1
                else:
                    written += 1
        time.sleep(0.2)

    # Only report source liveness on an APPLY run — a dry-run (no --apply) is a preview and
    # must not mark the source healthy when nothing was actually persisted.
    if args.apply:
        try:
            from lib.data_source_report import report_source
            report_source("hermes_social", written > 0, rows=written,
                          error=None if written else "0 symbols produced sentiment")
        except Exception:
            pass

    print(f"  Forum hits: {hits} symbols | Persisted: {written} sentiment records")
    print(f"[hermes-social] complete (apply={args.apply})")
    return {"universe": len(symbols), "hits": hits, "written": written, "dry_run": not args.apply}


if __name__ == "__main__":
    main()
