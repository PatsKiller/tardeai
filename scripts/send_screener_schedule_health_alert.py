#!/usr/bin/env python3
"""send_screener_schedule_health_alert.py — Send Telegram alert on screener schedule health.

Default: dry-run. Use --send for delivery. No trades. No orders.

OPS-HYGIENE-1 routing:
  - P0_INTERRUPT  : schedule failure blocks actionable opportunity discovery
  - P1_DIGEST     : routine health / some stale screeners
  - P3_LOG_ONLY   : all screeners healthy

Usage:
    .venv/bin/python scripts/send_screener_schedule_health_alert.py --dry-run --verbose
    .venv/bin/python scripts/send_screener_schedule_health_alert.py --send --verbose
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# ── Schedule classification (shared with arch5 baseline) ─────────────────────

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

_FRESHNESS_THRESHOLDS = {
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


def _is_stale(last_run, session: str, now: datetime) -> bool:
    if last_run is None:
        return True
    if not hasattr(last_run, "tzinfo") or last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    threshold = _FRESHNESS_THRESHOLDS.get(session, 24)
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


def _build_alert_message(stale_screeners: list, total_active: int, now: datetime) -> str:
    """Build a Telegram-formatted alert message."""
    lines = [
        f"*Screener Schedule Health*  ({now.strftime('%Y-%m-%d %H:%M')} UTC)",
        "",
        f"Active: {total_active}  |  Stale: {len(stale_screeners)}",
        "",
    ]
    if stale_screeners:
        lines.append("Stale screeners:")
        for s in stale_screeners[:10]:  # cap to avoid Telegram length issues
            last = s.get("last_run", "never")
            lines.append(f"  - {s['display_name']} (id={s['screener_id']}, sched={s['schedule']}, last={last})")
        if len(stale_screeners) > 10:
            lines.append(f"  ... and {len(stale_screeners) - 10} more")
    else:
        lines.append("All screeners are fresh. No action required.")
    return "\n".join(lines)


def _determine_priority(stale_screeners: list, total_active: int) -> str:
    """Determine alert priority using OPS-HYGIENE-1 logic.

    P0: schedule failure blocks actionable opportunity discovery
        (majority of daily screeners stale = opportunity discovery blocked)
    P1: routine health / some stale
    P3: all healthy
    """
    if not stale_screeners:
        return "P3_LOG_ONLY"

    # Count how many intraday/after_close screeners are stale (these block opportunity discovery)
    daily_stale = sum(1 for s in stale_screeners if s.get("session") in ("intraday", "after_close"))
    # If more than half of active screeners are stale AND daily session screeners affected -> P0
    if daily_stale >= 3 or (total_active > 0 and len(stale_screeners) / total_active > 0.5):
        return "P0_INTERRUPT"

    return "P1_DIGEST"


def main():
    p = argparse.ArgumentParser(description="Send screener schedule health alert (default: dry-run)")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Report only, no Telegram send (default)")
    p.add_argument("--send", action="store_true",
                   help="Actually send Telegram alert if warranted")
    p.add_argument("--output-json", type=str, help="Write JSON report to path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.send:
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
    conn.close()

    total_active = len(rows)
    stale_screeners = []

    for r in rows:
        session = _classify_session(r.get("schedule"))
        if _is_stale(r.get("last_run"), session, now):
            stale_screeners.append({
                "screener_id":  r.get("screener_id"),
                "display_name": r.get("display_name"),
                "schedule":     r.get("schedule"),
                "session":      session,
                "last_run":     str(r.get("last_run")) if r.get("last_run") else None,
            })

    message = _build_alert_message(stale_screeners, total_active, now)
    priority = _determine_priority(stale_screeners, total_active)

    # ── Router gate ──────────────────────────────────────────────────────────
    from telegram_alert_router import classify_alert, should_send_telegram

    # Use classify_alert for the message, but override with our OPS-HYGIENE-1 logic
    router_level = classify_alert(message)
    effective_level = priority  # our OPS-HYGIENE-1 classification takes precedence
    should_send = should_send_telegram(message) if effective_level != "P3_LOG_ONLY" else False

    # For P0, always allow send (override router dedupe)
    if effective_level == "P0_INTERRUPT":
        should_send = True

    sent = False
    if not args.dry_run and should_send:
        try:
            # send_telegram, NOT send_alert -- `send_alert` has never existed in
            # telegram_alert.py. `sent` also used to be set unconditionally after the
            # call, so it claimed delivery it never checked; take the return value.
            from telegram_alert import send_telegram
            sent = bool(send_telegram(message))
            if not sent:
                print(f"  WARN: Telegram send returned False — alert NOT delivered")
        except Exception as e:
            # Reported regardless of --verbose: a health alert that failed to send is
            # exactly the case a quiet run must not hide.
            print(f"  WARN: Telegram send failed ({type(e).__name__}: {e}) — alert NOT delivered")

    report = {
        "generated_at":    now.isoformat(),
        "mode":            "SEND" if not args.dry_run else "DRY-RUN",
        "total_active":    total_active,
        "stale_count":     len(stale_screeners),
        "stale_screeners": stale_screeners,
        "priority":        effective_level,
        "router_level":    router_level,
        "should_send":     should_send,
        "sent":            sent,
        "message":         message,
    }

    # ── Verbose output ───────────────────────────────────────────────────────
    if args.verbose:
        mode = report["mode"]
        print(f"SCREENER-SCHEDULE-HEALTH-ALERT  mode={mode}")
        print(f"  total_active:  {total_active}")
        print(f"  stale_count:   {len(stale_screeners)}")
        print(f"  priority:      {effective_level}")
        print(f"  router_level:  {router_level}")
        print(f"  should_send:   {should_send}")
        print(f"  sent:          {sent}")
        if stale_screeners:
            print("  stale screeners:")
            for s in stale_screeners:
                print(f"    {s['screener_id']:6}  {s['display_name']!s:40s}  "
                      f"last_run={s['last_run']}")
        print("  message preview:")
        for line in message.split("\n"):
            print(f"    | {line}")

    # ── JSON output ──────────────────────────────────────────────────────────
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    # ── Markdown output ──────────────────────────────────────────────────────
    if args.output_md:
        md = [
            "# Screener Schedule Health Alert\n",
            f"Generated: {now.isoformat()}  |  Mode: {report['mode']}\n",
            "## Summary",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total active | {total_active} |",
            f"| Stale count | {len(stale_screeners)} |",
            f"| Priority | {effective_level} |",
            f"| Should send | {should_send} |",
            f"| Sent | {sent} |",
        ]
        if stale_screeners:
            md += ["", "## Stale Screeners",
                   "| ID | Name | Schedule | Session | Last Run |",
                   "|----|------|----------|---------|----------|"]
            for s in stale_screeners:
                md.append(f"| {s['screener_id']} | {s['display_name']} | "
                          f"{s['schedule']} | {s['session']} | {s['last_run']} |")
        md += ["", "## Alert Message", "```", message, "```", ""]

        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    print(f"Health alert: {report['mode']} | {len(stale_screeners)} stale, "
          f"priority={effective_level}, sent={sent}")


if __name__ == "__main__":
    main()
