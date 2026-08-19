#!/usr/bin/env python3
"""daily_incubator_refresh.py — Daily refresh of active incubator universe.

Run daily on trading days (8:15 AM). Updates scores, RVOL, catalysts.
Writes IMPROVED / DEGRADED / STAYED_ACTIVE events.

Usage:
    .venv/bin/python scripts/daily_incubator_refresh.py --dry-run
    .venv/bin/python scripts/daily_incubator_refresh.py --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

log = logging.getLogger("daily_incubator_refresh")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ACTIVE_INCUBATOR_QUERY = """
SELECT id, symbol, strategy_id, baseline_score, latest_score, best_score,
       rvol_baseline, rvol_latest, gap_latest,
       catalyst, catalyst_verified, days_active, status
FROM incubator_universe
WHERE status = 'ACTIVE'
ORDER BY symbol
"""

LATEST_SCAN_QUERY = """
SELECT s.score, s.rvol, s.gap_pct, s.catalyst, s.catalyst_verified,
       s.decision, s.grade, s.run_type, s.scanned_at
FROM trade_ai_scans s
WHERE s.symbol = %s
ORDER BY s.scanned_at DESC
LIMIT 1
"""

UPDATE_INCUBATOR = """
UPDATE incubator_universe SET
    latest_score = %s,
    score_delta = %s - baseline_score,
    best_score = GREATEST(COALESCE(best_score, 0), %s),
    rvol_latest = %s,
    gap_latest = %s,
    catalyst = %s,
    catalyst_verified = %s,
    days_active = days_active + 1,
    last_seen_at = NOW(),
    updated_at = NOW()
WHERE id = %s
"""

EVENT_INSERT = """
INSERT INTO incubator_events (symbol, strategy_id, event_type, reason_codes, old_score, new_score, payload)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def determine_event(inc, scan):
    """Determine event type based on score/rvol/catalyst changes."""
    old_score = float(inc.get("latest_score") or inc.get("baseline_score") or 0)
    new_score = float(scan.get("score") or 0)
    score_delta = new_score - float(inc.get("baseline_score") or 0)

    old_rvol = float(inc.get("rvol_latest") or inc.get("rvol_baseline") or 0)
    new_rvol = float(scan.get("rvol") or 0)
    rvol_change_pct = ((new_rvol - old_rvol) / old_rvol * 100) if old_rvol > 0 else 0

    old_catalyst_verified = inc.get("catalyst_verified") or False
    new_catalyst_verified = scan.get("catalyst_verified") or False

    reasons = []

    # Check IMPROVED conditions
    if score_delta >= 5:
        reasons.append(f"score_improved_by_{score_delta:.1f}")
    if not old_catalyst_verified and new_catalyst_verified:
        reasons.append("catalyst_became_verified")
    if rvol_change_pct > 50:
        reasons.append(f"rvol_increased_{rvol_change_pct:.0f}pct")

    if reasons:
        return "IMPROVED", reasons

    # Check DEGRADED conditions
    reasons = []
    if score_delta <= -5:
        reasons.append(f"score_dropped_by_{abs(score_delta):.1f}")
    if old_catalyst_verified and not new_catalyst_verified:
        reasons.append("catalyst_stale")
    if old_rvol > 0 and rvol_change_pct < -50:
        reasons.append(f"rvol_collapsed_{abs(rvol_change_pct):.0f}pct")

    if reasons:
        return "DEGRADED", reasons

    return "STAYED_ACTIVE", ["no_significant_change"]


def refresh_ticker(conn, inc, dry_run=False):
    """Refresh a single incubator entry with latest scan data."""
    symbol = inc["symbol"]
    strategy_id = inc.get("strategy_id") or ""

    cur = conn.cursor()
    cur.execute(LATEST_SCAN_QUERY, [symbol])
    row = cur.fetchone()

    if not row:
        log.debug("No recent scan data for %s — skipping", symbol)
        return "no_data"

    cols = [d[0] for d in cur.description]
    scan = dict(zip(cols, row))

    new_score = float(scan.get("score") or 0)
    new_rvol = float(scan.get("rvol") or 0)
    new_gap = float(scan.get("gap_pct") or 0)
    new_catalyst = scan.get("catalyst")
    new_catalyst_verified = scan.get("catalyst_verified")

    event_type, reason_codes = determine_event(inc, scan)
    old_score = float(inc.get("latest_score") or inc.get("baseline_score") or 0)

    if dry_run:
        log.info("[DRY-RUN] %s %s score=%.1f->%.1f rvol=%.1f event=%s reasons=%s",
                 symbol, strategy_id, old_score, new_score, new_rvol,
                 event_type, reason_codes)
        return event_type.lower()

    # Update incubator_universe
    cur.execute(UPDATE_INCUBATOR, [
        new_score, new_score, new_score,
        new_rvol, new_gap,
        new_catalyst, new_catalyst_verified,
        inc["id"],
    ])

    # Write event
    payload = {
        "old_score": old_score,
        "new_score": new_score,
        "old_rvol": float(inc.get("rvol_latest") or 0),
        "new_rvol": new_rvol,
        "scan_source": scan.get("run_type"),
        "scanned_at": str(scan.get("scanned_at")),
    }
    cur.execute(EVENT_INSERT, [
        symbol, strategy_id, event_type,
        json.dumps(reason_codes),
        old_score, new_score,
        json.dumps(payload),
    ])

    return event_type.lower()


def _ensure_conn(conn):
    """Return conn if still open, else a fresh connection.

    The catalyst-refresh loop makes slow network calls (up to 30 symbols × 7 news
    providers) while the scan-refresh transaction is held open. The server's idle
    guard can terminate that held-open connection, so the final commit() raised
    `psycopg2.InterfaceError: connection already closed`. Reconnect on demand.
    """
    try:
        if conn is not None and not conn.closed:
            return conn
    except Exception:
        pass
    return get_conn()


def main():
    parser = argparse.ArgumentParser(description="Daily incubator refresh")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        log.error("Must specify --dry-run or --apply")
        sys.exit(1)

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(ACTIVE_INCUBATOR_QUERY)
        cols = [d[0] for d in cur.description]
        active = [dict(zip(cols, row)) for row in cur.fetchall()]
        log.info("Found %d active incubator entries to refresh", len(active))

        counts = {"improved": 0, "degraded": 0, "stayed_active": 0, "no_data": 0}

        for inc in active:
            result = refresh_ticker(conn, inc, dry_run=args.dry_run)
            counts[result] = counts.get(result, 0) + 1

        # Commit the scan-refresh work BEFORE the slow catalyst HTTP loop, so the
        # transaction isn't held open (idle-in-transaction) across minutes of network
        # calls — that held-open transaction is what the server's idle guard killed.
        if args.apply:
            conn.commit()
            log.info("Committed scan-refresh changes")

        # ── Catalyst refresh for stale incubator symbols ──
        # Symbols with no scan in 3+ days get fresh catalyst enrichment
        catalyst_refreshed = 0
        try:
            from catalyst_enrichment import enrich_ticker
            cur.execute("""
                SELECT symbol, id, latest_score FROM (
                    SELECT DISTINCT ON (iu.symbol) iu.symbol, iu.id, iu.latest_score
                    FROM incubator_universe iu
                    WHERE iu.status = 'ACTIVE'
                      AND iu.latest_score >= 35
                      AND NOT EXISTS (
                          SELECT 1 FROM trade_ai_scans s
                          WHERE s.symbol = iu.symbol
                          AND s.scanned_at > NOW() - INTERVAL '3 days'
                      )
                    ORDER BY iu.symbol, iu.latest_score DESC
                ) sub
                ORDER BY latest_score DESC
                LIMIT 30
            """)
            stale_symbols = cur.fetchall()
            log.info("Found %d incubator symbols with stale catalyst (no scan in 3d)", len(stale_symbols))

            for row in stale_symbols:
                sym, inc_id = row[0], row[1]
                if args.dry_run:
                    log.info("[DRY-RUN] Would refresh catalyst for %s", sym)
                    catalyst_refreshed += 1
                    continue
                try:
                    result = enrich_ticker(sym)
                    if result.get("has_fresh_catalyst"):
                        # enrich_ticker makes slow HTTP calls (7 news providers); the
                        # server idle-guard can close our connection mid-loop. Reconnect
                        # and grab a fresh cursor before each write so the update isn't lost.
                        conn = _ensure_conn(conn)
                        cur = conn.cursor()
                        cur.execute("""
                            UPDATE incubator_universe
                            SET catalyst = %s, catalyst_verified = %s, updated_at = NOW()
                            WHERE id = %s
                        """, [
                            result.get("catalyst_summary", "")[:500],
                            result.get("catalyst_verified", False),
                            inc_id,
                        ])
                        catalyst_refreshed += 1
                        log.info("  Catalyst refreshed: %s verified=%s",
                                 sym, result.get("catalyst_verified"))
                except Exception as e:
                    log.warning("  Catalyst refresh failed for %s: %s", sym, e)
        except ImportError:
            log.warning("catalyst_enrichment not available — skipping catalyst refresh")
        except Exception as e:
            log.warning("Catalyst refresh pass failed: %s", e)

        # Reconnect if the server idle-guard closed the connection during the slow
        # catalyst HTTP loop, then commit the catalyst updates.
        conn = _ensure_conn(conn)
        if args.apply:
            conn.commit()
            log.info("Committed catalyst-refresh changes")
        else:
            conn.rollback()

        log.info("=== SUMMARY ===")
        log.info("Improved:           %d", counts["improved"])
        log.info("Degraded:           %d", counts["degraded"])
        log.info("Stayed active:      %d", counts["stayed_active"])
        log.info("No data:            %d", counts["no_data"])
        log.info("Catalyst refreshed: %d", catalyst_refreshed)
        log.info("Total processed:    %d", len(active))
        log.info("Mode:               %s", "DRY-RUN" if args.dry_run else "APPLIED")

    except Exception:
        conn.rollback()
        log.exception("daily_incubator_refresh failed")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    with PipelineRun("daily_incubator_refresh") as _run:
        main()

