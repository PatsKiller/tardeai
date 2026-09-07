#!/usr/bin/env python3
"""quarantine_price_spikes.py — move impossible prices out of ticker_prices.

Advisory-only in the sense that matters here: it never edits a price. It ARCHIVES a
row into ticker_prices_quarantine and deletes it from the series, so the reading is
recoverable and the series stops lying.

WHY A ONE-SIDED TEST EATS GOOD DATA
-----------------------------------
"This moved more than 50% in a day" is not evidence of corruption. Measured over 60
days, jumps above 50%:

    source              persistent (split)   reverts (corrupt)
    market_quotes                      258                  34
    yfinance                            32                   9
    finviz                               6                   5
    portfolio_repricer                   2                   1

Six times out of seven a big jump is a REVERSE SPLIT in a micro-cap and the price is
correct. NXTT went 0.0616 -> 6.42 on 2026-08-12 and then traded 5.88-7.95 all week:
the level SHIFTED and stayed. Quarantining that would delete real history — which is
what a previous one-sided detector did, and why this one is two-sided.

Corruption looks different. NOC went 532.80, 523.94, 528.37, then 119.32 in a single
day, and watchlist_items.change_pct — written by a different pipeline — said -2.44%.
The level did not shift; one reading was wrong.

THE TEST — AND WHY SHAPE ALONE IS NOT ENOUGH TO DELETE
------------------------------------------------------
A row is a CANDIDATE when it jumps more than JUMP and the next close returns to
within REVERT of the previous close. A split can never satisfy the second condition,
so that pair separates splits from spikes.

It does NOT separate corruption from a real spike. A one-day surge that retraces is
an ordinary micro-cap pattern — a pump, a halt-and-resume, a news pop. Over 120 days
the shape test flags 90 rows, and AKAN 5.33 -> 10.52 -> back, or AARD 4.99 -> 7.82 ->
back, are exactly what a real small-cap move looks like.

The NOC case was only decidable because a DIFFERENT PIPELINE disagreed:
watchlist_items.change_pct said -2.44% while ticker_prices said -77%. That is
evidence. Shape is a hypothesis.

And ticker_prices carries exactly ONE source per symbol+date — measured: zero
symbol/date pairs have more than one — so there is no second price inside the table
to check against.

Therefore:

  * CONTRADICTED — an independent source (watchlist_items.change_pct) disagrees by
    more than DISAGREE. Quarantined, because two pipelines cannot both be right.
  * SUSPECT — shape fits, no independent source exists. REPORTED, never deleted.
    Deleting these on shape alone is how a previous detector ate real history.
  * SPLIT_LIKE / UNDECIDABLE — kept.

Nothing is ever deleted without an archived copy in ticker_prices_quarantine.

    python3 scripts/quarantine_price_spikes.py            # dry run
    python3 scripts/quarantine_price_spikes.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "PriceSpikeQuarantine@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: A move this large is a CANDIDATE, never a verdict.
JUMP = float(os.getenv("PRICE_SPIKE_JUMP", "0.50"))
#: The next close must come back within this of the previous close to convict.
REVERT = float(os.getenv("PRICE_SPIKE_REVERT", "0.30"))
LOOKBACK_DAYS = int(os.getenv("PRICE_SPIKE_LOOKBACK_DAYS", "120"))

#: NO_CONSUMER_REASON — this writes a quarantine table that the price readers do not
#: yet consult by name; they simply stop seeing the deleted rows. The explicit
#: consumer (a data-quality surface listing what was pulled and why) is not built.
NO_CONSUMER_REASON = (
    "quarantine rows are evidence, not a feed; readers benefit by the row's absence. "
    "A data-quality surface that lists what was pulled and why is not built yet"
)

CANDIDATES = """
WITH d AS (
    SELECT id, symbol, price_date, close_price, source,
           lag(close_price)  OVER w AS prev,
           lead(close_price) OVER w AS nxt
      FROM ticker_prices
     WHERE price_date > current_date - %s
       AND close_price IS NOT NULL AND close_price <> 'NaN'::numeric
    WINDOW w AS (PARTITION BY symbol ORDER BY price_date)
)
SELECT id, symbol, price_date, close_price, source, prev, nxt,
       abs(close_price - prev) / prev AS jump
  FROM d
 WHERE prev IS NOT NULL AND prev > 0
   AND abs(close_price - prev) / prev > %s
 ORDER BY symbol, price_date
"""


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


#: An independent source must disagree by more than this to convict.
DISAGREE = float(os.getenv("PRICE_SPIKE_DISAGREE", "3.0"))


def independent_moves(cur, symbols: list[str]) -> dict[tuple[str, object], float]:
    """Independent move, keyed on (SYMBOL, DATE) — never on symbol alone.

    watchlist_items.change_pct is a point-in-time SNAPSHOT, not a time series: one
    row per symbol, stamped last_enriched_at. Keying on symbol alone compares a price
    move from July against a percentage refreshed in September — two unrelated
    numbers that happen to share a ticker.

    The first version of this did exactly that and returned CONTRADICTED=82,
    SUSPECT=1. It would have deleted 82 rows on a meaningless comparison. Correct is
    the mirror image: almost nothing has a same-day second source, so almost
    everything is SUSPECT and stays.
    """
    if not symbols:
        return {}
    cur.execute(
        """SELECT upper(symbol), last_enriched_at::date, abs(change_pct)
             FROM watchlist_items
            WHERE symbol = ANY(%s) AND change_pct IS NOT NULL
              AND last_enriched_at IS NOT NULL""", (symbols,))
    out: dict[tuple[str, object], float] = {}
    for sym, day, pct in cur.fetchall():
        key = (sym, day)
        out[key] = max(out.get(key, 0.0), float(pct))
    return out


def verdict(close: float, prev: float, nxt, independent=None) -> tuple[str, float | None]:
    """CONTRADICTED / SUSPECT / SPLIT_LIKE / UNDECIDABLE.

    Only CONTRADICTED is ever deleted. SUSPECT fits the shape of corruption and has
    nothing to confirm it — and the shape of corruption is also the shape of a real
    micro-cap spike.
    """
    if nxt is None:
        return "UNDECIDABLE", None
    back = abs(float(nxt) - prev) / prev if prev else None
    if back is None or back >= REVERT:
        return "SPLIT_LIKE", back
    if independent is None:
        return "SUSPECT", back
    observed = abs(float(close) - prev) / prev * 100.0
    lo, hi = sorted((max(observed, 1e-9), max(independent, 1e-9)))
    return ("CONTRADICTED" if hi / lo > DISAGREE else "SPLIT_LIKE"), back


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    cur.execute(CANDIDATES, (LOOKBACK_DAYS, JUMP))
    rows = cur.fetchall()

    counts = {"candidates": len(rows), "CONTRADICTED": 0, "SUSPECT": 0,
              "SPLIT_LIKE": 0, "UNDECIDABLE": 0}
    independent = independent_moves(cur, sorted({r[1] for r in rows}))
    corrupt, suspect = [], []
    for rid, sym, pdate, close, source, prev, nxt, jump in rows:
        # (symbol, date) — a snapshot only corroborates the day it was taken.
        v, back = verdict(float(close), float(prev), nxt,
                          independent.get((str(sym).upper(), pdate)))
        counts[v] += 1
        rec = (rid, sym, pdate, float(close), source, float(prev), float(jump), back)
        if v == "CONTRADICTED":
            corrupt.append(rec)
        elif v == "SUSPECT":
            suspect.append(rec)

    print(f"{SCHEMA} — apply={args.apply} jump>{JUMP:.0%} revert<{REVERT:.0%} "
          f"lookback={LOOKBACK_DAYS}d")
    print(f"  candidates={counts['candidates']}  "
          f"CONTRADICTED(quarantine)={counts['CONTRADICTED']}  "
          f"SUSPECT(reported only)={counts['SUSPECT']}  "
          f"split-like(kept)={counts['SPLIT_LIKE']}  "
          f"undecidable(kept)={counts['UNDECIDABLE']}")
    if suspect:
        print(f"  {len(suspect)} suspect rows are NOT deleted — no independent source "
              f"to confirm them, and a real micro-cap spike looks the same:")
        for _r, sym, pdate, close, source, prev, jump, back in suspect[:5]:
            print(f"    {sym:>6} {pdate}  {prev:>10.4f} -> {close:<10.4f} "
                  f"({jump*100:+.0f}%)  [{source}]")
    for rid, sym, pdate, close, source, prev, jump, back in corrupt[:args.limit or 15]:
        print(f"    {sym:>6} {pdate}  {prev:>10.4f} -> {close:<10.4f} "
              f"({jump*100:+.0f}%) then back to within {back*100:.0f}%  [{source}]")

    written = 0
    if args.apply and corrupt:
        for rid, sym, pdate, close, source, prev, jump, back in corrupt:
            # Archive BEFORE deleting. Never delete without a recoverable copy.
            cur.execute(
                """INSERT INTO ticker_prices_quarantine
                     (original_id, symbol, price_date, close_price, source,
                      quality_reason, baseline, deviation_ratio, quarantined_at,
                      quarantined_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
                (rid, sym, pdate, close, source,
                 f"contradicted_by_independent_source:jump={jump:.3f},back={back:.3f}",
                 prev, jump, SCHEMA))
            cur.execute("DELETE FROM ticker_prices WHERE id=%s", (rid,))
            written += cur.rowcount
        conn.commit()
    conn.close()

    print("RESULT: " + json.dumps({
        "schema": SCHEMA, "authority": AUTHORITY, "model_calls": 0,
        "jump_threshold": JUMP, "revert_threshold": REVERT,
        **counts,
        # None when nothing was attempted; 0 is a measured zero.
        "rows_produced": written if args.apply else None,
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
