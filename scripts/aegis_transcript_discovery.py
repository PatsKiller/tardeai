"""
aegis_transcript_discovery.py — Aegis Tier 1D: Transcript intelligence + bounded web discovery.

Sources:
- Existing youtube_transcripts DB (preferred — already ingested, no network)
- YouTube transcript API (earnings calls, finance commentary for tracked symbols)
- Brave Search API (bounded article/transcript discovery; degrades on network failure)
- Existing article_index from pipeline (internal enrichment)

All outputs marked model='aegis', source='aegis:transcript' or 'aegis:discovery'.
Entry point: main() (returns a dict; aegis_overnight.py calls it) / cli() for the cron lane.

Usage (cron L291, lane aegis-transcript-discovery):
  python3 scripts/aegis_transcript_discovery.py [--dry-run]

--dry-run (refactor wave 3, 2026-10-10) puts the db_adapter session in READ ONLY, resolves the universe and runs
the internal reads (youtube_transcripts corpus, article_index), then prints a DRY-RUN report and returns: no
Brave query and no YouTube transcript API call (network=False; it reports what WOULD be queried when
AEGIS_BRAVE_ENABLED=1), never calls persist_transcripts/persist_discovery/_db_write, and writes no receipt.

Exit codes (cli): 0 = ran (zero records is a finding, still 0); 1 = the run failed: Postgres unavailable
(SELECT 1 probe), or there were records to persist and EVERY write failed. A single failed write or a Brave/network
failure is a soft failure (logged, exit 0; the DB corpus remains the durable path). 2 = usage error (argparse).
A real run writes <state_root>/data/runtime/aegis-transcript-discovery_last.json (LaneRunReceipt@v1; ok_at only on
success); a crash writes a failed receipt and re-raises.
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
LANE_ID = "aegis-transcript-discovery"

def _routing_on() -> bool:
    try:
        from scripts.lib.search_router import engine_enabled
    except ImportError:
        from lib.search_router import engine_enabled  # type: ignore
    return engine_enabled()


def _governed_brave_web(query: str, *, count: int = 3, freshness: str = "pw"):
    """Lane C chokepoint — no direct Brave HTTP from this module.

    With SEARCH_ROUTING_ENGINE=1 the question goes to the search routing engine instead (class
    transcript_discovery: cache + SearXNG with named engines, free only by policy, 2026-10-10)."""
    if _routing_on():
        try:
            from scripts.lib.search_router import route_query
        except ImportError:
            from lib.search_router import route_query  # type: ignore
        resp = route_query(query, caller="aegis_transcript_discovery", kind="web", count=count, enabled=True)
        if resp.ok:
            return list(resp.results or []), "OK"
        return ([], resp.reason) if str(resp.reason).startswith("NO_COVERAGE") else (None, resp.reason)
    try:
        from scripts.lib.brave_router import search as _governed, router_enabled
    except ImportError:
        from lib.brave_router import search as _governed, router_enabled  # type: ignore
    if not router_enabled():
        return None, "ROUTER_DISABLED"
    resp = _governed(
        query, kind="web", count=count, freshness=freshness,
        caller="aegis_transcript_discovery", purpose="aegis.transcript",
        api_key=BRAVE_KEY, enabled=True,
    )
    if not resp.ok:
        return None, resp.reason
    return list(resp.results or []), "OK"


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


def _db_available() -> bool:
    """Postgres reachable through db_adapter (``SELECT 1``). False = every read and persist would fail."""
    return bool(_db_query("SELECT 1 AS ok", fetch="one"))


def _enforce_readonly_db() -> bool:
    """Dry run: put this thread's db_adapter session in READ ONLY at the server (AGENTS.md §6)."""
    try:
        from db_adapter import _get_conn
        from lib.lane_last_receipt import enforce_readonly

        conn = _get_conn()
        if conn is None:
            return False
        enforce_readonly(conn)
        return True
    except Exception as e:
        print(f"  [aegis-td] READ ONLY session not established: {type(e).__name__}")
        return False


def _brave_enabled() -> bool:
    return os.getenv("AEGIS_BRAVE_ENABLED", "0").lower() in ("1", "true", "yes")


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

def fetch_db_youtube_transcripts(symbols: list[str], max_per_symbol: int = 2,
                                 lookback_days: int = 14) -> list[dict]:
    """Query already-ingested youtube_transcripts related to symbols. No network."""
    records = []
    if not symbols:
        return records

    for sym in symbols[:20]:
        rows = _db_query(
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
        ) or []

        for r in rows:
            title = (r.get("title") or "")[:120]
            summary = (r.get("summary") or "")[:300]
            body = (r.get("transcript_text") or "")[:500]
            if not title and not summary and not body:
                continue  # never invent
            stance, themes = _stance_and_themes(title, summary, body)
            records.append({
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
            })
    return records


# ── D1: YouTube transcript ingestion (Brave-assisted, DB-first) ───────────

def fetch_youtube_transcripts(symbols: list[str], max_per_symbol: int = 1, network: bool = True) -> list[dict]:
    """Prefer DB transcripts; optionally enrich via Brave + youtube_transcript_api.

    network=False (the --dry-run path) returns the DB corpus only: no Brave query, no YouTube API call.

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
    if not network:
        print("  [youtube] network=False — DB corpus only (no Brave / YouTube API request)")
        return records

    if os.getenv("AEGIS_BRAVE_ENABLED", "0").lower() not in ("1", "true", "yes"):
        print("  [youtube] Brave discovery retired default — DB path only; "
              "set AEGIS_BRAVE_ENABLED=1 to re-enable")
        return records

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("  [youtube] youtube_transcript_api not available — using DB/article fallback only")
        return records

    if not BRAVE_KEY and not _routing_on():
        print("  [youtube] No Brave key — skipping live YouTube discovery (DB path retained)")
        return records

    seen_ids = {r.get("video_id") for r in records if r.get("video_id")}
    brave_ok = True

    try:
        from scripts.lib.search_budget import guard as _sb_guard
    except ImportError:
        from lib.search_budget import guard as _sb_guard  # type: ignore

    for sym in symbols[:12]:
        if not brave_ok:
            break
        try:
            results, reason = _governed_brave_web(
                f"{sym} stock analysis earnings 2026 site:youtube.com", count=3, freshness="pw"
            )
            if results is None:
                print(f"  [youtube] governed deny ({reason}) for {sym} — continuing with DB")
                brave_ok = False
                break

            for r in results[:max_per_symbol]:
                video_url = r.get("url", "")
                video_id = None
                m = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
                if m:
                    video_id = m.group(1)
                if video_id and video_id in seen_ids:
                    continue

                title = r.get("title", "")[:120]
                description = (r.get("description") or "")[:200]

                transcript_text = ""
                if video_id:
                    try:
                        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                        full = " ".join(t["text"] for t in transcript)
                        transcript_text = full[:2000]
                    except Exception:
                        pass

                stance, themes = _stance_and_themes(title, description, transcript_text)
                summary = transcript_text[:300] if transcript_text else description
                if not title and not summary:
                    continue
                records.append({
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
                })
                if video_id:
                    seen_ids.add(video_id)

            time.sleep(0.5)
        except Exception as e:
            if _is_network_error(e):
                print(f"  [youtube] Brave unreachable ({e}) — continuing with DB/Hermes-style fallback "
                      f"({len(records)} records so far)")
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
    if not BRAVE_KEY and not _routing_on():
        print("  [brave-disc] No Brave key — skipping live discovery")
        return []

    discovery_records = []

    try:
        from scripts.lib.search_budget import guard as _sb_guard
    except ImportError:
        from lib.search_budget import guard as _sb_guard  # type: ignore

    for sym in symbols[:10]:
        try:
            results, reason = _governed_brave_web(
                f"{sym} stock earnings analysis news 2026", count=3, freshness="pw"
            )
            if results is None:
                break
            for r in results[:3]:
                title = r.get("title", "")[:120]
                src_url = r.get("url", "")
                if not title and not src_url:
                    continue
                discovery_records.append({
                    "symbol": sym, "theme": None,
                    "query": f"{sym} stock analysis",
                    "source_url": src_url,
                    "source_title": title,
                    "source_description": (r.get("description") or "")[:200],
                    "source_family": _classify_source(src_url),
                    "trust_tier": _tier_source(src_url),
                })
            time.sleep(0.4)
        except Exception as e:
            if _is_network_error(e):
                print(f"  [brave-disc] Network unreachable ({e}) — aborting Brave symbol scan; "
                      f"DB/article fallback remains available")
                return discovery_records
            print(f"  [brave-disc] {sym} error: {e}")

    for t in themes:
        try:
            results, reason = _governed_brave_web(t["query"], count=3, freshness="pw")
            if results is None:
                break
            for r in results[:3]:
                title = r.get("title", "")[:120]
                src_url = r.get("url", "")
                if not title and not src_url:
                    continue
                discovery_records.append({
                    "symbol": None, "theme": t["theme"],
                    "query": t["query"],
                    "source_url": src_url,
                    "source_title": title,
                    "source_description": (r.get("description") or "")[:200],
                    "source_family": _classify_source(src_url),
                    "trust_tier": _tier_source(src_url),
                })
            time.sleep(0.4)
        except Exception as e:
            if _is_network_error(e):
                print(f"  [brave-disc] Network unreachable on theme scan ({e}) — stopping Brave themes")
                return discovery_records
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

def main(dry_run: bool = False):
    print(f"[aegis-transcript] Starting — {RUN_ID}" + (" (DRY RUN)" if dry_run else ""))
    readonly = _enforce_readonly_db() if dry_run else False
    if not _db_available():
        print("  [aegis-td] Postgres unavailable — nothing can be read or persisted")
        return {"transcripts": 0, "discovery": 0, "youtube": 0, "articles": 0, "db_ok": False,
                "error": "db_unavailable"}

    from aegis_nightly_ingestion import resolve_universe
    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    priority = sorted(symbols, key=lambda s: (
        0 if any("recovery" in u["reasons"] for u in universe if u["symbol"] == s) else
        1 if any("watchlist" in u["reasons"] for u in universe if u["symbol"] == s) else 2
    ))
    print(f"  Universe: {len(symbols)} symbols")

    # D1: YouTube transcripts (DB preferred, Brave optional; the dry run never touches the network)
    yt_records = fetch_youtube_transcripts(priority, network=not dry_run)
    print(f"  YouTube: {len(yt_records)} transcript records")

    # Internal article enrichment (Hermes-style local fallback)
    article_records = enrich_from_article_index(symbols)
    print(f"  Article index: {len(article_records)} records")

    all_transcripts = yt_records + article_records
    if dry_run:
        brave_on = _brave_enabled() and bool(BRAVE_KEY)
        from lib.lane_last_receipt import dry_run_report
        summary = {"universe": len(symbols), "youtube_db": len(yt_records), "articles": len(article_records),
                   "would_write_transcripts": len(all_transcripts),
                   "would_query_brave": (min(len(priority), 12) + min(len(priority), 10) + len(PORTFOLIO_THEMES))
                   if brave_on else 0,
                   "brave_enabled": _brave_enabled(), "readonly_session": readonly, "run_id": RUN_ID}
        dry_run_report(LANE_ID, summary, would_write=[
            f"transcript_intel_history: <= {len(all_transcripts)} rows (run_id={RUN_ID}, ON CONFLICT DO NOTHING)",
            "aegis_discovery_index: 0 rows unless AEGIS_BRAVE_ENABLED=1"])
        return {**summary, "dry_run": True, "transcripts": 0, "discovery": 0}

    t_written = persist_transcripts(all_transcripts)
    print(f"  Transcripts persisted: {t_written}")

    # D2: Brave bounded discovery (degrades gracefully on network failure)
    discovery = fetch_brave_discovery(priority, PORTFOLIO_THEMES)
    d_written = persist_discovery(discovery)
    print(f"  Discovery: {len(discovery)} found, {d_written} persisted")

    print(f"[aegis-transcript] Complete — {datetime.now().isoformat()}")
    result = {
        "transcripts": t_written,
        "discovery": d_written,
        "youtube": len(yt_records),
        "articles": len(article_records),
        "to_write": len(all_transcripts) + len(discovery),
        "db_ok": True,
    }
    if result["to_write"] and t_written + d_written == 0:
        result["error"] = "all_writes_failed"
    return result


def cli(argv=None) -> int:
    """Cron entry: --dry-run, honest exit code, LaneRunReceipt@v1 on real runs only (see module docstring)."""
    import argparse

    ap = argparse.ArgumentParser(description="Aegis transcript + discovery ingestion (cron L291)")
    ap.add_argument("--dry-run", action="store_true",
                    help="DB reads + report; no Brave/YouTube request, no INSERT, no receipt")
    args = ap.parse_args(argv)
    if args.dry_run:
        result = main(dry_run=True)
        return 1 if result.get("error") else 0

    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        result = main()
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                           script="aegis_transcript_discovery.py", error=f"{type(exc).__name__}: {exc}")
        raise
    failed = bool(result.get("error"))
    write_lane_receipt(LANE_ID, ok=not failed, exit_code=1 if failed else 0, started_at=started,
                       script="aegis_transcript_discovery.py",
                       summary={k: result.get(k) for k in ("transcripts", "discovery", "youtube", "articles",
                                                           "to_write", "error")},
                       error=result.get("error"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(cli())
