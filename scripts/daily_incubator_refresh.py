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

def get_conn():
    # Shared session13_db currently imports the entire dotenv. Keep that
    # import behind the real-run boundary; the integrator owns narrowing it.
    from session13_db import get_conn as connect
    return connect()

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


def _conn_closed(conn) -> bool:
    try:
        return conn is None or bool(conn.closed)
    except Exception:
        return True


def _ensure_conn_checked(conn):
    """(connection, reopened): ``_ensure_conn`` plus whether it had to open a new one."""
    if not _conn_closed(conn):
        return conn, False
    return _ensure_conn(conn), True


def _safe_rollback(conn) -> None:
    """rollback() only on an open connection; a failure here is logged, never raised over the original error."""
    if _conn_closed(conn):
        log.warning("rollback skipped: connection already closed")
        return
    try:
        conn.rollback()
    except Exception as exc:  # noqa: BLE001
        log.warning("rollback failed after the error above: %s: %s", type(exc).__name__, exc)


def _safe_close(conn) -> None:
    if _conn_closed(conn):
        return
    try:
        conn.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("close failed: %s: %s", type(exc).__name__, exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Daily incubator refresh", allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    args = parser.parse_args(argv)

    if args.dry_run:
        print("DRY-RUN daily-incubator-refresh: would refresh active scan scores, record incubator events,"
              " refresh up to 30 stale catalysts and write lane receipt; counts NOT_MEASURED")
        return 0

    if not args.dry_run and not args.apply:
        log.error("Must specify --dry-run or --apply")
        sys.exit(1)

    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        counts = _run(args)
    except (Exception, SystemExit) as exc:
        rc = exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) else 1
        write_lane_receipt("daily-incubator-refresh", ok=False, exit_code=rc,
                           started_at=started, script="daily_incubator_refresh.py", error=type(exc).__name__,
                           output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    write_lane_receipt("daily-incubator-refresh", ok=True, exit_code=0, started_at=started,
                       script="daily_incubator_refresh.py", summary=counts, output=lane_output(counts))
    return 0


def lane_output(counts: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: incubator_events rows, one per active entry with
    fresh scan data). attempted = active entries; an entry without recent scan data is a typed skip; nothing to
    refresh = ``no_new_input``."""
    processed, no_data = int(counts.get("processed") or 0), int(counts.get("no_data") or 0)
    produced = max(processed - no_data, 0)
    return {"produced_count": produced, "attempted_count": processed, "skipped_reasons": {"no_scan_data": no_data},
            "empty_reason": "no_new_input" if produced == 0 else None}


def _run(args):
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
        # 2026-10-16: the scan-refresh loop itself can outlive the idle guard. Re-check the connection before this
        # commit too; a closed one means the loop's uncommitted rows are gone, so say so instead of crashing on
        # commit() (the 08:15 ET live run died here and the except handler's rollback() masked the real error).
        conn, reopened = _ensure_conn_checked(conn)
        if reopened:
            counts["scan_refresh_lost"] = len(active)
            log.error("connection closed before the scan-refresh commit: %d entries' uncommitted rows were lost; "
                      "reconnected for the catalyst pass", len(active))
        cur = conn.cursor()
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
        return {**counts, "processed": len(active), "catalyst_refreshed": catalyst_refreshed}

    except Exception:
        # Log the ORIGINAL exception first: a rollback() on a connection the server already closed raises
        # psycopg2.InterfaceError and used to replace the real error in the log (2026-10-16 08:15 ET).
        log.exception("daily_incubator_refresh failed")
        _safe_rollback(conn)
        sys.exit(1)
    finally:
        _safe_close(conn)


def cli(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    # Validate before telemetry imports (which otherwise read .env on import).
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(raw)
    if args.dry_run:
        return main(raw)
    try:
        from pipeline_registry import PipelineRun
    except ImportError:
        return main(raw)
    with PipelineRun("daily_incubator_refresh"):
        return main(raw)


if __name__ == "__main__":
    raise SystemExit(cli())

