#!/usr/bin/env python3
"""Build analyst, ETF, mutual fund, and stock intelligence JSON files.

This is a safe, best-effort enrichment pipeline:
- reads current holdings, AI watchlist, and discovery candidates
- classifies symbols as ETF, mutual_fund, stock, or unknown
- enriches with available provider APIs if keys exist in .env
- writes JSON state files used by the agent router freshness gate
- optionally mirrors results to Postgres when DB_* vars exist

No trades, YAML changes, or watchlist removals are executed here.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
CONFIG = ROOT / "config/agent_discovery_config.json"


def load_env() -> Dict[str, str]:
    env_path = ROOT / ".env"
    vals: Dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), vals[k.strip()])
    return vals


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(errors="ignore"))
    except Exception as e:
        print(f"[asset-intel] WARN: could not read {path}: {e}")
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def http_json(url: str, timeout: int = 20) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TradeAI-AgentIntel/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        print(f"[asset-intel] provider miss: {e}")
        return None


def normalize_symbol(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", str(sym or "").upper()).strip()


def classify_asset(symbol: str, holding: Optional[Dict[str, Any]] = None) -> str:
    s = normalize_symbol(symbol)
    if holding:
        txt = " ".join(str(holding.get(k, "")) for k in ("asset_type", "sector_type", "name", "description")).lower()
        if "mutual" in txt or "fund" in txt and len(s) == 5 and s.endswith("X"):
            return "mutual_fund"
        if "etf" in txt or "exchange traded" in txt:
            return "etf"
        if "stock" in txt or "equity" in txt:
            return "stock"
    if len(s) == 5 and s.endswith("X"):
        return "mutual_fund"
    # Common ETFs can look like stocks, so later provider data can override.
    known_etfs = {"SCHD", "DGRO", "JEPI", "SCHG", "SPY", "QQQ", "VTI", "VOO", "BND", "XLI", "XLB", "ARKG", "DIV"}
    if s in known_etfs:
        return "etf"
    return "stock"


def load_symbols() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    holdings = read_json(STATE / "holdings.json", {})
    hlist = holdings.get("holdings", []) if isinstance(holdings, dict) else []
    for h in hlist:
        sym = normalize_symbol(h.get("symbol"))
        if sym:
            out.setdefault(sym, {"symbol": sym, "sources": set(), "holding": h})
            out[sym]["sources"].add("holdings")

    for fname in ("ai_watchlist.json", "discovery_candidates.json"):
        data = read_json(STATE / fname, {})
        entries = []
        if isinstance(data, dict):
            entries = data.get("candidates") or data.get("watchlist") or data.get("items") or []
        elif isinstance(data, list):
            entries = data
        for item in entries:
            if isinstance(item, dict):
                sym = normalize_symbol(item.get("symbol") or item.get("ticker"))
                if sym:
                    out.setdefault(sym, {"symbol": sym, "sources": set(), "holding": None})
                    out[sym]["sources"].add(fname)
    for v in out.values():
        v["sources"] = sorted(v["sources"])
    return out


def yahoo_quote(symbol: str) -> Dict[str, Any]:
    url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + urllib.parse.quote(symbol)
    data = http_json(url)
    result = ((data or {}).get("quoteResponse") or {}).get("result") or []
    if not result:
        return {}
    q = result[0]
    return {
        "provider": "yahoo_fallback",
        "price": q.get("regularMarketPrice"),
        "market_cap": q.get("marketCap"),
        "trailing_pe": q.get("trailingPE"),
        "dividend_yield_pct": (q.get("trailingAnnualDividendYield") or 0) * 100 if q.get("trailingAnnualDividendYield") is not None else None,
        "quote_type": q.get("quoteType"),
        "short_name": q.get("shortName"),
        "long_name": q.get("longName"),
        "currency": q.get("currency"),
        "exchange": q.get("fullExchangeName") or q.get("exchange"),
        "fifty_two_week_high": q.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": q.get("fiftyTwoWeekLow")
    }


def fmp_profile(symbol: str, key: str) -> Dict[str, Any]:
    if not key:
        return {}
    url = f"https://financialmodelingprep.com/api/v3/profile/{urllib.parse.quote(symbol)}?apikey={urllib.parse.quote(key)}"
    data = http_json(url)
    if isinstance(data, list) and data:
        p = data[0]
        return {
            "provider": "fmp",
            "price": p.get("price"),
            "beta": p.get("beta"),
            "market_cap": p.get("mktCap"),
            "last_dividend": p.get("lastDiv"),
            "range": p.get("range"),
            "company_name": p.get("companyName"),
            "currency": p.get("currency"),
            "exchange": p.get("exchangeShortName"),
            "industry": p.get("industry"),
            "sector": p.get("sector"),
            "description": p.get("description")
        }
    return {}


def finnhub_recommendation(symbol: str, key: str) -> Dict[str, Any]:
    if not key:
        return {}
    url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={urllib.parse.quote(symbol)}&token={urllib.parse.quote(key)}"
    data = http_json(url)
    if isinstance(data, list) and data:
        r = data[0]
        return {
            "provider": "finnhub",
            "recommendation_period": r.get("period"),
            "strong_buy": r.get("strongBuy"),
            "buy": r.get("buy"),
            "hold": r.get("hold"),
            "sell": r.get("sell"),
            "strong_sell": r.get("strongSell")
        }
    return {}


def score_symbol(symbol: str, asset_type: str, merged: Dict[str, Any]) -> Dict[str, Any]:
    score = 0.0
    reasons = []
    dy = merged.get("dividend_yield_pct")
    if dy is None and merged.get("last_dividend") and merged.get("price"):
        try:
            dy = float(merged["last_dividend"]) / float(merged["price"]) * 100
        except Exception:
            dy = None
    if dy is not None:
        if dy >= 3:
            score += 18; reasons.append(f"yield {dy:.2f}%")
        elif dy >= 1.8:
            score += 10; reasons.append(f"modest yield {dy:.2f}%")
    mcap = merged.get("market_cap")
    if mcap:
        try:
            if float(mcap) >= 5_000_000_000:
                score += 10; reasons.append("liquid large/mid cap")
        except Exception:
            pass
    if asset_type in ("etf", "mutual_fund"):
        score += 8; reasons.append("fund/ETF diversification candidate")
    if merged.get("buy") or merged.get("strong_buy"):
        try:
            buys = int(merged.get("buy") or 0) + int(merged.get("strong_buy") or 0)
            sells = int(merged.get("sell") or 0) + int(merged.get("strong_sell") or 0)
            if buys > sells:
                score += min(15, buys * 2); reasons.append("positive analyst skew")
        except Exception:
            pass
    # No aggressive decisions here: low-data candidates stay in research queue.
    if not reasons:
        reasons.append("needs more data")
    bucket = "research_queue"
    if dy is not None and dy >= 2 and asset_type in ("etf", "mutual_fund", "stock"):
        bucket = "dividend_core"
    elif asset_type == "stock" and score >= 15:
        bucket = "compounder"
    return {"score": round(score, 3), "bucket": bucket, "reasons": reasons}


def mirror_to_db(rows: List[Dict[str, Any]], env: Dict[str, str]) -> None:
    # Optional. Avoid hard dependency on psycopg2.
    if not all(env.get(k) for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")):
        return
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(host=env["DB_HOST"], port=env["DB_PORT"], dbname=env["DB_NAME"], user=env["DB_USER"], password=env["DB_PASSWORD"])
        with conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO asset_intelligence_history (symbol, asset_type, payload) VALUES (%s, %s, %s::jsonb)",
                    (r["symbol"], r["asset_type"], json.dumps(r))
                )
                cur.execute(
                    "INSERT INTO analyst_data_history (symbol, asset_type, payload) VALUES (%s, %s, %s::jsonb)",
                    (r["symbol"], r["asset_type"], json.dumps(r.get("analyst", {})))
                )
        conn.close()
    except Exception as e:
        print(f"[asset-intel] WARN: DB mirror skipped: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="Comma-separated additional symbols to enrich")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=250)
    args = ap.parse_args()

    env = load_env()
    cfg = read_json(CONFIG, {})
    symbols = load_symbols()
    for sym in [normalize_symbol(x) for x in args.symbols.split(",") if x.strip()]:
        symbols.setdefault(sym, {"symbol": sym, "sources": ["cli"], "holding": None})

    rows: List[Dict[str, Any]] = []
    missing_keys = []
    if not env.get("FMP_API_KEY"):
        missing_keys.append("FMP_API_KEY")
    if not env.get("FINNHUB_API_KEY"):
        missing_keys.append("FINNHUB_API_KEY")

    for sym, meta in list(symbols.items())[: args.limit]:
        holding = meta.get("holding")
        asset_type = classify_asset(sym, holding)
        profile = {}
        profile.update(yahoo_quote(sym))
        fmp = fmp_profile(sym, env.get("FMP_API_KEY", ""))
        profile.update({k: v for k, v in fmp.items() if v is not None})
        analyst = finnhub_recommendation(sym, env.get("FINNHUB_API_KEY", ""))
        score = score_symbol(sym, asset_type, {**profile, **analyst})
        rows.append({
            "symbol": sym,
            "asset_type": asset_type,
            "sources": meta.get("sources", []),
            "generated_at": now_iso(),
            "profile": profile,
            "analyst": analyst,
            "score": score["score"],
            "bucket": score["bucket"],
            "reasons": score["reasons"],
            "holding_context": holding or {}
        })
        time.sleep(0.05)

    by_type = {"etf": [], "mutual_fund": [], "stock": [], "unknown": []}
    analyst_data: Dict[str, Any] = {"generated_at": now_iso(), "symbols": {}, "missing_provider_keys": missing_keys}
    for r in rows:
        by_type.setdefault(r["asset_type"], []).append(r)
        analyst_data["symbols"][r["symbol"]] = r.get("analyst", {})

    write_json(STATE / "analyst_data.json", analyst_data)
    write_json(STATE / "etf_intelligence.json", {"generated_at": now_iso(), "items": by_type.get("etf", [])})
    write_json(STATE / "mutual_fund_intelligence.json", {"generated_at": now_iso(), "items": by_type.get("mutual_fund", [])})
    write_json(STATE / "stock_intelligence.json", {"generated_at": now_iso(), "items": by_type.get("stock", [])})
    write_json(STATE / "asset_intelligence.json", {"generated_at": now_iso(), "items": rows, "config": cfg.get("version")})
    mirror_to_db(rows, env)

    summary = {
        "ok": True,
        "generated_at": now_iso(),
        "symbols_enriched": len(rows),
        "counts": {k: len(v) for k, v in by_type.items()},
        "missing_provider_keys": missing_keys,
        "files_written": [
            str(STATE / "analyst_data.json"),
            str(STATE / "etf_intelligence.json"),
            str(STATE / "mutual_fund_intelligence.json"),
            str(STATE / "stock_intelligence.json"),
            str(STATE / "asset_intelligence.json")
        ]
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"[asset-intel] enriched {len(rows)} symbols; wrote intelligence state files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
