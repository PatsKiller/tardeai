#!/usr/bin/env python3
"""fix_llm_consumption_cost_units.py — repair a column that is not what it says.

`llm_consumption_log.estimated_cost_usd` is not USD for the rows written before
the 2026-08-03 guard (commit b532ab3a, "Never store char-relative units in
estimated_cost_usd"). Those rows carry `cost_basis IS NULL` and span 2026-07-08
to 2026-08-18 — the tail past 08-03 is pre-guard code still serving from older
release directories.

Measured 2026-08-30 before any change:

    cost_basis IS NULL rows          4,069
    of which estimated_cost_usd > 0  4,069   (claimed sum $17,423.42)
      with usable token counts       1,216
      without token counts           2,853
    rows within 10x of a plausible token-derived cost:  0

Not one is plausibly USD. A single `deepseek-v4-pro` call of 60,548 in / 3,429
out is recorded as $257.15 where the rate card gives $0.047 — off by ~5,500x.
I tested and refuted the obvious hypothesis (that the column held latency): of
412 such rows with a duration, 0 matched `duration_ms/1000`.

What this does, and does not do:

  * **Nothing is destroyed.** The original value is copied into
    `metadata_json.legacy_cost_value` with its own note before the column is
    touched, so the change is reversible from the row itself.
  * Rows WITH tokens are recomputed from the published rate card, at the tier
    that actually applied (peak is Mon-Fri 01:00-04:00 and 06:00-10:00 UTC),
    and marked `cost_basis='recomputed_from_tokens_20260830'`.
  * Rows WITHOUT tokens are set to NULL and marked
    `cost_basis='unknown_units_nulled_20260830'`. **NULL, not zero** — zero is a
    claim that the call was free, and we do not know that. An honest absence.
  * Rows that already carry a `cost_basis` are never touched.

Usage:
    python3 scripts/fix_llm_consumption_cost_units.py --dry-run
    python3 scripts/fix_llm_consumption_cost_units.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

# Rates per 1M tokens, off-peak. Peak is 2x. Source: the rate card installed in
# CLAUDE.md / AGENTS.md on 2026-08-30 from api-docs.deepseek.com.
RATES = {
    "flash": {"hit": 0.007, "miss": 0.22, "out": 0.66},
    "pro":   {"hit": 0.022, "miss": 0.66, "out": 1.98},
}

# Peak: Mon-Fri, 01:00-03:59 and 06:00-09:59 UTC.
PEAK_SQL = (
    "(EXTRACT(dow FROM created_at AT TIME ZONE 'UTC') BETWEEN 1 AND 5 AND "
    " (EXTRACT(hour FROM created_at AT TIME ZONE 'UTC') BETWEEN 1 AND 3 OR "
    "  EXTRACT(hour FROM created_at AT TIME ZONE 'UTC') BETWEEN 6 AND 9))"
)

IS_PRO = "(model_name ILIKE '%pro%' OR model_name ILIKE '%reasoner%')"

RECOMPUTED = "recomputed_from_tokens_20260830"
NULLED = "unknown_units_nulled_20260830"


def _conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"))


def _cost_expr() -> str:
    """SQL that computes real USD from tokens and the tier that applied."""
    f, p = RATES["flash"], RATES["pro"]
    return f"""
      (CASE WHEN {IS_PRO} THEN
          (coalesce(cache_hit_tokens,0) * {p['hit']}
           + GREATEST(coalesce(tokens_in,0) - coalesce(cache_hit_tokens,0), 0) * {p['miss']}
           + coalesce(tokens_out,0) * {p['out']}) / 1000000.0
       ELSE
          (coalesce(cache_hit_tokens,0) * {f['hit']}
           + GREATEST(coalesce(tokens_in,0) - coalesce(cache_hit_tokens,0), 0) * {f['miss']}
           + coalesce(tokens_out,0) * {f['out']}) / 1000000.0
       END) * (CASE WHEN {PEAK_SQL} THEN 2.0 ELSE 1.0 END)
    """


TARGET = "cost_basis IS NULL AND estimated_cost_usd IS NOT NULL"
HAS_TOKENS = "tokens_in IS NOT NULL AND tokens_out IS NOT NULL"


def report(cur) -> dict:
    cur.execute(f"""SELECT count(*), sum(estimated_cost_usd),
                           count(*) FILTER (WHERE {HAS_TOKENS}),
                           count(*) FILTER (WHERE NOT ({HAS_TOKENS}))
                    FROM llm_consumption_log WHERE {TARGET}""")
    n, claimed, with_tok, without = cur.fetchone()
    cur.execute(f"""SELECT sum({_cost_expr()}) FROM llm_consumption_log
                    WHERE {TARGET} AND {HAS_TOKENS}""")
    real = cur.fetchone()[0]
    return {"rows": n or 0, "claimed_sum": float(claimed or 0),
            "with_tokens": with_tok or 0, "without_tokens": without or 0,
            "recomputed_sum": float(real or 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = _conn()
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM llm_consumption_log")
    total_before = cur.fetchone()[0]
    before = report(cur)

    print("=== before ===")
    print(f"  table rows total        : {total_before}")
    print(f"  rows to repair          : {before['rows']}")
    print(f"    with usable tokens    : {before['with_tokens']}  -> recomputed")
    print(f"    without tokens        : {before['without_tokens']}  -> NULL (not zero)")
    print(f"  claimed sum (not USD)   : {before['claimed_sum']:,.2f}")
    print(f"  recomputed real USD     : ${before['recomputed_sum']:,.4f}")

    if args.dry_run:
        print("\ndry run — nothing written")
        return 0

    # 1. Preserve the original value on the row itself before touching it.
    cur.execute(f"""
        UPDATE llm_consumption_log
           SET metadata_json = coalesce(metadata_json,'{{}}'::jsonb) || jsonb_build_object(
                 'legacy_cost_value', estimated_cost_usd,
                 'legacy_cost_note',
                 'value was NOT USD; column repaired 2026-08-30, see '
                 'scripts/fix_llm_consumption_cost_units.py')
         WHERE {TARGET}""")
    preserved = cur.rowcount

    # 2. Recompute where tokens allow it.
    cur.execute(f"""
        UPDATE llm_consumption_log
           SET estimated_cost_usd = ROUND(({_cost_expr()})::numeric, 8),
               cost_basis = '{RECOMPUTED}'
         WHERE {TARGET} AND {HAS_TOKENS}""")
    recomputed = cur.rowcount

    # 3. NULL where we cannot know. Never invent a number, never write zero.
    cur.execute(f"""
        UPDATE llm_consumption_log
           SET estimated_cost_usd = NULL,
               cost_basis = '{NULLED}'
         WHERE {TARGET}""")
    nulled = cur.rowcount

    conn.commit()

    cur.execute("SELECT count(*) FROM llm_consumption_log")
    total_after = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM llm_consumption_log WHERE {TARGET}")
    remaining = cur.fetchone()[0]
    cur.execute(f"""SELECT count(*), sum(estimated_cost_usd)
                    FROM llm_consumption_log WHERE cost_basis='{RECOMPUTED}'""")
    rn, rs = cur.fetchone()
    cur.execute("""SELECT count(*) FROM llm_consumption_log
                   WHERE metadata_json ? 'legacy_cost_value'""")
    kept = cur.fetchone()[0]

    print("\n=== after ===")
    print(f"  originals preserved     : {preserved}")
    print(f"  recomputed              : {recomputed}  (sum ${float(rs or 0):,.4f})")
    print(f"  nulled (unknown units)  : {nulled}")
    print(f"  rows still unrepaired   : {remaining}")
    print(f"  rows carrying the legacy value: {kept}")
    print(f"  table rows before/after : {total_before} / {total_after}"
          f"  (delta {total_after - total_before}, must be 0)")

    ok = (total_after == total_before and remaining == 0
          and kept >= preserved and rn == recomputed)
    print("\nRESULT:", "OK" if ok else "CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
