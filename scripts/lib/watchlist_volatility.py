"""Watchlist plan stop vs ATR context — ATR₂₀ (Maria/Telegram) + ATR₁₄ (Finviz/industry)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ATR20_CACHE_PATH = PROJECT_ROOT / "data" / "runtime" / "atr20_cache.json"
ATR20_CACHE_TTL_H = 6
MAX_ATR20_FETCH_PER_REQUEST = 30


def volatility_band(atr_pct: float | None) -> str | None:
    """ATR% of price → low | moderate | high | extreme."""
    if atr_pct is None:
        return None
    p = float(atr_pct)
    if p < 2:
        return "low"
    if p < 5:
        return "moderate"
    if p < 10:
        return "high"
    return "extreme"


def _atr_from_bars(bars: list[dict], period: int = 20) -> float | None:
    if len(bars) < period + 1:
        return None
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    trs = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / period if trs else None


def _load_atr20_cache() -> dict:
    try:
        return json.loads(ATR20_CACHE_PATH.read_text()) or {}
    except Exception:
        return {}


def _save_atr20_cache(cache: dict) -> None:
    try:
        ATR20_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ATR20_CACHE_PATH.write_text(json.dumps(cache, indent=2, default=str))
    except Exception:
        pass


def _fetch_atr20(symbol: str) -> float | None:
    """20-day ATR from daily bars (yfinance → Alpaca fallback) — matches Maria Telegram math."""
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from watchlist_entry_planner import _bars  # noqa: E402
        bars = _bars(symbol.upper(), 70)
        if not bars:
            return None
        return _atr_from_bars(bars, 20)
    except Exception:
        return None


def atr20_for_symbol(symbol: str, price: float | None = None, *, allow_fetch: bool = True) -> dict:
    """Return atr_20 + atr_20_pct (+ band). Uses disk cache with TTL."""
    sym = (symbol or "").upper().strip()
    out: dict = {}
    if not sym:
        return out
    cache = _load_atr20_cache()
    row = cache.get(sym) or {}
    atr = row.get("atr_20")
    ts = row.get("ts")
    fresh = False
    if atr is not None and ts:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(str(ts).replace("Z", "+00:00"))).total_seconds() / 3600
            fresh = age_h < ATR20_CACHE_TTL_H
        except Exception:
            fresh = False
    if not fresh and allow_fetch:
        atr = _fetch_atr20(sym)
        if atr is not None:
            cache[sym] = {
                "atr_20": round(float(atr), 4),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            _save_atr20_cache(cache)
    if atr is None:
        return out
    atr = float(atr)
    out["atr_20"] = round(atr, 4)
    if price:
        try:
            px = float(price)
            if px > 0:
                out["atr_20_pct"] = round(atr / px * 100, 2)
                band = volatility_band(out["atr_20_pct"])
                if band:
                    out["volatility_band_20"] = band
        except (TypeError, ValueError):
            pass
    return out


def _atr20_cache_fresh(row: dict, now: datetime) -> bool:
    atr = row.get("atr_20")
    ts = row.get("ts")
    if atr is None or not ts:
        return False
    try:
        age_h = (now - datetime.fromisoformat(str(ts).replace("Z", "+00:00"))).total_seconds() / 3600
        return age_h < ATR20_CACHE_TTL_H
    except Exception:
        return False


def _apply_atr20_to_item(it: dict, atr: float) -> None:
    try:
        px = float(it.get("price") or it.get("latest_price") or 0) or None
    except (TypeError, ValueError):
        px = None
    atr = float(atr)
    it["atr_20"] = round(atr, 4)
    if px and px > 0:
        it["atr_20_pct"] = round(atr / px * 100, 2)
        band = volatility_band(it["atr_20_pct"])
        if band:
            it["volatility_band_20"] = band


def attach_atr20_batch(items: list[dict], *, max_fetch: int | None = None) -> None:
    """Fill atr_20 on items — cache-first; fetch misses with plan symbols prioritized."""
    if not items:
        return
    cap = max_fetch
    if cap is None:
        cap = min(30, max(MAX_ATR20_FETCH_PER_REQUEST, len(items))) if len(items) <= 30 else MAX_ATR20_FETCH_PER_REQUEST
    cache = _load_atr20_cache()
    budget = max(0, int(cap))
    now = datetime.now(timezone.utc)
    dirty = False

    def _rank(it: dict) -> tuple:
        has_plan = 0 if it.get("entry_stop") else 1
        rank = it.get("hermes_rank")
        try:
            hr = int(rank) if rank is not None else 99999
        except (TypeError, ValueError):
            hr = 99999
        return (has_plan, hr)

    ordered = sorted(items, key=_rank)

    # Pass 1: apply fresh cache (no network).
    need_fetch: list[dict] = []
    for it in ordered:
        sym = str(it.get("symbol") or "").upper()
        if not sym:
            continue
        row = cache.get(sym) or {}
        if _atr20_cache_fresh(row, now):
            _apply_atr20_to_item(it, float(row["atr_20"]))
        else:
            need_fetch.append(it)

    # Pass 2: fetch misses — plans + top Hermes rank first.
    for it in need_fetch:
        if budget <= 0:
            break
        sym = str(it.get("symbol") or "").upper()
        fetched = _fetch_atr20(sym)
        if fetched is None:
            continue
        atr = round(float(fetched), 4)
        cache[sym] = {"atr_20": atr, "ts": now.isoformat()}
        _apply_atr20_to_item(it, atr)
        budget -= 1
        dirty = True

    if dirty:
        _save_atr20_cache(cache)


def warm_atr20_cache(symbols: list[str], *, max_fetch: int | None = None) -> dict:
    """Pre-fetch ATR₂₀ for a symbol list (watchlist warm). Returns {warmed, skipped, failed}."""
    syms = []
    seen: set[str] = set()
    for s in symbols:
        sym = (s or "").upper().strip()
        if sym and sym not in seen:
            seen.add(sym)
            syms.append(sym)
    cache = _load_atr20_cache()
    now = datetime.now(timezone.utc)
    warmed = skipped = failed = 0
    budget = max_fetch if max_fetch is not None else len(syms)
    for sym in syms:
        row = cache.get(sym) or {}
        if _atr20_cache_fresh(row, now):
            skipped += 1
            continue
        if budget <= 0:
            break
        atr = _fetch_atr20(sym)
        budget -= 1
        if atr is None:
            failed += 1
            continue
        cache[sym] = {"atr_20": round(float(atr), 4), "ts": now.isoformat()}
        warmed += 1
    if warmed:
        _save_atr20_cache(cache)
    return {"warmed": warmed, "skipped": skipped, "failed": failed, "total": len(syms)}


def refresh_atr20_symbol(symbol: str, price: float | None = None) -> dict:
    """Force-refresh ATR₂₀ for one symbol (manual/auto card refresh)."""
    sym = (symbol or "").upper().strip()
    atr = _fetch_atr20(sym)
    if atr is None:
        return {}
    cache = _load_atr20_cache()
    cache[sym] = {"atr_20": round(float(atr), 4), "ts": datetime.now(timezone.utc).isoformat()}
    _save_atr20_cache(cache)
    out = {"atr_20": cache[sym]["atr_20"]}
    if price:
        try:
            px = float(price)
            if px > 0:
                out["atr_20_pct"] = round(float(atr) / px * 100, 2)
                band = volatility_band(out["atr_20_pct"])
                if band:
                    out["volatility_band_20"] = band
        except (TypeError, ValueError):
            pass
    return out


def plan_volatility_fields(
    *,
    entry_limit: float | None,
    entry_stop: float | None,
    price: float | None,
    atr_14: float | None,
    atr_20: float | None = None,
    atr_20_pct: float | None = None,
) -> dict:
    """Derive ATR% and plan stop distance in ATR multiples (ATR₂₀ primary, ATR₁₄ secondary)."""
    out: dict = {}
    try:
        px = float(price) if price is not None else None
    except (TypeError, ValueError):
        px = None
    try:
        atr14 = float(atr_14) if atr_14 is not None else None
    except (TypeError, ValueError):
        atr14 = None
    if px and atr14 and atr14 > 0:
        out["atr_14"] = round(atr14, 4)
        out["atr_pct"] = round(atr14 / px * 100, 2)
    try:
        atr20 = float(atr_20) if atr_20 is not None else None
    except (TypeError, ValueError):
        atr20 = None
    if atr_20_pct is not None:
        try:
            out["atr_20_pct"] = round(float(atr_20_pct), 2)
        except (TypeError, ValueError):
            pass
    if atr20 and atr20 > 0:
        out["atr_20"] = round(atr20, 4)
        if px and px > 0 and "atr_20_pct" not in out:
            out["atr_20_pct"] = round(atr20 / px * 100, 2)
    if out.get("atr_20_pct") is not None:
        band20 = volatility_band(out["atr_20_pct"])
        if band20:
            out["volatility_band_20"] = band20
            out["volatility_band"] = band20
    elif out.get("atr_pct") is not None:
        band14 = volatility_band(out["atr_pct"])
        if band14:
            out["volatility_band"] = band14

    try:
        entry = float(entry_limit) if entry_limit is not None else None
        stop = float(entry_stop) if entry_stop is not None else None
    except (TypeError, ValueError):
        entry = stop = None
    if entry and stop and entry > stop:
        dist = entry - stop
        out["plan_stop_dist_pct"] = round(dist / entry * 100, 2)
        if atr20 and atr20 > 0:
            out["plan_stop_atr20_mult"] = round(dist / atr20, 2)
            out["plan_stop_tight_vs_atr20"] = out["plan_stop_atr20_mult"] < 1.0
        if atr14 and atr14 > 0:
            out["plan_stop_atr_mult"] = round(dist / atr14, 2)
            out["plan_stop_tight_vs_atr"] = out["plan_stop_atr_mult"] < 1.0
        # Primary tight flag: ATR₂₀ (Maria parity), fallback ATR₁₄
        out["plan_stop_tight"] = out.get("plan_stop_tight_vs_atr20") or out.get("plan_stop_tight_vs_atr") or False
    return out