# Source Export: scripts/remediate_stale_screeners_arch5.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/remediate_stale_screeners_arch5.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c25d5f956d726574d3d0f13e9eb922a2a83073e8bca1cdb3ec977d0d6ec2225c` |
| **File Size** | 11037 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""remediate_stale_screeners_arch5.py — Detect and tag stale screener metadata.

Default: dry-run (report only). Use --apply to write metadata updates.
Never changes screener criteria or strategy YAML. Schedule metadata only.
Read-only audit in dry-run. No trades. No orders.

Usage:
    .venv/bin/python scripts/remediate_stale_screeners_arch5.py --verbose
    .venv/bin/python scripts/remediate_stale_screeners_arch5.py --stale-hours 48 --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# ── Schedule-aware freshness thresholds (hours) ─────────────────────────────

_SESSION_MAP = {
    "daily_1000_1600": "intraday",
    "daily":           "intraday",
    "daily_1600":      "after_close",
    "weekly":          "weekly",
    "weekly_sun_1000": "weekly",
    "weekly_wed_1000": "weekly",
    "weekly_mon_1000": "weekly",
    "biweekly":        "biweekly",
    "monthly":         "monthly",
}

_DEFAULT_THRESHOLDS = {
    "intraday":    24,
    "after_close": 24,
    "weekly":      8 * 24,
    "biweekly":    16 * 24,
    "monthly":     35 * 24,
    "unknown":     24,
}


def _classify_session(schedule: str) -> str:
    if not schedule:
        return "unknown"
    return _SESSION_MAP.get(schedule.strip().lower(), "unknown")


def _stale_threshold_hours(session: str, override_hours: int | None) -> int:
    if override_hours is not None:
        return override_hours
    return _DEFAULT_THRESHOLDS.get(session, 24)


def _is_stale(last_run, session: str, now: datetime, override_hours: int | None) -> bool:
    if last_run is None:
        return True
    if not hasattr(last_run, "tzinfo") or last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    threshold = _stale_threshold_hours(session, override_hours)
    return (now - last_run) > timedelta(hours=threshold)


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _has_column(conn, table: str, column: str) -> bool:
    """Check if a column exists on the table (PostgreSQL)."""
    row = _q(conn, """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        LIMIT 1
    """, [table, column], fetch="one")
    return bool(row)


def main():
    p = argparse.ArgumentParser(description="Remediate stale screener metadata (default: dry-run)")
    p.add_argument("--stale-hours", type=int, default=None,
                   help="Override stale threshold (hours). Default: schedule-aware.")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Report only, no DB writes (default)")
    p.add_argument("--apply", action="store_true",
                   help="Apply metadata updates (set last_run_status='stale')")
    p.add_argument("--output-json", type=str, help="Write JSON report to path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    now = datetime.now(timezone.utc)

    rows = _q(conn, """
        SELECT screener_id, display_name, strategy_type, schedule, active,
               last_run, results_count
        FROM finviz_screeners
        WHERE active = TRUE
        ORDER BY screener_id
    """)

    # Check if last_run_status column exists
    has_status_col = _has_column(conn, "finviz_screeners", "last_run_status")

    stale_screeners = []
    orphaned_screeners = []
    missing_session = []

    for r in rows:
        session = _classify_session(r.get("schedule"))
        stale = _is_stale(r.get("last_run"), session, now, args.stale_hours)
        results = r.get("results_count")

        entry = {
            "screener_id":   r.get("screener_id"),
            "display_name":  r.get("display_name"),
            "strategy_type": r.get("strategy_type"),
            "schedule":      r.get("schedule"),
            "session":       session,
            "last_run":      str(r.get("last_run")) if r.get("last_run") else None,
            "results_count": results,
        }

        if stale:
            entry["reason"] = "last_run older than threshold" if r.get("last_run") else "last_run is NULL"
            threshold = _stale_threshold_hours(session, args.stale_hours)
            entry["threshold_hours"] = threshold
            stale_screeners.append(entry)

        # Orphaned: active but no results at all
        if r.get("active") and (results is None or results == 0):
            orphaned_screeners.append(entry)

        # Missing session assignment
        if session == "unknown":
            missing_session.append(entry)

    # ── Apply phase (metadata only) ──────────────────────────────────────────
    applied = []
    if not args.dry_run and stale_screeners and has_status_col:
        for s in stale_screeners:
            try:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE finviz_screeners
                    SET last_run_status = 'stale'
                    WHERE screener_id = %s
                """, [s["screener_id"]])
                applied.append(s["screener_id"])
            except Exception as e:
                if args.verbose:
                    print(f"  WARN: failed to update screener_id={s['screener_id']}: {e}")
        conn.commit()

    conn.close()

    mode = "APPLY" if not args.dry_run else "DRY-RUN"
    report = {
        "generated_at":        now.isoformat(),
        "mode":                mode,
        "stale_hours_override": args.stale_hours,
        "has_status_column":   has_status_col,
        "stale_count":         len(stale_screeners),
        "stale_screeners":     stale_screeners,
        "orphaned_count":      len(orphaned_screeners),
        "orphaned_screeners":  orphaned_screeners,
        "missing_session_count": len(missing_session),
        "missing_session":     missing_session,
        "applied":             applied,
    }

    # ── Verbose output ───────────────────────────────────────────────────────
    if args.verbose:
        print(f"REMEDIATE-STALE-SCREENERS-ARCH5  mode={mode}")
        print(f"  stale_count:          {report['stale_count']}")
        print(f"  orphaned_count:       {report['orphaned_count']}")
        print(f"  missing_session:      {report['missing_session_count']}")
        print(f"  has_status_column:    {has_status_col}")
        if stale_screeners:
            print("  stale screeners:")
            for s in stale_screeners:
                print(f"    {s['screener_id']:6}  {s['display_name']!s:40s}  "
                      f"last_run={s['last_run']}  reason={s['reason']}")
        if orphaned_screeners:
            print("  orphaned screeners (active but 0 results):")
            for s in orphaned_screeners:
                print(f"    {s['screener_id']:6}  {s['display_name']!s:40s}")
        if missing_session:
            print("  missing session assignment:")
            for s in missing_session:
                print(f"    {s['screener_id']:6}  schedule={s['schedule']!s}")
        if applied:
            print(f"  applied updates: {applied}")
        elif not args.dry_run and stale_screeners and not has_status_col:
            print("  WARN: last_run_status column missing — no updates applied. "
                  "Add column: ALTER TABLE finviz_screeners ADD COLUMN last_run_status TEXT;")

    # ── JSON output ──────────────────────────────────────────────────────────
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    # ── Markdown output ──────────────────────────────────────────────────────
    if args.output_md:
        md = [
            "# Remediate Stale Screeners (ARCH-5)\n",
            f"Generated: {now.isoformat()}  |  Mode: {mode}\n",
            "## Summary",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Stale screeners | {report['stale_count']} |",
            f"| Orphaned screeners | {report['orphaned_count']} |",
            f"| Missing session | {report['missing_session_count']} |",
            f"| Status column exists | {has_status_col} |",
            f"| Updates applied | {len(applied)} |",
        ]
        if stale_screeners:
            md += ["", "## Stale Screeners",
                   "| ID | Name | Schedule | Last Run | Reason | Threshold (h) |",
                   "|----|------|----------|----------|--------|----------------|"]
            for s in stale_screeners:
                md.append(f"| {s['screener_id']} | {s['display_name']} | {s['schedule']} | "
                          f"{s['last_run']} | {s['reason']} | {s.get('threshold_hours', '')} |")
        if orphaned_screeners:
            md += ["", "## Orphaned Screeners (active, 0 results)",
                   "| ID | Name | Schedule |",
                   "|----|------|----------|"]
            for s in orphaned_screeners:
                md.append(f"| {s['screener_id']} | {s['display_name']} | {s['schedule']} |")
        if missing_session:
            md += ["", "## Missing Session Assignment",
                   "| ID | Schedule |",
                   "|----|----------|"]
            for s in missing_session:
                md.append(f"| {s['screener_id']} | {s['schedule']} |")
        md.append("")

        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    print(f"ARCH-5 remediate: {mode} | {report['stale_count']} stale, "
          f"{report['orphaned_count']} orphaned, {report['missing_session_count']} missing session, "
          f"{len(applied)} applied")


if __name__ == "__main__":
    main()
```
