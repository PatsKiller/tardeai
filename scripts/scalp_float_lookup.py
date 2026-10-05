#!/usr/bin/env python3
"""Float (and reference price) lookup for scalp-universe symbols the scanner left without one.

Operator 2026-10-05: an unknown float must FAIL CLOSED, but look it up before excluding. Bare
social rows (HPE, DELL, CHPT) carried no float in scalp_scan_results; a real small cap the scanner
never enriched would be lost too. Order: cache → Finviz Elite export v=131 (header-keyed, via
finviz_enrichment._fetch_view; one request per 20 tickers) → Alpha Vantage OVERVIEW SharesFloat
(free tier 25/day, paced). Bounded per run by config `universe.float_lookup`. Results — found and
not-found — are cached with TTLs so the 5-minute engine does not refetch.

READ-ONLY toward every provider. No secret is printed or stored; the cache holds numbers only.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_REPO = Path(__file__).resolve().parent.parent


def default_cache_path() -> Path:
    try:
        from active_trader.momentum_alerts import journal_dir
        return journal_dir() / "scalp_float_cache.json"
    except Exception:  # noqa: BLE001
        return _REPO / "data" / "state" / "scalp_float_cache.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True))
    os.replace(tmp, path)


def _fresh(rec: dict, now: float, fl: dict) -> bool:
    ttl_h = fl["ttl_hours"] if rec.get("float_mm") is not None else fl["negative_ttl_hours"]
    return (now - float(rec.get("fetched_ts") or 0)) < float(ttl_h) * 3600


def _positive(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None   # finviz_enrichment stores an absent float as 0.0 — that is unknown


def finviz_fetch(symbols: list[str]) -> dict:
    """{SYM: {"float_mm", "price"}} from Finviz v=131 (Shares Float is in millions)."""
    import finviz_enrichment as fe
    out = {}
    for sym, rec in (fe._fetch_view(symbols, 131, _REPO) or {}).items():
        out[sym.upper()] = {"float_mm": _positive(rec.get("float_m")), "price": _positive(rec.get("price"))}
    return out


def alpha_vantage_float(symbol: str) -> Optional[float]:
    """SharesFloat from AV OVERVIEW, in millions. None on missing key, quota notice or error."""
    from external_market_data_ingest import _av_overview, _av_burst_notice, _env, AV_MIN_INTERVAL_S
    key = _env("ALPHA_VANTAGE_API_KEY")
    if not key:
        return None
    data = _av_overview(symbol, key)
    if _av_burst_notice(data) or "Information" in data or "Note" in data:
        return None
    time.sleep(AV_MIN_INTERVAL_S)
    sf = _positive(data.get("SharesFloat"))
    return round(sf / 1e6, 4) if sf else None


def lookup_floats(symbols: list[str], u: dict, *, cache_path: Optional[Path] = None,
                  finviz: Callable[[list[str]], dict] = finviz_fetch,
                  av: Callable[[str], Optional[float]] = alpha_vantage_float,
                  now: Optional[float] = None) -> dict:
    """{SYM: {"float_mm", "price", "source"}} for the symbols it could resolve (cache or provider).
    Symbols still unknown are cached negative and left out of the result."""
    fl = u["float_lookup"]
    if not fl.get("enabled") or not symbols:
        return {}
    now = time.time() if now is None else now
    path = cache_path or default_cache_path()
    cache = _load(path)
    out, need = {}, []
    for s in dict.fromkeys(x.upper() for x in symbols):
        rec = cache.get(s)
        if rec and _fresh(rec, now, fl):
            if rec.get("float_mm") is not None:
                out[s] = {k: rec.get(k) for k in ("float_mm", "price", "source")}
        else:
            need.append(s)
    need = need[: int(fl["max_lookups_per_run"])]
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    got = {}
    if need and "finviz" in fl["sources"]:
        try:
            got = finviz(need) or {}
        except Exception as e:  # noqa: BLE001
            print(f"  [float-lookup] finviz failed: {type(e).__name__}")
    av_left = int(fl["av_max_lookups_per_run"]) if "alpha_vantage" in fl["sources"] else 0
    for s in need:
        rec = got.get(s) or {}
        flt, price, src = rec.get("float_mm"), rec.get("price"), "finviz"
        if flt is None and av_left > 0:
            av_left -= 1
            try:
                flt, src = av(s), "alpha_vantage"
            except Exception as e:  # noqa: BLE001
                print(f"  [float-lookup] alpha_vantage {s} failed: {type(e).__name__}")
                flt = None
        cache[s] = {"float_mm": flt, "price": price, "source": src if flt is not None else None,
                    "fetched_ts": now, "fetched_at": stamp}
        if flt is not None:
            out[s] = {"float_mm": flt, "price": price, "source": src}
    if need:
        try:
            _save(path, cache)
        except Exception as e:  # noqa: BLE001
            print(f"  [float-lookup] cache not saved: {type(e).__name__}")
        print(f"  [float-lookup] looked up {len(need)}: found {sum(1 for s in need if s in out)}")
    return out
