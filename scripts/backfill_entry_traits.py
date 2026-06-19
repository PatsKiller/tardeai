#!/usr/bin/env python3
"""backfill_entry_traits.py — populate the structured entry-trait columns on paper_trades from the
setup_type string (operator 2026-06-19). The strings carry the data
("RVOL 43.0x | Float 106M | Gap +12.3% | Verified catalyst | A 47pts | Source screener") but the
typed columns (rvol_at_entry / float_m_at_entry / score_at_entry / signal_grade / catalyst_verified)
were left null — which made Winner-DNA analysis empty. This fills them where null, parsing only; never
overwrites a value already set. Idempotent. Run with --apply (default dry-run).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

_RVOL = re.compile(r"RVOL\s+([\d.]+)x", re.I)
_FLOAT = re.compile(r"Float\s+([\d.]+)\s*M", re.I)
_GRADE = re.compile(r"\b([A-D][+\-]?)\s+(\d+)\s*pts", re.I)
_CATA = re.compile(r"verified catalyst", re.I)


def _parse(setup: str) -> dict:
    out = {}
    if not setup:
        return out
    m = _RVOL.search(setup)
    if m:
        out["rvol_at_entry"] = float(m.group(1))
    m = _FLOAT.search(setup)
    if m:
        out["float_m_at_entry"] = float(m.group(1))
    m = _GRADE.search(setup)
    if m:
        out["signal_grade"] = m.group(1).upper()
        out["score_at_entry"] = int(m.group(2))
    if _CATA.search(setup):
        out["catalyst_verified"] = True
    return out


def main():
    apply = "--apply" in sys.argv
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT id, setup_type, rvol_at_entry, float_m_at_entry, score_at_entry,
                          signal_grade, catalyst_verified
                     FROM paper_trades
                    WHERE setup_type IS NOT NULL AND setup_type <> ''""")
    rows = cur.fetchall()
    cols = ("id", "setup_type", "rvol_at_entry", "float_m_at_entry", "score_at_entry", "signal_grade", "catalyst_verified")
    updated = 0
    fields_set = 0
    for r in rows:
        d = dict(zip(cols, r))
        parsed = _parse(d["setup_type"])
        # only fill columns that are currently NULL (never overwrite real data)
        to_set = {k: v for k, v in parsed.items() if d.get(k) is None}
        if not to_set:
            continue
        updated += 1
        fields_set += len(to_set)
        if apply:
            sets = ", ".join(f"{k}=%s" for k in to_set)
            cur.execute(f"UPDATE paper_trades SET {sets} WHERE id=%s", (*to_set.values(), d["id"]))
        else:
            print(f"  #{d['id']}: would set {to_set}")
    if apply:
        conn.commit()
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {updated} trades, {fields_set} fields backfilled "
          f"(of {len(rows)} with setup_type)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
