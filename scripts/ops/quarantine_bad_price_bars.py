#!/usr/bin/env python3
"""quarantine_bad_price_bars.py — find pre-listing / reused-symbol bars in ticker_prices and quarantine them.

Operator 2026-10-26 (a live prospectus): ONE row — a quote-snapshot close dated the day before a new listing's first
session, several times below every following close — produced a 1-year low at that price, a several-hundred-percent
YTD return, an impossible beta and volatility, and a correlation to the book near 1.
``scripts/quarantine_price_spikes.py`` cannot see it: it needs a previous close (the row is the FIRST of the
series) and the level after it persists, which that script reads, correctly, as split-like.

Detector: ``scripts.lib.prospectus.blocks.clean_series`` — the same rule the prospectus applies before computing any
statistic, so the reader and the correction agree on what a bad bar is:

  * ISOLATED — a run of at most 2 closes more than 3x away from the median of the neighbouring 10 sessions on both
    sides (one side at the start / end of the series), while those neighbours agree with each other.
  * BREAK — a persistent jump above 3x (unadjusted split or reused symbol). Reported, never quarantined.

Verdicts (only PRE_LISTING is ever quarantined, and only with --apply):

  * PRE_LISTING — an ISOLATED run at the START of the series whose source differs from the source of the sessions
    that follow (a quote snapshot written before the listing's first daily bar). Two pipelines disagree about the
    level and the later one is corroborated by every following session.
  * SUSPECT — any other ISOLATED run. Reported only; a real one-day spike has the same shape (see
    quarantine_price_spikes.py for why shape alone never convicts).
  * BREAK — reported only.

Quarantine is the existing governed mechanism of quarantine_price_spikes.py: the row is copied into
``ticker_prices_quarantine`` (original id, symbol, date, close, source, reason, baseline, ratio, who) and only then
removed from the series, in one transaction, so it is recoverable. ``--apply`` is operator-only: it needs a
state-write grant id (``--grant``), which is recorded in ``quarantined_by``. Agents run the dry run only.

    python3 scripts/ops/quarantine_bad_price_bars.py --symbols AAA,BBB          # dry run (default), SELECTs only
    python3 scripts/ops/quarantine_bad_price_bars.py --prospectus-universe      # every symbol with a prospectus
    python3 scripts/ops/quarantine_bad_price_bars.py --symbols AAA --apply --grant <state-write grant id>

READ_ONLY_ADVISORY: no broker, order or stop path; MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import blocks as bk  # noqa: E402

SCHEMA = "BadPriceBarQuarantine@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LOOKBACK_DAYS = int(os.getenv("BAD_BAR_LOOKBACK_DAYS", "1100"))

SERIES_SQL = """
SELECT id, price_date, close_price, source
  FROM ticker_prices
 WHERE upper(symbol) = %s AND price_date > current_date - %s
   AND close_price IS NOT NULL AND close_price <> 'NaN'::numeric AND close_price > 0
 ORDER BY price_date
"""


def classify(rows: list[dict]) -> dict:
    """rows: [{id, price_date, close_price, source}] sorted by date → verdicts for one symbol."""
    by_date = {str(r["price_date"])[:10]: r for r in rows}
    series = [(d, float(r["close_price"])) for d, r in sorted(by_date.items())]
    _clean, excluded, brk = bk.clean_series(series)
    out: dict[str, Any] = {"sessions": len(series), "pre_listing": [], "suspect": [], "break": brk}
    if not excluded:
        return out
    dates = [d for d, _ in series]
    for e in excluded:
        row = by_date[e["date"]]
        idx = dates.index(e["date"])
        following = [by_date[d] for d in dates[idx + 1: idx + 1 + bk.SERIES_CONFIRM_SESSIONS] if d not in
                     {x["date"] for x in excluded}]
        after = [float(r["close_price"]) for r in following]
        dominant = Counter(str(r.get("source") or "") for r in following).most_common(1)
        baseline = statistics.median(after) if after else None
        rec = {"id": row.get("id"), "date": e["date"], "close": float(row["close_price"]), "source": row.get("source"),
               "baseline": baseline, "ratio": round(max(baseline, e["close"]) / min(baseline, e["close"]), 2)
               if baseline else None, "following_source": dominant[0][0] if dominant else None, "reason": e["reason"]}
        leading = all(d in {x["date"] for x in excluded} for d in dates[:idx + 1])
        if leading and dominant and str(row.get("source") or "") != dominant[0][0]:
            out["pre_listing"].append(rec)
        else:
            out["suspect"].append(rec)
    return out


def prospectus_symbols(state_root: Path) -> list[str]:
    base = state_root / "data/prospectus"
    from scripts.lib.prospectus.store import norm_symbol
    return sorted(p.name for p in base.iterdir() if p.is_dir() and norm_symbol(p.name) == p.name) if base.is_dir() else []


def default_query() -> Callable:
    from db_adapter import _execute  # type: ignore  # house adapter; credentials never handled here

    return lambda sql, params=None, fetch="all": _execute(sql, params, fetch=fetch)


def scan(symbols: Iterable[str], query: Callable) -> dict[str, dict]:
    out = {}
    for sym in symbols:
        rows = [dict(r) for r in (query(SERIES_SQL, (sym, LOOKBACK_DAYS), fetch="all") or [])]
        res = classify(rows)
        if res["pre_listing"] or res["suspect"] or res["break"]:
            out[sym] = res
    return out


def apply(found: dict[str, dict], *, grant: str, connect: Callable) -> int:
    """Archive each PRE_LISTING row into ticker_prices_quarantine, then remove it from the series (one transaction)."""
    conn = connect()
    moved = 0
    try:
        cur = conn.cursor()
        for sym, res in found.items():
            for r in res["pre_listing"]:
                cur.execute(
                    """INSERT INTO ticker_prices_quarantine
                         (original_id, symbol, price_date, close_price, source, quality_reason, baseline,
                          deviation_ratio, quarantined_at, quarantined_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)""",
                    (r["id"], sym, r["date"], r["close"], r["source"],
                     f"pre_listing_bar: {r['reason']}; following source {r['following_source']}",
                     r["baseline"], r["ratio"], f"{SCHEMA} grant={grant}"))
                cur.execute("DELETE FROM ticker_prices WHERE id=%s", (r["id"],))
                moved += cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return moved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Quarantine pre-listing / reused-symbol price bars (dry run by default).")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--prospectus-universe", action="store_true", help="every symbol with a prospectus directory")
    ap.add_argument("--apply", action="store_true", help="operator only: archive + remove PRE_LISTING rows")
    ap.add_argument("--grant", default="", help="state-write grant id (required with --apply; recorded)")
    args = ap.parse_args(argv)
    if args.apply and not args.grant.strip():
        print("REFUSED: --apply needs --grant <state-write grant id> (operator-only correction)")
        return 2
    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.prospectus_universe:
        from scripts.lib.anthropic_routing import state_root
        syms = sorted(set(syms) | set(prospectus_symbols(Path(state_root()))))
    if not syms:
        print("nothing to scan: pass --symbols or --prospectus-universe")
        return 2
    found = scan(syms, default_query())
    moved = None
    if args.apply:
        from db_adapter import get_connection  # type: ignore
        moved = apply(found, grant=args.grant.strip(), connect=get_connection)
    print(json.dumps({"schema": SCHEMA, "authority": AUTHORITY, "mode": "apply" if args.apply else "dry_run",
                      "scanned": len(syms), "hits": found,
                      "pre_listing": sum(len(r["pre_listing"]) for r in found.values()),
                      "suspect_reported_only": sum(len(r["suspect"]) for r in found.values()),
                      "breaks_reported_only": sum(1 for r in found.values() if r["break"]),
                      "rows_quarantined": moved}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
