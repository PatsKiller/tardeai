#!/usr/bin/env python3
"""Hermes YouTube discovery — discover & ingest YouTube transcript content for related targets.

Hermes already LOOKS UP existing transcripts via RAG (content_embeddings has ~1,150 youtube
rows). This adds the DISCOVERY half: for symbols Hermes is researching, use SearXNG's youtube
engine to find relevant videos, fetch their transcripts (cookie-gated, via youtube_transcript_ingest),
and stage a finding into hermes_research_intelligence so the content flows into curation → RAG.

Cookie-gated: transcript fetch needs authenticated config/youtube_cookies.txt (see Pipeline tab
stoplight). Kept small per run to avoid YouTube 429 rate-limiting.

    python3 scripts/hermes_youtube_discovery.py                    # dry-run (discover only)
    python3 scripts/hermes_youtube_discovery.py --apply --limit 5
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://127.0.0.1:18888/search")
KILL = PROJECT_ROOT / "hermes_sidecar" / ".hermes" / "DISABLED"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [hermes-yt] %(message)s")
log = logging.getLogger()


def searx_youtube(query, n=3):
    params = urllib.parse.urlencode({"q": query, "format": "json", "engines": "youtube"})
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}?{params}", headers={"User-Agent": "hermes-yt"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        urls = []
        for x in data.get("results", []):
            u = x.get("url", "")
            if "youtube.com/watch" in u or "youtu.be/" in u:
                urls.append(u)
            if len(urls) >= n:
                break
        return urls
    except Exception as e:
        log.warning("searx error for %r: %s", query, e)
        return []


def get_targets(limit):
    from db_adapter import _execute
    rows = _execute(
        "SELECT DISTINCT symbol FROM watchlist_items WHERE status='active' AND symbol IS NOT NULL ORDER BY symbol LIMIT %s",
        (limit,), fetch="all")
    return [r["symbol"] for r in (rows or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="fetch transcripts + stage findings (default: dry-run)")
    ap.add_argument("--limit", type=int, default=5, help="number of target symbols per run")
    ap.add_argument("--videos", type=int, default=2, help="videos per target")
    args = ap.parse_args()

    if KILL.exists():
        log.info("kill switch present — aborting")
        return

    from db_adapter import get_connection
    syms = get_targets(args.limit)
    log.info("Targets (%d): %s", len(syms), ", ".join(syms))

    ingest_video = None
    conn = cur = None
    if args.apply:
        from youtube_transcript_ingest import ingest_video as _iv
        ingest_video = _iv
        conn = get_connection(); cur = conn.cursor()

    staged = ingested = found_total = 0
    for sym in syms:
        urls = searx_youtube(f"{sym} stock analysis", args.videos)
        found_total += len(urls)
        got = []
        if args.apply:
            for u in urls:
                try:
                    res = ingest_video(u, added_by="hermes_youtube_discovery")
                    if res and "error" not in res:
                        got.append(u)
                        if res.get("status") not in ("already_exists",):
                            ingested += 1
                except Exception as e:
                    log.warning("  ingest failed %s: %s", u, e)
                time.sleep(1.5)  # be gentle — YouTube rate-limits
            if urls:
                summary = (f"Hermes YouTube discovery for {sym}: {len(urls)} videos found via SearXNG, "
                           f"{len(got)} transcripts available. Feeds RAG via curation.")
                cur.execute(
                    """INSERT INTO hermes_research_intelligence
                       (research_type, symbol, topic, summary, confidence_score, status, source,
                        source_urls_json, hermes_agent_name, model_used, freshness_date, created_at)
                       VALUES ('youtube_discovery', %s, %s, %s, %s, 'staged', 'hermes',
                               %s, 'hermes_youtube_discovery', 'gemma3:4b', CURRENT_DATE, NOW())""",
                    (sym, f"youtube_discovery: {sym}", summary, 0.6, json.dumps(urls)))
                conn.commit(); staged += 1
        log.info("  %s: %d videos%s", sym, len(urls), f", {len(got)} transcripts" if args.apply else "")
        time.sleep(1)

    if conn:
        conn.close()
    mode = "APPLIED" if args.apply else "DRY-RUN"
    log.info("[%s] %d targets, %d videos found, %d staged, %d new transcripts", mode, len(syms), found_total, staged, ingested)
    if not args.apply:
        log.info("Dry-run — re-run with --apply to fetch transcripts + stage.")


if __name__ == "__main__":
    main()
