"""Export watchlist + holdings lifecycle into outcome_bus.json (read/write closed loop)."""
from __future__ import annotations

from typing import Any


def _load_watchlist_lifecycle() -> dict[str, Any]:
    try:
        from lib.hermes_scope_governor.watchlist_lifecycle import load_lifecycle_state
        return load_lifecycle_state() or {}
    except Exception:
        return {}


def _load_holdings_lifecycle() -> dict[str, Any]:
    try:
        from lib.hermes_holdings_lifecycle.holdings_lifecycle import load_holdings_lifecycle_state
        return load_holdings_lifecycle_state() or {}
    except Exception:
        return {}


def _load_closed_loop_eval() -> dict[str, Any] | None:
    try:
        from lib.hermes_thresholds.closed_loop_evaluation import closed_loop_evaluation_status
        st = closed_loop_evaluation_status()
        return st.get("latest")
    except Exception:
        return None


def _compact_watchlist_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "health_score": entry.get("health_score"),
        "display_score": entry.get("display_score"),
        "lifecycle_stage": entry.get("lifecycle_stage"),
        "scope_tier": entry.get("scope_tier"),
        "health_trend": entry.get("health_trend"),
        "health_delta": entry.get("health_delta"),
        "confidence_tier": entry.get("confidence_tier"),
        "outcome_gate": entry.get("outcome_gate"),
    }


def _compact_holding_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "health_score": entry.get("health_score"),
        "lifecycle_stage": entry.get("lifecycle_stage"),
        "health_delta": entry.get("health_delta"),
        "gain_pct": entry.get("gain_pct"),
        "outcome_gate": entry.get("outcome_gate"),
        "monitoring": entry.get("monitoring"),
    }


def build_lifecycle_slice() -> dict[str, Any]:
    wl = _load_watchlist_lifecycle()
    hl = _load_holdings_lifecycle()
    wl_symbols = wl.get("symbols") or {}
    hl_holdings = hl.get("holdings") or {}

    wl_compact = {
        sym: _compact_watchlist_entry(e)
        for sym, e in wl_symbols.items()
        if isinstance(e, dict)
    }
    hl_compact = {
        sym: _compact_holding_entry(e)
        for sym, e in hl_holdings.items()
        if isinstance(e, dict) and e.get("lifecycle_stage") != "exited"
    }

    blocked = wl.get("blocked_promotions") or []
    if not blocked and wl.get("blocked_promotion_count"):
        blocked = [{"note": "count_only", "count": wl.get("blocked_promotion_count")}]

    return {
        "watchlist": {
            "enabled": wl.get("enabled", True),
            "review_mode": wl.get("review_mode", True),
            "summary": wl.get("summary") or {},
            "blocked_promotion_count": wl.get("blocked_promotion_count", len(blocked)),
            "symbol_count": len(wl_compact),
            "symbols": wl_compact,
        },
        "holdings": {
            "enabled": hl.get("enabled", True),
            "review_mode": hl.get("review_mode", True),
            "summary": hl.get("summary") or {},
            "position_count": len(hl_compact),
            "symbols": hl_compact,
        },
        "promotion_gate_evaluation": _load_closed_loop_eval(),
    }


# Research depth → priority multiplier (holdings advisory)
HOLDINGS_RESEARCH_DEPTH_MULT: dict[str, float] = {
    "none": 0.0,
    "standard": 1.0,
    "elevated": 1.25,
    "full": 1.45,
}


def holdings_research_multiplier(sym: str, lifecycle: dict[str, Any] | None = None) -> float:
    """Per-holding research priority boost from lifecycle stage (review_mode safe default 1.0)."""
    lifecycle = lifecycle or {}
    holdings = (lifecycle.get("holdings") or {})
    if holdings.get("review_mode", True):
        # Still apply mild advisory boost in review mode — no suppression below 1.0 except exited
        pass
    meta = (holdings.get("symbols") or {}).get(sym.upper()) or (holdings.get("symbols") or {}).get(sym)
    if not meta:
        return 1.0
    stage = str(meta.get("lifecycle_stage") or "healthy")
    if stage == "exited":
        return 0.0
    depth = str((meta.get("monitoring") or {}).get("research_depth") or "standard")
    mult = HOLDINGS_RESEARCH_DEPTH_MULT.get(depth, 1.0)
    if stage == "trim_candidate":
        mult = max(mult, 1.45)
    elif stage == "watch":
        mult = max(mult, 1.20)
    return mult


def enrich_bus_with_lifecycle(bus: dict[str, Any]) -> dict[str, Any]:
    """Attach lifecycle slice and per-symbol lifecycle fields on by_symbol."""
    slice_data = build_lifecycle_slice()
    bus["lifecycle"] = slice_data

    by_sym = dict(bus.get("by_symbol") or {})
    for sym, meta in (slice_data.get("watchlist") or {}).get("symbols", {}).items():
        key = str(sym).upper()
        row = dict(by_sym.get(key) or {})
        row["watchlist_lifecycle"] = meta
        by_sym[key] = row
    for sym, meta in (slice_data.get("holdings") or {}).get("symbols", {}).items():
        key = str(sym).upper()
        row = dict(by_sym.get(key) or {})
        row["holdings_lifecycle"] = meta
        by_sym[key] = row
    bus["by_symbol"] = by_sym
    return bus