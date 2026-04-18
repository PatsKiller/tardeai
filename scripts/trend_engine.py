"""trend_engine.py — Trend arrow computation for Trade AI v11.

Computes directional arrows by comparing current run data against the
previous run's snapshot stored in state.json.

Trend types:
  - Ticker score velocity  (score up/down/flat between runs)
  - Sector intraday trend  (sector ETF % up/down since last run snapshot)
  - RVOL acceleration      (RVOL higher/lower/flat vs last run)
  - SPY/QQQ/IWM direction  (index % up/down vs last run)
  - VIX direction          (fear rising/falling)

Arrows:
  ⬆  = accelerating / improving
  ⬇  = decelerating / deteriorating
  →  = flat (within threshold)
  🚀 = strong acceleration (RVOL jumped threshold)
  ❄  = cooling fast
"""
from __future__ import annotations
from typing import Any, Dict, List


# ── Thresholds ────────────────────────────────────────────────────────────────

SCORE_FLAT_BAND       = 3      # score delta <= 3 = flat
RVOL_FLAT_BAND        = 0.5   # RVOL delta <= 0.5 = flat
RVOL_STRONG_THRESHOLD = 2.0   # RVOL jumped >= 2x = rocket
SECTOR_FLAT_BAND      = 0.2   # sector % delta <= 0.2 = flat
INDEX_FLAT_BAND       = 0.15  # SPY/QQQ/IWM % delta <= 0.15 = flat
VIX_FLAT_BAND         = 0.5   # VIX % delta <= 0.5 = flat


# ── Arrow helpers ─────────────────────────────────────────────────────────────

def _score_arrow(delta: float) -> str:
    if delta > SCORE_FLAT_BAND:  return "⬆"
    if delta < -SCORE_FLAT_BAND: return "⬇"
    return "→"

def _rvol_arrow(current: float, previous: float) -> str:
    delta = current - previous
    if delta >= RVOL_STRONG_THRESHOLD: return "🚀"
    if delta > RVOL_FLAT_BAND:         return "⬆"
    if delta < -RVOL_FLAT_BAND:        return "❄"
    return "→"

def _pct_arrow(current: float, previous: float, band: float) -> str:
    delta = current - previous
    if delta > band:  return "⬆"
    if delta < -band: return "⬇"
    return "→"


# ── Ticker trend enrichment ───────────────────────────────────────────────────

def enrich_ticker_trends(
    scored_tickers: List[Dict[str, Any]],
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Add trend metadata to each scored ticker dict.

    Adds keys:
      score_arrow   : ⬆ / ⬇ / →
      score_delta   : numeric score change vs last run
      rvol_arrow    : ⬆ / ⬇ / → / 🚀 / ❄
      rvol_delta    : numeric RVOL change vs last run
      prev_score    : score from last run (or None if first appearance)
      prev_rvol     : RVOL from last run (or None)
    """
    for t in scored_tickers:
        sym = t["symbol"]
        prev_entry = state.get(sym, {})
        history = prev_entry.get("score_history", [])
        last = history[-1] if history else {}

        prev_score = last.get("score")
        prev_rvol  = prev_entry.get("last_rvol")

        t["prev_score"]   = prev_score
        t["score_delta"]  = (t["score"] - prev_score) if prev_score is not None else 0
        t["score_arrow"]  = _score_arrow(t["score_delta"]) if prev_score is not None else "🆕"

        current_rvol = t.get("relative_volume", 0) or 0
        t["prev_rvol"]  = prev_rvol
        t["rvol_delta"] = round(current_rvol - prev_rvol, 2) if prev_rvol is not None else 0
        t["rvol_arrow"] = _rvol_arrow(current_rvol, prev_rvol) if prev_rvol is not None else "→"

        # Persist current RVOL for next run comparison
        state.setdefault(sym, {})["last_rvol"] = current_rvol

    return scored_tickers


# ── Sector trend enrichment ───────────────────────────────────────────────────

def enrich_sector_trends(
    sectors: List[Dict[str, Any]],
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Add trend arrows to each sector dict by comparing to previous run snapshot."""
    prev_sectors: Dict[str, float] = state.get("_prev_sector_pcts", {})

    for s in sectors:
        sym = s["symbol"]
        current_pct  = s.get("change_percent", 0) or 0
        previous_pct = prev_sectors.get(sym)
        if previous_pct is not None:
            s["trend_arrow"] = _pct_arrow(current_pct, previous_pct, SECTOR_FLAT_BAND)
            s["sector_delta"] = round(current_pct - previous_pct, 2)
        else:
            s["trend_arrow"]  = "→"
            s["sector_delta"] = 0

    # Persist for next run
    state["_prev_sector_pcts"] = {s["symbol"]: s.get("change_percent", 0) for s in sectors}
    return sectors


# ── Index trend enrichment ────────────────────────────────────────────────────

def enrich_index_trends(
    indices: Dict[str, Dict[str, Any]],
    state: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Add trend arrows and deltas to SPY/QQQ/IWM."""
    prev_indices: Dict[str, float] = state.get("_prev_index_pcts", {})

    for sym, data in indices.items():
        current_pct  = data.get("change_percent", 0) or 0
        previous_pct = prev_indices.get(sym)
        if previous_pct is not None:
            data["trend_arrow"] = _pct_arrow(current_pct, previous_pct, INDEX_FLAT_BAND)
            data["index_delta"] = round(current_pct - previous_pct, 2)
        else:
            data["trend_arrow"] = "→"
            data["index_delta"] = 0

    state["_prev_index_pcts"] = {sym: d.get("change_percent", 0) for sym, d in indices.items()}
    return indices


# ── VIX trend enrichment ──────────────────────────────────────────────────────

def enrich_vix_trend(
    vix: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Add trend arrow to VIX dict."""
    prev_vix_pct = state.get("_prev_vix_pct")
    current_pct  = vix.get("change_percent", 0) or 0

    if prev_vix_pct is not None:
        vix["trend_arrow"] = _pct_arrow(current_pct, prev_vix_pct, VIX_FLAT_BAND)
        vix["vix_delta"]   = round(current_pct - prev_vix_pct, 2)
    else:
        vix["trend_arrow"] = "→"
        vix["vix_delta"]   = 0

    state["_prev_vix_pct"] = current_pct
    return vix


# ── Master enrichment call ────────────────────────────────────────────────────

def enrich_all_trends(
    scored_tickers: List[Dict[str, Any]],
    market_snapshot: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich tickers and market snapshot with all trend arrows.

    Mutates scored_tickers, market_snapshot in place.
    Also mutates state to persist current values for next run.
    Returns the mutated market_snapshot.
    """
    enrich_ticker_trends(scored_tickers, state)
    enrich_sector_trends(market_snapshot.get("sectors", []), state)
    enrich_index_trends(market_snapshot.get("indices", {}), state)
    enrich_vix_trend(market_snapshot.get("vix", {}), state)
    return market_snapshot
