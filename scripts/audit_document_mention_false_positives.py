#!/usr/bin/env python3
"""Read-only audit: which existing document_mentions rows would the false-positive rule drop?

    PGOPTIONS='-c default_transaction_read_only=on' python3 scripts/audit_document_mention_false_positives.py

Writes nothing. Prints the count, the top offenders, 10 samples and the PROPOSED cleanup SQL (archive, then delete,
for the operator to run -- this script never does).
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_document_mentions import _conn  # noqa: E402
from lib import document_mentions as DM  # noqa: E402


def main() -> int:
    conn = _conn()
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute("SELECT id, source_table, source_id, symbol, matched_via, matched_text, role FROM document_mentions "
                "WHERE matched_via IN ('company_name','ticker_alias')")
    rows = cur.fetchall()
    by_table: dict[str, set[int]] = collections.defaultdict(set)
    for r in rows:
        by_table[r[1]].add(r[2])
    texts: dict[tuple[str, int], tuple[str, str]] = {}
    for table, ids in by_table.items():
        spec = DM.SOURCES.get(table)
        if not spec or not spec["text"]:
            continue
        cols = " || ' ' || ".join(f"coalesce({c}::text,'')" for c in spec["text"])
        cur.execute(f"SELECT {spec['id']}, {cols}, coalesce({spec['own_symbol']}::text,'') FROM {table} "  # noqa: S608
                    f"WHERE {spec['id']} = ANY(%s)", (sorted(ids),))
        for i, t, own in cur.fetchall():
            texts[(table, i)] = (t, own)
    drop: list[tuple] = []
    reasons: collections.Counter = collections.Counter()
    offenders: collections.Counter = collections.Counter()
    for mid, table, sid, sym, via, mt, role in rows:
        t, own = texts.get((table, sid), ("", ""))
        why = DM.false_positive_reason(mt, sym, via, text=t, own_symbol=own or None)
        if why:
            drop.append((mid, table, sid, sym, mt, role, why))
            reasons[why] += 1
            offenders[(mt, sym)] += 1
    print(f"examined={len(rows)} would_drop={len(drop)} ({100 * len(drop) / max(1, len(rows)):.1f}%)")
    print("reasons:", dict(reasons))
    print("top offenders:", offenders.most_common(15))
    if "--verbose" in sys.argv:
        print("offenders 15-80:", offenders.most_common(80)[15:])
        print("no_word_boundary:", collections.Counter((d[4], d[3]) for d in drop if d[6] == "no_word_boundary").most_common(12))
    step = max(1, len(drop) // 10)
    print("samples (id, source_table, source_id, symbol, matched_text, role, reason):")
    for s in drop[::step][:10]:
        print("  ", s)
    print("\n-- PROPOSED CLEANUP (operator to run; archive first, never run by this script)\n"
          "CREATE TABLE IF NOT EXISTS document_mentions_archive_20261107 (LIKE document_mentions);\n"
          "-- ids come from this audit; apply in batches of 5000:\n"
          "INSERT INTO document_mentions_archive_20261107 SELECT * FROM document_mentions WHERE id = ANY(:ids);\n"
          "DELETE FROM document_mentions WHERE id = ANY(:ids);")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
