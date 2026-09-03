"""
aegis_transcript_discovery.py — Aegis Tier 1D: Transcript intelligence + bounded web discovery.

Sources:
- Existing youtube_transcripts DB (preferred — already ingested, no network)
- YouTube transcript API (earnings calls, finance commentary for tracked symbols)
- Brave Search API (bounded article/transcript discovery; degrades on network failure)
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

# Portfolio themes to scan beyond individual symbols
PORTFOLIO_THEMES = [
    {"theme": "covered-calls-income", "query": "covered call strategy income ETF 2026"},
    {"theme": "defense-sector", "query": "defense sector stocks earnings outlook"},
    {"theme": "dividend-income", "query": "dividend income portfolio strategy SCHD"},
]

# Network-class errors that should not zero the entire discovery path.
_NETWORK_ERROR_MARKERS = (
    "Network is unreachable",
    "Failed to establish a new connection",
    "Name or service not known",
    "Connection refused",
    "Temporary failure in name resolution",
    "Max retries exceeded",
    "ConnectTimeout",
    "ConnectionError",
)


def _brave_router():
    """The one governed Brave path. Returns None when unavailable (→ DENY).

    Every Brave query in this module goes through the canonical router: the
    three loops below used to build their own URL, header and key read, so a
    provider failure was indistinguishable from a quiet week and none of the
    error classes reached the operator.
    """
    try:
        from scripts.lib import brave_research_router as R

        return R
    except ImportError:  # pragma: no cover
        try:
            from lib import brave_research_router as R  # type: ignore

            return R
        except ImportError:
            return None


def _is_network_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}"
    return any(m in msg for m in _NETWORK_ERROR_MARKERS)


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


def _stance_and_themes(title: str, description: str, body: str = "") -> tuple[str, list]:
    text_lower = (title + " " + description + " " + body[:500]).lower()
    bullish = sum(1 for w in ("bull", "buy", "upside", "breakout", "growth") if w in text_lower)
    bearish = sum(1 for w in ("bear", "sell", "downside", "crash", "risk") if w in text_lower)
    stance = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    themes = []
    for t_word in ("earnings", "dividend", "covered call", "options", "growth", "value", "defense", "AI", "tech"):
        if t_word.lower() in text_lower:
            themes.append(t_word)
    return stance, themes[:5]


# ── D0: Prefer existing youtube_transcripts DB ────────────────────────────


def fetch_db_youtube_transcripts(symbols: list[str], max_per_symbol: int = 2, lookback_days: int = 14) -> list[dict]:
    """Query already-ingested youtube_transcripts related to symbols. No network."""
    records = []
    if not symbols:
        return records

    for sym in symbols[:20]:
        rows = (
            _db_query(
                """SELECT video_id, title, channel_name, url, summary, transcript_text,
                      quality_score, strategy_tags, ingested_at
               FROM youtube_transcripts
               WHERE ingested_at > NOW() - make_interval(days => %s)
                 AND (
                      title ILIKE %s
                   OR COALESCE(summary, '') ILIKE %s
                   OR COALESCE(transcript_text, '') ILIKE %s
                   OR COALESCE(strategy_tags::text, '') ILIKE %s
                 )
               ORDER BY quality_score DESC NULLS LAST, ingested_at DESC
               LIMIT %s""",
                (lookback_days, f"%{sym}%", f"%{sym}%", f"%{sym}%", f"%{sym}%", max_per_symbol),
            )
            or []
        )

        for r in rows:
            title = (r.get("title") or "")[:120]
            summary = (r.get("summary") or "")[:300]
            body = (r.get("transcript_text") or "")[:500]
            if not title and not summary and not body:
                continue  # never invent
            stance, themes = _stance_and_themes(title, summary, body)
            records.append(
                {
                    "symbol": sym,
                    "theme": None,
                    "source_family": "youtube",
                    "source_name": "youtube_transcripts_db",
                    "channel": (r.get("url") or r.get("channel_name") or "")[:80],
                    "title": title,
                    "summary": summary or body[:300],
                    "stance": stance,
                    "notable_themes": themes,
                    "confidence": 0.55,
                    "video_id": r.get("video_id"),
                    "quality_score": r.get("quality_score"),
                }
            )
    return records


# ── D1: YouTube transcript ingestion (Brave-assisted, DB-first) ───────────


def fetch_youtube_transcripts(symbols: list[str], max_per_symbol: int = 1) -> list[dict]:
    """Prefer DB transcripts; optionally enrich via Brave + youtube_transcript_api.

    Brave network failures are logged and skipped — never invents rows.
    Brave live discovery is OFF by default (Wave 3 2026-09-01) — set
    AEGIS_BRAVE_ENABLED=1 to re-enable. DB corpus remains the durable path.
    Consumer: aegis transcript store — do not delete this function.
    """
    import os

    # Preferred path: already-ingested corpus
    records = fetch_db_youtube_transcripts(symbols, max_per_symbol=max(max_per_symbol, 2))
    if records:
        print(f"  [youtube] DB corpus: {len(records)} symbol-related transcripts")

    if os.getenv("AEGIS_BRAVE_ENABLED", "0").lower() not in ("1", "true", "yes"):
        print("  [youtube] Brave discovery retired default — DB path only; set AEGIS_BRAVE_ENABLED=1 to re-enable")
        return records

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("  [youtube] youtube_transcript_api not available — using DB/article fallback only")
        return records

    # Key resolution belongs to the router: BRAVE_KEY here is an env-only read
    # and returns empty when the key lives in .env, which would skip discovery
    # on a perfectly healthy credential.
    if _brave_router() is None:
        print("  [youtube] research router unavailable — DB path retained")
        return records

    seen_ids = {r.get("video_id") for r in records if r.get("video_id")}
    brave_ok = True

    _R = _brave_router()
    if _R is None:
        print("  [youtube] research router unavailable — DENY (never fail open)")
        return records

    for sym in symbols[:12]:
        if not brave_ok:
            break
        # Discovery and transcript retrieval are separate stages with separate
        # health: this loop only finds candidate videos. A failure here is a
        # discovery failure, not an empty transcript lane.
        _outcome = _R.search(
            f"{sym} stock analysis earnings 2026 site:youtube.com",
            purpose=_R.Purpose.TRANSCRIPT_DISCOVERY,
            priority=_R.Priority.WATCHLIST,
            caller="aegis_transcript_discovery",
            count=3,
            freshness="pw",
        )
        if _outcome.status in (
            _R.Status.DENIED_BUDGET,
            _R.Status.DENIED_RESERVE,
            _R.Status.DENIED_PURPOSE_QUOTA,
            _R.Status.DENIED_WEEKEND,
            _R.Status.BUDGET_UNAVAILABLE,
        ):
            print(f"  [youtube] {_outcome.status.value} at {sym} — {_outcome.degradation_note()}")
            break
        if _outcome.degraded:
            print(f"  [youtube] {sym}: {_outcome.status.value} — continuing with DB")
            continue
        try:
            for r in [x.to_dict() for x in _outcome.results][:max_per_symbol]:
                video_url = r.get("url", "")
                video_id = None
                m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", video_url)
                if m:
                    video_id = m.group(1)
                if video_id and video_id in seen_ids:
                    continue

                title = r.get("title", "")[:120]
                description = (r.get("description") or "")[:200]

                transcript_text = ""
                if video_id:
                    try:
                        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
                        full = " ".join(t["text"] for t in transcript)
                        transcript_text = full[:2000]
                    except Exception:
                        pass

                stance, themes = _stance_and_themes(title, description, transcript_text)
                summary = transcript_text[:300] if transcript_text else description
                if not title and not summary:
                    continue
                records.append(
                    {
                        "symbol": sym,
                        "source_family": "youtube",
                        "source_name": "youtube_transcript",
                        "channel": video_url[:80],
                        "title": title,
                        "summary": summary,
                        "stance": stance,
                        "notable_themes": themes,
                        "confidence": 0.45 if transcript_text else 0.30,
                        "video_id": video_id,
                    }
                )
                if video_id:
                    seen_ids.add(video_id)

            time.sleep(0.5)
        except Exception as e:
            if _is_network_error(e):
                print(
                    f"  [youtube] Brave unreachable ({e}) — continuing with DB/Hermes-style fallback "
                    f"({len(records)} records so far)"
                )
                brave_ok = False
                break
            print(f"  [youtube] {sym} error: {e}")

    return records


# ── D2: Brave bounded discovery ──────────────────────────────────────────


def fetch_brave_discovery(symbols: list[str], themes: list[dict]) -> list[dict]:
    """Bounded Brave discovery for articles, transcripts, commentary.

    On network failure: log clearly and return whatever was collected (often []).
    Callers should still run DB/article enrichment — this never invents data.

    Default OFF (Wave 3 2026-09-01). A search API is not a news feed; news
    belongs on RSS/Finviz. Set AEGIS_BRAVE_ENABLED=1 to re-enable. Consumer
    named (aegis transcript / discovery store) — do not delete.
    """
    import os

    if os.getenv("AEGIS_BRAVE_ENABLED", "0").lower() not in ("1", "true", "yes"):
        print("  [brave-disc] retired default — set AEGIS_BRAVE_ENABLED=1 to re-enable")
        return []
    if _brave_router() is None:
        print("  [brave-disc] research router unavailable — DENY (never fail open)")
        return []

    discovery_records = []

    _R = _brave_router()
    if _R is None:
        print("  [brave-disc] research router unavailable — DENY (never fail open)")
        return discovery_records

    for sym in symbols[:10]:
        _outcome = _R.search(
            f"{sym} stock earnings analysis news 2026",
            purpose=_R.Purpose.LONG_TAIL_DISCOVERY,
            priority=_R.Priority.WATCHLIST,
            caller="aegis_transcript_discovery",
            count=3,
            freshness="pw",
        )
        if _outcome.status in (
            _R.Status.DENIED_BUDGET,
            _R.Status.DENIED_RESERVE,
            _R.Status.DENIED_PURPOSE_QUOTA,
            _R.Status.DENIED_WEEKEND,
            _R.Status.BUDGET_UNAVAILABLE,
        ):
            print(f"  [brave-disc] {_outcome.status.value} at {sym} — {_outcome.degradation_note()}")
            break
        if _outcome.status in (_R.Status.TRANSPORT_ERROR, _R.Status.TIMEOUT):
            print(
                f"  [brave-disc] {_outcome.status.value} ({_outcome.reason}) — "
                f"aborting Brave symbol scan; DB/article fallback remains available"
            )
            return discovery_records
        if _outcome.degraded:
            continue
        for r in _outcome.results[:3]:
            if not r.title and not r.url:
                continue
            discovery_records.append(
                {
                    "symbol": sym,
                    "theme": None,
                    "query": f"{sym} stock analysis",
                    "source_url": r.url,
                    "source_title": r.title[:120],
                    "source_description": r.description[:200],
                    "source_family": _classify_source(r.url),
                    "trust_tier": _tier_source(r.url),
                    "attribution": r.attribution,
                }
            )

    for t in themes:
        _outcome = _R.search(
            t["query"],
            purpose=_R.Purpose.LONG_TAIL_DISCOVERY,
            priority=_R.Priority.COLD_UNIVERSE,
            caller="aegis_transcript_discovery",
            count=3,
            freshness="pw",
        )
        if _outcome.status in (
            _R.Status.DENIED_BUDGET,
            _R.Status.DENIED_RESERVE,
            _R.Status.DENIED_PURPOSE_QUOTA,
            _R.Status.DENIED_WEEKEND,
            _R.Status.BUDGET_UNAVAILABLE,
        ):
            print(f"  [brave-disc] {_outcome.status.value} on theme scan — {_outcome.degradation_note()}")
            break
        if _outcome.status in (_R.Status.TRANSPORT_ERROR, _R.Status.TIMEOUT):
            print(f"  [brave-disc] {_outcome.status.value} on theme scan ({_outcome.reason}) — stopping Brave themes")
            return discovery_records
        if _outcome.degraded:
            continue
        for r in _outcome.results[:3]:
            if not r.title and not r.url:
                continue
            discovery_records.append(
                {
                    "symbol": None,
                    "theme": t["theme"],
                    "query": t["query"],
                    "source_url": r.url,
                    "source_title": r.title[:120],
                    "source_description": r.description[:200],
                    "source_family": _classify_source(r.url),
                    "trust_tier": _tier_source(r.url),
                    "attribution": r.attribution,
                }
            )

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
    rows = (
        _db_query(
            """SELECT title, url, source, portfolio_symbol, sentiment, impact_tier, published_at
           FROM article_index
           WHERE portfolio_symbol = ANY(%s) AND ingested_at > NOW() - INTERVAL '48 hours'
           ORDER BY ingested_at DESC LIMIT 20""",
            (symbols,),
        )
        or []
    )
    for r in rows:
        records.append(
            {
                "symbol": r.get("portfolio_symbol"),
                "source_family": "article_index",
                "source_name": r.get("source", ""),
                "channel": r.get("url", "")[:80],
                "title": r.get("title", "")[:120],
                "summary": f"[{r.get('impact_tier', '')}] {r.get('sentiment', '')} — via {r.get('source', '')}",
                "stance": r.get("sentiment", "neutral"),
                "notable_themes": [],
                "confidence": 0.55,
            }
        )
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
            (
                RUN_ID,
                r.get("symbol"),
                r.get("theme"),
                r["source_family"],
                r.get("source_name"),
                r.get("channel"),
                r.get("title"),
                r.get("summary"),
                r.get("stance"),
                r.get("notable_themes", []),
                r.get("confidence", 0.4),
                json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:transcript"}),
            ),
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
            (
                RUN_ID,
                r.get("symbol"),
                r.get("theme"),
                r.get("query"),
                r.get("source_url"),
                r.get("source_title"),
                r.get("source_description"),
                r.get("source_family"),
                r.get("trust_tier"),
                json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:discovery"}),
            ),
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
    priority = sorted(
        symbols,
        key=lambda s: (
            0
            if any("recovery" in u["reasons"] for u in universe if u["symbol"] == s)
            else 1
            if any("watchlist" in u["reasons"] for u in universe if u["symbol"] == s)
            else 2
        ),
    )
    print(f"  Universe: {len(symbols)} symbols")

    # D1: YouTube transcripts (DB preferred, Brave optional)
    yt_records = fetch_youtube_transcripts(priority)
    print(f"  YouTube: {len(yt_records)} transcript records")

    # Internal article enrichment (Hermes-style local fallback)
    article_records = enrich_from_article_index(symbols)
    print(f"  Article index: {len(article_records)} records")

    all_transcripts = yt_records + article_records
    t_written = persist_transcripts(all_transcripts)
    print(f"  Transcripts persisted: {t_written}")

    # D2: Brave bounded discovery (degrades gracefully on network failure)
    discovery = fetch_brave_discovery(priority, PORTFOLIO_THEMES)
    d_written = persist_discovery(discovery)
    print(f"  Discovery: {len(discovery)} found, {d_written} persisted")

    print(f"[aegis-transcript] Complete — {datetime.now().isoformat()}")
    return {
        "transcripts": t_written,
        "discovery": d_written,
        "youtube": len(yt_records),
        "articles": len(article_records),
    }


if __name__ == "__main__":
    main()
