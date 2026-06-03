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
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TABLES = {
    "content_embeddings": {"id": "id", "text": "COALESCE(title,'') || ' ' || COALESCE(array_to_string(top_keywords,' '),'')"},
    "hermes_research_intelligence": {"id": "id", "text": "COALESCE(topic,'') || ' ' || COALESCE(summary,'')"},
}


def _ensure_columns(cur, table):
    for col in ("category_content", "category_sector", "category_lifecycle"):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_cat ON {table} (category_content)")


def tag_table(table, limit, use_llm):
    import taxonomy
    from db_adapter import get_connection
    spec = TABLES[table]
    conn = get_connection(); cur = conn.cursor()
    _ensure_columns(cur, table); conn.commit()

    cur.execute(f"""SELECT {spec['id']} AS id, {spec['text']} AS txt
                    FROM {table}
                    WHERE category_content IS NULL
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT %s""", (limit,))
    rows = cur.fetchall()
    classify = taxonomy.classify if use_llm else (lambda t, symbol=None: taxonomy.classify_fast(t))
    tagged = 0
    for rid, txt in rows:
        c = classify(txt or "")
        cur.execute(f"""UPDATE {table}
                        SET category_content=%s, category_sector=%s, category_lifecycle=%s
                        WHERE {spec['id']}=%s""",
                    (c.get("content"), c.get("sector"), c.get("lifecycle"), rid))
        tagged += 1
        if tagged % 200 == 0:
            conn.commit()
    conn.commit()
    # coverage
    cur.execute(f"SELECT COUNT(*) FILTER (WHERE category_content IS NOT NULL), COUNT(*) FROM {table}")
    cov, total = cur.fetchone()
    conn.close()
    print(f"[{table}] tagged {tagged} this run · coverage {cov}/{total}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=list(TABLES))
    ap.add_argument("--all", action="store_true", help="both tables")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--use-llm", action="store_true", help="LLM-refine (slow; default heuristic)")
    args = ap.parse_args()
    tables = list(TABLES) if args.all else ([args.table] if args.table else [])
    if not tables:
        ap.error("specify --table or --all")
    for t in tables:
        tag_table(t, args.limit, args.use_llm)


if __name__ == "__main__":
    main()
