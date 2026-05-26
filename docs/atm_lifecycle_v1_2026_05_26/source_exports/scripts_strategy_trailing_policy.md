# Source Export: scripts/strategy_trailing_policy.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/strategy_trailing_policy.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `08e803bf3df2dfbb32f0c45620523547ca7894937b21d9ed040ecf41864e20d3` |
| **File Size** | 7450 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""STOP-V2.3 — Strategy-aware trailing stop policy.

Maps strategy families to trailing tier configurations.
Used by unified_stop_supervisor to determine when/how to trail stops.

Does NOT move stops directly — returns recommendations only.
"""

# Strategy family classification
STRATEGY_FAMILIES = {
    # Momentum / Scalp — tight trailing, same-day exit
    "momentum_scalp": "momentum",
    "gap_and_go": "momentum",
    "earnings_catalyst": "momentum",
    "screener": "momentum",

    # Swing / Breakout — medium trailing, multi-day hold
    "swing_trade": "swing",
    "swing_breakout": "swing",
    "fib_retracement_bounce": "swing",
    "speculative_growth": "swing",
    "earnings_post_momentum": "swing",
    "earnings_pre_buildup": "swing",

    # Income / Dividend — wide trailing, long hold
    "dividend_growth_compounder": "income",
    "reit_income": "income",
    "bond_income": "income",
    "high_yield_income_bdc": "income",
    "income_add": "income",
    "international_dividend": "income",
    "covered_call_income": "income",
    "tax_loss_harvest": "income",

    # Position / Compounder — widest trailing, very long hold
    "core_growth_compounder": "position",
    "core_index": "position",
    "defense_thesis": "position",
    "sector_rotation": "position",

    # Recovery — patient trailing
    "recovery_watch": "income",  # treat like income for trailing
}

# Trailing tier definitions per family
# Each tier: (r_threshold, lock_r, description)
# lock_r=0.0 means breakeven
TRAILING_TIERS = {
    "momentum": {
        "tiers": [
            (1.0, 0.0, "breakeven"),
            (1.5, 0.5, "lock 0.5R"),
            (2.0, 1.0, "lock 1.0R"),
            (3.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "intraday", "close_at": "15:45"},
        "max_hold_days": None,  # intraday only
        "after_hours_trail": False,
    },
    "swing": {
        "tiers": [
            (1.0, 0.0, "breakeven"),
            (1.5, 0.5, "lock 0.5R"),
            (2.0, 1.0, "lock 1.0R"),
            (3.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "calendar", "max_hold_days": 21},
        "after_hours_trail": False,
    },
    "income": {
        "tiers": [
            (1.5, 0.0, "breakeven"),
            (2.5, 0.5, "lock 0.5R"),
            (3.5, 1.0, "lock 1.0R"),
            (5.0, 2.0, "lock 2.0R"),
        ],
        "time_stop": {"type": "review", "review_at_days": 90},
        "after_hours_trail": False,
    },
    "position": {
        "tiers": [
            (2.0, 0.0, "breakeven"),
            (3.0, 0.5, "lock 0.5R"),
            (4.0, 1.5, "lock 1.5R"),
            (6.0, 3.0, "lock 3.0R"),
        ],
        "time_stop": {"type": "review", "review_at_days": 180},
        "after_hours_trail": False,
    },
}

# Default for unknown strategies — conservative, requires review
DEFAULT_POLICY = {
    "tiers": [],  # no auto-trailing for unknown strategies
    "time_stop": {"type": "review", "review_at_days": 30},
    "after_hours_trail": False,
    "requires_review": True,
}


def get_strategy_family(strategy_id: str) -> str:
    """Return the family name for a strategy_id."""
    return STRATEGY_FAMILIES.get(strategy_id, "unknown")


def get_trailing_policy(strategy_id: str) -> dict:
    """Return the trailing policy for a strategy."""
    family = get_strategy_family(strategy_id)
    policy = TRAILING_TIERS.get(family, DEFAULT_POLICY).copy()
    policy["family"] = family
    policy["strategy_id"] = strategy_id
    policy["requires_review"] = family == "unknown"
    return policy


def recommend_stop(strategy_id: str, entry_price: float, planned_stop: float,
                   current_stop: float, current_price: float,
                   market_hours: bool = True) -> dict:
    """Compute trailing stop recommendation for a position.

    Returns recommendation dict — does NOT execute any stop movement.
    """
    policy = get_trailing_policy(strategy_id)
    family = policy["family"]

    if not entry_price or not planned_stop or entry_price <= planned_stop:
        return {
            "action": "hold",
            "reason": "invalid entry/stop data",
            "family": family,
            "current_stop": current_stop,
            "recommended_stop": current_stop,
        }

    initial_risk = entry_price - planned_stop
    if initial_risk <= 0:
        return {
            "action": "hold",
            "reason": "zero or negative initial risk",
            "family": family,
            "current_stop": current_stop,
            "recommended_stop": current_stop,
        }

    r_multiple = (current_price - entry_price) / initial_risk
    tiers = policy.get("tiers", [])

    # Find highest qualifying tier
    best_tier = None
    for r_threshold, lock_r, desc in reversed(tiers):
        if r_multiple >= r_threshold:
            best_tier = (r_threshold, lock_r, desc)
            break

    if not best_tier:
        return {
            "action": "hold",
            "reason": f"R={r_multiple:.2f} below first tier threshold",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": current_stop,
            "policy_version": "v2.3",
        }

    r_threshold, lock_r, desc = best_tier
    new_stop = round(entry_price + lock_r * initial_risk, 2)

    # Stop can only move UP (tighten), never down
    effective_stop = max(new_stop, current_stop) if current_stop else new_stop

    if effective_stop <= current_stop:
        return {
            "action": "hold",
            "reason": f"R={r_multiple:.2f} tier={desc} but stop already at/above ${current_stop}",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": current_stop,
            "tier": desc,
            "policy_version": "v2.3",
        }

    # Check after-hours block
    if not market_hours and not policy.get("after_hours_trail", False):
        return {
            "action": "recommend_deferred",
            "reason": f"After hours — would trail to ${effective_stop} ({desc}) but blocked until market open",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": effective_stop,
            "tier": desc,
            "blocked_by": "after_hours",
            "policy_version": "v2.3",
        }

    # Check unknown strategy
    if policy.get("requires_review"):
        return {
            "action": "recommend_review",
            "reason": f"Unknown strategy '{strategy_id}' — trailing requires operator review",
            "family": family,
            "r_multiple": round(r_multiple, 2),
            "current_stop": current_stop,
            "recommended_stop": effective_stop,
            "blocked_by": "unknown_strategy",
            "policy_version": "v2.3",
        }

    return {
        "action": "recommend_trail",
        "reason": f"R={r_multiple:.2f} >= {r_threshold}R — {desc} (${current_stop} → ${effective_stop})",
        "family": family,
        "r_multiple": round(r_multiple, 2),
        "current_stop": current_stop,
        "recommended_stop": effective_stop,
        "tier": desc,
        "tier_r_threshold": r_threshold,
        "tier_lock_r": lock_r,
        "policy_version": "v2.3",
    }
```
