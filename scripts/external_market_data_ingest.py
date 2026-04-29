#!/usr/bin/env python3
"""external_market_data_ingest.py — yfinance + Alpha Vantage + FRED data ingestion.

Sources:
  yfinance: real-time quotes, dividends, earnings dates (no API key)
  Alpha Vantage: fundamentals, company overview (free key)
  FRED: macro economic series (free key, optional)

Usage:
    python3 scripts/external_market_data_ingest.py --test
    python3 scripts/external_market_data_ingest.py --quotes          # yfinance quotes for all symbols
    python3 scripts/external_market_data_ingest.py --fundamentals    # Alpha Vantage fundamentals
    python3 scripts/external_market_data_ingest.py --fred            # FRED macro snapshot
    python3 scripts/external_market_data_ingest.py --all             # Everything
"""
import json, os, sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith(f"{key}="): val = line.split("=", 1)[1].strip()
    return val


def _get_symbols() -> list:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()
    return [s for s in symbols if "-" not in s and len(s) <= 5]


# ── yfinance ─────────────────────────────────────────────────────────

def ingest_yfinance_quotes(symbols: list = None) -> dict:
    """Fetch real-time quotes via yfinance for all portfolio symbols."""
    import yfinance as yf
    if not symbols:
        symbols = _get_symbols()

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0

    for batch_start in range(0, len(symbols), 10):
        batch = symbols[batch_start:batch_start + 10]
        try:
            tickers = yf.Tickers(" ".join(batch))
            for sym in batch:
                try:
                    t = tickers.tickers.get(sym)
                    if not t:
                        continue
                    info = t.info or {}
                    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                    if not price:
                        continue

                    cur.execute("""
                        INSERT INTO market_quotes (symbol, source, price, prev_close, day_change_pct,
                            volume, avg_volume, market_cap, pe_ratio, forward_pe,
                            dividend_yield, fifty_two_week_high, fifty_two_week_low)
                        VALUES (%s, 'yfinance', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (sym, price,
                          info.get("previousClose"),
                          info.get("regularMarketChangePercent"),
                          info.get("volume"),
                          info.get("averageVolume"),
                          info.get("marketCap"),
                          info.get("trailingPE"),
                          info.get("forwardPE"),
                          info.get("dividendYield"),
                          info.get("fiftyTwoWeekHigh"),
                          info.get("fiftyTwoWeekLow")))
                    fetched += 1
                except Exception:
                    pass
        except Exception as e:
            print(f"  [yfinance] Batch error: {e}")

    conn.commit()
    conn.close()
    print(f"[yfinance] Fetched {fetched}/{len(symbols)} quotes")
    return {"source": "yfinance", "fetched": fetched, "total": len(symbols)}


# ── Alpha Vantage ────────────────────────────────────────────────────

def ingest_alpha_vantage(symbols: list = None, limit: int = 5) -> dict:
    """Fetch company fundamentals via Alpha Vantage (free tier: 25 calls/day)."""
    import urllib.request
    api_key = _env("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("[alpha-vantage] No ALPHA_VANTAGE_API_KEY — skipping")
        return {"source": "alpha_vantage", "fetched": 0, "reason": "no_key"}

    if not symbols:
        symbols = _get_symbols()[:limit]  # Free tier limited

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0

    for sym in symbols[:limit]:
        try:
            url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={sym}&apikey={api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "TradeAI/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if "Symbol" not in data:
                continue

            metrics = {
                "MarketCap": data.get("MarketCapitalization"),
                "PE": data.get("PERatio"),
                "ForwardPE": data.get("ForwardPE"),
                "PEG": data.get("PEGRatio"),
                "DividendYield": data.get("DividendYield"),
                "EPS": data.get("EPS"),
                "RevenuePerShare": data.get("RevenuePerShareTTM"),
                "ProfitMargin": data.get("ProfitMargin"),
                "ROE": data.get("ReturnOnEquityTTM"),
                "DebtToEquity": data.get("DebtToEquityRatio", data.get("DebtToEquityCurrentRatio")),
                "Beta": data.get("Beta"),
                "52WeekHigh": data.get("52WeekHigh"),
                "52WeekLow": data.get("52WeekLow"),
                "50DayMA": data.get("50DayMovingAverage"),
                "200DayMA": data.get("200DayMovingAverage"),
                "AnalystTargetPrice": data.get("AnalystTargetPrice"),
            }

            for metric, value in metrics.items():
                if value and value != "None" and value != "-":
                    try:
                        cur.execute("""
                            INSERT INTO fundamental_data (symbol, source, metric_name, metric_value, period)
                            VALUES (%s, 'alpha_vantage', %s, %s, 'latest')
                            ON CONFLICT (symbol, source, metric_name, period) DO UPDATE SET metric_value=EXCLUDED.metric_value, fetched_at=NOW()
                        """, (sym, metric, float(value)))
                    except (ValueError, TypeError):
                        pass

            fetched += 1
            print(f"  [av] {sym}: {len([v for v in metrics.values() if v and v != 'None'])} metrics")
        except Exception as e:
            print(f"  [av] {sym}: {e}")

    conn.commit()
    conn.close()
    return {"source": "alpha_vantage", "fetched": fetched}


# ── FRED ─────────────────────────────────────────────────────────────

FRED_SERIES = {
    "DFF": "Federal Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Spread (inversion signal)",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "Consumer Price Index (inflation)",
    "VIXCLS": "VIX Closing Value",
    "MORTGAGE30US": "30-Year Mortgage Rate",
    "SP500": "S&P 500 Index",
}


def ingest_fred() -> dict:
    """Fetch key macro economic series from FRED."""
    import urllib.request
    api_key = _env("FRED_API_KEY")
    if not api_key:
        print("[fred] No FRED_API_KEY — skipping")
        return {"source": "fred", "fetched": 0, "reason": "no_key"}

    conn = _get_conn()
    cur = conn.cursor()
    fetched = 0

    for series_id, name in FRED_SERIES.items():
        try:
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={series_id}&api_key={api_key}&file_type=json"
                   f"&sort_order=desc&limit=1")
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            obs = data.get("observations", [])
            if obs:
                val = obs[0].get("value", ".")
                obs_date = obs[0].get("date", "")
                if val != "." and obs_date:
                    cur.execute("""
                        INSERT INTO fred_economic_series (series_id, series_name, value, observation_date)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (series_id, observation_date) DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, (series_id, name, float(val), obs_date))
                    fetched += 1
                    print(f"  [fred] {series_id}: {val} ({obs_date})")
        except Exception as e:
            print(f"  [fred] {series_id}: {e}")

    conn.commit()
    conn.close()
    return {"source": "fred", "fetched": fetched}


# ── Macro context for agents ─────────────────────────────────────────

def get_macro_context() -> str:
    """Get macro economic context for agent prompt injection."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT DISTINCT ON (series_id) series_id, series_name, value, observation_date
        FROM fred_economic_series
        ORDER BY series_id, observation_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return ""

    lines = ["MACRO ECONOMIC CONTEXT (FRED):"]
    for r in rows:
        lines.append(f"  {r['series_name']}: {float(r['value']):.2f} ({r['observation_date']})")
    return "\n".join(lines)


def get_yfinance_context(symbol: str) -> str:
    """Get latest yfinance quote context for a symbol."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT * FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1
    """, (symbol,))
    r = cur.fetchone()

    # Also get Alpha Vantage fundamentals
    cur.execute("""
        SELECT metric_name, metric_value FROM fundamental_data
        WHERE symbol=%s AND source='alpha_vantage'
        ORDER BY fetched_at DESC LIMIT 10
    """, (symbol,))
    avs = cur.fetchall()
    conn.close()

    parts = []
    if r:
        p = float(r.get("price") or 0)
        dy = float(r.get("dividend_yield") or 0)
        pe = float(r.get("pe_ratio") or 0)
        hi = float(r.get("fifty_two_week_high") or 0)
        lo = float(r.get("fifty_two_week_low") or 0)
        parts.append(f"YFINANCE QUOTE ({symbol}): ${p:.2f} | PE:{pe:.1f} | Yield:{dy*100:.1f}% | 52wk: ${lo:.0f}-${hi:.0f}")

    if avs:
        av_str = ", ".join(f"{a['metric_name']}={float(a['metric_value']):.2f}" for a in avs[:6])
        parts.append(f"ALPHA VANTAGE ({symbol}): {av_str}")

    return "\n".join(parts)


# ── Test ─────────────────────────────────────────────────────────────

def test():
    print("=== External Market Data Test ===\n")

    # yfinance
    print("yfinance (V, SCHD, LMT):")
    result = ingest_yfinance_quotes(["V", "SCHD", "LMT"])
    print(f"  Result: {result}")

    # Alpha Vantage
    print("\nAlpha Vantage (V):")
    result = ingest_alpha_vantage(["V"], limit=1)
    print(f"  Result: {result}")

    # FRED
    print("\nFRED macro:")
    result = ingest_fred()
    print(f"  Result: {result}")

    # Context test
    print("\nyfinance context for V:")
    print(f"  {get_yfinance_context('V')}")
    print(f"\nMacro context:")
    print(f"  {get_macro_context()}")

    # Counts
    conn = _get_conn()
    cur = conn.cursor()
    for t in ["market_quotes", "fundamental_data", "fred_economic_series"]:
        cur.execute(f"SELECT count(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]} rows")
    conn.close()

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--quotes" in sys.argv:
        ingest_yfinance_quotes()
    elif "--fundamentals" in sys.argv:
        ingest_alpha_vantage()
    elif "--fred" in sys.argv:
        ingest_fred()
    elif "--all" in sys.argv:
        ingest_yfinance_quotes()
        ingest_alpha_vantage()
        ingest_fred()
    else:
        print("Usage: --test | --quotes | --fundamentals | --fred | --all")
