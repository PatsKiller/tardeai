# Source Export: scripts/migrate_screener_arch3_catalog_lifecycle.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/migrate_screener_arch3_catalog_lifecycle.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `d1c3c058b7bb302207991e07908e1f143278a20cd23808ead34984954ba521f5` |
| **File Size** | 4662 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""migrate_screener_arch3_catalog_lifecycle.py — Create screener membership tables.

Idempotent. Non-destructive. No drops.

Usage:
    .venv/bin/python scripts/migrate_screener_arch3_catalog_lifecycle.py --dry-run
    .venv/bin/python scripts/migrate_screener_arch3_catalog_lifecycle.py --apply
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

# Existing tables we leverage: incubator_universe (catalog), ticker_strategy_classifications
# New tables needed: screener_symbol_membership, screener_symbol_membership_history

TABLES = [
    {
        "name": "screener_symbol_membership",
        "sql": """
CREATE TABLE IF NOT EXISTS screener_symbol_membership (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    screener_id VARCHAR(64) NOT NULL,
    first_seen_in_screener_at TIMESTAMPTZ,
    last_seen_in_screener_at TIMESTAMPTZ,
    last_seen_run_id VARCHAR(64),
    present_this_run BOOLEAN DEFAULT TRUE,
    consecutive_seen_count INTEGER DEFAULT 1,
    consecutive_missing_count INTEGER DEFAULT 0,
    membership_status VARCHAR(20) DEFAULT 'present',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, screener_id)
);
""",
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_ssm_symbol ON screener_symbol_membership(symbol);",
            "CREATE INDEX IF NOT EXISTS idx_ssm_screener ON screener_symbol_membership(screener_id);",
            "CREATE INDEX IF NOT EXISTS idx_ssm_status ON screener_symbol_membership(membership_status);",
            "CREATE INDEX IF NOT EXISTS idx_ssm_last_seen ON screener_symbol_membership(last_seen_in_screener_at);",
        ],
    },
    {
        "name": "screener_symbol_membership_history",
        "sql": """
CREATE TABLE IF NOT EXISTS screener_symbol_membership_history (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    screener_id VARCHAR(64) NOT NULL,
    run_id VARCHAR(64),
    event_type VARCHAR(20) NOT NULL,
    event_at TIMESTAMPTZ DEFAULT NOW(),
    reason TEXT,
    metadata_json JSONB
);
""",
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_ssmh_symbol ON screener_symbol_membership_history(symbol, screener_id);",
            "CREATE INDEX IF NOT EXISTS idx_ssmh_event_at ON screener_symbol_membership_history(event_at);",
        ],
    },
]


def main():
    p = argparse.ArgumentParser(description="Screener catalog lifecycle migration (default: dry-run)")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.apply: args.dry_run = False

    results = []

    if args.dry_run:
        for t in TABLES:
            results.append({"table": t["name"], "action": "would_create", "indexes": len(t["indexes"])})
            if args.verbose:
                print(f"  DRY RUN: would create {t['name']} + {len(t['indexes'])} indexes")
    else:
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            for t in TABLES:
                cur.execute(t["sql"])
                for idx in t["indexes"]:
                    cur.execute(idx)
                results.append({"table": t["name"], "action": "created_or_exists", "indexes": len(t["indexes"])})
                if args.verbose:
                    print(f"  APPLIED: {t['name']} + {len(t['indexes'])} indexes")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"error": str(e)})

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "dry_run" if args.dry_run else "apply",
              "tables": results, "existing_catalog": "incubator_universe (leveraged)", "existing_classifications": "ticker_strategy_classifications (leveraged)"}

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Catalog Lifecycle Migration {'DRY RUN' if args.dry_run else 'APPLIED'}\n"]
        for r in results:
            md.append(f"- {r.get('table', 'error')}: {r.get('action', r.get('error', '?'))}")
        md.append(f"\nExisting tables leveraged: incubator_universe, ticker_strategy_classifications")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
```
