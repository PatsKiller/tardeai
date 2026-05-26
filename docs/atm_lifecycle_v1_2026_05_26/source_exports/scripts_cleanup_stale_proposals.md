# Source Export: scripts/cleanup_stale_proposals.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/cleanup_stale_proposals.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `ee310f7aab9c3cf1cf369a7813605c8aeaedb45eec2ac720ed56c838665d5728` |
| **File Size** | 3570 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""cleanup_stale_proposals.py — Reject stale/blocked paper proposals during market hours.

Rejects proposals that are:
- PENDING/APPROVED older than 24 hours
- BLOCKED for more than 4 hours
- MISSING_DATA for more than 48 hours

PAPER ONLY. Does not touch broker, execution, or holdings.

Usage:
    .venv/bin/python scripts/cleanup_stale_proposals.py --dry-run
    .venv/bin/python scripts/cleanup_stale_proposals.py --apply
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [cleanup] {msg}", flush=True)

def main():
    p = argparse.ArgumentParser(description="Reject stale/blocked paper proposals")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Find stale proposals
    cur.execute("""
        SELECT id, symbol, status, action_state, created_at, NOW() - created_at AS age
        FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        ORDER BY created_at
    """)
    stale = cur.fetchall()

    if not stale:
        log("No stale proposals to clean up.")
        conn.close()
        return

    log(f"Found {len(stale)} stale proposals:")
    for row in stale:
        pid, sym, status, action, created, age = row
        reason = "blocked" if action == "BLOCKED" else ("missing_data" if action == "MISSING_DATA" else "stale_24h")
        log(f"  #{pid} {sym} [{status}/{action}] age={age} → {reason}")

    if args.dry_run:
        log("DRY RUN — no changes made.")
        conn.close()
        return

    cur.execute("""
        UPDATE paper_trade_proposals
        SET status = 'REJECTED',
            action_state = 'REJECTED',
            action_label = CASE
              WHEN action_state = 'BLOCKED' THEN 'Auto-rejected: blocked and stale'
              WHEN action_state = 'MISSING_DATA' THEN 'Auto-rejected: missing data and stale'
              ELSE 'Auto-rejected: older than 24h'
            END,
            updated_at = NOW()
        WHERE status IN ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
          AND (
            created_at < NOW() - INTERVAL '24 hours'
            OR (action_state = 'BLOCKED' AND created_at < NOW() - INTERVAL '4 hours')
            OR (action_state = 'MISSING_DATA' AND created_at < NOW() - INTERVAL '48 hours')
          )
        RETURNING id, symbol
    """)
    rejected = cur.fetchall()
    conn.commit()
    conn.close()

    log(f"Rejected {len(rejected)} stale proposals.")
    for pid, sym in rejected:
        log(f"  #{pid} {sym}")

if __name__ == "__main__":
    main()
```
