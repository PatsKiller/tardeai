#!/usr/bin/env python3
"""Single writer of ``etf_holdings_snapshot`` — top holdings of held and watched ETFs (design P1-T9, precision PR).

Source: yfinance fund data (provider already granted; free; the top 10 holdings is what it serves — the registry row's
"top-25" is an upper bound, not a promise). Fund holdings only — never a position, amount or account (§2A).

  python3 scripts/lib/writers/etf_holdings_writer.py                 # dry run: fetch and print, write nothing
  python3 scripts/lib/writers/etf_holdings_writer.py --symbols SCHG  # one fund
  python3 scripts/lib/writers/etf_holdings_writer.py --apply         # write — REFUSED until the §7A row is granted

§7A: a store gets its registry row before any write. ``--apply`` checks ``config/data_source_authority.json`` for the
``etf_holdings_snapshot`` domain in the granted list naming this file as its writer, and refuses (exit 3) otherwise.
The row is proposed in PR #2333. Cadence (Sun 19:00 ET weekly + on a new ETF position, lane ``etf-holdings-weekly``)
is declared there and installed only on the operator's word (§25.10.2).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DOMAIN = "etf_holdings_snapshot"
WRITER = "scripts/lib/writers/etf_holdings_writer.py"
MIGRATION = ROOT / "migrations" / "2026_10_31_etf_holdings_snapshot.sql"


def default_symbols() -> list[str]:
    funds = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text()).get("funds") or {}
    return sorted(k for k, v in funds.items() if isinstance(v, dict) and str(v.get("lookthrough") or "") != "none")


def fetch(symbol: str, *, ticker_factory: Any = None) -> list[dict[str, Any]]:
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    df = ticker_factory(symbol).funds_data.top_holdings
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for holding, rec in df.iterrows():
        w = rec.get("Holding Percent")
        if w is None:
            continue
        rows.append(
            {
                "etf": symbol.upper(),
                "holding": str(holding).upper(),
                "name": str(rec.get("Name") or ""),
                "weight": round(float(w), 6),
                "as_of": now,
                "source": "yfinance.funds_data.top_holdings",
            }
        )
    return rows


def granted() -> tuple[bool, str]:
    try:
        reg = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    except (OSError, ValueError) as exc:
        return False, f"registry unreadable: {exc}"
    for key in ("domains", "granted", "sources"):
        for row in reg.get(key) or []:
            if isinstance(row, dict) and row.get("domain") == DOMAIN:
                ok = str(row.get("status") or "").lower() in ("granted", "active") and row.get("writer") == WRITER
                return ok, f"{DOMAIN} row status={row.get('status')} writer={row.get('writer')}"
    return False, f"no {DOMAIN} row in config/data_source_authority.json (proposed in PR #2333)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--symbols", help="comma-separated ETF symbols (default: decomposed funds in fund_lookthrough.json)"
    )
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    syms = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else default_symbols()
    out, errors = [], {}
    for s in syms:
        try:
            out.extend(fetch(s))
        except Exception as exc:  # noqa: BLE001 — one fund failing is reported, the rest still print
            errors[s] = f"{type(exc).__name__}: {exc}"
    print(
        json.dumps(
            {
                "mode": "apply" if a.apply else "dry_run",
                "symbols": syms,
                "rows": len(out),
                "by_etf": {s: [r["holding"] for r in out if r["etf"] == s] for s in syms},
                "errors": errors,
            },
            indent=1,
        )
    )
    if not a.apply:
        return 0 if out else 1
    ok, why = granted()
    if not ok:
        print(f"REFUSED: §7A — {why}. Nothing written.", file=sys.stderr)
        return 3
    from scripts.lib.market_risk.reader import _default_conn  # the engine's connection helper

    conn = _default_conn()
    with conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO etf_holdings_snapshot (etf, holding, name, weight, as_of, source) VALUES "
            "(%(etf)s, %(holding)s, %(name)s, %(weight)s, %(as_of)s, %(source)s) ON CONFLICT (etf, holding, as_of) DO NOTHING",
            out,
        )
    print(f"wrote {len(out)} rows")
    return 0


if __name__ == "__main__":
    for p in (ROOT, ROOT / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    raise SystemExit(main())
