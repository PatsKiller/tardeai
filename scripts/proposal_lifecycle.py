#!/usr/bin/env python3
"""proposal_lifecycle.py — Central source of truth for proposal lifecycle rules.

Strategy-aware expiry windows, monitoring intervals, intraday vs overnight
classification, price drift thresholds, entry-zone validity, and status transitions.

Usage:
    from scripts.proposal_lifecycle import get_expiry_hours, is_overnight, evaluate_lifecycle_status
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

# ── Strategy Expiry Map ────────────────────────────────────────────────────

STRATEGY_EXPIRY_HOURS = {
    # INTRADAY — same-day only
    "momentum_scalp": 8,
    "gap_and_go": 10,
    # SHORT SWING
    "earnings_catalyst": 72,
    "swing_breakout": 120,
    "swing_trade": 168,
    "speculative_growth": 168,
    # MEDIUM SWING
    "sector_rotation": 336,
    # POSITION / LONGER TERM
    "income_add": 240,
    "core_growth_compounder": 720,
    "core_index": 720,
    "covered_call_income": 720,
    "defense_thesis": 720,
    "dividend_growth_compounder": 720,
    "high_yield_income_bdc": 720,
    "international_dividend": 720,
    "recovery_watch": 336,
    "reit_income": 720,
    "bond_income": 720,
    "tax_loss_harvest": 168,
    "cash_or_stable": 720,
}
DEFAULT_EXPIRY_HOURS = 48

# Derive timeframe class map and intraday set from strategy YAML configs
# No hardcoded strategy lists — scales automatically to 40+ strategies
def _load_timeframe_class_map():
    """Load timeframe_class from all config/strategies/*.yaml files."""
    import yaml as _yaml
    _skip = {'strategy_schema', 'recommendation_schema', 'shared_risk_rules'}
    _dir = Path(__file__).resolve().parent.parent / "config" / "strategies"
    _map = {}
    for p in _dir.glob("*.yaml"):
        if p.stem in _skip:
            continue
        try:
            with open(p) as f:
                cfg = _yaml.safe_load(f) or {}
            tc = cfg.get("timeframe_class", "").upper()
            if tc:
                _map[p.stem] = tc.lower()
        except Exception:
            pass
    return _map

TIMEFRAME_CLASS_MAP = _load_timeframe_class_map()
INTRADAY_STRATEGIES = {sid for sid, tc in TIMEFRAME_CLASS_MAP.items() if tc == "intraday"}

STRATEGY_TYPE_LABELS = {
    "INTRADAY": "Intraday",
    "SHORT_SWING": "Short Swing",
    "MEDIUM_SWING": "Medium Swing",
    "POSITION": "Position",
    "CASH": "Cash",
}


def get_strategy_metadata(strategy_id: str) -> dict:
    """Resolve display name, timeframe, and strategy type for a proposal."""
    sid = (strategy_id or "").strip()
    cfg = {}
    try:
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config(sid) or {}
    except Exception:
        pass
    tc_raw = cfg.get("timeframe_class") or ""
    if tc_raw:
        strategy_type = str(tc_raw).upper()
    else:
        strategy_type = get_timeframe_class(sid).upper()
    return {
        "strategy_id": sid,
        "display_name": cfg.get("display_name") or sid.replace("_", " ").title(),
        "timeframe": cfg.get("timeframe"),
        "timeframe_class": strategy_type.lower(),
        "strategy_type": strategy_type,
        "strategy_type_label": STRATEGY_TYPE_LABELS.get(
            strategy_type, strategy_type.replace("_", " ").title()
        ),
        "status": cfg.get("status"),
    }

# Drift thresholds by timeframe class
PRICE_DRIFT_THRESHOLDS = {
    "intraday": 2.0,
    "short_swing": 5.0,
    "medium_swing": 8.0,
    "position": 12.0,
}

# Monitor intervals in minutes
MONITOR_INTERVALS = {
    "intraday": 15,
    "short_swing": 60,
    "medium_swing": 240,
    "position": 480,
}


def get_expiry_hours(strategy_id: str) -> int:
    return STRATEGY_EXPIRY_HOURS.get(strategy_id, DEFAULT_EXPIRY_HOURS)


def get_max_expiry_hours(strategy_id: str) -> int:
    base = get_expiry_hours(strategy_id)
    if strategy_id in INTRADAY_STRATEGIES:
        return base  # no extension for intraday
    if base >= 720:
        return 720  # long-term strategies cap at 720
    return base * 2


_INTRADAY_TTL_CACHE: dict = {}


def _intraday_ttl_minutes(strategy_id: str, default: int = 30) -> int:
    """Minutes-based TTL for intraday scalps, from the strategy's intraday_execution.proposal_ttl_minutes.
    A scalp setup is valid for minutes, not hours — the old hours TTL (+ market-close extension) let
    proposals sit ~9h and expire un-actioned. Cached per process."""
    if strategy_id in _INTRADAY_TTL_CACHE:
        return _INTRADAY_TTL_CACHE[strategy_id]
    ttl = default
    try:
        import os, yaml
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "config", "strategies", f"{strategy_id}.yaml")
        if os.path.exists(p):
            cfg = yaml.safe_load(open(p)) or {}
            ttl = int((cfg.get("intraday_execution") or {}).get("proposal_ttl_minutes") or default)
    except Exception:
        ttl = default
    _INTRADAY_TTL_CACHE[strategy_id] = ttl
    return ttl


def get_expiry_datetime(strategy_id: str, created_at: datetime = None) -> datetime:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    # INTRADAY scalp/momentum: short minutes-based TTL and NO market-close extension — a stale scalp
    # proposal must die in minutes, not get pushed out to 16:00 ET.
    if strategy_id in INTRADAY_STRATEGIES:
        return created_at + timedelta(minutes=_intraday_ttl_minutes(strategy_id))
    hours = get_expiry_hours(strategy_id)
    raw_expiry = created_at + timedelta(hours=hours)

    # Ensure proposals don't expire before the next Alpaca trading window.
    # If raw expiry falls before next market open, extend to next day's market close.
    try:
        import zoneinfo
        et = zoneinfo.ZoneInfo("America/New_York")
        expiry_et = raw_expiry.astimezone(et)
        # Alpaca extended-hours start at 4:00 AM ET, market closes at 4:00 PM ET
        # If expiry lands before 5:00 AM on a weekday, push to same-day 16:00 ET
        # (5 AM gives the 4 AM auto-approver at least 1 hour margin)
        if expiry_et.weekday() < 5 and expiry_et.hour < 5:
            expiry_et = expiry_et.replace(hour=16, minute=0, second=0, microsecond=0)
            return expiry_et.astimezone(timezone.utc)
        # If expiry lands on weekend, push to Monday 16:00 ET
        if expiry_et.weekday() >= 5:
            days_to_mon = 7 - expiry_et.weekday()
            expiry_et = (expiry_et + timedelta(days=days_to_mon)).replace(
                hour=16, minute=0, second=0, microsecond=0)
            return expiry_et.astimezone(timezone.utc)
    except Exception:
        pass
    return raw_expiry


def get_max_expiry_datetime(strategy_id: str, created_at: datetime = None) -> datetime:
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    # Intraday scalps must not be re-extended past their minutes TTL by the staleness policy.
    if strategy_id in INTRADAY_STRATEGIES:
        return created_at + timedelta(minutes=_intraday_ttl_minutes(strategy_id))
    hours = get_max_expiry_hours(strategy_id)
    return created_at + timedelta(hours=hours)


def is_intraday(strategy_id: str) -> bool:
    return strategy_id in INTRADAY_STRATEGIES


def is_overnight(strategy_id: str) -> bool:
    return strategy_id not in INTRADAY_STRATEGIES


def get_monitor_interval(strategy_id: str) -> int:
    tc = get_timeframe_class(strategy_id)
    return MONITOR_INTERVALS.get(tc, 60)


def get_price_drift_threshold(strategy_id: str) -> float:
    tc = get_timeframe_class(strategy_id)
    return PRICE_DRIFT_THRESHOLDS.get(tc, 5.0)


def get_timeframe_class(strategy_id: str) -> str:
    if strategy_id in TIMEFRAME_CLASS_MAP:
        return TIMEFRAME_CLASS_MAP[strategy_id]
    hours = get_expiry_hours(strategy_id)
    if hours <= 10:
        return "intraday"
    if hours <= 168:
        return "short_swing"
    if hours <= 336:
        return "medium_swing"
    return "position"


def _is_market_hours() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    hour_utc = now.hour + now.minute / 60.0
    return 13.5 <= hour_utc <= 20.0


def evaluate_lifecycle_status(strategy_id, current_price, entry_price,
                               created_at, expires_at, max_expires_at=None,
                               quote_context=None):
    """Evaluate lifecycle status for a proposal.

    Returns dict with:
        lifecycle_status, entry_zone_status, entry_zone_valid,
        price_drift_pct, message, can_extend, extension_reason
    """
    now = datetime.now(timezone.utc)
    result = {
        "lifecycle_status": "ACTIVE",
        "entry_zone_status": None,
        "entry_zone_valid": None,
        "price_drift_pct": None,
        "message": "",
        "can_extend": False,
        "extension_reason": None,
        "expiry_basis": "calendar_hours",
    }

    if current_price is None or entry_price is None or entry_price <= 0:
        result["lifecycle_status"] = "BLOCKED_NO_PRICE"
        result["message"] = "No current price available for lifecycle evaluation"
        return result

    # Price drift
    drift_pct = (current_price - entry_price) / entry_price * 100
    result["price_drift_pct"] = round(drift_pct, 2)

    drift_threshold = get_price_drift_threshold(strategy_id)
    abs_drift = abs(drift_pct)

    # Entry zone check
    if abs_drift <= drift_threshold:
        result["entry_zone_status"] = "ENTRY_ZONE_VALID"
        result["entry_zone_valid"] = True
    elif abs_drift <= drift_threshold * 1.5:
        result["entry_zone_status"] = "ENTRY_ZONE_MARGINAL"
        result["entry_zone_valid"] = True
    else:
        result["entry_zone_status"] = "ENTRY_MISSED"
        result["entry_zone_valid"] = False
        result["lifecycle_status"] = "ENTRY_MISSED"
        result["message"] = f"Price drifted {drift_pct:+.1f}% beyond {drift_threshold}% threshold"

    # Expiry check
    if expires_at and now > expires_at:
        if is_intraday(strategy_id):
            result["lifecycle_status"] = "EXPIRED_INTRADAY"
            result["message"] = "Intraday strategy expired at EOD"
            result["can_extend"] = False
            return result

        # Check max expiry
        if max_expires_at and now > max_expires_at:
            result["lifecycle_status"] = "EXPIRED_MAX_WINDOW"
            result["message"] = "Maximum strategy window expired"
            result["can_extend"] = False
            return result

        # Can extend if entry zone still valid
        if result["entry_zone_valid"]:
            result["lifecycle_status"] = "ACTIVE"
            result["can_extend"] = True
            result["extension_reason"] = "ENTRY_ZONE_STILL_VALID"
            result["message"] = f"Entry zone valid ({drift_pct:+.1f}%), eligible for extension"
        else:
            result["lifecycle_status"] = "NEEDS_REVIEW"
            result["message"] = f"Expired with entry missed ({drift_pct:+.1f}%)"
            result["can_extend"] = False

    elif result["entry_zone_valid"] and result["lifecycle_status"] == "ACTIVE":
        result["lifecycle_status"] = "ENTRY_ZONE_VALID" if abs_drift <= drift_threshold else "ACTIVE"
        result["message"] = f"Active, price {drift_pct:+.1f}% from entry"

    # Stale check
    if created_at:
        age_hours = (now - created_at).total_seconds() / 3600
        max_h = get_max_expiry_hours(strategy_id)
        if age_hours > max_h * 0.8 and result["lifecycle_status"] == "ACTIVE":
            result["lifecycle_status"] = "STALE"
            result["message"] = f"Proposal age {age_hours:.0f}h approaching max {max_h}h"

    # Quote context warnings
    if quote_context:
        if quote_context.get("is_delayed") and result.get("can_extend"):
            result["extension_reason"] = "ENTRY_ZONE_VALID_DELAYED_QUOTE"

    return result


if __name__ == "__main__":
    with PipelineRun("proposal_lifecycle") as _run:
        strategies = sorted(STRATEGY_EXPIRY_HOURS.keys())
        print(f"{'Strategy':32} {'Hours':>5} {'Max':>5} {'Class':15} {'Overnight':>9} {'Intraday':>8}")
        print("-" * 90)
        for s in strategies:
            print(f"{s:32} {get_expiry_hours(s):5} {get_max_expiry_hours(s):5} "
                  f"{get_timeframe_class(s):15} {str(is_overnight(s)):>9} {str(is_intraday(s)):>8}")

