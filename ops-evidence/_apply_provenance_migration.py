#!/usr/bin/env python3
"""Apply the provenance migration (additive) under the active db-write grant.

Wraps the migration in a single transaction, then verifies by re-reading
information_schema. Read-only except the two ADD COLUMN statements in
migrations/2026_09_10_communication_event_provenance.sql.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from env_bootstrap import load_env  # noqa: E402

load_env()

import os  # noqa: E402

import psycopg2  # noqa: E402

HOST = os.getenv("DB_HOST", "localhost")
PORT = int(os.getenv("DB_PORT", "5432"))
NAME = os.getenv("DB_NAME", "trade_ai")
USER = os.getenv("DB_USER", "trade_ai")
PWD = os.getenv("DB_PASSWORD", "")

MIGRATION = ROOT / "migrations" / "2026_09_10_communication_event_provenance.sql"


def main() -> int:
    sql = MIGRATION.read_text(encoding="utf-8")
    conn = psycopg2.connect(host=HOST, port=PORT, dbname=NAME, user=USER,
                            password=PWD, connect_timeout=10)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    finally:
        conn.close()

    # Verify
    conn = psycopg2.connect(host=HOST, port=PORT, dbname=NAME, user=USER,
                            password=PWD, connect_timeout=10)
    conn.autocommit = True
    out = {"ok": True, "migration": MIGRATION.name}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_name = 'communication_events'
              AND column_name IN ('source_sha', 'provenance')
            ORDER BY column_name
        """)
        out["columns"] = [{"column_name": r[0], "data_type": r[1]} for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM communication_events")
        out["communication_events_rows"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM communication_events WHERE provider_settlement_state = 'SETTLED'")
        out["settled_rows"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM communication_events WHERE provider_settlement_state = 'UNKNOWN_LEGACY'")
        out["unknown_legacy_rows"] = cur.fetchone()[0]
    conn.close()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
