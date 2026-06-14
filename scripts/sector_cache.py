#!/usr/bin/env python3
"""sector_cache.py — durable GICS sector lookup for individual stocks/ETFs (yfinance-backed).

Phase3's look-through resolves funds via fund_lookthrough.json and direct stocks via the snapshot's
classification fields — but those fields are often empty, so real holdings (Visa, RTX, NEE …) fell to
"Other / Unclassified". This is the fallback: yfinance sector (equities) / category (sector ETFs),
normalized to the GICS naming used in resolved_sectors, and CACHED to data/portfolios/state/sector_cache.json
so the network hit is one-time per symbol. Diversified ETFs (Derivative Income, Large Blend …) return
None so the look-through / Other handles them.

  from sector_cache import get_sector ;  get_sector("V")  -> "Financial Services"
  python3 scripts/sector_cache.py --warm AAPL,V,XLI   # pre-fetch + cache
"""
from __future__ import annotations

import json
from pathlib import Path

_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "sector_cache.json"

# yfinance equity sectors already match the resolved_sectors GICS taxonomy. ETF `category` strings need
# mapping; only true SECTOR categories map — diversified categories return None (not a sector).
_GICS = {"Technology", "Healthcare", "Financial Services", "Communication Services", "Industrials",
         "Consumer Cyclical", "Consumer Defensive", "Energy", "Basic Materials", "Real Estate", "Utilities"}
_ETF_CAT_TO_GICS = {
    "financial": "Financial Services", "health": "Healthcare", "technology": "Technology",
    "industrials": "Industrials", "utilities": "Utilities", "energy": "Energy",
    "materials": "Basic Materials", "natural resources": "Basic Materials", "real estate": "Real Estate",
    "communications": "Communication Services", "consumer defensive": "Consumer Defensive",
    "consumer cyclical": "Consumer Cyclical",
}


def _load() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(d, indent=2, sort_keys=True))
    except Exception:
        pass


def _normalize(sector: str | None, category: str | None) -> str | None:
    if sector and sector in _GICS:
        return sector
    if sector:  # yfinance sometimes returns close variants
        s = sector.strip()
        if s in _GICS:
            return s
    if category:  # ETF — only sector ETFs map to a GICS sector
        return _ETF_CAT_TO_GICS.get(category.strip().lower())
    return None


def _fetch(sym: str) -> str | None:
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info or {}
        return _normalize(info.get("sector"), info.get("category"))
    except Exception:
        return None


def get_sector(sym: str, allow_fetch: bool = True) -> str | None:
    """Return the GICS sector for a symbol, or None if not a single-sector security. Cached. A cached
    None (miss) is stored as "" to avoid refetching every run; pass allow_fetch=False to read-only."""
    sym = (sym or "").strip().upper()
    if not sym:
        return None
    cache = _load()
    if sym in cache:
        v = cache[sym]
        return v or None
    if not allow_fetch:
        return None
    sec = _fetch(sym)
    cache[sym] = sec or ""
    _save(cache)
    return sec


def warm(symbols: list[str]) -> dict:
    """Pre-fetch a batch (e.g. all holdings) into the cache. Returns {resolved, missed}."""
    resolved = missed = 0
    for s in symbols:
        if get_sector(s):
            resolved += 1
        else:
            missed += 1
    return {"resolved": resolved, "missed": missed, "total": len(symbols)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--warm", help="comma-separated symbols to pre-fetch")
    a = ap.parse_args()
    if a.warm:
        print(json.dumps(warm([s.strip() for s in a.warm.split(",") if s.strip()]), indent=2))
    else:
        print(f"cache: {_CACHE_PATH} ({len(_load())} symbols)")
