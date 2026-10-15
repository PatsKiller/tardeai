#!/usr/bin/env python3
"""Read-only check of research_insights.source_reference uniqueness and the unique index (packet
research-insights-unique-index-20261015). SELECT only, in a READ ONLY session, through scripts/db_adapter._get_conn()
(the repo's own DB helper; this script never reads a credential file itself).

    check_research_insights.py --code-root CODE           # preflight: exit 0 iff 0 duplicate groups
    check_research_insights.py --code-root CODE --post    # verify: also requires the index present, VALID, UNIQUE

AUTHORITY: READ_ONLY. No write, no DDL.
"""

from __future__ import annotations

import argparse
import json
import sys

INDEX = "uq_research_insights_source_reference"

QUERIES = {
    "totals": (
        "SELECT count(*) AS rows, count(source_reference) AS non_null,"
        " count(DISTINCT source_reference) AS distinct_refs,"
        " count(*) FILTER (WHERE source_reference IS NULL) AS null_refs,"
        " min(created_at)::text AS first, max(created_at)::text AS last FROM research_insights"
    ),
    "duplicates": (
        "SELECT count(*) AS dup_groups, coalesce(sum(n), 0)::bigint AS rows_in_groups,"
        " coalesce(sum(n - 1), 0)::bigint AS extra_rows FROM ("
        " SELECT source_reference, count(*) AS n FROM research_insights WHERE source_reference IS NOT NULL"
        " GROUP BY source_reference HAVING count(*) > 1) d"
    ),
    "top_groups": (
        "SELECT source_reference, count(*) AS n, min(id) AS min_id, max(id) AS max_id FROM research_insights"
        " WHERE source_reference IS NOT NULL GROUP BY source_reference HAVING count(*) > 1"
        " ORDER BY n DESC, source_reference LIMIT 25"
    ),
    "index": (
        "SELECT c.relname AS name, i.indisvalid AS valid, i.indisunique AS unique, pg_get_indexdef(i.indexrelid) AS def"
        " FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
        f" WHERE i.indexrelid = to_regclass('public.{INDEX}')"
    ),
    "size": "SELECT pg_size_pretty(pg_total_relation_size('research_insights')) AS size",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--post", action="store_true", help="also require the index present, valid and unique")
    a = ap.parse_args(argv)
    sys.path.insert(0, a.code_root)
    sys.path.insert(0, a.code_root + "/scripts")
    import psycopg2.extras

    from scripts import db_adapter

    conn = db_adapter._get_conn()
    conn.rollback()
    conn.set_session(readonly=True)
    out: dict = {"db": {"dbname": conn.info.dbname, "host": conn.info.host, "port": conn.info.port}}
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SHOW transaction_read_only")
        out["transaction_read_only"] = cur.fetchone()["transaction_read_only"]
        for name, sql in QUERIES.items():
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            out[name] = rows if name == "top_groups" else (rows[0] if rows else None)
    finally:
        conn.rollback()
    ok = out["transaction_read_only"] == "on" and int(out["duplicates"]["dup_groups"]) == 0
    if a.post:
        idx = out["index"]
        ok = ok and bool(idx and idx["valid"] and idx["unique"] and idx["def"].endswith("(source_reference)"))
    out["verdict"] = ("VERIFY" if a.post else "PREFLIGHT") + (" OK" if ok else " FAILED")
    print(json.dumps(out, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
