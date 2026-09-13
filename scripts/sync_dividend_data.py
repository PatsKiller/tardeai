#!/usr/bin/env python3
"""sync_dividend_data.py — Sync dividend data from yfinance (declared provider) to ticker_dividend_data.

Replaces seed-only ticker_dividend_data with real API data.

Usage:
    python3 scripts/sync_dividend_data.py [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    except Exception:
        return {}


def sync(symbols: list = None) -> dict:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if not symbols:
        cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r["symbol"] for r in cur.fetchall()]
        # Filter to real tickers (skip Fidelity proprietary)
        symbols = [s for s in symbols if not any(s.startswith(p) for p in ["FID-", "SP500-", "SS-", "TRP-", "WM-", "AB-", "JPM-", "VANG-"])]

    updated = 0
    for sym in symbols[:30]:  # Rate limit
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

    result = {"symbols_checked": len(symbols[:30]), "updated": updated}
    print(f"[dividend-sync] Updated {updated} of {len(symbols[:30])} symbols from yfinance")
    return result


if __name__ == "__main__":
    r = sync()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2, default=str))
