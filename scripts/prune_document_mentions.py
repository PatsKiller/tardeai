#!/usr/bin/env python3
"""Retire mention rows whose document is gone or aged out.

    python3 scripts/prune_document_mentions.py            # dry run
    python3 scripts/prune_document_mentions.py --apply

WHY A MENTION HAS NO LIFETIME OF ITS OWN
----------------------------------------
A mention is a derived fact — *this document mentions this issuer, in this role*.
Its relevance is entirely the document's relevance, so:

  · source document purged  -> its mentions MUST go. That is referential
    integrity, not judgment: an orphan points at a source_id that no longer
    exists and will silently match nothing, or worse, a recycled id.
  · document retained       -> its mentions are exactly as relevant as it is.

Asking a model "is this 90-day-old mention still relevant?" 40,000 times is
expensive, non-deterministic, and answers a question a foreign key already
answers. NO MODEL RUNS HERE, and none should: if the question is whether a
DOCUMENT is worth keeping, that is curation and it already lives at the document
layer (usefulness_score, deep_curation_verdict, retirement_relevance).

WHY DELETING HERE IS NOT THE "NEVER DELETE" RULE
------------------------------------------------
AGENTS.md forbids deleting authoritative state without a tripwire. A mention row
is a PROJECTION: re-runnable from the source document by the extractor, and once
the document is gone it is not evidence of anything — it is a dangling pointer.
The archive-with-tripwire rule protects irreplaceable state; this is the opposite.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def retention_windows() -> dict[str, tuple[str, int]]:
    """(timestamp column, days) per source, READ from db_retention.

    Read, never copied. A source whose retention changes changes its mentions'
    retention automatically, so the two can never silently disagree.
    """
    from lib.document_mentions import SOURCES

    try:
        import db_retention
        policies = {t: (col, days) for t, col, days in db_retention.POLICIES}
    except Exception as exc:
        print(f"[prune] cannot read db_retention.POLICIES ({type(exc).__name__}) — "
              "refusing to invent windows", file=sys.stderr)
        return {}
    return {t: policies[t] for t in SOURCES if t in policies}


def _conn():
    import psycopg2
    from lib.env_bootstrap import load_env
    load_env()
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"))


def plan(conn) -> dict:
    """What would be removed, and why. Counts only — no writes."""
    from lib.document_mentions import SOURCES

    cur = conn.cursor()
    out = {"orphans": {}, "aged": {}, "unwindowed": []}
    windows = retention_windows()

    for table, spec in SOURCES.items():
        idcol = spec["id"]
        cur.execute(f"""SELECT count(*) FROM document_mentions m
                         WHERE m.source_table = %s
                           AND NOT EXISTS (SELECT 1 FROM {table} s
                                            WHERE s.{idcol} = m.source_id)""", (table,))
        out["orphans"][table] = cur.fetchone()[0]

        if table not in windows:
            # No declared window: report it rather than invent one. A source with
            # no retention grows unbounded and that must be visible.
            out["unwindowed"].append(table)
            continue
        tscol, days = windows[table]
        cur.execute(f"""SELECT count(*) FROM document_mentions m
                          JOIN {table} s ON s.{idcol} = m.source_id
                         WHERE m.source_table = %s
                           AND s.{tscol} < now() - make_interval(days => %s)""",
                    (table, days))
        out["aged"][table] = cur.fetchone()[0]
    return out


def prune(conn, *, apply: bool) -> dict:
    from lib.document_mentions import SOURCES

    p = plan(conn)
    p["deleted"] = 0
    if not apply:
        return p

    cur = conn.cursor()
    windows = retention_windows()
    for table, spec in SOURCES.items():
        idcol = spec["id"]
        cur.execute(f"""DELETE FROM document_mentions m
                         WHERE m.source_table = %s
                           AND NOT EXISTS (SELECT 1 FROM {table} s
                                            WHERE s.{idcol} = m.source_id)""", (table,))
        p["deleted"] += max(cur.rowcount or 0, 0)
        if table not in windows:
            continue
        tscol, days = windows[table]
        cur.execute(f"""DELETE FROM document_mentions m
                         USING {table} s
                         WHERE s.{idcol} = m.source_id
                           AND m.source_table = %s
                           AND s.{tscol} < now() - make_interval(days => %s)""",
                    (table, days))
        p["deleted"] += max(cur.rowcount or 0, 0)
    conn.commit()
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    conn = _conn()
    try:
        res = prune(conn, apply=a.apply)
    finally:
        conn.close()

    if a.json:
        import json
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"[{'APPLY' if a.apply else 'DRY RUN — nothing deleted'}]")
        for t in sorted(set(res["orphans"]) | set(res["aged"])):
            print(f"  {t}: orphans={res['orphans'].get(t, 0)} aged={res['aged'].get(t, 0)}")
        if res["unwindowed"]:
            print(f"  NO RETENTION WINDOW (grows unbounded): {', '.join(res['unwindowed'])}")
        if a.apply:
            print(f"  deleted={res['deleted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
