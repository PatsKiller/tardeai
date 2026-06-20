#!/usr/bin/env python3
"""etf_performance_enrich.py — YTD price performance + dividend yield + trailing dividend for ETFs/funds
(and any instrument), from yfinance. Fills the gap the operator flagged: "I want actual ETF YTD performance
... yield and dividends." Stores on symbol_profiles so the watchlist API → skill → agent can report it.

YTD = price return (year-start close → latest close). Yield = trailing dividend yield. Dividend = TTM $/share.
Read-only re: trading. Bounded + polite. --symbols X,Y to target; default = all etf/fund/inverse_etf on
symbol_profiles. --no-fetch skips network (no-op). Cron weekly alongside classify_instruments/etf_analyst.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
if not __import__("os").getenv("DB_PASSWORD"):
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
from db_adapter import _get_conn


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _norm_yield(v):
    """yfinance yields are inconsistent (0.025 fraction vs 2.5 percent). Normalize to a percent."""
    if not isinstance(v, (int, float)) or v <= 0:
        return None
    return round(v * 100, 2) if v < 1 else round(float(v), 2)


def main():
    conn = _get_conn(); cur = conn.cursor()
    for col, typ in (("ytd_return_pct", "numeric"), ("dividend_yield_pct", "numeric"),
                     ("ttm_dividend", "numeric"), ("perf_updated_at", "timestamptz")):
        cur.execute(f"ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS {col} {typ}")
    conn.commit()

    target = _flag("--symbols")
    if target:
        syms = [s.strip().upper() for s in target.split(",") if s.strip()]
    else:
        cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('etf','fund','inverse_etf') ORDER BY 1")
        syms = [r[0] for r in cur.fetchall()]
    if "--no-fetch" in sys.argv or not syms:
        print(f'{{"ok": true, "symbols": {len(syms)}, "note": "no-fetch or empty"}}')
        return 0

    import yfinance as yf, time as _t
    done = 0
    for s in syms[:300]:
        _t.sleep(0.8)
        try:
            tk = yf.Ticker(s)
            info = tk.info or {}
            # YTD = price return year-start → latest (auto_adjust=False so it's price, dividends counted separately)
            ytd = None
            try:
                h = tk.history(period="ytd", auto_adjust=False)
                if h is not None and len(h) >= 2:
                    c0, c1 = float(h["Close"].iloc[0]), float(h["Close"].iloc[-1])
                    if c0 > 0:
                        ytd = round((c1 - c0) / c0 * 100, 2)
            except Exception:
                pass
            if ytd is None and isinstance(info.get("ytdReturn"), (int, float)):
                ytd = round(info["ytdReturn"] * 100, 2)   # fund total-return fallback
            dy = _norm_yield(info.get("yield") or info.get("dividendYield") or info.get("trailingAnnualDividendYield"))
            div = info.get("trailingAnnualDividendRate")
            div = round(float(div), 4) if isinstance(div, (int, float)) and div > 0 else None
            cur.execute("""UPDATE symbol_profiles SET ytd_return_pct=%s, dividend_yield_pct=%s,
                             ttm_dividend=%s, perf_updated_at=now() WHERE upper(symbol)=%s""",
                        (ytd, dy, div, s))
            done += cur.rowcount
        except Exception:
            continue
    conn.commit()
    import json
    print(json.dumps({"ok": True, "symbols": len(syms), "updated": done}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
