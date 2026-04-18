"""short_interest.py — Short interest / squeeze flag for Trade AI v12.

Reads short_float % directly from Finviz screener data (already downloaded).
No additional API calls required.

Squeeze tiers:
  high_squeeze    : short float > 30% — significant short fuel
  moderate_squeeze: short float 15-30%
  low_squeeze     : short float 5-15%
  none            : < 5% or unknown

Short float is a catalyst pillar multiplier in scoring.py:
  high_squeeze    + high-impact catalyst → +2 pts bonus on catalyst pillar
  moderate_squeeze + any catalyst        → +1 pt bonus

Also generates a run-level squeeze summary for the dashboard.
"""
from __future__ import annotations
from typing import Any, Dict, List


# ── Thresholds ─────────────────────────────────────────────────────────────────

HIGH_SQUEEZE_PCT     = 30.0
MODERATE_SQUEEZE_PCT = 15.0
LOW_SQUEEZE_PCT      =  5.0


# ── Finviz column names for short data ────────────────────────────────────────

SHORT_FLOAT_COLS = [
    "Short Float",      # standard Finviz column name
    "short_float",      # normalised column name after ingestion
    "Short Float (SA)", # alternate Finviz Elite label
    "Shs Float",        # sometimes merged
]


def _extract_short_float(ticker_row: Dict[str, Any]) -> float:
    """Extract short float % from a ticker row dict, trying multiple column names."""
    for col in SHORT_FLOAT_COLS:
        val = ticker_row.get(col)
        if val is not None:
            try:
                s = str(val).replace("%", "").replace(",", "").strip()
                if s and s != "-":
                    return float(s)
            except (ValueError, TypeError):
                continue
    return 0.0


def _squeeze_tier(short_pct: float) -> str:
    if short_pct >= HIGH_SQUEEZE_PCT:     return "high_squeeze"
    if short_pct >= MODERATE_SQUEEZE_PCT: return "moderate_squeeze"
    if short_pct >= LOW_SQUEEZE_PCT:      return "low_squeeze"
    return "none"


def _squeeze_emoji(tier: str) -> str:
    return {
        "high_squeeze":     "🔥",
        "moderate_squeeze": "⚠️",
        "low_squeeze":      "📊",
        "none":             "",
    }.get(tier, "")


def _squeeze_bonus(tier: str, catalyst_tier: str) -> int:
    """Catalyst pillar bonus points for squeeze + catalyst combination."""
    has_catalyst = catalyst_tier in ("high_impact", "medium_impact")
    if tier == "high_squeeze" and catalyst_tier == "high_impact":
        return 2
    if tier in ("high_squeeze", "moderate_squeeze") and has_catalyst:
        return 1
    return 0


# ── Main enrichment ────────────────────────────────────────────────────────────

def enrich_short_interest(
    tickers: List[Dict[str, Any]],
    scored: List[Dict[str, Any]] | None = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Add short interest fields to each ticker row and return a run summary.

    Enriches tickers in-place. If scored is provided, also enriches scored tickers.
    Returns (enriched_tickers, short_summary).

    Fields added per ticker:
      short_float_pct  : float (percentage, e.g. 24.5)
      squeeze_tier     : "high_squeeze" | "moderate_squeeze" | "low_squeeze" | "none"
      squeeze_emoji    : str
      squeeze_bonus    : int  (catalyst pillar bonus points)
    """
    high_squeezers     = []
    moderate_squeezers = []

    # Build lookup from scored list if provided
    scored_lookup: Dict[str, Dict] = {t["symbol"]: t for t in (scored or [])}

    for row in tickers:
        sym         = str(row.get("symbol", "")).upper()
        short_pct   = _extract_short_float(row)
        tier        = _squeeze_tier(short_pct)
        emoji       = _squeeze_emoji(tier)
        cat_tier    = scored_lookup.get(sym, {}).get("catalyst_tier", "none")
        bonus       = _squeeze_bonus(tier, cat_tier)

        row["short_float_pct"] = round(short_pct, 1)
        row["squeeze_tier"]    = tier
        row["squeeze_emoji"]   = emoji
        row["squeeze_bonus"]   = bonus

        if tier == "high_squeeze":
            high_squeezers.append({"symbol": sym, "short_pct": short_pct})
        elif tier == "moderate_squeeze":
            moderate_squeezers.append({"symbol": sym, "short_pct": short_pct})

    # Apply same data to scored tickers
    ticker_lookup = {str(t.get("symbol","")).upper(): t for t in tickers}
    for s in (scored or []):
        sym = str(s.get("symbol","")).upper()
        src = ticker_lookup.get(sym, {})
        s["short_float_pct"] = src.get("short_float_pct", 0.0)
        s["squeeze_tier"]    = src.get("squeeze_tier", "none")
        s["squeeze_emoji"]   = src.get("squeeze_emoji", "")
        s["squeeze_bonus"]   = src.get("squeeze_bonus", 0)

    # Run-level summary
    summary = {
        "high_squeeze_count":     len(high_squeezers),
        "moderate_squeeze_count": len(moderate_squeezers),
        "top_squeezers":          sorted(high_squeezers, key=lambda x: x["short_pct"], reverse=True)[:5],
        "any_squeeze":            len(high_squeezers) + len(moderate_squeezers) > 0,
    }
    return tickers, summary


def apply_squeeze_bonus_to_scores(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply squeeze bonus to catalyst pillar score for each ticker.

    Called AFTER short interest enrichment and BEFORE final score capping.
    Mutates scored in-place.
    """
    for t in scored:
        bonus = t.get("squeeze_bonus", 0)
        if bonus > 0:
            pb = t.get("pillar_breakdown", {})
            old_cat   = pb.get("catalyst", 0)
            new_cat   = min(15, old_cat + bonus)   # cap at pillar max
            pb["catalyst"] = new_cat
            t["pillar_breakdown"] = pb
            t["score"] = min(55, t.get("score", 0) + bonus)
            t["squeeze_applied"] = True
    return scored
