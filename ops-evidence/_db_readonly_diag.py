#!/usr/bin/env python3
"""READ-ONLY DB diagnostic for Phase 1 settlement migration preflight.

Only executes SELECT / information_schema reads. No INSERT/UPDATE/DELETE/ALTER/
CREATE/TRUNCATE anywhere. Prints schema metadata + row counts, never secrets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

# Load DB creds via the sanctioned runtime path (env_bootstrap). Values are
# loaded into os.environ and never printed.
from env_bootstrap import load_env  # noqa: E402

load_env()

import psycopg2  # noqa: E402

HOST = __import__("os").getenv("DB_HOST", "localhost")
PORT = __import__("os").getenv("DB_PORT", "5432")
NAME = __import__("os").getenv("DB_NAME", "trade_ai")
USER = __import__("os").getenv("DB_USER", "trade_ai")
PWD = __import__("os").getenv("DB_PASSWORD", "")


def main() -> int:
    conn = psycopg2.connect(
        host=HOST, port=int(PORT), dbname=NAME, user=USER, password=PWD,
        connect_timeout=10,
    )
    conn.autocommit = True
    out: dict = {
        "db": {"host": HOST, "port": PORT, "name": NAME, "user": USER},
        "tables": {},
    }
    tables = [
        "communication_events",
        "communication_deliveries",
        "communication_outbox",
        "communication_entity_links",
    ]
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
                """,
                (t,),
            )
            cols = [
                {
                    "column_name": r[0],
                    "data_type": r[1],
                    "is_nullable": r[2],
                    "column_default": r[3],
                }
                for r in cur.fetchall()
            ]
            # Row count (read-only)
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                cnt = cur.fetchone()[0]
            except Exception as exc:
                cnt = f"ERROR: {type(exc).__name__}"
            # Constraints
            cur.execute(
                """
                SELECT conname, contype, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = %s::regclass
                ORDER BY conname
                """,
                (t,),
            )
            cons = [
                {"name": r[0], "type": r[1], "def": r[2]} for r in cur.fetchall()
            ]
            # Indexes
            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = %s
                ORDER BY indexname
                """,
                (t,),
            )
            idx = [{"name": r[0], "def": r[1]} for r in cur.fetchall()]
            out["tables"][t] = {
                "row_count": cnt,
                "columns": cols,
                "constraints": cons,
                "indexes": idx,
            }

        # Whether v2 settlement columns already exist
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'communication_events'
              AND column_name IN (
                'provider_message_id','provider_settled_at',
                'provider_settlement_state','delivery_owner',
                'gateway_mode_at_dispatch','curation_kind',
                'curation_provenance','subject_guid'
              )
            ORDER BY column_name
            """
        )
        out["settlement_columns_present"] = [r[0] for r in cur.fetchall()]

        # schema version strings present in existing rows (informational)
        try:
            cur.execute(
                "SELECT schema_version, COUNT(*) FROM communication_events GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
            )
            out["schema_version_counts"] = [
                {"version": r[0], "count": r[1]} for r in cur.fetchall()
            ]
        except Exception as exc:
            out["schema_version_counts"] = f"ERROR: {type(exc).__name__}"

    conn.close()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
