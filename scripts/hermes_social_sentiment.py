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

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply``; no ``--apply`` is still a
dry run. It resolves the universe exactly like a real run (the tracked resolver's db_adapter session is
made READ ONLY at the server first), then reports the SearXNG queries it WOULD send instead of sending
them (SearXNG fans out to rate-limited public engines), and returns BEFORE ``persist`` / ``report_source``
are reachable. It writes no receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1 ``<state_root>/data/runtime/hermes-social-sentiment_last.json``
(``ok_at`` only on success). Exit codes: 0 = ran (an empty universe or zero forum hits is a finding,
still 0); 1 = the run failed (universe resolution raised; EVERY SearXNG request errored; or forum hits
existed but EVERY persist failed); 2 = usage error. Single failed searches/persists are soft failures.
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
from datetime import datetime, timezone
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
LANE_ID = "hermes-social-sentiment"
#: SearXNG request outcomes in this process (read by main() for the exit code)
_FETCH_STATS = {"ok": 0, "error": 0}
#: set by resolve_universe() when the tracked-universe resolver raised
_UNIVERSE_ERROR: list[str] = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.hermes_social_sentiment
        from scripts.lib import lane_last_receipt as lr
    return lr

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


UNIVERSE = "tracked"   # stamped in provenance so the scalp scanner can tell scalp-universe rows apart


def resolve_scalp_universe(limit: int = 25) -> list[str]:
    """Today's social-scalp candidates (awaiting-catalyst scouts first, then GO/WAIT by score)."""
    try:
        from hermes_momentum_catalyst_researcher import get_scalp_candidates
        return list(get_scalp_candidates(max_tickers=limit))
    except Exception as e:  # noqa: BLE001
        print(f"  [hermes-social] scalp universe unavailable ({e})")
        return []


def resolve_universe() -> list[str]:
    """Tracked symbols. Reuse aegis universe; fall back to a small watchlist-safe set."""
    _UNIVERSE_ERROR.clear()
    try:
        from aegis_nightly_ingestion import resolve_universe as _ru
        return [u["symbol"] for u in _ru()]
    except Exception as e:
        _UNIVERSE_ERROR.append(type(e).__name__)
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
        _FETCH_STATS["ok"] += 1
        return data.get("results", [])
    except Exception as e:
        _FETCH_STATS["error"] += 1
        print(f"  [hermes-social] searxng error: {e}")
        return []


FORUM_DOMAIN_HINTS = ("reddit.com", "stocktwits.com", "wallstreetbets", "seekingalpha.com")


def forum_queries(symbol: str) -> list[str]:
    return [
        f"site:reddit.com {symbol} stock",
        f"site:stocktwits.com {symbol}",
        f"{symbol} stock sentiment reddit",
    ]


def search_forum(symbol: str, limit: int = 6) -> list[dict]:
    """Search forums for a symbol, prioritizing actual forum/community domains.

    SearXNG's general engines honor `site:` inconsistently, so we collect across a few
    targeted queries and rank forum-domain results (Reddit/StockTwits/etc.) ahead of the
    generic quote pages the engines otherwise surface first.
    """
    queries = forum_queries(symbol)
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
         json.dumps({"run_id": RUN_ID, "agent": "hermes", "source": "hermes:searxng_social",
                     "universe": UNIVERSE}, default=str))
    )


def _resolve(args) -> list[str]:
    global UNIVERSE
    UNIVERSE = args.universe
    symbols = resolve_scalp_universe(args.max_symbols) if args.universe == "scalp" else resolve_universe()
    return symbols[:args.max_symbols]


def _dry_run(args) -> int:
    """Universe read + would-fetch report. ``search_forum``, ``persist`` and ``report_source`` are not
    reachable from here."""
    lr = _receipt_lib()
    if args.universe == "tracked":
        try:
            from db_adapter import _get_conn
            lr.enforce_readonly(_get_conn())  # the tracked resolver's _db_query shares this session
        except Exception as e:
            print(f"  [hermes-social] DRY-RUN db unavailable: {type(e).__name__}: {e}")
            return 1
    symbols = _resolve(args)
    if _UNIVERSE_ERROR:
        return 1
    queries = [q for sym in symbols for q in forum_queries(sym)]
    print(f"  Universe: {len(symbols)} symbols (capped at {args.max_symbols})")
    print(f"  Would send {len(queries)} SearXNG queries ({SEARXNG_URL}); not sent in a dry run")
    lr.dry_run_report(
        LANE_ID,
        {"universe_kind": args.universe, "universe": len(symbols), "symbols": symbols[:25],
         "would_fetch_searxng_queries": len(queries), "sample_query": queries[0] if queries else None},
        would_write=["social_sentiment_history (source_family=hermes) x symbols with forum hits",
                     "data_source_health (hermes_social)"],
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the universe + report the would-send queries; no SearXNG, no write; wins over --apply")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=25)
    ap.add_argument("--universe", choices=["tracked", "scalp"], default="tracked",
                    help="tracked = portfolio/watch universe (default); scalp = today's social-scalp "
                         "candidates, so the scalp scanner sees Hermes forum mentions pre-market")
    args = ap.parse_args(argv)

    print(f"[hermes-social] starting — {RUN_ID} (universe={args.universe})")
    if args.dry_run or not args.apply:
        return _dry_run(args)

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    _FETCH_STATS.update(ok=0, error=0)
    symbols: list[str] = []
    written = hits = 0
    try:
        symbols = _resolve(args)
        if _UNIVERSE_ERROR:
            raise RuntimeError(f"universe resolution failed ({_UNIVERSE_ERROR[0]})")
        if not symbols:
            print("  [hermes-social] empty universe — nothing to do")
        else:
            print(f"  Universe: {len(symbols)} symbols (capped at {args.max_symbols})")
            for sym in symbols:
                mentions = search_forum(sym)
                if mentions:
                    hits += 1
                    sentiment = normalize(sym, mentions)
                    if sentiment and persist(sym, sentiment):
                        written += 1
                time.sleep(0.2)

            # Only report source liveness on an APPLY run — a dry-run is a preview and
            # must not mark the source healthy when nothing was actually persisted.
            try:
                from lib.data_source_report import report_source
                report_source("hermes_social", written > 0, rows=written,
                              error=None if written else "0 symbols produced sentiment")
            except Exception:
                pass
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="hermes_social_sentiment.py", error=f"{type(exc).__name__}: {exc}")
        raise

    print(f"  Forum hits: {hits} symbols | Persisted: {written} sentiment records")
    print("[hermes-social] complete (apply=True)")
    all_fetch_failed = bool(symbols) and _FETCH_STATS["ok"] == 0 and _FETCH_STATS["error"] > 0
    all_persist_failed = hits > 0 and written == 0
    rc = 1 if (all_fetch_failed or all_persist_failed) else 0
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="hermes_social_sentiment.py",
                          summary={"universe_kind": args.universe, "universe": len(symbols), "hits": hits,
                                   "written": written, "searxng_ok": _FETCH_STATS["ok"],
                                   "searxng_errors": _FETCH_STATS["error"]})
    return rc


if __name__ == "__main__":
    sys.exit(main())
