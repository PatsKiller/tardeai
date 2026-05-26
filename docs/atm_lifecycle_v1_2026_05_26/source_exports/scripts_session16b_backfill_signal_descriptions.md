# Source Export: scripts/session16b_backfill_signal_descriptions.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/session16b_backfill_signal_descriptions.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `fb5e41b88fd04bc04c91db0688c32e426071fb6d85079188126de0dbbaa0a991` |
| **File Size** | 2624 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""session16b_backfill_signal_descriptions.py — Backfill better setup descriptions for recent signals."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

db_password = os.getenv("DB_PASSWORD")
if not db_password:
    raise RuntimeError("DB_PASSWORD missing from .env")

import psycopg2

conn = psycopg2.connect(
    host="127.0.0.1", port=5432, dbname="trade_ai",
    user="trade_ai", password=db_password
)
cur = conn.cursor()


def build_setup_description(row):
    parts = []
    if row.get('rvol') is not None:
        parts.append(f"RVOL {float(row['rvol']):.1f}x")
    if row.get('gap_pct') is not None:
        parts.append(f"Gap {float(row['gap_pct']):+.1f}%")
    if row.get('float_m') is not None:
        parts.append(f"Float {float(row['float_m']):.1f}M")
    if row.get('catalyst_verified'):
        parts.append("Catalyst verified")
    elif row.get('catalyst'):
        parts.append("Unverified catalyst")
    grade = row.get('signal_grade', '')
    score = row.get('signal_score')
    if grade or score is not None:
        parts.append(f"{grade or '?'} {float(score or 0):.0f}pts")
    return " | ".join(parts) if parts else "Strategy signal"


# Get recent signals with blank or generic descriptions
cur.execute("""
    SELECT id, symbol, strategy_id, signal_grade, signal_score,
           rvol, float_m, gap_pct, catalyst, catalyst_verified,
           setup_description
    FROM strategy_signals
    WHERE fired_at > NOW() - INTERVAL '7 days'
    ORDER BY fired_at DESC
""")
cols = [d[0] for d in cur.description]
rows = [dict(zip(cols, r)) for r in cur.fetchall()]

updated = 0
for row in rows:
    desc = row.get('setup_description', '') or ''
    # Skip good descriptions
    if desc and 'RVOL' in desc and '|' in desc:
        continue
    # Skip if not generic
    if desc and 'GO signal from' not in desc and desc != 'Strategy signal' and len(desc) > 30:
        continue

    new_desc = build_setup_description(row)
    if new_desc and new_desc != desc:
        cur.execute("UPDATE strategy_signals SET setup_description = %s WHERE id = %s",
                    [new_desc, row['id']])
        print(f"  {row['symbol']}: {new_desc}")
        updated += 1

conn.commit()
conn.close()
print(f"\nUpdated {updated} signal descriptions")
```
