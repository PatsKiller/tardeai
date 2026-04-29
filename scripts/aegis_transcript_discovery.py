"""
aegis_transcript_discovery.py — Aegis Tier 1D: Transcript intelligence + bounded web discovery.

Sources:
- YouTube transcript API (earnings calls, finance commentary for tracked symbols)
- Brave Search API (bounded article/transcript discovery)
- Existing article_index from pipeline (internal enrichment)

All outputs marked model='aegis', source='aegis:transcript' or 'aegis:discovery'.
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
RUN_ID = f"aegis-transcript-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
BRAVE_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")

# Portfolio themes to scan beyond individual symbols
PORTFOLIO_THEMES = [
    {"theme": "covered-calls-income", "query": "covered call strategy income ETF 2026"},
    {"theme": "defense-sector", "query": "defense sector stocks earnings outlook"},
    {"theme": "dividend-income", "query": "dividend income portfolio strategy SCHD"},
]


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
        print(f"  [aegis-td] DB write error: {e}")
        return False


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


# ── D1: YouTube transcript ingestion ─────────────────────────────────────

def fetch_youtube_transcripts(symbols: list[str], max_per_symbol: int = 1) -> list[dict]:
    """Search YouTube for earnings/analysis videos and extract transcript summaries."""
    records = []
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("  [youtube] youtube_transcript_api not available — using Brave fallback")
        return records

    # Use Brave to find relevant YouTube videos for top symbols
    if not BRAVE_KEY:
        print("  [youtube] No Brave key for YouTube discovery — skipping")
        return records

    for sym in symbols[:12]:  # Budget: 12 symbols
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            params = {"q": f"{sym} stock analysis earnings 2026 site:youtube.com", "count": 3, "freshness": "pw"}
            resp = requests.get(url, params=params, timeout=10,
                               headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"})
            if resp.status_code != 200:
                continue
            results = resp.json().get("web", {}).get("results", [])

            for r in results[:max_per_symbol]:
                video_url = r.get("url", "")
                video_id = None
                m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
                if m:
                    video_id = m.group(1)

                title = r.get("title", "")[:120]
                description = (r.get("description") or "")[:200]

                # Try to get transcript
                transcript_text = ""
                if video_id:
                    try:
                        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                        # Take first ~2000 chars for summary
                        full = " ".join(t["text"] for t in transcript)
                        transcript_text = full[:2000]
                    except Exception:
                        pass  # Many videos don't have transcripts

                # Determine stance from title/description
                text_lower = (title + " " + description + " " + transcript_text[:500]).lower()
                bullish = sum(1 for w in ("bull", "buy", "upside", "breakout", "growth") if w in text_lower)
                bearish = sum(1 for w in ("bear", "sell", "downside", "crash", "risk") if w in text_lower)
                stance = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

                # Extract themes
                themes = []
                for t_word in ("earnings", "dividend", "covered call", "options", "growth", "value", "defense", "AI", "tech"):
                    if t_word.lower() in text_lower:
                        themes.append(t_word)

                summary = transcript_text[:300] if transcript_text else description
                records.append({
                    "symbol": sym,
                    "source_family": "youtube",
                    "source_name": "youtube_transcript",
                    "channel": video_url[:80],
                    "title": title,
                    "summary": summary,
                    "stance": stance,
                    "notable_themes": themes[:5],
                    "confidence": 0.45 if transcript_text else 0.30,
                })

            time.sleep(0.5)
        except Exception as e:
            print(f"  [youtube] {sym} error: {e}")

    return records


# ── D2: Brave bounded discovery ──────────────────────────────────────────

def fetch_brave_discovery(symbols: list[str], themes: list[dict]) -> list[dict]:
    """Bounded Brave discovery for articles, transcripts, commentary."""
    if not BRAVE_KEY:
        print("  [brave-disc] No Brave key — skipping")
        return []

    discovery_records = []

    # Symbol-level discovery (top 10)
    for sym in symbols[:10]:
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            params = {"q": f"{sym} stock earnings analysis news 2026", "count": 3, "freshness": "pw"}
            resp = requests.get(url, params=params, timeout=10,
                               headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"})
            if resp.status_code != 200:
                continue
            for r in resp.json().get("web", {}).get("results", [])[:3]:
                discovery_records.append({
                    "symbol": sym, "theme": None,
                    "query": f"{sym} stock analysis",
                    "source_url": r.get("url", ""),
                    "source_title": r.get("title", "")[:120],
                    "source_description": (r.get("description") or "")[:200],
                    "source_family": _classify_source(r.get("url", "")),
                    "trust_tier": _tier_source(r.get("url", "")),
                })
            time.sleep(0.4)
        except Exception as e:
            print(f"  [brave-disc] {sym} error: {e}")

    # Theme-level discovery
    for t in themes:
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            params = {"q": t["query"], "count": 3, "freshness": "pw"}
            resp = requests.get(url, params=params, timeout=10,
                               headers={"X-Subscription-Token": BRAVE_KEY, "Accept": "application/json"})
            if resp.status_code != 200:
                continue
            for r in resp.json().get("web", {}).get("results", [])[:3]:
                discovery_records.append({
                    "symbol": None, "theme": t["theme"],
                    "query": t["query"],
                    "source_url": r.get("url", ""),
                    "source_title": r.get("title", "")[:120],
                    "source_description": (r.get("description") or "")[:200],
                    "source_family": _classify_source(r.get("url", "")),
                    "trust_tier": _tier_source(r.get("url", "")),
                })
            time.sleep(0.4)
        except Exception as e:
            print(f"  [brave-disc] theme {t['theme']} error: {e}")

    return discovery_records


def _classify_source(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "transcript"
    if any(s in u for s in ("seekingalpha", "bloomberg", "reuters", "cnbc", "marketwatch", "yahoo")):
        return "finance_press"
    if any(s in u for s in ("reddit.com", "stocktwits")):
        return "social"
    if any(s in u for s in ("sec.gov", "edgar")):
        return "filing"
    return "web"


def _tier_source(url: str) -> str:
    u = url.lower()
    if any(s in u for s in ("sec.gov", "yahoo.com/finance", "finviz")):
        return "A"
    if any(s in u for s in ("seekingalpha", "bloomberg", "reuters", "cnbc", "marketwatch")):
        return "B"
    if any(s in u for s in ("reddit.com", "stocktwits")):
        return "C"
    if any(s in u for s in ("youtube.com",)):
        return "D"
    return "E"


# ── Internal article enrichment ──────────────────────────────────────────

def enrich_from_article_index(symbols: list[str]) -> list[dict]:
    """Pull recent relevant articles from existing article_index."""
    records = []
    rows = _db_query(
        """SELECT title, url, source, portfolio_symbol, sentiment, impact_tier, published_at
           FROM article_index
           WHERE portfolio_symbol = ANY(%s) AND ingested_at > NOW() - INTERVAL '48 hours'
           ORDER BY ingested_at DESC LIMIT 20""",
        (symbols,)
    ) or []
    for r in rows:
        records.append({
            "symbol": r.get("portfolio_symbol"),
            "source_family": "article_index",
            "source_name": r.get("source", ""),
            "channel": r.get("url", "")[:80],
            "title": r.get("title", "")[:120],
            "summary": f"[{r.get('impact_tier','')}] {r.get('sentiment','')} — via {r.get('source','')}",
            "stance": r.get("sentiment", "neutral"),
            "notable_themes": [],
            "confidence": 0.55,
        })
    return records


# ── Persistence ──────────────────────────────────────────────────────────

def persist_transcripts(records: list[dict]) -> int:
    written = 0
    for r in records:
        ok = _db_write(
            """INSERT INTO transcript_intel_history
               (run_id, symbol, theme, source_family, source_name, channel, title, summary,
                stance, notable_themes, confidence, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, title) DO NOTHING""",
            (RUN_ID, r.get("symbol"), r.get("theme"), r["source_family"], r.get("source_name"),
             r.get("channel"), r.get("title"), r.get("summary"),
             r.get("stance"), r.get("notable_themes", []), r.get("confidence", 0.4),
             json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:transcript"}))
        )
        if ok:
            written += 1
    return written


def persist_discovery(records: list[dict]) -> int:
    written = 0
    for r in records:
        ok = _db_write(
            """INSERT INTO aegis_discovery_index
               (run_id, symbol, theme, query, source_url, source_title, source_description,
                source_family, trust_tier, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, source_url) DO NOTHING""",
            (RUN_ID, r.get("symbol"), r.get("theme"), r.get("query"),
             r.get("source_url"), r.get("source_title"), r.get("source_description"),
             r.get("source_family"), r.get("trust_tier"),
             json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:discovery"}))
        )
        if ok:
            written += 1
    return written


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print(f"[aegis-transcript] Starting — {RUN_ID}")

    from aegis_nightly_ingestion import resolve_universe
    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    # Priority: recovery > watchlist > holdings
    priority = sorted(symbols, key=lambda s: (
        0 if any("recovery" in u["reasons"] for u in universe if u["symbol"] == s) else
        1 if any("watchlist" in u["reasons"] for u in universe if u["symbol"] == s) else 2
    ))
    print(f"  Universe: {len(symbols)} symbols")

    # D1: YouTube transcripts
    yt_records = fetch_youtube_transcripts(priority)
    print(f"  YouTube: {len(yt_records)} transcript records")

    # Internal article enrichment
    article_records = enrich_from_article_index(symbols)
    print(f"  Article index: {len(article_records)} records")

    all_transcripts = yt_records + article_records
    t_written = persist_transcripts(all_transcripts)
    print(f"  Transcripts persisted: {t_written}")

    # D2: Brave bounded discovery
    discovery = fetch_brave_discovery(priority, PORTFOLIO_THEMES)
    d_written = persist_discovery(discovery)
    print(f"  Discovery: {len(discovery)} found, {d_written} persisted")

    print(f"[aegis-transcript] Complete — {datetime.now().isoformat()}")
    return {"transcripts": t_written, "discovery": d_written, "youtube": len(yt_records), "articles": len(article_records)}


if __name__ == "__main__":
    main()
