# Source Export: scripts/send_alert_digest.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/send_alert_digest.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `777aa0db5383874e773045e0af53110aad34b3d993bf5db45b392ff9b5616b79` |
| **File Size** | 3743 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""send_alert_digest.py — sends morning (8 AM) or evening (4 PM) digest.

Aggregates queued alerts into one consolidated Telegram message.

Usage:
    .venv/bin/python scripts/send_alert_digest.py morning
    .venv/bin/python scripts/send_alert_digest.py evening
    .venv/bin/python scripts/send_alert_digest.py morning --dry-run

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def main(slot, dry_run=False):
    assert slot in ('morning', 'evening'), "Slot must be 'morning' or 'evening'"
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT alert_type, symbol, message, metadata
        FROM digest_queue
        WHERE digest_slot = %s AND sent = FALSE
          AND queued_at > NOW() - INTERVAL '12 hours'
        ORDER BY queued_at ASC
    """, [slot])
    items = cur.fetchall()

    if not items:
        print(f"No items for {slot} digest")
        conn.close()
        return

    # Group by alert_type
    by_type = defaultdict(list)
    for alert_type, symbol, message, metadata in items:
        by_type[alert_type].append({
            'symbol': symbol,
            'message': message,
            'metadata': metadata or {}
        })

    # Build digest
    icon = '\U0001f305' if slot == 'morning' else '\U0001f307'
    lines = [f"{icon} *{slot.upper()} DIGEST* \u2014 {datetime.now().strftime('%H:%M ET')}"]
    lines.append("")

    for alert_type, entries in sorted(by_type.items()):
        symbols = [e['symbol'] for e in entries if e['symbol']]
        unique_symbols = sorted(set(symbols))
        lines.append(f"*{alert_type.replace('_', ' ').title()}* ({len(entries)})")
        if unique_symbols:
            lines.append(f"  Symbols: {', '.join(unique_symbols[:10])}")
        # Show first entry message preview
        if entries[0]['message']:
            preview = entries[0]['message'][:120].replace('\n', ' ')
            lines.append(f"  {preview}")
        lines.append("")

    lines.append(f"Total: {len(items)} items aggregated")
    lines.append("Full detail: https://ms01-openclaw.tail163d14.ts.net/v2/alerts")

    digest_msg = "\n".join(lines)

    if dry_run:
        print(f"=== DRY RUN — {slot} digest ===")
        print(digest_msg)
        print(f"=== {len(items)} items would be marked sent ===")
        conn.close()
        return

    # Send
    try:
        from telegram_alert import send_telegram
        send_telegram(digest_msg)
    except Exception as e:
        print(f"Telegram send failed: {e}")

    # Mark sent
    cur.execute("""
        UPDATE digest_queue SET sent = TRUE, sent_at = NOW()
        WHERE digest_slot = %s AND sent = FALSE
          AND queued_at > NOW() - INTERVAL '12 hours'
    """, [slot])
    conn.commit()
    conn.close()
    print(f"Sent {slot} digest with {len(items)} items")


if __name__ == '__main__':
    slot = sys.argv[1] if len(sys.argv) > 1 else 'morning'
    dry_run = '--dry-run' in sys.argv
    main(slot, dry_run=dry_run)
```
