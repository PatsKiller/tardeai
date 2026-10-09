#!/usr/bin/env python3
"""Populate document_mentions for news_articles and catalyst_events.

    python3 scripts/backfill_document_mentions.py --table news_articles --limit 500
    python3 scripts/backfill_document_mentions.py --all --limit 5000 --apply
    python3 scripts/backfill_document_mentions.py --all --rescan --apply   # after a registry change

DRY RUN IS THE DEFAULT. `--apply` is required to write.

2026-10-09: documents the extractor cannot decide (undecided / no mention) are never written, so the old
"newest N not yet in document_mentions" query re-read the same ~4000 stuck documents per table every hour
(catalyst_events: 443 s for 2 writable docs). The hourly cron (timeout 25m) was killed in the third table
every run since 09-30, so sec_form4 was never reached and the log (block-buffered) stayed empty. Each table
now scans forward from a per-table watermark (persistent state), stops on a time budget, and logs as it goes.
`--rescan` restores the full newest-first pass for when the identity registry changes.

Deterministic only. Documents whose subject cannot be decided without judgment
are COUNTED and skipped, not guessed — they are the model's residual, and the
count is the honest measure of how big that residual is.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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


WATERMARK_MARGIN = 200   # re-read a little below the mark: ids can commit slightly out of order


def watermark_path() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base) / "state" / "document_mentions_watermark.json"


def load_watermarks() -> dict:
    try:
        return json.loads(watermark_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_watermarks(marks: dict) -> None:
    p = watermark_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(marks, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def select_sql(table: str, spec: dict, text_expr: str, mark) -> tuple[str, tuple]:
    """Newest-first over everything unwritten (no mark / --rescan), else forward from the mark."""
    base = f"""SELECT {spec['id']}, {spec['own_symbol']}, {text_expr}
                 FROM {table}
                WHERE {spec['id']} NOT IN (
                      SELECT source_id FROM document_mentions WHERE source_table = %s)"""
    if mark is None:
        return base + f"\n             ORDER BY {spec['id']} DESC\n                LIMIT %s", (table,)
    return (base + f"\n                  AND {spec['id']} > %s\n             ORDER BY {spec['id']} ASC\n                LIMIT %s",
            (table, max(0, int(mark) - WATERMARK_MARGIN)))


def run(table: str, limit: int, apply: bool, mark=None, deadline: float | None = None,
        seed: bool = False) -> dict:
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
    if mark is None and seed:
        # First watermark run: start just below the newest document already written for this table; the
        # unwritten documents under it are the undecided backlog every earlier run re-read.
        cur.execute("SELECT max(source_id) FROM document_mentions WHERE source_table = %s", (table,))
        mark = (cur.fetchone() or [None])[0]
    sql, params = select_sql(table, spec, text_expr, mark)
    cur.execute(sql, params + (limit,))
    rows = cur.fetchall()

    stat = {"table": table, "documents": len(rows), "subject": 0, "mentioned": 0,
            "undecided_docs": 0, "no_mention": 0, "written": 0, "multi": 0,
            "scanned": 0, "max_id": None, "budget_hit": False}

    for doc_id, own_symbol, text in rows:
        if deadline is not None and time.monotonic() >= deadline:
            stat["budget_hit"] = True
            break
        stat["scanned"] += 1
        stat["max_id"] = doc_id if stat["max_id"] is None else max(stat["max_id"], doc_id)
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
    ap.add_argument("--rescan", action="store_true",
                    help="ignore the watermarks: newest-first over every unwritten document")
    ap.add_argument("--budget-s", type=float, default=1200.0,
                    help="stop scanning after this many seconds (the hourly cron is killed at 25 min)")
    a = ap.parse_args()

    from lib.document_mentions import SOURCES
    targets = sorted(SOURCES) if a.all else ([a.table] if a.table else [])
    if not targets:
        ap.error("--table or --all required")

    t0 = time.monotonic()
    deadline = t0 + a.budget_s if a.budget_s and a.budget_s > 0 else None
    marks = {} if a.rescan else load_watermarks()
    print(f"[{'APPLY' if a.apply else 'DRY RUN — nothing written'}] {time.strftime('%F %T')}"
          f" budget={a.budget_s:.0f}s{' rescan' if a.rescan else ''}", flush=True)
    for t in targets:
        if deadline is not None and time.monotonic() >= deadline:
            print(f"  {t}: skipped (budget spent)", flush=True)
            continue
        s = run(t, a.limit, a.apply, mark=marks.get(t), deadline=deadline, seed=not a.rescan)
        # The mark only moves on --apply runs that scanned forward, so a dry run never hides documents.
        if a.apply and s["max_id"] is not None:
            marks[t] = max(int(s["max_id"]), int(marks.get(t) or 0))
        print(f"  {s['table']}: docs={s['documents']} scanned={s['scanned']} multi_mention={s['multi']} "
              f"subject={s['subject']} mentioned={s['mentioned']} "
              f"undecided={s['undecided_docs']} no_mention={s['no_mention']} "
              f"written={s['written']} mark={marks.get(t)}{' BUDGET' if s['budget_hit'] else ''} "
              f"t={time.monotonic() - t0:.0f}s", flush=True)
    if a.apply:
        save_watermarks(marks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
