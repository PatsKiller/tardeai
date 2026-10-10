#!/usr/bin/env python3
"""sync_dividend_data.py — Sync dividend data from yfinance (declared provider) to ticker_dividend_data.

Replaces seed-only ticker_dividend_data with real API data.

Usage:
    python3 scripts/sync_dividend_data.py [--json] [--dry-run]

Lane ``sync-dividend-data`` (cron L216). ``--dry-run`` opens a READ ONLY session, reads the symbol
universe (ticker_strategy_classifications, the same query as a real run), prints what a real run would
fetch and upsert, and returns before any yfinance call or INSERT is reachable; it writes no receipt.
A real run writes ``<state_root>/data/runtime/sync-dividend-data_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success).

Exit codes: 0 = ran (symbols without a dividend, or zero symbols, are findings, not failures);
1 = the run failed: crash / DB unavailable (failed receipt, exception re-raised), or every symbol's
yfinance fetch raised (nothing could be fetched when work existed); 2 = usage error.
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "sync-dividend-data"
SYMBOL_CAP = 30  # rate limit
_SKIP_PREFIXES = ["FID-", "SP500-", "SS-", "TRP-", "WM-", "AB-", "JPM-", "VANG-"]
#: yfinance fetches that raised during the last sync() in this process (read by main() for the exit code)
_FETCH_ERRORS: list = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.sync_dividend_data
        from scripts.lib import lane_last_receipt as lr
    return lr


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _fetch_yf_dividend(symbol: str) -> dict:
    """Dividend facts from yfinance (declared provider for the dividends domain).

    FMP retired 2026-09-13 (paid-only; 403/429 since July). yfinance `info` carries
    dividendRate (annual $/share), exDividendDate (epoch) and the last price.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        result = {}
        rate = info.get("dividendRate")
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if rate and float(rate) > 0:
            result["annual_dividend_per_share"] = round(float(rate), 4)
            if price and float(price) > 0:
                result["dividend_yield_pct"] = round(float(rate) / float(price) * 100, 2)
        exd = info.get("exDividendDate")
        if exd:
            result["ex_div_date"] = datetime.utcfromtimestamp(int(exd)).date().isoformat()
        beta = info.get("beta")
        if beta:
            result["_beta"] = float(beta)
        return result
    except Exception as exc:
        _FETCH_ERRORS.append(f"{symbol}: {type(exc).__name__}")
        return {}


def _universe(cur) -> list:
    """Active strategy-classified symbols, Fidelity proprietary codes removed (read-only SELECT)."""
    cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    # Filter to real tickers (skip Fidelity proprietary)
    return [s for s in symbols if not any(s.startswith(p) for p in _SKIP_PREFIXES)]


def preview(symbols: list = None) -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, universe SELECT only; no yfinance call, no INSERT."""
    import psycopg2.extras
    conn = _get_conn()
    try:
        _receipt_lib().enforce_readonly(conn)
        if not symbols:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            symbols = _universe(cur)
    finally:
        conn.close()
    batch = symbols[:SYMBOL_CAP]
    return {"symbols_total": len(symbols), "would_check": len(batch), "symbols": batch}


def sync(symbols: list = None) -> dict:
    import psycopg2.extras
    _FETCH_ERRORS.clear()
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if not symbols:
        symbols = _universe(cur)

    updated = 0
    for sym in symbols[:SYMBOL_CAP]:  # Rate limit
        data = _fetch_yf_dividend(sym)
        if data:
            # Remove internal fields
            clean = {k: v for k, v in data.items() if not k.startswith("_") and v is not None}
            if clean:
                yld = clean.get("dividend_yield_pct")
                annual = clean.get("annual_dividend_per_share")
                exd = clean.get("ex_div_date")
                cur.execute("""
                    INSERT INTO ticker_dividend_data (symbol, dividend_yield_pct, annual_dividend_per_share, ex_div_date, source, last_updated, updated_at)
                    VALUES (%s, %s, %s, %s, 'yfinance', now(), now())
                    ON CONFLICT (symbol) DO UPDATE SET
                        dividend_yield_pct = COALESCE(EXCLUDED.dividend_yield_pct, ticker_dividend_data.dividend_yield_pct),
                        annual_dividend_per_share = COALESCE(EXCLUDED.annual_dividend_per_share, ticker_dividend_data.annual_dividend_per_share),
                        ex_div_date = COALESCE(EXCLUDED.ex_div_date, ticker_dividend_data.ex_div_date),
                        source = 'yfinance', last_updated = now(), updated_at = now()
                """, (sym, yld, annual, exd))
                updated += 1
                print(f"  {sym}: yield={yld}% annual_div={annual}")

    conn.commit()
    conn.close()

    result = {"symbols_checked": len(symbols[:SYMBOL_CAP]), "updated": updated,
              "fetch_errors": len(_FETCH_ERRORS)}
    print(f"[dividend-sync] Updated {updated} of {len(symbols[:SYMBOL_CAP])} symbols from yfinance")
    return result


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Sync yfinance dividend data into ticker_dividend_data.")
    ap.add_argument("--json", action="store_true", help="also print the result as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="read the symbol universe (READ ONLY) and report; no fetch, no write, no receipt")
    a = ap.parse_args(argv)
    if a.dry_run:
        # Structural (AGENTS.md §6): sync() -- yfinance + INSERT -- is not reachable from this branch.
        plan = preview()
        if a.json:
            print(json.dumps(plan, indent=2, default=str))
        _receipt_lib().dry_run_report(
            LANE_ID, {"symbols_total": plan["symbols_total"], "would_check": plan["would_check"],
                      "first_symbols": plan["symbols"][:10]},
            would_write=[f"ticker_dividend_data upsert (<= {plan['would_check']} rows, yfinance dividendRate)"])
        return 0
    started = _receipt_lib().now_iso()
    try:
        r = sync()
    except Exception as exc:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="sync_dividend_data.py", error=f"{type(exc).__name__}: {exc}")
        raise
    if a.json:
        print(json.dumps(r, indent=2, default=str))
    failed = r["symbols_checked"] > 0 and r["fetch_errors"] >= r["symbols_checked"]
    rc = 1 if failed else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                                      script="sync_dividend_data.py", summary=r)
    return rc


if __name__ == "__main__":
    sys.exit(main())
