#!/usr/bin/env python3
"""repair_finviz_strategy_type_20261107.py — undo the ticker-as-``strategy_type`` pollution.

``scripts/finviz_proactive_research.py`` wrote the TICKER into ``news_articles.strategy_type`` on every
row it saved (```strategy_type: sym```). ``strategy_type`` is a STRATEGY classification: topic_curator,
the iris taxonomy and rag_retrieval key on it, so 440 news rows carry a symbol where a strategy class
belongs, and 369 ``catalyst_events`` rows built from them carry the same pollution. Nothing writes a
strategy class for this source, so the correct value is NULL (let the classifier own it) — measured
2026-11-07: 440/440 news and 369/369 catalyst finviz rows have ``strategy_type = symbol``, and no
finviz row has any other value.

Scope is deliberately narrow: only ``source = 'finviz_news'``. The topic_* collectors also store a key in
``strategy_type``, but there the ``symbol`` COLUMN holds a topic id (``d23_defense_aerospace``,
``su_industry_tobacco``), not a ticker — that convention is its own decision, not this defect.

Archive first (AGENTS.md §0 rule 6): the old values are written to a gzip jsonl archive with a sha256
manifest and a tripwire record, re-read and count-checked, and only then are the rows updated by id.
Dry run by default; ``--apply`` is required to write.

  python3 scripts/repair_finviz_strategy_type_20261107.py            # report only
  python3 scripts/repair_finviz_strategy_type_20261107.py --apply    # archive, then UPDATE ... SET NULL
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LABEL = "strategy_type_repair"
WRITER = "repair_finviz_strategy_type_20261107"
SOURCE = "finviz_news"
BATCH = 500
PREDICATE = ("source = %s AND strategy_type IS NOT NULL AND upper(strategy_type) = upper(symbol)")

TABLES = {
    "news_articles": ("SELECT id, symbol, strategy_type, title FROM news_articles WHERE {p} ORDER BY id",
                      "SELECT count(*) FROM news_articles WHERE {p}"),
    "catalyst_events": ("SELECT id, symbol, strategy_type, headline FROM catalyst_events WHERE {p} ORDER BY id",
                        "SELECT count(*) FROM catalyst_events WHERE {p}"),
}


def _count(cur, table: str) -> int:
    cur.execute(TABLES[table][1].format(p=PREDICATE), (SOURCE,))
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _archive_and_null(conn, table: str) -> dict:
    """Archive every selected row, verify the archive, then NULL exactly those ids. All or nothing."""
    from lib.retention_archive import (archive_root, verify_archive, write_jsonl_gz, write_manifest)

    cur = conn.cursor()
    cur.execute(TABLES[table][0].format(p=PREDICATE), (SOURCE,))
    rows = cur.fetchall()
    if not rows:
        return {"table": table, "archived": 0, "updated": 0}
    ids = [r[0] for r in rows]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = archive_root() / table / f"{stamp}-{LABEL}-b0001.jsonl.gz"
    payload = [{"id": r[0], "symbol": r[1], "strategy_type": r[2], "title": r[3],
                "repaired_at": datetime.now(timezone.utc).isoformat(), "writer": WRITER} for r in rows]
    n, sha, size = write_jsonl_gz(payload, dest)
    if n != len(rows):
        raise RuntimeError(f"{table}: archive wrote {n} rows, expected {len(rows)}")
    write_manifest(dest, table=table, rows=n, sha256=sha, bytes=size, label=LABEL, writer=WRITER,
                   kind="column_values", where=PREDICATE.replace("%s", repr(SOURCE)))
    ok, why = verify_archive(dest, expected_rows=n, expected_sha256=sha, key="id", expected_keys=ids)
    if not ok:
        raise RuntimeError(f"{table}: archive verification failed ({why}); nothing updated")
    cur.execute(f"UPDATE {table} SET strategy_type = NULL WHERE id = ANY(%s)", (ids,))
    if cur.rowcount != len(ids):
        conn.rollback()
        raise RuntimeError(f"{table}: updated {cur.rowcount} of {len(ids)} archived rows; rolled back")
    conn.commit()
    return {"table": table, "archived": n, "updated": cur.rowcount, "archive": str(dest), "sha256": sha}


def _load_env() -> None:
    """Same env the lanes load (DB_*), so a dry run sees the same database the lane writes."""
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - the venv always has python-dotenv
        return
    for name, value in dotenv_values(ROOT / ".env").items():
        if name.startswith("DB_") and value is not None:
            os.environ.setdefault(name, value)


def _connect():
    """The lane's own connector (imported late so a test can substitute one)."""
    from db_adapter import get_connection
    return get_connection()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="archive then NULL the polluted values")
    args = ap.parse_args(argv)
    _load_env()
    conn = _connect()
    try:
        cur = conn.cursor()
        before = {t: _count(cur, t) for t in TABLES}
        print(json.dumps({"mode": "APPLY" if args.apply else "DRY", "source": SOURCE,
                          "before": before}, indent=2))
        if not args.apply:
            for t in TABLES:
                cur.execute(TABLES[t][0].format(p=PREDICATE) + " LIMIT 3", (SOURCE,))
                print(f"  {t} sample: " + json.dumps([dict(zip(("id", "symbol", "strategy_type", "title"), r))
                                                      for r in cur.fetchall()]))
            print(json.dumps({"writes": "none", "would_update": before,
                              "after_expected": {t: 0 for t in TABLES}}, indent=2))
            return 0
        results = [_archive_and_null(conn, t) for t in TABLES]
        after = {t: _count(cur, t) for t in TABLES}
        print(json.dumps({"mode": "APPLY", "results": results, "after": after}, indent=2, default=str))
        return 0 if not any(after.values()) else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
