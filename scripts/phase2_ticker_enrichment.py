#!/usr/bin/env python3
# phase2_ticker_enrichment.py
# Enriches ticker_snapshot_latest.json with yfinance fundamentals,
# finvizfinance full page data, and sector/industry classification.
# Run after deploy to populate initial data. Also runs in portfolio_orchestrator
# monthly pipeline.

from __future__ import annotations
import argparse, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


def _safe_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _optional_yfinance(symbol: str) -> dict:
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        fast = {}
        try:
            fast = t.fast_info or {}
        except Exception:
            pass
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        out = {}
        # Sector / industry classification
        for k in ("sector", "industry"):
            if info.get(k) not in (None, "", "N/A"):
                out[k] = info[k]
        # Fundamentals
        for k in ("marketCap", "averageVolume", "dividendYield",
                  "trailingPE", "forwardPE", "beta",
                  "targetMeanPrice", "targetHighPrice", "targetLowPrice",
                  "recommendationKey", "numberOfAnalystOpinions",
                  "trailingEps", "forwardEps", "bookValue",
                  "priceToBook", "debtToEquity", "returnOnEquity",
                  "revenueGrowth", "earningsGrowth",
                  "fiftyTwoWeekHigh", "fiftyTwoWeekLow"):
            if info.get(k) not in (None, "", "N/A"):
                out[k] = info[k]
        # Fast info fields
        for k in ("last_price", "day_high", "day_low",
                  "year_high", "year_low", "market_cap", "shares"):
            if hasattr(fast, k) and getattr(fast, k) is not None:
                out[k] = getattr(fast, k)
            elif isinstance(fast, dict) and fast.get(k) is not None:
                out[k] = fast[k]
        return out
    except Exception:
        return {}


def _optional_finvizfinance(symbol: str) -> dict:
    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(symbol)
        out = {}
        try:
            f = stock.ticker_fundament() or {}
            for k, v in f.items():
                key = str(k).strip().lower().replace(" ", "_").replace("/", "_")
                out[key] = v
        except Exception:
            pass
        try:
            d = stock.ticker_description()
            if d:
                out["description"] = d
        except Exception:
            pass
        return out
    except Exception:
        return {}


def load_symbols(project_root: Path) -> list:
    state_dir = project_root / "data" / "portfolios" / "state"
    holdings = _safe_json(state_dir / "holdings.json", {})
    finviz_cache = _safe_json(state_dir / "finviz_quote_cache.json", {})
    tickers = set()
    for h in holdings.get("holdings", []):
        sym = h.get("symbol")
        if sym and not h.get("is_loan") and not h.get("is_cash"):
            tickers.add(sym)
    if isinstance(finviz_cache, dict):
        tickers.update(k for k in finviz_cache.keys() if not k.startswith("_"))
    return sorted(tickers)


def main():
    ap = argparse.ArgumentParser(description="Phase 2 ticker enrichment")
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    project_root = Path(args.project_root)
    state_dir = project_root / "data" / "portfolios" / "state"
    log_dir = project_root / "logs" / "phase2"
    log_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_json(state_dir / "ticker_snapshot_latest.json",
                      {"_meta": {}, "tickers": {}})
    base.setdefault("_meta", {})
    base.setdefault("tickers", {})
    symbols = load_symbols(project_root)
    print(f"[phase2_enrichment] enriching {len(symbols)} symbols...")

    def enrich(sym):
        return sym, {
            "yfinance":      _optional_yfinance(sym),
            "finvizfinance": _optional_finvizfinance(sym),
        }

    verbose = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(enrich, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            sym, extra = fut.result()
            rec = base["tickers"].setdefault(sym, {"symbol": sym})
            rec.setdefault("quote", {})
            rec.setdefault("performance", {})
            rec.setdefault("technicals", {})
            rec.setdefault("analyst", {})
            rec.setdefault("fundamentals", {})
            rec.setdefault("classification", {})
            rec.setdefault("resolved", {})

            yf = extra["yfinance"]
            fv = extra["finvizfinance"]

            if yf:
                # Classification
                if yf.get("sector"):
                    rec["classification"]["yf_sector"] = yf["sector"]
                if yf.get("industry"):
                    rec["classification"]["yf_industry"] = yf["industry"]
                # Analyst
                for k in ("targetMeanPrice", "targetHighPrice", "targetLowPrice",
                          "recommendationKey", "numberOfAnalystOpinions"):
                    if k in yf:
                        rec["analyst"][f"yf_{k}"] = yf[k]
                # Fundamentals
                for k in ("marketCap", "averageVolume", "dividendYield",
                          "trailingPE", "forwardPE", "beta",
                          "trailingEps", "forwardEps", "bookValue",
                          "priceToBook", "debtToEquity", "returnOnEquity",
                          "revenueGrowth", "earningsGrowth",
                          "fiftyTwoWeekHigh", "fiftyTwoWeekLow"):
                    if k in yf:
                        rec["fundamentals"][f"yf_{k}"] = yf[k]
                # Quote enrichment
                for k in ("last_price", "day_high", "day_low",
                          "year_high", "year_low", "market_cap", "shares"):
                    if k in yf:
                        rec["quote"][f"yf_{k}"] = yf[k]

            if fv:
                for k, v in fv.items():
                    lk = str(k).lower()
                    if lk in ("sector", "industry"):
                        rec["classification"][f"fv_{lk}"] = v
                    elif any(x in lk for x in ["atr", "rsi", "sma", "ema",
                                               "volatility", "beta",
                                               "high", "low"]):
                        rec["technicals"][f"fv_{lk}"] = v
                    elif any(x in lk for x in ["recommend", "target",
                                               "analyst", "price_target"]):
                        rec["analyst"][f"fv_{lk}"] = v
                    elif lk == "description":
                        rec["fundamentals"]["description"] = v
                    else:
                        rec["fundamentals"][f"fv_{lk}"] = v

            verbose.append({
                "symbol":            sym,
                "has_yfinance":      bool(yf),
                "has_finvizfinance": bool(fv),
                "yf_sector":         yf.get("sector", ""),
                "fv_sector":         fv.get("sector", ""),
                "classification":    sorted(rec.get("classification", {}).keys()),
            })
            print(f"  {sym}: yf={'yes' if yf else 'no'} fv={'yes' if fv else 'no'} "
                  f"sector={yf.get('sector','') or fv.get('sector','')}")

    base["_meta"]["phase2_enriched_at"] = datetime.now().isoformat()
    base["_meta"]["phase2_symbol_count"] = len(base["tickers"])

    latest = state_dir / "ticker_snapshot_latest.json"
    latest.write_text(json.dumps(base, indent=2, default=str), encoding="utf-8")

    verbose_log = log_dir / "phase2_enrichment_verbose.json"
    verbose_log.write_text(json.dumps(verbose, indent=2, default=str), encoding="utf-8")

    print(f"[phase2_enrichment] Done. Written: {latest}")
    print(f"[phase2_enrichment] Verbose log: {verbose_log}")


if __name__ == "__main__":
    main()
