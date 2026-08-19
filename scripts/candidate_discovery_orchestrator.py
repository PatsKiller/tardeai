#!/usr/bin/env python3
"""candidate_discovery_orchestrator.py — Multi-source candidate discovery.

Rewired (2026-08-19 watchlist audit, Gap D): the previous version only wrote
candidate_discovery_events in DEGRADED mode (Finviz failure), so the feed was
permanently empty while Finviz was healthy, and it never reported liveness. This
version polls the discovery_sources package (finviz, social_scalp, news_catalyst,
incubator, yahoo_movers, polygon), ALWAYS writes candidate_discovery_events on
--apply, and reports each source's liveness via report_source() so the health
agent can see it go stale.

Usage:
    python candidate_discovery_orchestrator.py --dry-run
    python candidate_discovery_orchestrator.py --apply
    python candidate_discovery_orchestrator.py --apply --max-candidates 200
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _all_sources():
    from discovery_sources.finviz_source import FinvizSource
    from discovery_sources.social_source import SocialSource
    from discovery_sources.news_catalyst_source import NewsCatalystSource
    from discovery_sources.incubator_source import IncubatorSource
    from discovery_sources.yahoo_source import YahooSource
    from discovery_sources.polygon_source import PolygonSource
    return [
        FinvizSource(),
        SocialSource(),
        NewsCatalystSource(),
        IncubatorSource(),
        YahooSource(),
        PolygonSource(),
    ]


def _record_events(conn, candidates: list[dict], degraded: bool) -> int:
    cur = conn.cursor()
    n = 0
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    for c in candidates:
        event_id = f"disc_{ts}_{uuid.uuid4().hex[:8]}"
        cur.execute(
            """INSERT INTO candidate_discovery_events
                   (event_id, source_key, symbol, source_confidence,
                    normalized_payload, degraded, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (event_id) DO NOTHING""",
            (event_id, c["source_key"], c["symbol"],
             c.get("source_confidence", 0.5),
             json.dumps(c.get("normalized_payload", {})),
             degraded, c.get("reason", "")))
        n += 1
    conn.commit()
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=100)
    args = parser.parse_args()

    conn = _get_conn()
    sources = _all_sources()

    print(f"[discovery] polling {len(sources)} sources")
    candidates = []
    counts = {}
    for src in sources:
        # Each source runs on the shared connection; a failed query can leave it in an
        # aborted-transaction state that would poison every later source. Roll back first.
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            found = src.discover(conn, limit=50)
        except Exception as e:
            print(f"  [discovery] {src.source_key} error: {e}")
            found = []
        # Finviz source emits a synthetic FINVIZ_OK status row, not a ticker — drop it.
        real = [c for c in found if c.get("symbol") != "FINVIZ_OK"]
        counts[src.source_key] = len(real)
        candidates.extend(real)
        print(f"  [discovery] {src.source_key}: {len(real)} candidates")

    # Dedup by (symbol, source_key); keep first.
    seen = set()
    unique = []
    for c in candidates:
        key = (c["symbol"], c["source_key"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    unique = unique[: args.max_candidates]

    recorded = 0
    if args.apply and not args.dry_run:
        recorded = _record_events(conn, unique, degraded=False)
        print(f"  [discovery] recorded {recorded} events")
    elif args.dry_run:
        print(f"  [discovery] DRY-RUN — would record {len(unique)} events")

    # Report liveness per source (apply only — dry-run must not mark sources healthy).
    # finviz is owned by finviz_health_check.py (its only reporter per crontab); polygon is
    # optional (no POLYGON_API_KEY) and must not be flagged as a failure when unconfigured.
    if args.apply:
        try:
            from lib.data_source_report import report_source
            for key, n in counts.items():
                if key == "finviz":
                    continue
                if key == "polygon" and not os.getenv("POLYGON_API_KEY"):
                    continue
                report_source(key, n > 0, rows=n,
                              error=None if n > 0 else f"0 candidates from {key}")
        except Exception:
            pass

    summary = {
        "candidates_by_source": counts,
        "total_unique": len(unique),
        "recorded": recorded,
        "dry_run": args.dry_run,
    }
    print(f"  Summary: {json.dumps(summary)}")
    conn.close()
    return summary


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
