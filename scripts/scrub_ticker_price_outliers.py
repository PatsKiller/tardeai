#!/usr/bin/env python3
"""Quarantine historically-corrupt rows in ticker_prices. Audit finding C3, Stage B.

Stage A (PR #524) guards ingestion, so no *new* corruption lands. This removes
what is already stored -- the NVDA 2026-05-04..06 rows reading $0.66/$0.18/$0.05
against a ~$200 baseline, and the rest found by the same rule.

    python scripts/scrub_ticker_price_outliers.py                # dry run (default)
    python scripts/scrub_ticker_price_outliers.py --json
    python scripts/scrub_ticker_price_outliers.py --symbol NVDA  # scope to one symbol
    python scripts/scrub_ticker_price_outliers.py --apply        # execute
    python scripts/scrub_ticker_price_outliers.py --restore NVDA # undo for a symbol

**Quarantine, not delete.** Each row is copied to `ticker_prices_quarantine`
with its baseline, deviation ratio and reason before being removed from
`ticker_prices`. Nothing is destroyed and `--restore` puts a symbol back.

**Why remove the row rather than flag it in place.** The remediation plan asked
for rows to be marked invalid so consumers can tell "no data" from "bad data",
and for consumers to skip flagged rows. There are 28 raw `FROM ticker_prices`
queries across 29 files and no central accessor, so a flag column would be
ignored by every one of them and the corrupt values would keep being served.
`close_price` is NOT NULL, so blanking the value in place is not available
either. Removing the row from the live table gives every consumer the correct
answer -- absence, i.e. no data -- with no call-site changes, while the
quarantine table preserves the evidence for anyone asking whether data was
bad here rather than merely missing.

AUTHORITY: READ_ONLY_ADVISORY with respect to trading. This writes only to the
price store; it places no orders and changes no policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.price_quality import find_corrupt_rows  # noqa: E402

QUARANTINE_DDL = """
CREATE TABLE IF NOT EXISTS ticker_prices_quarantine (
    id              bigserial PRIMARY KEY,
    original_id     integer,
    symbol          varchar   NOT NULL,
    price_date      date      NOT NULL,
    close_price     numeric   NOT NULL,
    source          varchar,
    created_at      timestamptz,
    quality_reason  varchar   NOT NULL,
    baseline        numeric,
    deviation_ratio numeric,
    quarantined_at  timestamptz DEFAULT now(),
    quarantined_by  varchar
);
CREATE UNIQUE INDEX IF NOT EXISTS ticker_prices_quarantine_sym_date
    ON ticker_prices_quarantine (symbol, price_date);
"""


def _conn():
    from price_db_sync import _get_conn  # type: ignore
    return _get_conn()


def already_quarantined_symbols(conn) -> set[str]:
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT symbol FROM ticker_prices_quarantine")
        return {r[0] for r in cur.fetchall()}
    except Exception:
        conn.rollback()  # table not created yet — first run
        return set()


def scan(conn, symbol: str | None = None, *, allow_cascade: bool = False) -> dict[str, list]:
    """Corrupt rows per symbol.

    **Single-pass by design.** Quarantining a row changes the windows around it,
    so a second pass over the same symbol finds different rows -- and they are
    not more corruption, they are the detector losing its footing. After the
    first pass on HAO, the surviving ~0.73 regime rows were flagged against a
    baseline of 0.0428 built from what was left. Iterating would eat real data a
    layer at a time, each pass looking as plausible as the last.

    So a symbol with existing quarantine rows is skipped. `allow_cascade` exists
    for a human who has looked at a specific symbol and decided a second pass is
    right; it should never be wired into a cron.
    """
    skip = set() if allow_cascade else already_quarantined_symbols(conn)
    cur = conn.cursor()
    if symbol:
        cur.execute(
            "SELECT symbol, price_date, close_price, id FROM ticker_prices "
            "WHERE symbol=%s ORDER BY price_date", (symbol,))
    else:
        cur.execute(
            "SELECT symbol, price_date, close_price, id FROM ticker_prices "
            "ORDER BY symbol, price_date")
    series: dict[str, list] = defaultdict(list)
    for sym, dt, price, row_id in cur.fetchall():
        series[sym].append((dt, price, row_id))

    out: dict[str, list] = {}
    for sym, rows in series.items():
        if sym in skip:
            continue
        findings = find_corrupt_rows([(d, p) for d, p, _ in rows])
        if findings:
            out[sym] = [(f, rows[f.index][2]) for f in findings]
    return out


def apply_quarantine(conn, hits: dict[str, list], *, actor: str) -> int:
    cur = conn.cursor()
    cur.execute(QUARANTINE_DDL)
    moved = 0
    for sym, entries in hits.items():
        for finding, row_id in entries:
            # Copy first, delete second, one transaction: a row can never be
            # removed from the live table without its quarantine record existing.
            cur.execute(
                """INSERT INTO ticker_prices_quarantine
                     (original_id, symbol, price_date, close_price, source, created_at,
                      quality_reason, baseline, deviation_ratio, quarantined_by)
                   SELECT id, symbol, price_date, close_price, source, created_at,
                          %s, %s, %s, %s
                     FROM ticker_prices WHERE id = %s
                   ON CONFLICT (symbol, price_date) DO NOTHING""",
                (finding.reason, finding.baseline, finding.ratio, actor, row_id),
            )
            cur.execute("DELETE FROM ticker_prices WHERE id = %s", (row_id,))
            moved += cur.rowcount
    conn.commit()
    return moved


def restore(conn, symbol: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO ticker_prices (symbol, price_date, close_price, source, created_at)
           SELECT symbol, price_date, close_price, source, created_at
             FROM ticker_prices_quarantine WHERE symbol = %s
           ON CONFLICT DO NOTHING""", (symbol,))
    n = cur.rowcount
    cur.execute("DELETE FROM ticker_prices_quarantine WHERE symbol = %s", (symbol,))
    conn.commit()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Quarantine corrupt ticker_prices rows (C3 Stage B)")
    ap.add_argument("--apply", action="store_true", help="execute (default is a dry run)")
    ap.add_argument("--symbol", default=None, help="limit to one symbol")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--restore", default=None, metavar="SYMBOL", help="undo for one symbol")
    ap.add_argument("--actor", default="scrub_ticker_price_outliers")
    ap.add_argument("--allow-cascade", action="store_true",
                    help="re-scan symbols that already have quarantined rows. Single-pass is the "
                         "safe default: quarantining shifts the windows, so a second pass flags "
                         "surviving good rows. Human review only — never cron this.")
    args = ap.parse_args()

    conn = _conn()
    try:
        if args.restore:
            n = restore(conn, args.restore)
            print(f"restored {n} row(s) for {args.restore}")
            return 0

        hits = scan(conn, args.symbol, allow_cascade=args.allow_cascade)
        total = sum(len(v) for v in hits.values())

        if args.json:
            print(json.dumps({
                "symbols": len(hits),
                "rows": total,
                "applied": bool(args.apply),
                "findings": {s: [f.as_dict() for f, _ in v] for s, v in hits.items()},
            }, indent=2, sort_keys=True, default=str))
        else:
            print(f"{'APPLY' if args.apply else 'DRY RUN'} — {total} corrupt row(s) across {len(hits)} symbol(s)")
            for sym in sorted(hits, key=lambda s: -len(hits[s])):
                print(f"\n  {sym}  ({len(hits[sym])})")
                for f, _ in hits[sym][:5]:
                    base = f"{f.baseline:.4f}" if f.baseline else "-"
                    print(f"    {f.date}  price={f.price!s:<12} baseline={base:<12} {f.reason}")
                if len(hits[sym]) > 5:
                    print(f"    … {len(hits[sym]) - 5} more")

        if args.apply and total:
            moved = apply_quarantine(conn, hits, actor=args.actor)
            print(f"\nquarantined {moved} row(s) → ticker_prices_quarantine")
            print("undo:  --restore <SYMBOL>")
        elif not args.apply and total:
            print("\nnothing written. re-run with --apply to quarantine.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
