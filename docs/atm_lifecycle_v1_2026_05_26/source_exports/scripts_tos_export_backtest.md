# Source Export: scripts/tos_export_backtest.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/tos_export_backtest.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `336aaae3c1b5d2926e2215f15a3df9fd04c52160645e8f03fe75520f873d1310` |
| **File Size** | 13130 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""
TOS export + lightweight backtesting layer.

Inputs:
- data/portfolios/state/ai_watchlist.json
- data/portfolios/state/ai_watchlist_review.json
- data/portfolios/state/asset_intelligence.json
- data/portfolios/state/etf_intelligence.json
- data/portfolios/state/mutual_fund_intelligence.json
- data/portfolios/state/stock_intelligence.json
- data/portfolios/state/price_cache.json

Outputs:
- exports/tos_watchlists/*.txt
- data/portfolios/state/tos_trade_plans.json
- data/portfolios/state/backtest_summary.json

Safety:
- No broker execution
- No Schwab/TOS API writes
- Export/watchlist + research only
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data/portfolios/state"
EXPORT_DIR = PROJECT_ROOT / "exports/tos_watchlists"


def load_json(name, default):
    p = STATE_DIR / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


EXCLUDE_SYMBOLS = {
    "CASH", "SRNE", "SP500-D", "AB-DISC-Z", "SS-GACEQ", "SS-SMMD",
    "TRP-LVAL", "WM-BLAIR", "JPM-LGCG", "FID-DIVINTL"
}

SYMBOL_ALIASES = {
    "FID-CONTRA-F": "FCNTX",
}

DIVIDEND_SYMBOLS = {
    "SCHD", "DGRO", "JEPI", "DIV", "PFLT", "CSWC", "BND", "NEE"
}

SWING_SYMBOLS = {
    "AVAV", "KTOS", "RKLB", "IRDM", "DRS", "KBR", "LDOS", "CACI", "TDG"
}

STOCK_OVERRIDES = {
    "LHX", "RTX", "LMT", "NOC", "AVAV", "KTOS", "RKLB", "IRDM",
    "DRS", "KBR", "LDOS", "CACI", "TDG", "V", "NEE", "CSWC", "PFLT"
}

FUND_OVERRIDES = {
    "AMANX", "FCNTX"
}

ETF_OVERRIDES = {
    "SCHD", "SCHG", "JEPI", "DIV", "BND", "ARKG", "ARKQ", "XLB", "XLI"
}

def normalize_symbol(x):
    if not x:
        return ""
    s = str(x).strip().upper().replace("$", "")
    s = SYMBOL_ALIASES.get(s, s)
    if s in EXCLUDE_SYMBOLS:
        return ""
    return s


def extract_symbols(obj):
    symbols = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() in {"symbol", "ticker", "asset", "name"}:
                    s = normalize_symbol(v)
                    if s and 1 <= len(s) <= 12 and any(c.isalpha() for c in s):
                        symbols.add(s)
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(obj)
    return sorted(symbols)


def get_asset_type(symbol, asset_intel, etf, mf, stock):
    if symbol in ETF_OVERRIDES:
        return "etf"
    if symbol in STOCK_OVERRIDES:
        return "stock"
    if symbol in FUND_OVERRIDES:
        return "mutual_fund"
    if symbol in etf:
        return "etf"
    if symbol in mf:
        return "mutual_fund"
    if symbol in stock:
        return "stock"

    # fallback: search asset intelligence if list/dict structures vary
    blob = json.dumps(asset_intel).upper()
    if f'"{symbol}"' in blob:
        if symbol.endswith("X"):
            return "mutual_fund"
    if symbol.endswith("X"):
        return "mutual_fund"
    return "stock"


def classify_bucket(symbol, asset_type, data):
    text = json.dumps(data).lower()

    if symbol in DIVIDEND_SYMBOLS:
        return "dividend_income"

    if symbol in SWING_SYMBOLS:
        return "swing_trade"

    if asset_type in {"etf", "mutual_fund"}:
        if any(x in text for x in ["dividend", "yield", "income", "schd", "dgro", "jepi", "distribution"]):
            return "dividend_income"
        if any(x in text for x in ["bond", "treasury", "fixed income"]):
            return "bond_income"
        if any(x in text for x in ["growth", "momentum", "nasdaq", "tech"]):
            return "growth_fund"
        return "fund_rotation"

    if any(x in text for x in ["swing", "momentum", "breakout", "relative volume", "defense", "aerospace"]):
        return "swing_trade"

    if any(x in text for x in ["dividend", "yield", "bdc", "income"]):
        return "dividend_stock"

    return "compiled_entry"


def price_series(symbol, price_cache):
    raw = price_cache.get(symbol) or price_cache.get(symbol.upper()) or {}
    if not isinstance(raw, dict):
        return []
    rows = []
    for d, p in raw.items():
        try:
            rows.append((d, float(p)))
        except Exception:
            pass
    rows.sort()
    return rows


def max_drawdown(values):
    peak = None
    mdd = 0.0
    for v in values:
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd = (v - peak) / peak
            mdd = min(mdd, dd)
    return mdd


def simple_backtest(symbol, prices):
    if len(prices) < 30:
        return {
            "symbol": symbol,
            "status": "insufficient_price_history",
            "days": len(prices),
        }

    vals = [p for _, p in prices]
    latest = vals[-1]

    def ret(n):
        if len(vals) <= n or vals[-n-1] == 0:
            return None
        return (latest / vals[-n-1]) - 1

    r21 = ret(21)
    r63 = ret(63)
    r126 = ret(126)
    r252 = ret(252)

    last_20 = vals[-20:]
    last_50 = vals[-50:] if len(vals) >= 50 else vals
    sma20 = mean(last_20)
    sma50 = mean(last_50)

    rets = []
    for i in range(1, len(vals)):
        if vals[i-1]:
            rets.append(vals[i] / vals[i-1] - 1)

    volatility_63 = None
    if len(rets) >= 63:
        sample = rets[-63:]
        avg = mean(sample)
        var = mean([(x - avg) ** 2 for x in sample])
        volatility_63 = math.sqrt(var) * math.sqrt(252)

    dd_252 = max_drawdown(vals[-252:]) if len(vals) >= 60 else max_drawdown(vals)

    trend = "neutral"
    if latest > sma20 > sma50:
        trend = "uptrend"
    elif latest < sma20 < sma50:
        trend = "downtrend"

    score = 50
    for r, weight in [(r21, 10), (r63, 15), (r126, 15), (r252, 15)]:
        if r is not None:
            if r > 0:
                score += weight
            else:
                score -= weight
    if trend == "uptrend":
        score += 15
    if trend == "downtrend":
        score -= 15
    if dd_252 < -0.20:
        score -= 10
    score = max(0, min(100, score))

    return {
        "symbol": symbol,
        "status": "ok",
        "days": len(prices),
        "latest_price": round(latest, 4),
        "return_1m_pct": None if r21 is None else round(r21 * 100, 2),
        "return_3m_pct": None if r63 is None else round(r63 * 100, 2),
        "return_6m_pct": None if r126 is None else round(r126 * 100, 2),
        "return_12m_pct": None if r252 is None else round(r252 * 100, 2),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "trend": trend,
        "volatility_63_ann_pct": None if volatility_63 is None else round(volatility_63 * 100, 2),
        "max_drawdown_252_pct": round(dd_252 * 100, 2),
        "backtest_score": score,
    }


def build_trade_plan(symbol, asset_type, bucket, bt):
    if bucket in {"dividend_income", "dividend_stock", "bond_income"}:
        setup = "income_or_rotation"
        entry = "Add only after Steph allocation review; prefer pullback, support hold, or confirmed dividend thesis."
        stop = "Use portfolio risk rule; ETF/fund default 8-12% trailing unless overridden."
        target = "Income quality, dividend growth, risk-adjusted yield, and account fit."
        horizon = "3-24 months"
    elif bucket == "swing_trade":
        setup = "swing_trade"
        entry = "Close above trigger level / 20-day high with volume confirmation; avoid chasing extended move."
        stop = "Initial stop below recent swing low or ATR-based stop."
        target = "Scale at 1.5R-3R or trail while trend holds."
        horizon = "2 days-8 weeks"
    else:
        setup = "compiled_entry"
        entry = "Needs Maria catalyst review + Risk technical confirmation before trade."
        stop = "Use technical invalidation level from Risk Agent."
        target = "Depends on catalyst and trend strength."
        horizon = "watchlist until validated"

    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "bucket": bucket,
        "setup_type": setup,
        "entry_trigger": entry,
        "stop_rule": stop,
        "target_rule": target,
        "holding_period": horizon,
        "tos_watchlist": bucket.upper(),
        "backtest_status": bt.get("status"),
        "backtest_score": bt.get("backtest_score"),
        "trend": bt.get("trend"),
        "remove_rule": "Remove if thesis stale, trend degrades, reliability blocks, or no trade plan after review window.",
        "requires_review": ["maria", "risk_agent"] if setup != "income_or_rotation" else ["maria", "steph", "risk_agent", "tax_agent"],
    }


def write_watchlist(name, symbols):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    p = EXPORT_DIR / f"{name}_{date}.txt"
    p.write_text("\n".join(sorted(set(symbols))) + ("\n" if symbols else ""))
    latest = EXPORT_DIR / f"{name}_LATEST.txt"
    latest.write_text(p.read_text())
    return str(p), str(latest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ai_watchlist = load_json("ai_watchlist.json", {})
    ai_review = load_json("ai_watchlist_review.json", {})
    asset_intel = load_json("asset_intelligence.json", {})
    etf = load_json("etf_intelligence.json", {})
    mf = load_json("mutual_fund_intelligence.json", {})
    stock = load_json("stock_intelligence.json", {})
    price_cache = load_json("price_cache.json", {})

    symbols = set()
    symbols.update(extract_symbols(ai_watchlist))
    symbols.update(extract_symbols(ai_review))

    # fallback: include current intelligence symbols if AI watchlist structure lacks symbol keys
    if not symbols:
        for obj in [etf, mf, stock, asset_intel]:
            if isinstance(obj, dict):
                symbols.update(normalize_symbol(k) for k in obj.keys() if normalize_symbol(k))

    symbols = sorted(set(normalize_symbol(s) for s in symbols if normalize_symbol(s)))

    trade_plans = []
    backtests = []
    buckets = {
        "AI_DIVIDEND": [],
        "AI_SWING": [],
        "AI_COMPILED_ENTRIES": [],
        "AI_ETFS": [],
        "AI_MUTUAL_FUNDS": [],
        "AI_FUNDS_ETFS": [],
        "AI_DIVIDEND_ETFS": [],
        "AI_REVIEW_REMOVE": [],
    }

    for symbol in symbols:
        atype = get_asset_type(symbol, asset_intel, etf if isinstance(etf, dict) else {}, mf if isinstance(mf, dict) else {}, stock if isinstance(stock, dict) else {})
        data_blob = {
            "asset": asset_intel.get(symbol, {}) if isinstance(asset_intel, dict) else {},
            "etf": etf.get(symbol, {}) if isinstance(etf, dict) else {},
            "mutual_fund": mf.get(symbol, {}) if isinstance(mf, dict) else {},
            "stock": stock.get(symbol, {}) if isinstance(stock, dict) else {},
        }
        bucket = classify_bucket(symbol, atype, data_blob)
        bt = simple_backtest(symbol, price_series(symbol, price_cache))
        plan = build_trade_plan(symbol, atype, bucket, bt)

        backtests.append(bt)
        trade_plans.append(plan)

        if "dividend" in bucket or "income" in bucket:
            buckets["AI_DIVIDEND"].append(symbol)
        if bucket == "swing_trade":
            buckets["AI_SWING"].append(symbol)
        if atype == "etf":
            buckets["AI_ETFS"].append(symbol)
            buckets["AI_FUNDS_ETFS"].append(symbol)
            if "dividend" in bucket or "income" in bucket:
                buckets["AI_DIVIDEND_ETFS"].append(symbol)
        elif atype == "mutual_fund":
            buckets["AI_MUTUAL_FUNDS"].append(symbol)
            buckets["AI_FUNDS_ETFS"].append(symbol)
        if bucket == "compiled_entry":
            buckets["AI_COMPILED_ENTRIES"].append(symbol)

        if bt.get("status") != "ok" or (bt.get("backtest_score") is not None and bt.get("backtest_score") < 40):
            buckets["AI_REVIEW_REMOVE"].append(symbol)

    exported = {}
    for name, syms in buckets.items():
        exported[name] = write_watchlist(name, syms)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": len(symbols),
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "watchlist_exports": exported,
        "note": "TOS exports are one-symbol-per-line text files. No broker execution performed.",
    }

    (STATE_DIR / "tos_trade_plans.json").write_text(json.dumps({
        "generated_at": summary["generated_at"],
        "trade_plans": trade_plans,
    }, indent=2))

    (STATE_DIR / "backtest_summary.json").write_text(json.dumps({
        "generated_at": summary["generated_at"],
        "summary": summary,
        "backtests": backtests,
    }, indent=2))

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("TOS export + backtest complete")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
```
