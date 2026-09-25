#!/usr/bin/env python3
"""Backfill subject_guid / issuer_guid onto watch_directives and watchlist_items.

M5 Module 1 item 1c. The columns come from migrations/2026_09_24_watch_subject_guid.sql;
new and updated directives are stamped by watch_directives_writer. This script
fills the rows written before that.

Resolution is the writer's own (``watch_directives_writer.resolve_directive_subject``:
identity registry first, resolve_guid-walked, then the security_identity spine),
once per distinct symbol. Nothing is invented: an unresolvable symbol stays NULL
and is counted.

SAFE BY DEFAULT
  * ``--dry-run`` is the default: read-only, reports what WOULD be written.
  * ``--apply`` writes in batches (``--batch-size``), one commit per batch.
  * Idempotent: only rows whose GUID differs are updated
    (``subject_guid IS DISTINCT FROM``); a second run writes 0.
  * Scope defaults to live rows (watch_directives not archived, watchlist_items
    status='active'), the identity registry's own minting scope. ``--all-statuses``
    widens it.
  * ``--apply`` refuses when the migration has not been applied.

Usage:
  python scripts/backfill_watch_subject_guid.py                 # dry run, both tables
  python scripts/backfill_watch_subject_guid.py --json
  python scripts/backfill_watch_subject_guid.py --apply --batch-size 500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TABLES = ("watch_directives", "watchlist_items")
DEFAULT_BATCH = int(os.environ.get("TRADEAI_WATCH_GUID_BACKFILL_BATCH") or 500)

_SELECT = {
    ("watch_directives", False): (
        "SELECT id, upper(trim(spec->>'symbol')) AS symbol {guid_cols}\n"
        "  FROM watch_directives\n"
        " WHERE kind = 'ticker' AND status <> 'archived'\n"
        "   AND coalesce(trim(spec->>'symbol'), '') <> ''\n"
        " ORDER BY id"
    ),
    ("watch_directives", True): (
        "SELECT id, upper(trim(spec->>'symbol')) AS symbol {guid_cols}\n"
        "  FROM watch_directives\n"
        " WHERE kind = 'ticker' AND coalesce(trim(spec->>'symbol'), '') <> ''\n"
        " ORDER BY id"
    ),
    ("watchlist_items", False): (
        "SELECT id, upper(trim(symbol)) AS symbol {guid_cols}\n"
        "  FROM watchlist_items\n"
        " WHERE status = 'active' AND coalesce(trim(symbol), '') <> ''\n"
        " ORDER BY id"
    ),
    ("watchlist_items", True): (
        "SELECT id, upper(trim(symbol)) AS symbol {guid_cols}\n"
        "  FROM watchlist_items\n"
        " WHERE coalesce(trim(symbol), '') <> ''\n"
        " ORDER BY id"
    ),
}

_UPDATE = (
    "UPDATE {table} AS t\n"
    "   SET subject_guid = v.subject_guid::uuid,\n"
    "       issuer_guid  = COALESCE(v.issuer_guid::uuid, t.issuer_guid)\n"
    "  FROM (VALUES {values}) AS v(id, subject_guid, issuer_guid)\n"
    " WHERE t.id = v.id\n"
    "   AND t.subject_guid IS DISTINCT FROM v.subject_guid::uuid"
)


def _connect():
    """DB connection from DB_* env (loaded from the project .env when unset)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("refusing to open a database connection under pytest; pass conn")
    env_file = Path(os.environ.get("TRADE_AI_PROJECT_ROOT") or ROOT) / ".env"
    if not os.environ.get("DB_PASSWORD") and env_file.is_file():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT") or None,
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"),
    )


def columns_present(cur, table: str) -> bool:
    cur.execute(
        "SELECT count(*) FROM information_schema.columns"
        " WHERE table_name = %s AND column_name IN ('subject_guid', 'issuer_guid')",
        (table,),
    )
    row = cur.fetchone()
    n = row[0] if isinstance(row, (list, tuple)) else (next(iter(row.values())) if isinstance(row, dict) else row)
    return int(n or 0) == 2


def _default_resolver(symbol: str) -> dict[str, Any]:
    from scripts.lib.writers.watch_directives_writer import resolve_directive_subject  # noqa: PLC0415

    return resolve_directive_subject("ticker", {"symbol": symbol})


def plan_table(
    cur,
    table: str,
    *,
    all_statuses: bool = False,
    resolver: Callable[[str], dict[str, Any]] = _default_resolver,
    cache: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Read rows and resolve their symbols. Read-only."""
    present = columns_present(cur, table)
    guid_cols = ", subject_guid::text AS subject_guid" if present else ""
    cur.execute(_SELECT[(table, bool(all_statuses))].format(guid_cols=guid_cols))
    rows = cur.fetchall() or []
    cache = cache if cache is not None else {}
    updates: list[tuple[int, str, Optional[str]]] = []
    unresolved: dict[str, int] = {}
    already = 0
    sources: dict[str, int] = {}
    for r in rows:
        rid = r[0] if isinstance(r, (list, tuple)) else r["id"]
        sym = r[1] if isinstance(r, (list, tuple)) else r["symbol"]
        cur_guid = (
            r[2]
            if isinstance(r, (list, tuple)) and len(r) > 2
            else (r.get("subject_guid") if isinstance(r, dict) else None)
        )
        if sym not in cache:
            try:
                cache[sym] = resolver(sym) or {}
            except Exception as e:  # noqa: BLE001
                cache[sym] = {"identity_lookup_failed": f"{type(e).__name__}: {e}"}
        ident = cache[sym]
        guid = ident.get("subject_guid")
        if not guid:
            unresolved[sym] = unresolved.get(sym, 0) + 1
            continue
        src = str(ident.get("identity_source") or "unknown")
        sources[src] = sources.get(src, 0) + 1
        if cur_guid and str(cur_guid) == str(guid):
            already += 1
            continue
        updates.append((int(rid), str(guid), ident.get("issuer_guid")))
    return {
        "table": table,
        "columns_present": present,
        "rows_in_scope": len(rows),
        "distinct_symbols": len({(r[1] if isinstance(r, (list, tuple)) else r["symbol"]) for r in rows}),
        "resolved_rows": len(rows) - sum(unresolved.values()),
        "unresolved_rows": sum(unresolved.values()),
        "unresolved_symbols": len(unresolved),
        "unresolved_sample": sorted(unresolved, key=lambda s: -unresolved[s])[:15],
        "resolved_by_source": sources,
        "already_stamped": already,
        "would_update": len(updates),
        "_updates": updates,
    }


def _batches(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), max(1, size)):
        yield items[i : i + max(1, size)]


def apply_updates(
    conn, table: str, updates: list[tuple[int, str, Optional[str]]], *, batch_size: int = DEFAULT_BATCH
) -> int:
    if table not in TABLES:
        raise ValueError(f"unknown table {table!r}")
    written = 0
    for batch in _batches(updates, batch_size):
        cur = conn.cursor()
        values = ", ".join(["(%s, %s, %s)"] * len(batch))
        params: list[Any] = []
        for rid, guid, issuer in batch:
            params.extend([int(rid), guid, issuer])
        cur.execute(_UPDATE.format(table=table, values=values), params)
        rc = getattr(cur, "rowcount", None)
        written += rc if isinstance(rc, int) and rc >= 0 else len(batch)
        conn.commit()
    return written


def run(
    conn,
    *,
    tables: Iterable[str] = TABLES,
    apply: bool = False,
    all_statuses: bool = False,
    batch_size: int = DEFAULT_BATCH,
    resolver: Callable[[str], dict[str, Any]] = _default_resolver,
) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] = {"mode": "apply" if apply else "dry_run", "tables": []}
    for table in tables:
        plan = plan_table(conn.cursor(), table, all_statuses=all_statuses, resolver=resolver, cache=cache)
        updates = plan.pop("_updates")
        if apply:
            if not plan["columns_present"]:
                plan["error"] = "migration_not_applied: run migrations/2026_09_24_watch_subject_guid.sql first"
                plan["written"] = 0
            else:
                plan["written"] = apply_updates(conn, table, updates, batch_size=batch_size)
        elif hasattr(conn, "rollback"):
            conn.rollback()  # dry run: end the read-only transaction
        report["tables"].append(plan)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="read-only (default)")
    mode.add_argument("--apply", action="store_true", help="write the GUIDs")
    ap.add_argument("--table", choices=TABLES + ("both",), default="both")
    ap.add_argument("--all-statuses", action="store_true", help="include archived/removed rows")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    tables = TABLES if args.table == "both" else (args.table,)
    conn = _connect()
    try:
        report = run(
            conn, tables=tables, apply=bool(args.apply), all_statuses=args.all_statuses, batch_size=args.batch_size
        )
    finally:
        conn.close()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"mode: {report['mode']}")
        for t in report["tables"]:
            print(f"\n{t['table']}: columns_present={t['columns_present']}")
            for k in (
                "rows_in_scope",
                "distinct_symbols",
                "resolved_rows",
                "unresolved_rows",
                "unresolved_symbols",
                "already_stamped",
                "would_update",
                "written",
                "error",
            ):
                if k in t:
                    print(f"  {k}: {t[k]}")
            print(f"  resolved_by_source: {t['resolved_by_source']}")
            if t["unresolved_sample"]:
                print(f"  unresolved_sample: {', '.join(t['unresolved_sample'])}")
    return 1 if any(t.get("error") for t in report["tables"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
