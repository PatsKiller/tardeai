#!/usr/bin/env python3
"""Hermes Source Curation — Tracks A (self-learning source quality) + B (new-site discovery)
+ registers every source TYPE (web/social/youtube/sec/rss/ai-apis/seeking-alpha) into research_sources.

A: score each web domain by yield = (promoted+embedded)/total of the research it produced.
B: domains seen for the first time → registered as candidates (active=false) for vetting.
Connectors that need keys (AI APIs, Seeking Alpha) are registered dormant with status in notes.

Read-only to research; only writes the research_sources registry. Idempotent (UPSERT). Cron weekly.
"""
import os
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [source-curation] %(message)s")
log = logging.getLogger("source_curation")
DB = dict(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
          dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
          password=os.getenv("DB_PASSWORD", ""))

# Connector source types and how they're wired today (status drives the UI badge).
# active=True means it has a live ingestion path; needs_key/dormant are honest "not running" states.
CONNECTOR_TYPES = [
    {"type": "social", "name": "Reddit / Stocktwits / X", "active": True, "specialty": "social sentiment", "note": "live via social_ingest pipeline (Social Scalp)"},
    {"type": "youtube", "name": "YouTube transcripts", "active": True, "specialty": "video transcripts", "note": "live via transcript_processor (cookie-gated)"},
    {"type": "sec", "name": "SEC filings (Form 4)", "active": True, "specialty": "insider filings", "note": "live via sec_form4 ingest"},
    {"type": "rss", "name": "RSS feeds", "active": False, "specialty": "news feeds", "note": "connector ready (hermes_rss_ingest.py) — no feeds configured in config/hermes_rss_feeds.txt"},
    {"type": "ai_openai", "name": "OpenAI (ChatGPT)", "active": False, "specialty": "AI research", "note": "DORMANT — needs OPENAI_API_KEY"},
    {"type": "ai_anthropic", "name": "Anthropic (Claude)", "active": False, "specialty": "AI research", "note": "DORMANT — needs ANTHROPIC_API_KEY"},
    {"type": "ai_xai", "name": "xAI (Grok)", "active": False, "specialty": "AI research", "note": "DORMANT — needs XAI_API_KEY"},
    {"type": "seeking_alpha", "name": "Seeking Alpha", "active": False, "specialty": "equity research", "note": "DORMANT — needs SEEKING_ALPHA_API_KEY (via official API, not cookies)"},
]


def domains_from(srcjson):
    out = []
    try:
        urls = srcjson
        if isinstance(urls, str):
            urls = json.loads(urls)
        if isinstance(urls, dict):
            urls = list(urls.values())
        for u in (urls or []):
            if isinstance(u, str) and u.startswith("http"):
                d = urlparse(u).netloc.replace("www.", "")
                if d:
                    out.append(d)
    except Exception:
        pass
    return out


def upsert_source(cur, stype, name, cred, active, specialty, note, url=None):
    spec = [specialty] if isinstance(specialty, str) else (specialty or [])  # specialty is text[]
    cur.execute("SELECT id FROM research_sources WHERE source_type=%s AND source_name=%s", (stype, name))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE research_sources SET credibility_score=%s, active=%s, specialty=%s, notes=%s WHERE id=%s",
                    (cred, active, spec, note, row[0]))
        return False
    cur.execute("""INSERT INTO research_sources (source_type, source_name, source_url, credibility_score, specialty, active, notes, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())""", (stype, name, url, cred, spec, active, note))
    return True


def main():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    cur = conn.cursor()

    # ── A: web-domain yield scoring (+ B: new-domain discovery) ──
    cur.execute("""SELECT source_urls_json, status,
                          EXISTS(SELECT 1 FROM hermes_embedding_queue q WHERE q.source_research_id = r.id AND q.embedding_status='completed') AS embedded
                   FROM hermes_research_intelligence r
                   WHERE source_urls_json IS NOT NULL AND source_urls_json::text NOT IN ('null','[]','{}')""")
    agg = {}
    for srcjson, status, embedded in cur.fetchall():
        for d in set(domains_from(srcjson)):
            a = agg.setdefault(d, {"total": 0, "promoted": 0, "embedded": 0})
            a["total"] += 1
            if status == "promoted":
                a["promoted"] += 1
            if embedded:
                a["embedded"] += 1
    new_count = 0
    for d, a in agg.items():
        yield_pct = round(100 * (a["promoted"] + a["embedded"]) / max(a["total"], 1))
        active = a["total"] >= 2 and yield_pct >= 30           # preferred source threshold
        note = f"yield {yield_pct}% ({a['promoted']}p/{a['embedded']}e of {a['total']})" + ("" if active else " — candidate/low-yield")
        if upsert_source(cur, "web", d, yield_pct, active, "web search", note, url=f"https://{d}"):
            new_count += 1
    log.info("web domains scored: %d (%d newly discovered candidates)", len(agg), new_count)

    # ── Register connector source types (honest status: active / dormant / needs-key) ──
    for c in CONNECTOR_TYPES:
        # auto-activate AI/SeekingAlpha if a key is actually present
        active = c["active"]
        note = c["note"]
        key_env = {"ai_openai": "OPENAI_API_KEY", "ai_anthropic": "ANTHROPIC_API_KEY", "ai_xai": "XAI_API_KEY", "seeking_alpha": "SEEKING_ALPHA_API_KEY"}.get(c["type"])
        if key_env and os.environ.get(key_env):
            active = True
            note = f"ACTIVE — {key_env} present"
        upsert_source(cur, c["type"], c["name"], 50 if active else 0, active, c["specialty"], note)
    log.info("connector types registered: %d", len(CONNECTOR_TYPES))

    cur.execute("SELECT COUNT(*) FILTER (WHERE active), COUNT(*) FROM research_sources")
    a, t = cur.fetchone()
    log.info("research_sources: %d active / %d total", a, t)
    conn.close()


if __name__ == "__main__":
    main()
