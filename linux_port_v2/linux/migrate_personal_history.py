"""
Phase P1 migration — walk personal_situation.json history arrays
and insert each entry into personal_history table.

Idempotent: re-running uses fixed recorded_at='2026-04-19T00:00:00'
so ON CONFLICT DO NOTHING prevents duplicates.

Does NOT migrate "current" values — those stay in JSON until they
become history (i.e., until a user edits them via modal).

Run from project root:
    python3 linux_port_v2/linux/migrate_personal_history.py
"""

import os
import sys
import json
from pathlib import Path

# Load .env
ROOT = Path(__file__).resolve().parent.parent.parent
for line in (ROOT / ".env").read_text().splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(ROOT / "scripts"))
from db_adapter import USE_DB, _execute

if not USE_DB:
    print("ERROR: USE_DB is False. Check .env DB_* keys.")
    sys.exit(1)

PERSONAL_PATH = ROOT / "data" / "portfolios" / "state" / "personal_situation.json"
if not PERSONAL_PATH.exists():
    print(f"ERROR: {PERSONAL_PATH} not found")
    sys.exit(1)

data = json.loads(PERSONAL_PATH.read_text())
fields = data.get("fields", {})

# Walk all history entries
rows_to_insert = []
for field_name, field in fields.items():
    if not isinstance(field, dict):
        continue
    data_type = field.get("data_type", "unknown")
    category = field.get("category", "unknown")
    history = field.get("history", [])
    
    for h in history:
        if not isinstance(h, dict):
            continue
        rows_to_insert.append({
            "field_name": field_name,
            "value": h.get("value"),
            "data_type": data_type,
            "category": category,
            "effective_date": h.get("date", "2026-04-19"),
            "note": h.get("note", "migrated from JSON history"),
        })

print(f"Found {len(rows_to_insert)} history entries to migrate")

if not rows_to_insert:
    print("Nothing to migrate. Exiting.")
    sys.exit(0)

# Insert with fixed recorded_at for idempotency
inserted = 0
skipped = 0
for r in rows_to_insert:
    result = _execute(
        """INSERT INTO personal_history 
           (field_name, value, data_type, category, effective_date, recorded_at, note, source)
           VALUES (%s, %s, %s, %s, %s, '2026-04-19T00:00:00'::timestamptz, %s, 'migration')
           ON CONFLICT (field_name, effective_date, recorded_at) DO NOTHING""",
        (r["field_name"], json.dumps(r["value"]), r["data_type"], 
         r["category"], r["effective_date"], r["note"])
    )
    if result is True:
        inserted += 1  # Note: ON CONFLICT DO NOTHING also returns True; counts attempts
    else:
        skipped += 1

print(f"Migration complete: {inserted} attempts succeeded, {skipped} failed")
print()
print("Verify with:")
print("  psql -U trade_ai -h localhost -d trade_ai -c \"SELECT field_name, value, effective_date, source FROM personal_timeline\"")
