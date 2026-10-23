#!/usr/bin/env python3
"""Dry-run plan for migrations/2026_10_22_ops_controls.sql (AGENTS.md §0 rule 7). Writes nothing.

  ops_controls_migration_plan.py            offline: parse the file and print what it would create
  ops_controls_migration_plan.py --probe    plus a read-only to_regclass probe: which tables already exist

The migration itself is applied by the operator only (psql -f, see the file header). AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "migrations" / "2026_10_22_ops_controls.sql"
DOWN = ROOT / "migrations" / "2026_10_22_ops_controls.down.sql"


def _code(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def plan(sql_text: str) -> dict:
    code = _code(sql_text)
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", code)
    indexes = re.findall(r"CREATE INDEX IF NOT EXISTS (\w+)", code)
    grants = [" ".join(g.split()) for g in re.findall(r"GRANT[^;]+;", code)]
    destructive = re.findall(r"\b(DROP|DELETE\s+FROM|TRUNCATE\s+\w|ALTER\s+TABLE)\b", code, re.I)
    return {"file": str(UP.relative_to(ROOT)), "creates_tables": tables, "creates_indexes": indexes,
            "grants": grants, "destructive_statements": destructive, "additive": not destructive,
            "reverse": str(DOWN.relative_to(ROOT))}


def probe(tables: list[str]) -> dict:
    sys.path.insert(0, str(ROOT))
    from scripts import session13_db

    conn = session13_db.get_conn()
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute("SELECT t, to_regclass('public.' || t) IS NOT NULL FROM unnest(%s::text[]) t", (tables,))
            present = {t: bool(p) for t, p in cur.fetchall()}
    finally:
        conn.rollback()
        conn.close()
    return {"present": [t for t, p in present.items() if p], "absent": [t for t, p in present.items() if not p]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe", action="store_true", help="read-only probe of which tables already exist")
    args = ap.parse_args(argv)
    out = plan(UP.read_text(encoding="utf-8"))
    if args.probe:
        out["probe"] = probe(out["creates_tables"])
    print(json.dumps(out, indent=2))
    print("DRY RUN — nothing written. Apply (operator): psql \"$DB\" -v ON_ERROR_STOP=1 -f " + out["file"],
          file=sys.stderr)
    return 0 if out["additive"] else 2


if __name__ == "__main__":
    sys.exit(main())
