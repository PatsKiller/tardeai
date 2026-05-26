# Source Export: scripts/run_agent_queue_health.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_agent_queue_health.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `d310a11177b813853e39978ec48b82908b6a2be99813ebb898a261c0469553cc` |
| **File Size** | 4895 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""run_agent_queue_health.py — Agent queue health report.

Reports queue stats, throughput, stuck jobs, and backlog ETA.
Default: read-only. No mutations.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def main():
    p = argparse.ArgumentParser(description="Agent queue health report")
    p.add_argument("--reset-stuck", action="store_true", help="Reset stuck processing jobs to queued")
    p.add_argument("--stuck-threshold-minutes", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)
    cur = conn.cursor()

    # Queue stats
    cur.execute("SELECT status, COUNT(*) FROM watchlist_agent_jobs GROUP BY status ORDER BY count DESC")
    stats = {r[0]: r[1] for r in cur.fetchall()}

    # Stuck processing
    cur.execute(f"""SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE status='processing' AND started_at < NOW() - INTERVAL '{args.stuck_threshold_minutes} minutes'""")
    stuck_count = cur.fetchone()[0]

    # Throughput (last 24h)
    cur.execute("""SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE status='completed' AND completed_at > NOW() - INTERVAL '24 hours'""")
    throughput_24h = cur.fetchone()[0]

    # Throughput (last 7d avg)
    cur.execute("""SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE status='completed' AND completed_at > NOW() - INTERVAL '7 days'""")
    throughput_7d = cur.fetchone()[0]
    avg_daily = throughput_7d / 7

    # Backlog ETA
    queued = stats.get("queued", 0) + stats.get("pending", 0)
    eta_days = queued / avg_daily if avg_daily > 0 else float("inf")

    # Last completion
    cur.execute("SELECT MAX(completed_at) FROM watchlist_agent_jobs WHERE status='completed'")
    last_completed = cur.fetchone()[0]

    # Failure rate (last 24h)
    cur.execute("""SELECT COUNT(*) FROM watchlist_agent_jobs
        WHERE status='failed' AND completed_at > NOW() - INTERVAL '24 hours'""")
    failures_24h = cur.fetchone()[0]

    # Reset stuck if requested
    reset_count = 0
    if args.reset_stuck and stuck_count > 0:
        cur.execute(f"""UPDATE watchlist_agent_jobs SET status='queued', started_at=NULL
            WHERE status='processing' AND started_at < NOW() - INTERVAL '{args.stuck_threshold_minutes} minutes'""")
        reset_count = cur.rowcount
        conn.commit()

    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queue_stats": stats,
        "stuck_processing": stuck_count,
        "throughput_24h": throughput_24h,
        "avg_daily_7d": round(avg_daily, 1),
        "backlog_queued": queued,
        "backlog_eta_days": round(eta_days, 1),
        "last_completed": str(last_completed) if last_completed else None,
        "failures_24h": failures_24h,
        "reset_count": reset_count,
        "health": "healthy" if stuck_count < 10 and throughput_24h > 50 else "degraded" if throughput_24h > 0 else "stalled",
    }

    if args.verbose:
        print(f"Agent Queue Health: {report['health'].upper()}")
        for k, v in stats.items():
            print(f"  {k:20s} {v}")
        print(f"  Stuck (>{args.stuck_threshold_minutes}m): {stuck_count}")
        print(f"  Throughput 24h: {throughput_24h} | Avg daily (7d): {avg_daily:.0f}")
        print(f"  Backlog: {queued} jobs | ETA: {eta_days:.1f} days")
        print(f"  Last completed: {last_completed}")
        if reset_count:
            print(f"  Reset {reset_count} stuck jobs")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Agent Queue Health: {report['health'].upper()}\n"]
        md.append(f"| Metric | Value |")
        md.append(f"|--------|-------|")
        for k, v in stats.items():
            md.append(f"| {k} | {v} |")
        md.append(f"| stuck (>{args.stuck_threshold_minutes}m) | {stuck_count} |")
        md.append(f"| throughput 24h | {throughput_24h} |")
        md.append(f"| avg daily (7d) | {avg_daily:.0f} |")
        md.append(f"| backlog ETA | {eta_days:.1f} days |")
        md.append(f"| failures 24h | {failures_24h} |")
        if reset_count:
            md.append(f"\nReset {reset_count} stuck jobs to queued.")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
