#!/usr/bin/env python3
"""candidate_discovery_orchestrator.py — Multi-source candidate discovery.

Rewired (2026-08-19 watchlist audit, Gap D): the previous version only wrote
candidate_discovery_events in DEGRADED mode (Finviz failure), so the feed was
permanently empty while Finviz was healthy, and it never reported liveness. This
version polls the discovery_sources package (finviz, social_scalp, news_catalyst,
incubator, yahoo_movers), ALWAYS writes candidate_discovery_events on
--apply, and reports each source's liveness via report_source() so the health
agent can see it go stale.

Usage:
    python candidate_discovery_orchestrator.py --dry-run
    python candidate_discovery_orchestrator.py --apply
    python candidate_discovery_orchestrator.py --apply --max-candidates 200

Dry run (n8n refactor wave 3, 2026-10-10): ``--dry-run`` WINS over ``--apply``; no ``--apply`` is still a
dry run. It polls the DB-backed sources on a session made READ ONLY at the server, SKIPS the Finviz
source (its discover() probes the paid Finviz Elite export; reported as would-probe instead), prints a
``DRY-RUN`` report and returns BEFORE ``_record_events`` / ``report_source`` are reachable. It writes no
receipt.

A REAL (``--apply``) run writes LaneRunReceipt@v1
``<state_root>/data/runtime/candidate-discovery-orchestrator_last.json`` (``ok_at`` only on success).
Exit codes: 0 = ran (a source with 0 candidates is a finding, still 0); 1 = the run failed (DB
unavailable, recording the events raised, or EVERY source raised); 2 = usage error. One source raising
is a per-source soft failure.

Finding (2026-10-10): the finviz source only ever emits the synthetic FINVIZ_OK status row, which main()
drops, so ``candidates_by_source.finviz`` is 0 by construction even when Finviz is healthy.
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

LANE_ID = "candidate-discovery-orchestrator"
#: sources a dry run must not poll (their discover() makes a paid / rate-limited external fetch)
DRY_RUN_SKIP_SOURCES = ("finviz",)


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.candidate_discovery_orchestrator
        from scripts.lib import lane_last_receipt as lr
    return lr


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _all_sources():
    from discovery_sources.finviz_source import FinvizSource
    from discovery_sources.social_source import SocialSource
    from discovery_sources.news_catalyst_source import NewsCatalystSource
    from discovery_sources.incubator_source import IncubatorSource
    from discovery_sources.yahoo_source import YahooSource
    return [
        FinvizSource(),
        SocialSource(),
        NewsCatalystSource(),
        IncubatorSource(),
        YahooSource(),
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


def _poll(conn, sources, max_candidates: int, skip=()):
    """Poll each source (SELECT-only for the DB sources) -> (unique, counts, errors, skipped)."""
    print(f"[discovery] polling {len(sources)} sources")
    candidates = []
    counts = {}
    errors = {}
    skipped = []
    for src in sources:
        if src.source_key in skip:
            skipped.append(src.source_key)
            print(f"  [discovery] {src.source_key}: skipped in dry run (would probe its external source)")
            continue
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
            errors[src.source_key] = type(e).__name__
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
    return unique[:max_candidates], counts, errors, skipped


def _dry_run(args) -> int:
    """Read-only preview. ``_record_events`` and ``report_source`` are not reachable from here."""
    lr = _receipt_lib()
    try:
        conn = _get_conn()
        lr.enforce_readonly(conn)
        unique, counts, errors, skipped = _poll(conn, _all_sources(), args.max_candidates,
                                                skip=DRY_RUN_SKIP_SOURCES)
    except Exception as e:
        print(f"  [discovery] DRY-RUN failed: {type(e).__name__}: {e}")
        return 1
    print(f"  [discovery] DRY-RUN — would record {len(unique)} events")
    try:
        conn.close()
    except Exception:
        pass
    lr.dry_run_report(
        LANE_ID,
        {"candidates_by_source": counts, "would_record": len(unique), "source_errors": errors,
         "skipped_sources": skipped},
        would_write=["candidate_discovery_events (INSERT) x would_record",
                     "data_source_health per non-finviz source"],
    )
    polled = len(counts) + len(errors)
    return 1 if errors and len(errors) >= polled else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="read + report only; wins over --apply")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=100)
    args = parser.parse_args(argv)

    if args.dry_run or not args.apply:
        return _dry_run(args)

    lr = _receipt_lib()
    started = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        sources = _all_sources()
        unique, counts, errors, _ = _poll(conn, sources, args.max_candidates)

        recorded = _record_events(conn, unique, degraded=False)
        print(f"  [discovery] recorded {recorded} events")

        # Report liveness per source (apply only — dry-run must not mark sources healthy).
        # finviz is owned by finviz_health_check.py (its only reporter per crontab).
        # polygon was retired 2026-09-13 (config/data_source_authority.json).
        try:
            from lib.data_source_report import report_source
            for key, n in counts.items():
                if key == "finviz":
                    continue
                report_source(key, n > 0, rows=n,
                              error=None if n > 0 else f"0 candidates from {key}")
        except Exception:
            pass

        summary = {
            "candidates_by_source": counts,
            "total_unique": len(unique),
            "recorded": recorded,
            "source_errors": errors,
            "dry_run": False,
        }
        print(f"  Summary: {json.dumps(summary)}")
        conn.close()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="candidate_discovery_orchestrator.py", error=f"{type(exc).__name__}: {exc}")
        raise
    rc = 1 if errors and len(errors) == len(sources) else 0
    lr.write_lane_receipt(LANE_ID, ok=rc == 0, exit_code=rc, started_at=started,
                          script="candidate_discovery_orchestrator.py",
                          summary={k: v for k, v in summary.items() if k != "dry_run"})
    return rc


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    sys.exit(main())
