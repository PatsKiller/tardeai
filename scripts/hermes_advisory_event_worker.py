#!/usr/bin/env python3
"""Hermes Advisory Event Worker — dry-run consumer.

Usage:
    python scripts/hermes_advisory_event_worker.py [--apply]

Default: dry-run (reads events, logs intended action, no writes).
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
OUT = PR / "docs" / "hermes" / "phase44_bridge_worker_dryrun"
OUT.mkdir(parents=True, exist_ok=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    dry = not args.apply

    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
    cur = conn.cursor()

    cur.execute("SELECT id, event_type, source_table, source_id, priority, created_at FROM hermes_advisory_events WHERE event_status='pending' ORDER BY created_at LIMIT %s", (args.limit,))
    events = cur.fetchall()

    results = []
    for eid, etype, stbl, sid, pri, cat in events:
        now = datetime.now(timezone.utc)
        lat = int((now - cat.replace(tzinfo=timezone.utc if cat.tzinfo is None else cat.tzinfo)).total_seconds() * 1000)
        action = f"Would refresh advisory context for {stbl} id={sid} (type={etype})"
        results.append({"event_id": eid, "action": action, "latency_ms": lat, "dry_run": dry})
        print(f"  {'[DRY]' if dry else '[APPLY]'} event={eid} {etype} {stbl}:{sid} latency={lat}ms")

        if not dry:
            cur.execute("UPDATE hermes_advisory_events SET event_status='completed', processed_at=NOW(), latency_ms=%s WHERE id=%s", (lat, eid))
            conn.commit()

    (OUT / "worker_dryrun_results.json").write_text(json.dumps(results, indent=2, default=str))
    summary = f"# Bridge Worker Dry-Run — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\nEvents: {len(events)}\nMode: {'DRY-RUN' if dry else 'APPLY'}\n"
    for r in results:
        summary += f"\n- event={r['event_id']} latency={r['latency_ms']}ms {'(dry)' if r['dry_run'] else '(applied)'}"
    (OUT / "worker_dryrun_summary.md").write_text(summary)

    cur.close(); conn.close()
    print(f"\n{'DRY-RUN' if dry else 'APPLY'}: {len(events)} events processed. DB writes: {'0' if dry else str(len(events))}")

if __name__ == "__main__":
    main()
