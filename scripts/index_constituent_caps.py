#!/usr/bin/env python3
"""Market caps for the Market Risk Engine's index constituents (DSN-20261031-market-risk-engine, event category).

The engine measures earnings concentration over ``config/market_risk_policy.yaml`` ``event.index_universe`` (the 35
largest constituents) and reads their caps from ``market_quotes.market_cap`` (``PgReader.index_weights``). The quote
ingest only asks yfinance for names Alpaca cannot price, so the mega caps -- all priced by Alpaca -- never get a cap
(measured 2026-10-31: 4 of 35 within 30 days), and earnings concentration reads "not measured".

This refresher asks the EXISTING registered fallback provider (yfinance, registry domain ``quote_price``) for those
35 names once a day and writes ``symbol, price, market_cap`` through the single writer
(``lib.writers.market_quotes_writer.write_market_quotes``, source ``yfinance:index_caps``). No new store, no new
provider. Default is a dry run (prints what it would write); ``--apply`` writes. ``--universe`` overrides the list.
AUTHORITY: READ_ONLY_ADVISORY. Market data only; never touches a broker account or an order route.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SOURCE = "yfinance:index_caps"


def universe() -> list[str]:
    from lib.market_risk.policy import load_policy

    return [str(s).upper() for s in (load_policy().get("event") or {}).get("index_universe") or []]


def _yf_symbol(sym: str) -> str:
    return sym.replace(".", "-")  # BRK.B -> BRK-B on Yahoo


def fetch(
    symbols: list[str], *, info_of: Callable[[str], dict[str, Any]] | None = None
) -> tuple[list[dict], list[str]]:
    """One row per symbol with a positive cap and price; the symbols that returned neither."""
    if info_of is None:
        import yfinance as yf

        def info_of(s: str) -> dict[str, Any]:
            return yf.Ticker(_yf_symbol(s)).info or {}

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for s in symbols:
        try:
            info = info_of(s)
        except Exception as exc:  # one name failing must not cost the other 34; it is reported, not swallowed
            print(f"[index-caps] {s}: {type(exc).__name__}: {exc}", file=sys.stderr)
            missing.append(s)
            continue
        cap = info.get("marketCap")
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not cap or not price or float(cap) <= 0 or float(price) <= 0:
            missing.append(s)
            continue
        rows.append({"symbol": s, "price": float(price), "market_cap": int(cap)})
    return rows, missing


def run(*, apply: bool, symbols: list[str] | None = None, info_of=None, conn: Any = None) -> dict[str, Any]:
    syms = symbols or universe()
    rows, missing = fetch(syms, info_of=info_of)
    total = sum(r["market_cap"] for r in rows)
    out: dict[str, Any] = {
        "apply": apply,
        "universe": len(syms),
        "with_cap": len(rows),
        "coverage": round(len(rows) / len(syms), 3) if syms else 0.0,
        "missing": missing,
        "top": [
            {
                "symbol": r["symbol"],
                "cap_bn": round(r["market_cap"] / 1e9, 1),
                "weight": round(r["market_cap"] / total, 4) if total else None,
            }
            for r in sorted(rows, key=lambda r: -r["market_cap"])
        ],
        "written": 0,
    }
    if not apply or not rows:
        return out
    from lib.writers.market_quotes_writer import write_market_quotes

    own = conn is None
    if own:
        import external_market_data_ingest as ingest

        conn = ingest._get_conn()
    try:
        rc = write_market_quotes(conn.cursor(), rows, source=SOURCE)
        out["written"] = int(rc.rows_accepted)
        conn.commit()
    finally:
        if own:
            conn.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write to market_quotes (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--universe", help="comma-separated symbols instead of the policy's event.index_universe")
    a = ap.parse_args(argv)
    syms = [s.strip().upper() for s in a.universe.split(",") if s.strip()] if a.universe else None
    out = run(apply=bool(a.apply) and not a.dry_run, symbols=syms)
    print(json.dumps(out, indent=2))
    return 0 if out["coverage"] >= 0.8 else 2


if __name__ == "__main__":
    raise SystemExit(main())
