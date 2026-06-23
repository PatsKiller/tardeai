#!/usr/bin/env python3
"""market_rotation_signals.py — Detect index/style rotation (IWM vs SPY, small-cap news breadth).

Used by inference FeatureLayer, health_agent gap checks, and API synthesis. Deterministic + cheap.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

_SMALL_CAP_NEWS = re.compile(
    r"\b(small[\s-]?cap|russell\s*200|\brussell\b|\biwm\b|\brut\b|micro[\s-]?cap|"
    r"regional bank|value rotation|breadth thrust|market breadth)\b", re.I)

_SMALL_CAP_SYMS = re.compile(r"\b(IWM|IWN|IWO|IJR|VB|SLY|RUT)\b")


def _pct_change(closes: list) -> Optional[float]:
    if not closes or len(closes) < 2:
        return None
    try:
        a, b = float(closes[0]), float(closes[-1])
        if a <= 0:
            return None
        return round((b - a) / a * 100, 2)
    except (TypeError, ValueError):
        return None


def _returns_from_price_cache(sym: str, days: int) -> Optional[float]:
    try:
        cache = json.loads((STATE_DIR / "price_cache.json").read_text())
        series = (cache.get("symbols") or {}).get(sym.upper()) or (cache.get(sym.upper()))
        if isinstance(series, dict):
            closes = series.get("close") or series.get("closes") or []
        elif isinstance(series, list):
            closes = [r.get("close") if isinstance(r, dict) else r for r in series]
        else:
            closes = []
        if len(closes) < 2:
            return None
        window = closes[-min(len(closes), days + 1):]
        return _pct_change([window[0], window[-1]])
    except Exception:
        return None


def _returns_from_market_snapshot() -> Dict[str, Optional[float]]:
    out = {"spy_1d": None, "iwm_1d": None}
    try:
        from market_context import get_market_snapshot
        snap = get_market_snapshot()
        for sym, key in (("SPY", "spy_1d"), ("IWM", "iwm_1d")):
            d = (snap.get("indices") or {}).get(sym) or {}
            ch = d.get("change_percent")
            if ch is not None:
                out[key] = round(float(ch), 2)
    except Exception:
        pass
    return out


def detect_small_cap_rotation(*, news: list | None = None) -> Dict[str, Any]:
    """Return rotation signal when IWM is outperforming SPY on 1d or ~20d window."""
    snap = _returns_from_market_snapshot()
    spy_20 = _returns_from_price_cache("SPY", 20)
    iwm_20 = _returns_from_price_cache("IWM", 20)
    spy_5 = _returns_from_price_cache("SPY", 5)
    iwm_5 = _returns_from_price_cache("IWM", 5)

    rs_1d = None
    if snap["spy_1d"] is not None and snap["iwm_1d"] is not None:
        rs_1d = round(snap["iwm_1d"] - snap["spy_1d"], 2)
    rs_20 = None
    if spy_20 is not None and iwm_20 is not None:
        rs_20 = round(iwm_20 - spy_20, 2)
    rs_5 = None
    if spy_5 is not None and iwm_5 is not None:
        rs_5 = round(iwm_5 - spy_5, 2)

    news_hits = 0
    for n in news or []:
        blob = f"{n.get('title','')} {n.get('summary','')}"
        if _SMALL_CAP_NEWS.search(blob):
            news_hits += 1

    # Outperformance thresholds: 1d RS >= 0.35% or 20d RS >= 2.5%
    signal = None
    strength = 0.0
    if rs_20 is not None and rs_20 >= 2.5:
        signal = "small_cap_outperform"
        strength = min(1.0, rs_20 / 8.0)
    elif rs_5 is not None and rs_5 >= 1.2:
        signal = "small_cap_outperform"
        strength = min(0.85, rs_5 / 5.0)
    elif rs_1d is not None and rs_1d >= 0.35:
        signal = "small_cap_outperform"
        strength = min(0.7, rs_1d / 1.5)

    explain = []
    if rs_1d is not None:
        explain.append(f"IWM vs SPY 1d RS {rs_1d:+.2f}%")
    if rs_5 is not None:
        explain.append(f"5d IWM {iwm_5:+.2f}% vs SPY {spy_5:+.2f}%")
    if rs_20 is not None:
        explain.append(f"20d IWM {iwm_20:+.2f}% vs SPY {spy_20:+.2f}%")
    if news_hits:
        explain.append(f"{news_hits} small-cap/Russell news hits in lookback")

    return {
        "signal": signal,
        "strength": round(strength, 2),
        "rs_1d": rs_1d,
        "rs_5d": rs_5,
        "rs_20d": rs_20,
        "iwm_1d": snap.get("iwm_1d"),
        "spy_1d": snap.get("spy_1d"),
        "small_cap_news_hits": news_hits,
        "explain": "; ".join(explain) if explain else "insufficient index data",
    }


def coverage_gap(rotation: Dict[str, Any]) -> Dict[str, Any]:
    """Compare market small-cap strength vs system outputs (proposals, watchlist, news)."""
    gap = {"has_market_signal": rotation.get("signal") == "small_cap_outperform", "gaps": []}
    if not gap["has_market_signal"]:
        return gap

    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return gap
        props = _execute(
            """SELECT COUNT(*) AS c FROM paper_trade_proposals
               WHERE created_at > now() - interval '7 days'
                 AND (strategy_id IN ('swing_breakout','swing_trade','momentum_scalp','sector_rotation')
                      OR catalyst ILIKE '%small%' OR catalyst ILIKE '%russell%' OR catalyst ILIKE '%IWM%')""",
            fetch="one")
        wl = _execute(
            """SELECT COUNT(*) AS c FROM watchlist_items
               WHERE status='active' AND (
                      source = 'small_cap_rotation'
                      OR bucket = 'rotation'
                      OR provenance_reason ILIKE '%small%cap%'
                      OR provenance_reason ILIKE '%russell%'
                      OR symbol IN ('IWM','IWN','IWO'))""",
            fetch="one")
        news = _execute(
            """SELECT COUNT(*) AS c FROM news_articles
               WHERE created_at > now() - interval '7 days'
                 AND (title ILIKE '%small cap%' OR title ILIKE '%russell%'
                      OR summary ILIKE '%small cap%' OR summary ILIKE '%russell 200%')""",
            fetch="one")
        gap["proposal_count"] = int((props or {}).get("c") or 0)
        gap["watchlist_count"] = int((wl or {}).get("c") or 0)
        gap["news_count"] = int((news or {}).get("c") or 0)
        if gap["news_count"] < 3:
            gap["gaps"].append("thin_small_cap_news")
        if gap["proposal_count"] < 1:
            gap["gaps"].append("no_small_cap_swing_proposals")
        if gap["watchlist_count"] < 1:
            gap["gaps"].append("no_small_cap_watchlist")
        gap["severity"] = "warning" if gap["gaps"] else "info"
    except Exception as e:
        gap["error"] = str(e)[:200]
    return gap