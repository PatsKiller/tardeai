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

One HTTP request per view through the shared Finviz throttle, waiting at most
THROTTLE_WAIT_S for a slot (the probe budget), so a run is bounded well under the
300 s unit / n8n lane timeout whatever the throttle state. No writes except the
receipt. Exit 1 on any BLOCK, 2 when it could not run.

``--dry-run`` makes NO Finviz request (each one counts against the export quota)
and writes nothing. It builds the same plan the real run executes -- views,
probe tickers, the export URL with the token redacted, token present or not,
the throttle's read-only status (would-wait seconds, corrupt fields), whether
market_quotes answers -- prints it with the receipt it would write and the
worst-case runtime, and returns before ``_fetch`` is reachable. Exit 2 when the
real run could not start (no token). *Cause 2026-10-10: the old dry run fetched
every view and only skipped the receipt; with the throttle state holding a
last_request 76 days in the future it slept 300 s per view and the n8n shadow
fire was killed at 300 s (RUN_TIMEOUT 01:44Z and 13:11Z), holding the single
executor worker for five minutes each time.*

USAGE
-----
    python scripts/check_finviz_view_contracts.py            # report + receipt
    python scripts/check_finviz_view_contracts.py --json
    python scripts/check_finviz_view_contracts.py --dry-run  # plan only: no Finviz request, no receipt

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
#: Max seconds to wait for a throttle slot per view (finviz_http's probe budget; env-tunable there).
THROTTLE_WAIT_S = float(os.getenv("FINVIZ_PROBE_THROTTLE_TIMEOUT", "30"))
HTTP_TIMEOUT_S = 20
DB_CONNECT_TIMEOUT_S = 5
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
                                options="-c default_transaction_read_only=on",
                                connect_timeout=DB_CONNECT_TIMEOUT_S)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT ON (symbol) symbol, price FROM market_quotes WHERE symbol = ANY(%s) "
                    "AND fetched_at > now() - interval '3 days' AND price > 0 ORDER BY symbol, fetched_at DESC",
                    (list(PROBE_TICKERS),))
        rows = {s: float(p) for s, p in cur.fetchall()}
        conn.close()
        return rows
    except Exception:
        return None


def _env(key: str, default: str = "") -> str:
    import portfolio_technical as pt  # noqa: PLC0415

    return pt._env(key, default)


def _url(view: int, token: str) -> str:
    return f"https://elite.finviz.com/export.ashx?v={view}&t={','.join(PROBE_TICKERS)}&auth={token}"


def worst_case_seconds(n_views: int) -> float:
    """Upper bound on a real run: DB connect + per view (throttle wait + HTTP timeout)."""
    return DB_CONNECT_TIMEOUT_S + n_views * (THROTTLE_WAIT_S + HTTP_TIMEOUT_S)


def _throttle_status() -> dict:
    try:
        import finviz_throttle  # noqa: PLC0415

        return finviz_throttle.status()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def plan(token_present: bool, quotes_reachable: bool, throttle: dict) -> dict:
    """Pure: what a real run would do. Reads nothing, requests nothing."""
    views = sorted(VIEW_CONTRACTS)
    notes = []
    if not token_present:
        notes.append("FINVIZ_API_TOKEN not set: the real run would fail every view (exit 2)")
    if throttle.get("corrupt"):
        notes.append(f"throttle state corrupt {throttle['corrupt']}: acquire() discards it on the next request")
    wait = float(throttle.get("would_wait_s") or 0)
    if wait > THROTTLE_WAIT_S:
        notes.append(f"throttle busy {wait:.0f}s > {THROTTLE_WAIT_S:.0f}s budget: the real run proceeds after "
                     f"{THROTTLE_WAIT_S:.0f}s per view (fail-open)")
    if not quotes_reachable:
        notes.append("price cross-check would be skipped: market_quotes not reachable")
    return {"views": views, "probe_tickers": list(PROBE_TICKERS),
            "urls": [_url(v, "<redacted>") for v in views], "finviz_requests_planned": len(views),
            "finviz_requests_made": 0, "token_present": token_present, "quotes_reachable": quotes_reachable,
            "throttle": throttle, "worst_case_seconds": worst_case_seconds(len(views)),
            "would_write": str(RECEIPT), "notes": notes}


def _fetch(view: int) -> str:
    from finviz_http import finviz_get  # noqa: PLC0415

    token = _env("FINVIZ_API_TOKEN")
    if not token:
        raise RuntimeError("FINVIZ_API_TOKEN not set")
    resp = finviz_get(_url(view, token), headers={"User-Agent": _env("FINVIZ_USER_AGENT", "Mozilla/5.0")},
                      timeout=HTTP_TIMEOUT_S, throttle_timeout=THROTTLE_WAIT_S, raise_on_429=False)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="plan only: no Finviz request (quota), no receipt")
    args = ap.parse_args()
    quotes = _latest_quotes()
    if args.dry_run:
        # Returns here: _fetch (the quota spend) and the receipt write below are unreachable in a dry run.
        p = plan(bool(_env("FINVIZ_API_TOKEN")), quotes is not None, _throttle_status())
        report = {"schema": SCHEMA, "mode": "dry_run", "ran_at": datetime.now(timezone.utc).isoformat(),
                  "plan": p, "authority": "READ_ONLY_ADVISORY"}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"DRY RUN finviz_requests_made=0 planned={p['finviz_requests_planned']} views={p['views']} "
                  f"tickers={','.join(p['probe_tickers'])}")
            print(f"token_present={p['token_present']} quotes_reachable={p['quotes_reachable']} "
                  f"throttle_would_wait_s={p['throttle'].get('would_wait_s')} "
                  f"worst_case_s={p['worst_case_seconds']:.0f}")
            for n in p["notes"]:
                print(f"   note  {n}")
            print(f"would write {p['would_write']}")
        return 0 if p["token_present"] else 2
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
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if errors and not results:
        return 2
    return 1 if report["block"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
