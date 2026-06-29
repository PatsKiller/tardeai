#!/usr/bin/env python3
"""migrate_hermes_research_provenance.py — additive, idempotent provenance columns for Hermes research.

Adds nullable governance/provenance columns so every research row records WHY it ran and under what
budget decision. Purely additive (ADD COLUMN IF NOT EXISTS) — no data rewrite, no drops, reversible.
NOT a broker/execution write; advisory metadata only.

  python3 scripts/migrate_hermes_research_provenance.py            # apply
  python3 scripts/migrate_hermes_research_provenance.py --check    # report only, no DDL
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# table -> [(column, type)]  — all nullable, all additive.
COLUMNS = {
    "hermes_external_research": [
        ("trigger_source", "text"),       # normalized tier-driving source (vs free-text trigger_reason)
        ("budget_tier", "text"),          # T0..T4
        ("budget_decision", "text"),      # ALLOW | DEFER | METADATA_ONLY | BLOCK
        ("lane_used", "text"),
        ("research_expires_at", "timestamptz"),
        ("research_reason", "text"),
        ("downstream_outcome", "text"),   # proposal | block | risk_alert | no_action
    ],
    "hermes_research_intelligence": [
        ("trigger_source", "text"),
        ("trigger_id", "text"),
        ("budget_tier", "text"),
        ("budget_decision", "text"),
        ("lane_used", "text"),
        ("research_expires_at", "timestamptz"),
        ("downstream_outcome", "text"),
    ],
}


def _existing(conn, table):
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report missing columns, apply nothing")
    a = ap.parse_args()
    from db_adapter import _get_conn
    conn = _get_conn()
    report = {"applied": [], "already_present": [], "would_add": []}
    for table, cols in COLUMNS.items():
        have = _existing(conn, table)
        for name, typ in cols:
            if name in have:
                report["already_present"].append(f"{table}.{name}")
                continue
            if a.check:
                report["would_add"].append(f"{table}.{name} {typ}")
                continue
            cur = conn.cursor()
            cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {typ}')
            conn.commit()
            report["applied"].append(f"{table}.{name} {typ}")
    import json
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
