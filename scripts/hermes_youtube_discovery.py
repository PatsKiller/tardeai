#!/usr/bin/env python3
"""Hermes YouTube discovery — discover & ingest YouTube transcript content for related targets.

Hermes already LOOKS UP existing transcripts via RAG (content_embeddings has ~1,150 youtube
rows). This adds the DISCOVERY half: for symbols Hermes is researching, use SearXNG's youtube
engine to find relevant videos, fetch their transcripts (cookie-gated, via youtube_transcript_ingest),
and stage a finding into hermes_research_intelligence so the content flows into curation → RAG.

Cookie-gated: transcript fetch needs authenticated ~/.config/tradeai/youtube_cookies.txt (see Pipeline tab
stoplight). Kept small per run to avoid YouTube 429 rate-limiting.

    python3 scripts/hermes_youtube_discovery.py                    # dry-run (discover only)
    python3 scripts/hermes_youtube_discovery.py --apply --limit 5
"""
import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (--apply). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "hermes-youtube-discovery"
    _dr_would = (
        "pick --limit Hermes research targets, search SearXNG's youtube engine for --videos videos each and, "
        "with --apply, ingest their transcripts (cookie-gated) and stage findings into "
        "hermes_research_intelligence"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="target_symbol"))
    raise SystemExit(0)

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
KILL = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"

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
    """Non-circular discovery (2026-06-11): the loop previously only researched symbols ALREADY on the
    watchlist — it could never surface anything new. Now ~40% of each run's slots go to FRESH symbols:
    Schwab index movers (read-only) that are NOT on the watchlist yet."""
    from db_adapter import _execute
    rows = _execute(
        "SELECT DISTINCT symbol FROM watchlist_items WHERE status='active' AND symbol IS NOT NULL ORDER BY symbol LIMIT %s",
        (limit,), fetch="all")
    targets = [r["symbol"] for r in (rows or [])]
    fresh_slots = max(1, int(limit * 0.4))
    try:
        import schwab_transport
        wl = {t for t in targets}
        try:
            wl_all = _execute("SELECT DISTINCT symbol FROM watchlist_items WHERE status<>'removed'", fetch="all")
            wl = {r["symbol"] for r in (wl_all or [])}
        except Exception:
            pass
        fresh = []
        for idx in ("$SPX", "NASDAQ"):
            m = schwab_transport.get_movers(idx)
            for mv in (m.get("movers") or []):
                sym = (mv.get("symbol") or "").upper()
                if sym and sym.isalpha() and sym not in wl and sym not in fresh:
                    fresh.append(sym)
            if len(fresh) >= fresh_slots:
                break
        if fresh:
            targets = targets[: limit - len(fresh[:fresh_slots])] + fresh[:fresh_slots]
            print(f"[yt-discovery] fresh (non-watchlist) movers added: {fresh[:fresh_slots]}")
    except Exception:
        pass
    return targets


LANE_ID = "hermes-youtube-discovery"


def _receipt_lib():
    try:
        from scripts.lib import lane_last_receipt as lr
    except ImportError:
        from lib import lane_last_receipt as lr
    return lr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="fetch transcripts + stage findings (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline plan; wins over --apply (normally handled before imports, so main() stays test-safe)")
    ap.add_argument("--limit", type=int, default=5, help="number of target symbols per run")
    ap.add_argument("--videos", type=int, default=2, help="videos per target")
    args = ap.parse_args()
    apply = bool(args.apply) and not args.dry_run

    if KILL.exists():
        log.info("kill switch present — aborting")
        if apply:
            lr = _receipt_lib()
            # The lane ran and was deliberately suppressed: nothing produced, and the reason says so.
            lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=lr.now_iso(),
                                  script="hermes_youtube_discovery.py",
                                  output={"produced_count": 0, "attempted_count": 0,
                                          "skipped_reasons": {"kill_switch": 1},
                                          "empty_reason": "kill_switch_present"})
        return 0

    lr = _receipt_lib() if apply else None
    started = lr.now_iso() if lr else None
    try:
        from db_adapter import get_connection
        syms = get_targets(args.limit)
        log.info("Targets (%d): %s", len(syms), ", ".join(syms))

        ingest_video = None
        conn = cur = None
        if apply:
            from youtube_transcript_ingest import ingest_video as _iv
            ingest_video = _iv
            conn = get_connection(); cur = conn.cursor()

        staged = ingested = found_total = failed = 0
        for sym in syms:
            urls = searx_youtube(f"{sym} stock analysis", args.videos)
            found_total += len(urls)
            got = []
            if apply:
                for u in urls:
                    try:
                        res = ingest_video(u, added_by="hermes_youtube_discovery")
                        if res and "error" not in res:
                            got.append(u)
                            if res.get("status") not in ("already_exists",):
                                ingested += 1
                    except Exception as e:
                        failed += 1
                        log.warning("  ingest failed %s: %s", u, e)
                    time.sleep(1.5)  # be gentle — YouTube rate-limits
                if urls:
                    summary = (f"Hermes YouTube discovery for {sym}: {len(urls)} videos found via SearXNG, "
                               f"{len(got)} transcripts available. Feeds RAG via curation.")
                    # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
                    from lib.writers.hermes_research_writer import write_research_rows
                    rc = write_research_rows(cur, [{
                        "research_type": "youtube_discovery", "symbol": sym, "topic": f"youtube_discovery: {sym}",
                        "summary": summary, "confidence_score": 0.6, "status": "staged", "source": "hermes",
                        "source_urls_json": urls, "hermes_agent_name": "hermes_youtube_discovery",
                        "model_used": "gemma3:4b",
                    }], producer="hermes_youtube_discovery")
                    conn.commit(); staged += rc.rows_written
            log.info("  %s: %d videos%s", sym, len(urls), f", {len(got)} transcripts" if apply else "")
            time.sleep(1)

        if conn:
            conn.close()
    except BaseException as exc:
        if lr:
            # Every exit writes: a failed run never keeps a previous ok_at looking green.
            lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                  script="hermes_youtube_discovery.py", error=type(exc).__name__,
                                  output={"produced_count": 0, "attempted_count": 0,
                                          "skipped_reasons": {"run_failed": 1}})
        raise

    mode = "APPLIED" if apply else "DRY-RUN"
    log.info("[%s] %d targets, %d videos found, %d staged, %d new transcripts", mode, len(syms), found_total, staged, ingested)
    if not apply:
        log.info("Dry-run — re-run with --apply to fetch transcripts + stage.")
        return 0
    # produced_count = hermes_research_intelligence rows staged (the lane's registry output_signal is
    # data/runtime/hermes-youtube-discovery_last.json); attempted_count = videos found and considered.
    lr.write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started,
                          script="hermes_youtube_discovery.py",
                          summary={"targets": len(syms), "videos_found": found_total,
                                   "staged": staged, "new_transcripts": ingested},
                          output={"produced_count": staged, "attempted_count": found_total,
                                  "skipped_reasons": {"ingest_failed": failed},
                                  "empty_reason": "no_findings_staged" if staged == 0 else None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
