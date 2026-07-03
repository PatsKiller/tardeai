#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

def _safe_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _get_watchlist_symbols(state_dir: Path):
    symbols = set()
    for fname in ["watchlist_intelligence.json", "watchlist.json"]:
        p = state_dir / fname
        data = _safe_json(p, {})
        if isinstance(data, dict):
            for key in ("watchlist", "symbols", "tickers"):
                val = data.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            sym = item.get("symbol") or item.get("ticker")
                            if sym:
                                symbols.add(sym)
                        elif isinstance(item, str):
                            symbols.add(item)
    return symbols

def _optional_yfinance(symbol: str):
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).fast_info
        out = {}
        for k in ("market_cap","last_price","day_high","day_low","year_high","year_low","shares"):
            if k in info and info[k] is not None:
                out[k] = info[k]
        return out
    except Exception:
        return {}

def _optional_finvizfinance(symbol: str):
    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(symbol)
        d = stock.ticker_fundament()
        out = {}
        for k, v in d.items():
            key = str(k).strip().lower().replace(" ", "_").replace("/", "_")
            out[key] = v
        return out
    except Exception:
        return {}

def build_ticker_snapshot(portfolio: dict, project_root: Path) -> str:
    state_dir = project_root / "data" / "portfolios" / "state"
    raw_dir = state_dir / "raw_snapshots"
    raw_dir.mkdir(parents=True, exist_ok=True)
    hist_dir = state_dir / "ticker_snapshot_history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    holdings = portfolio.get("holdings", [])
    finviz_cache = _safe_json(state_dir / "finviz_quote_cache.json", {})
    technical_snapshot = _safe_json(state_dir / "technical_snapshot.json", {})
    price_cache = _safe_json(state_dir / "price_cache.json", {})

    symbols = set()
    for h in holdings:
        sym = h.get("symbol")
        if sym and not h.get("is_loan"):
            symbols.add(sym)
    symbols.update(_get_watchlist_symbols(state_dir))
    if isinstance(finviz_cache, dict):
        # cache carries bookkeeping keys like "_meta" — they are not tickers
        symbols.update(k for k in finviz_cache.keys() if not str(k).startswith("_"))
    symbols = sorted(s for s in symbols if not str(s).startswith("_"))

    records = {}
    now = datetime.now().isoformat()
    for sym in symbols:
        rec = {
            "symbol": sym,
            "fetched_at": now,
            "source_priority": ["finviz_quote_cache", "technical_snapshot", "price_cache", "yfinance", "finvizfinance"],
            "quote": {},
            "performance": {},
            "technicals": {},
            "analyst": {},
            "fundamentals": {},
            "classification": {},
            "resolved": {},
            "holdings_context": {},
        }

        cache = finviz_cache.get(sym, {}) if isinstance(finviz_cache, dict) else {}
        tech = technical_snapshot.get(sym, {}) if isinstance(technical_snapshot, dict) else {}
        pc = price_cache.get(sym, {}) if isinstance(price_cache, dict) else {}

        for k in ["price","change_pct","prev_close","volume","rvol","source","analyst","target","perf_week","perf_month","perf_quarter","perf_halfyr","perf_ytd","perf_year","volatility_w","volatility_m"]:
            if cache.get(k) not in (None, "", [], {}):
                bucket = "quote" if k in ("price","change_pct","prev_close","volume","rvol","source") else ("analyst" if k in ("analyst","target") else "performance")
                rec[bucket][k] = cache.get(k)

        # Core technical fields (from Finviz API + price-cache calculations)
        for k in ["rsi","atr","beta","sma20_pct","sma50_pct","sma200_pct",
                  "sma20","sma50","sma200","52wk_high","52wk_low",
                  "pct_from_high","pct_from_low","tech_score","tech_grade",
                  "macd_signal","cross","above_sma20","above_sma50",
                  "above_sma200","relative_volume"]:
            if tech.get(k) not in (None, "", [], {}):
                rec["technicals"][k] = tech.get(k)
        # Extended technical fields added in Phase 2
        for k in ["rsi_status","intent","suggested_stop","current_stop",
                  "stop_gap_pct","stop_needs_update","supports","resistances",
                  "bb_upper","bb_lower","bb_position_pct",
                  "week52_high","week52_low"]:
            if tech.get(k) not in (None, "", [], {}):
                rec["technicals"][k] = tech.get(k)
        # Analyst fields from technical snapshot (when populated)
        for k in ["analyst","target"]:
            if tech.get(k) not in (None, "", [], {}, 0.0):
                rec["analyst"].setdefault(k, tech.get(k))

        if isinstance(pc, dict):
            for k in ["price","close","last","marketCap","averageVolume","dividendYield","trailingPE","forwardPE"]:
                if pc.get(k) not in (None, "", [], {}):
                    key = str(k)
                    if key in ("price","close","last"):
                        rec["quote"].setdefault("price_cache_" + key, pc.get(k))
                    else:
                        rec["fundamentals"][key] = pc.get(k)

        owned = [h for h in holdings if h.get("symbol") == sym and not h.get("is_loan")]
        if owned:
            rec["holdings_context"] = {
                "accounts": sorted(set(h.get("account") for h in owned if h.get("account"))),
                "shares_total": round(sum(float(h.get("shares") or 0) for h in owned), 6),
                "market_value_total": round(sum(float(h.get("market_value") or 0) for h in owned), 2),
            }

        records[sym] = rec

    def enrich(sym):
        return sym, {"yfinance": _optional_yfinance(sym), "finvizfinance": _optional_finvizfinance(sym)}

    # Delisted positions (Schwab returns a bare CUSIP as the symbol) have no quote anywhere —
    # skip external enrichment for them instead of 404-spamming Yahoo on every snapshot build
    # (543354104 / 628518102 / 12507E201 logged a pair of quoteSummary 404s per sync for weeks).
    try:
        from schwab_position_sync import _looks_like_cusip
    except Exception:
        def _looks_like_cusip(s):
            return bool(s) and len(s) == 9 and s.isalnum() and not s.isalpha() and any(c.isdigit() for c in s)
    delisted = {str(h.get("symbol") or "").upper() for h in holdings if h.get("delisted")}
    enrichable = [s for s in symbols if s not in delisted and not _looks_like_cusip(s)]
    skipped = sorted(set(symbols) - set(enrichable))
    if skipped:
        print(f"  [snapshot] external enrichment skipped for delisted/CUSIP: {', '.join(skipped)}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(enrich, sym): sym for sym in enrichable}
        for fut in as_completed(futs):
            sym, extra = fut.result()
            if extra["yfinance"]:
                records[sym]["fundamentals"].update({f"yf_{k}": v for k, v in extra["yfinance"].items()})
            if extra["finvizfinance"]:
                records[sym]["fundamentals"].update({f"fv_{k}": v for k, v in extra["finvizfinance"].items()})

    manifest = {
        "_meta": {
            "generated_at": now,
            "symbol_count": len(records),
            "fields_note": "Normalized snapshot from current Finviz cache, technical snapshot, price cache, and optional yfinance/finvizfinance enrichment.",
        },
        "tickers": records,
    }

    latest = state_dir / "ticker_snapshot_latest.json"
    latest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (hist_dir / f"ticker_snapshot_{stamp}.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    fq = state_dir / "finviz_quote_cache.json"
    if fq.exists():
        (raw_dir / f"finviz_quote_cache_{stamp}.json").write_text(fq.read_text(encoding="utf-8"), encoding="utf-8")
    return str(latest)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    args = ap.parse_args()
    pr = Path(args.project_root)
    hp = pr / "data" / "portfolios" / "state" / "holdings.json"
    portfolio = json.loads(hp.read_text(encoding="utf-8"))
    out = build_ticker_snapshot(portfolio, pr)
    print(out)
