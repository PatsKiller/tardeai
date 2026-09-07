#!/usr/bin/env python3
"""Taxonomy tagger — Phase 2.

Tags the two convergence points with the canonical 3-axis taxonomy so TradeAI and Hermes
share one vocabulary:
  - content_embeddings  (the ~28k RAG corpus — had NO category)
  - hermes_research_intelligence (strategy_tags was never populated)

Adds category_content / category_sector / category_lifecycle columns (idempotent), then
classifies untagged rows. Default is heuristic (fast, no LLM) so bulk backfill doesn't
depend on the saturated shared GPU; pass --use-llm to refine small batches.

Tag-forward = run on a cron with --limit; it always tags the newest untagged rows first.

    python3 scripts/taxonomy_tagger.py --table content_embeddings --limit 1000
    python3 scripts/taxonomy_tagger.py --table hermes --limit 500
    python3 scripts/taxonomy_tagger.py --all --limit 1000      # both tables
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TABLES = {
    "content_embeddings": {"id": "id", "text": "COALESCE(title,'') || ' ' || COALESCE(array_to_string(top_keywords,' '),'')"},
    "hermes_research_intelligence": {"id": "id", "text": "COALESCE(topic,'') || ' ' || COALESCE(summary,'')"},
}


# Written when the heuristic finds nothing, so the row is not re-selected. Before this, every
# hourly run re-classified and re-UPDATEd the same ~500 unmatched rows forever (1 net row/run).
NO_MATCH = "no_match"

# ...but "not re-selected" was implemented as NEVER re-selected, and that is a trap.
#
# Measured 2026-09-06, bounded 20-row run: 17 no-match sentinels, 1 usable content tag,
# 0 sectors. At --limit 500 hourly this consumes the 32,060-row backlog in ~64 hours and
# permanently forecloses ~85% of it, including from any BETTER classifier later. Running it
# would burn the corpus it exists to enrich. That is why the cron is off, and why simply
# switching the cron back on would have been the wrong fix.
#
# A sentinel says "today's heuristic could not classify this" — a statement with a shelf
# life, not a fact about the row. So it gets one. Hourly runs then retry a given row about
# 12x/year instead of every hour, which is what the sentinel actually needed to prevent.
NO_MATCH_TTL_DAYS = int(os.environ.get("TAXONOMY_NO_MATCH_TTL_DAYS", "30"))


def _ensure_columns(cur, table):
    for col in ("category_content", "category_sector", "category_lifecycle"):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_cat ON {table} (category_content)")


def tag_table(table, limit, use_llm, ensure_schema=False):
    import taxonomy
    from db_adapter import get_connection
    spec = TABLES[table]
    conn = get_connection(); cur = conn.cursor()
    if ensure_schema:
        # One-time DDL only on request — the hourly ALTER TABLE took an exclusive lock every run
        # (9 recorded LockNotAvailable failures against live readers).
        _ensure_columns(cur, table); conn.commit()

    cur.execute(f"""SELECT {spec['id']} AS id, {spec['text']} AS txt
                    FROM {table}
                    WHERE category_content IS NULL
                       OR (category_content = %s
                           AND (taxonomy_tagged_at IS NULL
                                OR taxonomy_tagged_at < now() - make_interval(days => %s)))
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT %s""", (NO_MATCH, NO_MATCH_TTL_DAYS, limit))
    rows = cur.fetchall()
    classify = taxonomy.classify if use_llm else (lambda t, symbol=None: taxonomy.classify_fast(t))
    tagged = no_match = 0
    for rid, txt in rows:
        c = classify(txt or "")
        content = c.get("content")
        if content is None and c.get("sector") is None and c.get("lifecycle") is None:
            content = NO_MATCH
            no_match += 1
        else:
            tagged += 1
        cur.execute(f"""UPDATE {table}
                        SET category_content=%s, category_sector=%s, category_lifecycle=%s,
                            taxonomy_tagged_at=now()
                        WHERE {spec['id']}=%s""",
                    (content, c.get("sector"), c.get("lifecycle"), rid))
        if (tagged + no_match) % 200 == 0:
            conn.commit()
    conn.commit()
    # coverage (real tags only — no_match sentinels are processed-but-uncategorized)
    cur.execute(f"""SELECT COUNT(*) FILTER (WHERE category_content IS NOT NULL AND category_content <> %s),
                           COUNT(*) FROM {table}""", (NO_MATCH,))
    cov, total = cur.fetchone()
    conn.close()
    print(f"[{table}] tagged {tagged} this run ({no_match} no-match sentinels) · coverage {cov}/{total}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=list(TABLES))
    ap.add_argument("--all", action="store_true", help="both tables")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--use-llm", action="store_true", help="LLM-refine (slow; default heuristic)")
    ap.add_argument("--ensure-schema", action="store_true",
                    help="run the ADD COLUMN/CREATE INDEX DDL (one-time; not for the hourly cron)")
    args = ap.parse_args()
    tables = list(TABLES) if args.all else ([args.table] if args.table else [])
    if not tables:
        ap.error("specify --table or --all")
    for t in tables:
        tag_table(t, args.limit, args.use_llm, ensure_schema=args.ensure_schema)


if __name__ == "__main__":
    main()
