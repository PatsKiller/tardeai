#!/usr/bin/env python3
"""audit_table_readers_without_writers.py — find silently-starved data products.

A FAILING producer is visible: it errors, the watchdog flags it, someone pages.
A producer that was never wired up is INVISIBLE — its consumers just read an
empty table forever and report nothing. pattern_library sat empty while four
modules read it, because pattern_extractor was declared but never scheduled AND
carried a crash bug (found 2026-07-20).

This inverts the usual sweep: instead of asking "is every job running?", it asks
"does every table someone READS actually have something WRITING it?".

Signals, strongest first:
  EMPTY + readers + no writer  -> almost certainly a dead capability
  STALE + readers + no writer  -> was populated once, producer since lost
  rows  + readers + no writer  -> written by migration/seed/external process

SQL is found by regex over scripts/*.py, so this is a heuristic: dynamic SQL and
ORM access are invisible to it. It is a lead generator, not proof — every hit
needs confirming by hand.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

IDENT = r"([a-z_][a-z0-9_]*)"
READ = re.compile(rf"\bFROM\s+{IDENT}|\bJOIN\s+{IDENT}", re.I)
WRITE = re.compile(
    rf"\bINSERT\s+INTO\s+{IDENT}|\bUPDATE\s+{IDENT}\s+SET|\bDELETE\s+FROM\s+{IDENT}"
    rf"|\bCOPY\s+{IDENT}|\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{IDENT}"
    rf"|\bTRUNCATE\s+(?:TABLE\s+)?{IDENT}", re.I)

# SQL keywords / CTE noise that look like table names to the regex.
NOISE = {
    "select", "where", "values", "set", "table", "only", "lateral", "unnest",
    "generate_series", "dual", "information_schema", "pg_catalog", "pg_stat_activity",
    "pg_class", "pg_tables", "x", "t", "a", "b", "c", "e", "s", "w", "o", "p",
}


def scan():
    readers, writers = defaultdict(set), defaultdict(set)
    for f in sorted(ROOT.glob("scripts/*.py")):
        if f.name.startswith("audit_table_readers"):
            continue
        try:
            src = f.read_text(errors="replace")
        except Exception:
            continue
        for m in READ.finditer(src):
            for g in m.groups():
                if g and g.lower() not in NOISE:
                    readers[g.lower()].add(f.name)
        for m in WRITE.finditer(src):
            for g in m.groups():
                if g and g.lower() not in NOISE:
                    writers[g.lower()].add(f.name)
    return readers, writers


def real_tables(cur) -> dict:
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_type='BASE TABLE'""")
    return {r[0] for r in cur.fetchall()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Tables read by code but never written by it")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-readers", type=int, default=1)
    args = ap.parse_args()

    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    tables = real_tables(cur)
    readers, writers = scan()

    findings = []
    for t in sorted(tables):
        rs = readers.get(t, set())
        ws = writers.get(t, set())
        if len(rs) < args.min_readers or ws:
            continue
        try:
            cur.execute(f'SELECT count(*) FROM "{t}"')
            n = cur.fetchone()[0]
        except Exception:
            cur.connection.rollback()
            n = None
        findings.append({"table": t, "rows": n,
                         "reader_count": len(rs), "readers": sorted(rs)[:6]})

    findings.sort(key=lambda f: ((f["rows"] or 0) != 0, -(f["reader_count"])))
    empty = [f for f in findings if f["rows"] == 0]

    if args.json:
        print(json.dumps({"findings": findings, "empty_count": len(empty)}, indent=1))
        return 0

    print(f"tables in DB: {len(tables)} | read-but-never-written by scripts/: {len(findings)}")
    print(f"of those, EMPTY (strongest signal): {len(empty)}\n")
    for f in findings:
        tag = "EMPTY" if f["rows"] == 0 else (f"{f['rows']} rows" if f["rows"] is not None else "?")
        mark = "!!" if f["rows"] == 0 else "  "
        print(f"{mark} {f['table']:38s} {tag:>12s}  readers={f['reader_count']}: "
              f"{', '.join(f['readers'][:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
