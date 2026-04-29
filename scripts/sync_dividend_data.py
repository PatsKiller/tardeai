#!/usr/bin/env python3
"""sync_dividend_data.py — Sync live dividend data from FMP API to DB.

Replaces seed-only ticker_dividend_data with real API data.

Usage:
    python3 scripts/sync_dividend_data.py [--json]
"""
import json, os, sys, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_fmp_key():
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("FMP_API_KEY="): return line.split("=", 1)[1].strip()
    return ""


def _fetch_fmp_dividend(symbol: str, api_key: str) -> dict:
    """Fetch dividend data from FMP stable profile API."""
    try:
        url = f"https://financialmodelingprep.com/stable/profile?symbol={symbol}&apikey={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data and isinstance(data, list) and data[0]:
                d = data[0]
                result = {}
                last_div = float(d.get("lastDividend", 0) or 0)
                if last_div > 0:
                    result["annual_dividend_per_share"] = round(last_div * 4, 4)  # Quarterly estimate
                    price = float(d.get("price", 0) or 0)
                    if price > 0:
                        result["dividend_yield_pct"] = round(last_div * 4 / price * 100, 2)
                beta = d.get("beta")
                if beta:
                    result["_beta"] = float(beta)
                return result
    except Exception as e:
        pass
    return {}


def sync(symbols: list = None) -> dict:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    api_key = _get_fmp_key()

    if not api_key:
        print("[dividend-sync] No FMP_API_KEY configured")
        return {"error": "No FMP_API_KEY"}

    if not symbols:
        cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r["symbol"] for r in cur.fetchall()]
        # Filter to real tickers (skip Fidelity proprietary)
        symbols = [s for s in symbols if not any(s.startswith(p) for p in ["FID-", "SP500-", "SS-", "TRP-", "WM-", "AB-", "JPM-", "VANG-"])]

    updated = 0
    for sym in symbols[:30]:  # Rate limit
        data = _fetch_fmp_dividend(sym, api_key)
        if data:
            # Remove internal fields
            clean = {k: v for k, v in data.items() if not k.startswith("_") and v is not None}
            if clean:
                yld = clean.get("dividend_yield_pct")
                annual = clean.get("annual_dividend_per_share")
                cur.execute("""
                    INSERT INTO ticker_dividend_data (symbol, dividend_yield_pct, annual_dividend_per_share, source, last_updated, updated_at)
                    VALUES (%s, %s, %s, 'fmp_api', now(), now())
                    ON CONFLICT (symbol) DO UPDATE SET
                        dividend_yield_pct = COALESCE(EXCLUDED.dividend_yield_pct, ticker_dividend_data.dividend_yield_pct),
                        annual_dividend_per_share = COALESCE(EXCLUDED.annual_dividend_per_share, ticker_dividend_data.annual_dividend_per_share),
                        source = 'fmp_api', last_updated = now(), updated_at = now()
                """, (sym, yld, annual))
                updated += 1
                print(f"  {sym}: yield={yld}% annual_div={annual}")

    conn.commit()
    conn.close()

    result = {"symbols_checked": len(symbols[:30]), "updated": updated}
    print(f"[dividend-sync] Updated {updated} of {len(symbols[:30])} symbols from FMP API")
    return result


if __name__ == "__main__":
    r = sync()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2, default=str))
