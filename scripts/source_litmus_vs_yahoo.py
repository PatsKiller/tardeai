#!/usr/bin/env python3
"""Litmus: are the closes we store the closes that happened? Read-only.

WHY
---
2026-09-14, against Yahoo Finance for Friday 09-11 (sampled per source):

    source               compared  within 1%  off >1%  off >10%
    market_quotes              79         56       23         3   (29% off; micro-caps, IEX last print)
    finviz                     25         22        3         0
    portfolio_repricer         20         20        0         0

and, the same morning, Alpaca prev_close was one session stale for 7 of 9
symbols, and the repricer wrote sub-share position values as closes. None of it
failed anything: every value parsed and stored. A store is only trustworthy if
it is checked against a source that did not produce it.

WHAT
----
Samples the latest completed session in ``ticker_prices`` per ``source``, fetches
the same session's close from Yahoo Finance in ONE batched request, and reports
per source: compared / within tolerance / off / badly off. A source whose share
of badly-off rows exceeds its threshold is a BLOCK (exit 1). The receipt lists the
worst rows so a quarantine run can act on evidence -- this tool never edits or
deletes a price.

    python scripts/source_litmus_vs_yahoo.py --dry-run      # report, no receipt
    python scripts/source_litmus_vs_yahoo.py --json

AUTHORITY: READ_ONLY_ADVISORY. MBI = 0. No model calls.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "SourceLitmusReport@v1"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "source_litmus_last_run.json"
NO_CONSUMER_REASON = "data-integrity gate; a scheduled run or an operator invokes it and reads the receipt"

TOLERANCE = 0.01          # within 1% of the independent close is a match
BADLY_OFF = 0.10          # more than 10% is a wrong price, not a rounding difference
#: A source BLOCKs when more than this share of its compared rows is badly off.
BLOCK_SHARE = {"default": 0.02}
SAMPLE_PER_SOURCE = {"default": 40, "market_quotes": 120}


def evaluate(samples: Iterable[tuple[str, str, float]], reference: dict[str, Optional[float]]) -> dict:
    """Pure. samples = (symbol, source, stored_close); reference = {symbol: independent close}."""
    per: dict[str, dict] = defaultdict(lambda: {"compared": 0, "within": 0, "off": 0, "badly_off": 0,
                                                "no_reference": 0, "worst": []})
    for sym, src, stored in samples:
        st = per[src]
        ref = reference.get(sym)
        if not ref or ref <= 0 or stored is None:
            st["no_reference"] += 1
            continue
        st["compared"] += 1
        dev = abs(float(stored) - ref) / ref
        if dev <= TOLERANCE:
            st["within"] += 1
            continue
        st["off"] += 1
        if dev > BADLY_OFF:
            st["badly_off"] += 1
        st["worst"].append({"symbol": sym, "stored": float(stored), "reference": round(ref, 4),
                            "deviation_pct": round(dev * 100, 1)})
    block: list[str] = []
    for src, st in per.items():
        st["worst"] = sorted(st["worst"], key=lambda w: -w["deviation_pct"])[:15]
        limit = BLOCK_SHARE.get(src, BLOCK_SHARE["default"])
        share = (st["badly_off"] / st["compared"]) if st["compared"] else 0.0
        st["badly_off_share"] = round(share, 4)
        if st["compared"] and share > limit:
            block.append(f"{src}: {st['badly_off']}/{st['compared']} closes off by >{int(BADLY_OFF * 100)}% "
                         f"(limit {limit:.0%})")
    return {"sources": dict(per), "block": block}


def _db():
    import psycopg2  # noqa: PLC0415

    def setting(k, d=""):
        v = os.getenv(k, "")
        if v:
            return v
        try:
            for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{k}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
        return d
    return psycopg2.connect(host=setting("DB_HOST", "localhost"), dbname=setting("DB_NAME", "trade_ai"),
                            user=setting("DB_USER", "trade_ai"), password=setting("DB_PASSWORD"),
                            options="-c default_transaction_read_only=on", connect_timeout=5)


def _sample(cur, session: date, seed: int) -> list[tuple[str, str, float]]:
    cur.execute("SELECT symbol, source, close_price FROM ticker_prices WHERE price_date = %s "
                "AND symbol ~ '^[A-Z]{1,5}$' AND close_price > 0", (session,))
    by_src: dict[str, list] = defaultdict(list)
    for sym, src, close in cur.fetchall():
        by_src[str(src)].append((str(sym), str(src), float(close)))
    rng = random.Random(seed)
    out: list[tuple[str, str, float]] = []
    for src, rows in by_src.items():
        k = min(len(rows), SAMPLE_PER_SOURCE.get(src, SAMPLE_PER_SOURCE["default"]))
        out += rng.sample(rows, k)
    return out


def _last_session(cur) -> date:
    """The latest completed WEEKDAY with a real day's worth of closes.

    ``max(price_date)`` returned Sunday 2026-09-13 on the first dry run: closes
    are written with weekend dates, and Yahoo has no close for a day with no
    session, so all 120 samples came back "no reference" and the run exited 0.
    """
    cur.execute("""SELECT price_date FROM ticker_prices
                   WHERE price_date < CURRENT_DATE AND extract(isodow FROM price_date) < 6
                   GROUP BY price_date HAVING count(*) >= 100
                   ORDER BY price_date DESC LIMIT 1""")
    return cur.fetchone()[0]


def _weekend_rows(cur) -> list[dict]:
    """Closes dated Saturday/Sunday in the last 30 days: a close for a day with no session."""
    cur.execute("""SELECT price_date, source, count(*) FROM ticker_prices
                   WHERE price_date > CURRENT_DATE - 30 AND extract(isodow FROM price_date) >= 6
                   GROUP BY 1, 2 ORDER BY 1 DESC""")
    return [{"price_date": str(d), "source": s, "rows": int(n)} for d, s, n in cur.fetchall()]


def _yahoo_closes(symbols: list[str], session: date) -> dict[str, Optional[float]]:
    import yfinance as yf  # noqa: PLC0415
    from datetime import timedelta  # noqa: PLC0415

    df = yf.download(symbols, start=(session - timedelta(days=3)).isoformat(),
                     end=(session + timedelta(days=1)).isoformat(), progress=False,
                     auto_adjust=False, group_by="ticker", threads=True)
    out: dict[str, Optional[float]] = {}
    for s in symbols:
        try:
            out[s] = float(df[s]["Close"].dropna().loc[session.isoformat()])
        except Exception:
            out[s] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="report only; write no receipt")
    ap.add_argument("--seed", type=int, default=int(datetime.now(timezone.utc).strftime("%Y%m%d")))
    args = ap.parse_args()
    try:
        conn = _db()
        cur = conn.cursor()
        session = _last_session(cur)
        samples = _sample(cur, session, args.seed)
        weekend = _weekend_rows(cur)
        conn.close()
        reference = _yahoo_closes(sorted({s for s, _, _ in samples}), session)
    except Exception as exc:  # noqa: BLE001 -- cannot-run is exit 2, never a green 0
        print(f"ERROR: could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    result = evaluate(samples, reference)
    compared = sum(st["compared"] for st in result["sources"].values())
    report = {"schema": SCHEMA, "ran_at": datetime.now(timezone.utc).isoformat(), "session": session.isoformat(),
              "reference": "yahoo_finance daily close", "tolerance": TOLERANCE, "badly_off": BADLY_OFF,
              "compared": compared, "weekend_dated_rows_30d": weekend,
              **result, "authority": "READ_ONLY_ADVISORY"}
    if weekend:
        print(f"WARN closes dated on a weekend in 30 days: {sum(w['rows'] for w in weekend)} rows "
              f"({', '.join(sorted({w['source'] for w in weekend}))})")
    if compared == 0:
        # Nothing checked is not "nothing wrong" (AGENTS rule 8).
        print("ERROR: no stored close could be compared with the reference", file=sys.stderr)
        if not args.dry_run:
            RECEIPT.parent.mkdir(parents=True, exist_ok=True)
            RECEIPT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return 2
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Source litmus vs Yahoo — session {session}")
        print(f"{'source':20} {'compared':>8} {'within1%':>9} {'off':>5} {'>10%':>5} {'no_ref':>7}")
        for src, st in sorted(result["sources"].items()):
            print(f"{src:20} {st['compared']:>8} {st['within']:>9} {st['off']:>5} {st['badly_off']:>5} {st['no_reference']:>7}")
        for b in result["block"]:
            print(f"BLOCK {b}")
    if not args.dry_run:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 1 if result["block"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
