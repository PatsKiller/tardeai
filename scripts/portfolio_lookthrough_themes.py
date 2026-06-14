#!/usr/bin/env python3
"""portfolio_lookthrough_themes.py — TRUE stock-level look-through + theme exposure.

The sector look-through (phase3) shows GICS weights; this goes a layer deeper: it resolves every holding
to its UNDERLYING STOCKS (funds via their proxy ETF's yfinance top-holdings) and aggregates across the
whole portfolio, so you can see real exposure to themes (Magnificent 7, etc.) and single-stock
concentration that's hidden inside index/active funds.

Approximation honesty: yfinance gives each fund's TOP ~10 holdings (not the full book), so theme coverage
captures the mega-caps (which dominate Mag 7 / concentration) but understates the long tail. Cached to
data/portfolios/state/fund_holdings_cache.json.

  python3 scripts/portfolio_lookthrough_themes.py            # text report
  python3 scripts/portfolio_lookthrough_themes.py --json     # machine JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "portfolios" / "state"
HOLD_CACHE = STATE / "fund_holdings_cache.json"

THEMES = {
    "Magnificent 7": {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA"},
    "Semiconductors": {"NVDA", "AVGO", "AMD", "QCOM", "TXN", "MU", "INTC", "ASML", "TSM", "LRCX",
                       "AMAT", "ADI", "KLAC", "MRVL", "NXPI", "MCHP"},
    "AI mega-cap": {"NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "AMD", "PLTR", "TSM"},
}


def _load(p, d):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def _proxy_etf(sym: str) -> str | None:
    """Map a fund/opaque code to a public ETF whose holdings approximate it."""
    try:
        from holding_proxies import HOLDING_PROXY_MAP
    except Exception:
        HOLDING_PROXY_MAP = {}
    if sym in HOLDING_PROXY_MAP:
        return HOLDING_PROXY_MAP[sym][0]
    # SnapTrade 401k codes → their lookthrough_source (old proxy code) → ETF
    fmap = _load(ROOT / "config" / "snaptrade_401k_fund_map.json", {}).get("codes", {})
    if sym in fmap:
        src = fmap[sym].get("lookthrough_source")
        if src in HOLDING_PROXY_MAP:
            return HOLDING_PROXY_MAP[src][0]
    return None


def _fund_holdings(etf: str, cache: dict) -> dict[str, float]:
    """Top-holdings {stock: weight} for a fund/ETF, cached."""
    if etf in cache:
        return cache[etf]
    out: dict[str, float] = {}
    try:
        import yfinance as yf
        th = yf.Ticker(etf).funds_data.top_holdings
        for sym, row in th.iterrows():
            out[str(sym).upper()] = float(row["Holding Percent"])
    except Exception:
        out = {}
    cache[etf] = out
    return out


def run() -> dict:
    import holding_family as hf
    holdings = _load(STATE / "holdings.json", {}).get("holdings", [])
    cache = _load(HOLD_CACHE, {})

    underlying = defaultdict(float)   # stock -> $ exposure (look-through)
    total = 0.0
    covered = 0.0                     # $ we could resolve to underlying stocks
    for h in holdings:
        sym = (h.get("symbol") or "").upper()
        mv = float(h.get("market_value") or 0)
        if not sym or h.get("is_cash") or mv <= 0:
            continue
        total += mv
        # direct stock (clean ticker, not a fund) → itself
        if not hf.is_unstoppable_fund(sym) and sym.isalpha() and 1 <= len(sym) <= 5 and sym not in (
                "SPY", "QQQ", "SCHG", "SCHD", "DIV", "JEPI", "BND", "XLI", "XLB", "ARKG", "ARKQ", "VXUS",
                "IJH", "IWP", "IWN", "IWR", "IWM"):
            # treat as a direct stock UNLESS yfinance says it's a fund (cheap heuristic via proxy absence)
            etf = None
        else:
            etf = sym  # it IS an etf/fund we can pull holdings for
        if etf is None:
            etf2 = _proxy_etf(sym)
            if etf2 is None:
                # individual stock
                underlying[sym] += mv
                covered += mv
                continue
            etf = etf2
        else:
            etf = _proxy_etf(sym) or sym  # 401k code → proxy; real ETF → itself
        weights = _fund_holdings(etf, cache)
        if not weights:
            continue
        wsum = sum(weights.values())
        for stock, w in weights.items():
            underlying[stock] += mv * w
        covered += mv * wsum

    HOLD_CACHE.write_text(json.dumps(cache, indent=2))

    # theme aggregation
    theme_out = {}
    for name, basket in THEMES.items():
        val = sum(v for s, v in underlying.items() if s in basket)
        per = {s: round(underlying.get(s, 0), 0) for s in sorted(basket, key=lambda x: -underlying.get(x, 0)) if underlying.get(s, 0) > 0}
        theme_out[name] = {"value": round(val, 0), "pct_of_portfolio": round(val / total * 100, 2) if total else 0, "by_stock": per}

    top = sorted(underlying.items(), key=lambda x: -x[1])[:15]
    return {
        "portfolio_total": round(total, 0),
        "look_through_covered": round(covered, 0),
        "coverage_pct": round(covered / total * 100, 1) if total else 0,
        "themes": theme_out,
        "top_underlying_stocks": [{"symbol": s, "value": round(v, 0), "pct": round(v / total * 100, 2)} for s, v in top],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = run()
    if a.json:
        print(json.dumps(r, indent=2)); return 0
    print(f"Portfolio ${r['portfolio_total']:,.0f} · look-through coverage {r['coverage_pct']}% "
          f"(${r['look_through_covered']:,.0f})")
    for name, t in r["themes"].items():
        print(f"\n{name}: ${t['value']:,.0f}  ({t['pct_of_portfolio']}% of portfolio)")
        for s, v in t["by_stock"].items():
            bar = "#" * int(v / max(1, t["value"]) * 30)
            print(f"   {s:<6} ${v:>11,.0f}  {bar}")
    print("\nTop underlying single-stock exposure (look-through):")
    for row in r["top_underlying_stocks"]:
        print(f"   {row['symbol']:<6} ${row['value']:>11,.0f}  {row['pct']:>5.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
