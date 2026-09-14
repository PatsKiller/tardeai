#!/usr/bin/env python3
"""Do the Finviz saved views still carry the columns our readers depend on? Read-only.

WHY
---
Finviz export columns belong to saved views that can be edited on finviz.com.
A reader that maps by position mis-reads a changed view confidently; a reader
that maps by header name (lib/finviz_csv) refuses it -- but only at run time,
batch by batch, inside whichever job happens to run next. This check asks
Finviz for each declared view's header once, for three liquid tickers, and
compares it with ``lib/finviz_csv.VIEW_CONTRACTS`` plus a unit sanity row:

* every required header present (the drift gate);
* AAPL ``Market Cap`` above 1,000,000 -- the export is in MILLIONS; a value in
  billions (~4,800) would mean the unit changed under every consumer;
* ``Average Volume`` for AAPL between 1,000 and 1,000,000 -- THOUSANDS of shares;
* a price for each ticker within 50% of the latest ``market_quotes`` price when
  the database is reachable (an independent source; skipped, and said so, when not).

One HTTP request per view through the shared Finviz throttle. No writes except
the receipt. Exit 1 on any BLOCK, 2 when it could not run.

USAGE
-----
    python scripts/check_finviz_view_contracts.py            # report + receipt
    python scripts/check_finviz_view_contracts.py --json
    python scripts/check_finviz_view_contracts.py --dry-run  # report only, no receipt

AUTHORITY: READ_ONLY_ADVISORY. MBI = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.finviz_csv import VIEW_CONTRACTS, FinvizContractError, normalise_units, parse_export, to_number  # noqa: E402

SCHEMA = "FinvizViewContractReport@v1"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "finviz_view_contracts_last_run.json"
PROBE_TICKERS = ("AAPL", "MSFT", "HPE")
NO_CONSUMER_REASON = "data-integrity gate; a scheduled run or an operator invokes it and reads the receipt"


def evaluate(view: int, text: str, quotes: dict[str, float] | None) -> dict:
    """Pure: findings for one view's export text."""
    out: dict = {"view": view, "block": [], "warn": [], "headers": []}
    try:
        rows = parse_export(text, view=view)
    except FinvizContractError as exc:
        out["block"].append(f"contract: {exc}")
        return out
    out["headers"] = sorted({k for r in rows for k in r})
    by_sym = {str(r.get("Ticker") or "").upper(): r for r in rows}
    missing = [t for t in PROBE_TICKERS if t not in by_sym]
    if missing:
        out["warn"].append(f"probe tickers absent from export: {missing}")
    aapl = by_sym.get("AAPL")
    if aapl and "Market Cap" in aapl:
        cap_usd = normalise_units(aapl)["market_cap_usd"]
        if cap_usd is None or cap_usd < 1e12:
            out["block"].append(f"unit: AAPL Market Cap {aapl.get('Market Cap')!r} is not in MILLIONS (want > 1,000,000)")
    if aapl and "Average Volume" in aapl:
        av = to_number(aapl.get("Average Volume"))
        if av is None or not (1e3 <= av <= 1e6):
            out["block"].append(f"unit: AAPL Average Volume {aapl.get('Average Volume')!r} is not in THOUSANDS")
    if quotes is None:
        out["warn"].append("price cross-check skipped: market_quotes not reachable")
    else:
        for sym, row in by_sym.items():
            px, q = to_number(row.get("Price")), quotes.get(sym)
            if px and q and abs(px - q) / q > 0.5:
                out["block"].append(f"price: {sym} Finviz {px} vs market_quotes {q}")
    return out


def _latest_quotes() -> dict[str, float] | None:
    try:
        import psycopg2  # noqa: PLC0415

        conn = psycopg2.connect(host=os.environ.get("DB_HOST", "localhost"), dbname=os.environ.get("DB_NAME", "trade_ai"),
                                user=os.environ.get("DB_USER", "trade_ai"), password=os.environ.get("DB_PASSWORD"),
                                options="-c default_transaction_read_only=on", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT ON (symbol) symbol, price FROM market_quotes WHERE symbol = ANY(%s) "
                    "AND fetched_at > now() - interval '3 days' AND price > 0 ORDER BY symbol, fetched_at DESC",
                    (list(PROBE_TICKERS),))
        rows = {s: float(p) for s, p in cur.fetchall()}
        conn.close()
        return rows
    except Exception:
        return None


def _fetch(view: int) -> str:
    from finviz_http import finviz_get  # noqa: PLC0415
    import portfolio_technical as pt  # noqa: PLC0415

    token = pt._env("FINVIZ_API_TOKEN")
    if not token:
        raise RuntimeError("FINVIZ_API_TOKEN not set")
    url = f"https://elite.finviz.com/export.ashx?v={view}&t={','.join(PROBE_TICKERS)}&auth={token}"
    resp = finviz_get(url, headers={"User-Agent": pt._env("FINVIZ_USER_AGENT", "Mozilla/5.0")},
                      timeout=20, raise_on_429=False)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="report only; write no receipt")
    args = ap.parse_args()
    quotes = _latest_quotes()
    results, errors = [], []
    for view in sorted(VIEW_CONTRACTS):
        try:
            results.append(evaluate(view, _fetch(view), quotes))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"v={view}: {type(exc).__name__}: {exc}")
    report = {"schema": SCHEMA, "ran_at": datetime.now(timezone.utc).isoformat(), "views": results,
              "errors": errors, "block": sum(len(r["block"]) for r in results),
              "authority": "READ_ONLY_ADVISORY"}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in results:
            state = "BLOCK" if r["block"] else "OK"
            print(f"v={r['view']:<4} {state:<6} headers={len(r['headers'])}")
            for b in r["block"]:
                print(f"   BLOCK {b}")
            for w in r["warn"]:
                print(f"   warn  {w}")
        for e in errors:
            print(f"ERROR {e}")
        print(f"block={report['block']} errors={len(errors)}")
    if not args.dry_run:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if errors and not results:
        return 2
    return 1 if report["block"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
