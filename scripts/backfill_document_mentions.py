#!/usr/bin/env python3
"""Populate document_mentions for news_articles and catalyst_events.

    python3 scripts/backfill_document_mentions.py --table news_articles --limit 500
    python3 scripts/backfill_document_mentions.py --all --limit 5000 --apply

DRY RUN IS THE DEFAULT. `--apply` is required to write.

Deterministic only. Documents whose subject cannot be decided without judgment
are COUNTED and skipped, not guessed — they are the model's residual, and the
count is the honest measure of how big that residual is.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _conn():
    import psycopg2
    from lib.env_bootstrap import load_env
    load_env()
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD"))


def run(table: str, limit: int, apply: bool) -> dict:
    from lib import research_identity as RI
    from lib.document_mentions import SOURCES, extract, persist, subject_from_symbol

    spec = SOURCES[table]
    doc = RI.load_registry()
    conn = _conn()
    cur = conn.cursor()

    # ::text because some sources store JSON (research_insights.structured_thesis,
    # key_arguments) and COALESCE(json, '') is an invalid-input error, not an empty
    # string. Casting reads the JSON as prose, which is what the extractor wants.
    text_expr = (" || ' . ' || ".join(f"COALESCE({c}::text, '')" for c in spec["text"])
                 if spec.get("text") else "''")
    cur.execute(f"""SELECT {spec['id']}, {spec['own_symbol']}, {text_expr}
                      FROM {table}
                     WHERE {spec['id']} NOT IN (
                           SELECT source_id FROM document_mentions WHERE source_table = %s)
                     ORDER BY {spec['id']} DESC
                     LIMIT %s""", (table, limit))
    rows = cur.fetchall()

    stat = {"table": table, "documents": len(rows), "subject": 0, "mentioned": 0,
            "undecided_docs": 0, "no_mention": 0, "written": 0, "multi": 0}

    for doc_id, own_symbol, text in rows:
        if spec.get("subject_is_own_symbol"):
            # No body to scan: the row IS about its symbol (sec_form4 carries a
            # transaction, not prose). Extracting from "P" would find nothing and
            # report the row as unmentioned, which is false.
            found = subject_from_symbol(own_symbol, registry=doc)
        else:
            found = extract(text or "", own_symbol=own_symbol, registry=doc)
        if not found:
            stat["no_mention"] += 1
            continue
        if len(found) > 1:
            stat["multi"] += 1
        if any(r["role"] is None for r in found):
            # Several mentions, none of them the filed symbol. Judgment needed;
            # counted so the model residual is a measured number, not a guess.
            stat["undecided_docs"] += 1
            continue
        stat["subject"] += sum(1 for r in found if r["role"] == "subject")
        stat["mentioned"] += sum(1 for r in found if r["role"] == "mentioned")
        if apply:
            stat["written"] += persist(conn, source_table=table,
                                       source_id=doc_id, rows=found)

    conn.close()
    return stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=sorted(__import__(
        "lib.document_mentions", fromlist=["SOURCES"]).SOURCES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    a = ap.parse_args()

    from lib.document_mentions import SOURCES
    targets = sorted(SOURCES) if a.all else ([a.table] if a.table else [])
    if not targets:
        ap.error("--table or --all required")

    print(f"[{'APPLY' if a.apply else 'DRY RUN — nothing written'}]")
    for t in targets:
        s = run(t, a.limit, a.apply)
        print(f"  {s['table']}: docs={s['documents']} multi_mention={s['multi']} "
              f"subject={s['subject']} mentioned={s['mentioned']} "
              f"undecided={s['undecided_docs']} no_mention={s['no_mention']} "
              f"written={s['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
