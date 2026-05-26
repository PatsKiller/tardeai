# Source Export: scripts/report_screener_arch5_schedule_baseline.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/report_screener_arch5_schedule_baseline.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `e2b000dbd9240f572dee76d9bed8d385bc6c6d09c227eb607faebbf245486ae3` |
| **File Size** | 10157 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""report_screener_arch5_schedule_baseline.py — Schedule & freshness baseline for active screeners.

Read-only audit. No trades. No orders.

Usage:
    .venv/bin/python scripts/report_screener_arch5_schedule_baseline.py --verbose
    .venv/bin/python scripts/report_screener_arch5_schedule_baseline.py --since-days 7 --output-json /tmp/arch5.json
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# ── Schedule classification ─────────────────────────────────────────────────

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

# Maximum age (hours) before a screener is considered stale
_FRESHNESS_THRESHOLDS = {
    "intraday":    24,
    "after_close": 24,
    "weekly":      8 * 24,     # 8 days
    "biweekly":    16 * 24,    # 16 days
    "monthly":     35 * 24,    # 35 days
    "unknown":     24,
}


def _classify_session(schedule: str) -> str:
    if not schedule:
        return "unknown"
    return _SESSION_MAP.get(schedule.strip().lower(), "unknown")


def _expected_cadence(session: str) -> str:
    return {
        "intraday":    "daily",
        "after_close": "daily",
        "weekly":      "weekly",
        "biweekly":    "biweekly",
        "monthly":     "monthly",
        "unknown":     "unknown",
    }.get(session, "unknown")


def _is_stale(last_run, session: str, now: datetime) -> bool:
    if last_run is None:
        return True
    if not hasattr(last_run, "tzinfo") or last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    threshold_h = _FRESHNESS_THRESHOLDS.get(session, 24)
    return (now - last_run) > timedelta(hours=threshold_h)


def _q(conn, sql, params=None, fetch="all"):
    cur = conn.cursor()
    cur.execute(sql, params or [])
    if fetch == "one":
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else {}
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def main():
    p = argparse.ArgumentParser(description="ARCH-5 screener schedule baseline (read-only)")
    p.add_argument("--since-days", type=int, default=14,
                   help="Look-back window for freshness analysis (default: 14)")
    p.add_argument("--output-json", type=str, help="Write JSON report to path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection"); sys.exit(1)

    rows = _q(conn, """
        SELECT screener_id, display_name, strategy_type, schedule, active,
               last_run, results_count
        FROM finviz_screeners
        WHERE active = TRUE
        ORDER BY screener_id
    """)
    conn.close()

    now = datetime.now(timezone.utc)
    screeners = []
    stale_list = []
    session_counts: dict[str, int] = {}

    for r in rows:
        session = _classify_session(r.get("schedule"))
        cadence = _expected_cadence(session)
        stale = _is_stale(r.get("last_run"), session, now)

        entry = {
            "screener_id":    r.get("screener_id"),
            "display_name":   r.get("display_name"),
            "strategy_type":  r.get("strategy_type"),
            "schedule":       r.get("schedule"),
            "market_session": session,
            "expected_cadence": cadence,
            "last_run":       str(r.get("last_run")) if r.get("last_run") else None,
            "results_count":  r.get("results_count"),
            "stale":          stale,
        }
        screeners.append(entry)
        session_counts[session] = session_counts.get(session, 0) + 1
        if stale:
            stale_list.append(entry)

    # ── Coverage gap detection ───────────────────────────────────────────────
    expected_sessions = {"intraday", "after_close", "weekly"}
    present_sessions = set(session_counts.keys()) - {"unknown"}
    coverage_gaps = sorted(expected_sessions - present_sessions)
    # Also flag if premarket or overnight are completely absent
    if "premarket" not in present_sessions:
        coverage_gaps.append("premarket (no screener)")
    if "overnight" not in present_sessions:
        coverage_gaps.append("overnight (no screener)")

    # ── Recommendations ──────────────────────────────────────────────────────
    recommendations = []
    if stale_list:
        recommendations.append(
            f"{len(stale_list)} screener(s) stale — investigate last_run timestamps and cron schedules."
        )
    if "unknown" in session_counts:
        recommendations.append(
            f"{session_counts['unknown']} screener(s) have unrecognised schedule values — normalise to known cadences."
        )
    if coverage_gaps:
        recommendations.append(
            f"Coverage gaps detected: {', '.join(coverage_gaps)}. Consider adding screeners for missing sessions."
        )
    if not recommendations:
        recommendations.append("All screeners healthy. No action required.")

    report = {
        "generated_at":     now.isoformat(),
        "since_days":       args.since_days,
        "total_active":     len(screeners),
        "by_session":       session_counts,
        "stale_count":      len(stale_list),
        "stale_screeners":  stale_list,
        "coverage_gaps":    coverage_gaps,
        "recommendations":  recommendations,
        "screeners":        screeners,
    }

    # ── Verbose output ───────────────────────────────────────────────────────
    if args.verbose:
        print("SCREENER-ARCH-5 Schedule Baseline")
        print(f"  total_active:  {report['total_active']}")
        print(f"  by_session:    {report['by_session']}")
        print(f"  stale_count:   {report['stale_count']}")
        if stale_list:
            print("  stale screeners:")
            for s in stale_list:
                print(f"    {s['screener_id']:6}  {s['display_name']!s:40s}  last_run={s['last_run']}")
        if coverage_gaps:
            print(f"  coverage_gaps: {coverage_gaps}")
        print("  recommendations:")
        for rec in recommendations:
            print(f"    - {rec}")
        print("  screener details:")
        for s in screeners:
            flag = " STALE" if s["stale"] else ""
            print(f"    {s['screener_id']:6}  {s['display_name']!s:40s}  "
                  f"sched={s['schedule']!s:25s}  session={s['market_session']:12s}  "
                  f"results={s['results_count']!s:6s}{flag}")

    # ── JSON output ──────────────────────────────────────────────────────────
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    # ── Markdown output ──────────────────────────────────────────────────────
    if args.output_md:
        md = [
            "# SCREENER-ARCH-5 Schedule Baseline\n",
            f"Generated: {now.isoformat()}  |  Look-back: {args.since_days} days\n",
            "## Summary",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total active | {report['total_active']} |",
            f"| Stale count  | {report['stale_count']} |",
            "",
            "## By Session",
            "| Session | Count |",
            "|---------|-------|",
        ]
        for sess, cnt in sorted(session_counts.items()):
            md.append(f"| {sess} | {cnt} |")

        if stale_list:
            md += ["", "## Stale Screeners",
                   "| ID | Name | Schedule | Last Run |",
                   "|----|------|----------|----------|"]
            for s in stale_list:
                md.append(f"| {s['screener_id']} | {s['display_name']} | {s['schedule']} | {s['last_run']} |")

        if coverage_gaps:
            md += ["", "## Coverage Gaps"]
            for g in coverage_gaps:
                md.append(f"- {g}")

        md += ["", "## Recommendations"]
        for rec in recommendations:
            md.append(f"- {rec}")

        md += ["", "## All Screeners",
               "| ID | Name | Schedule | Session | Cadence | Results | Stale |",
               "|----|------|----------|---------|---------|---------|-------|"]
        for s in screeners:
            md.append(f"| {s['screener_id']} | {s['display_name']} | {s['schedule']} | "
                      f"{s['market_session']} | {s['expected_cadence']} | {s['results_count']} | "
                      f"{'YES' if s['stale'] else 'no'} |")
        md.append("")

        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    print(f"ARCH-5 baseline: {report['total_active']} active, {report['stale_count']} stale, "
          f"{len(coverage_gaps)} gap(s)")


if __name__ == "__main__":
    main()
```
