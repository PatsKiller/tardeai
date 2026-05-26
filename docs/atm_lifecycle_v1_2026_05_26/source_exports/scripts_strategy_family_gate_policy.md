# Source Export: scripts/strategy_family_gate_policy.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/strategy_family_gate_policy.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `194ca12444940a519367d57c6fe85ccc1a79787301b9045f25d4cf2d974b6fcb` |
| **File Size** | 5504 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""strategy_family_gate_policy.py — Strategy family classification and gating.

Pure functions. No DB writes. No broker calls.
"""

# Strategy → family mapping from YAML timeframe_class + bucket
STRATEGY_FAMILY_MAP = {
    "momentum_scalp": "INTRADAY_MOMENTUM",
    "gap_and_go": "GAP_EVENT",
    "earnings_catalyst": "EARNINGS_CATALYST",
    "earnings_post_momentum": "EARNINGS_CATALYST",
    "earnings_pre_buildup": "EARNINGS_CATALYST",
    "swing_breakout": "SHORT_SWING",
    "swing_trade": "SHORT_SWING",
    "fib_retracement_bounce": "SHORT_SWING",
    "speculative_growth": "SPECULATIVE_GROWTH",
    "recovery_watch": "RECOVERY_WATCH",
    "sector_rotation": "SECTOR_ROTATION",
    "dividend_growth_compounder": "DIVIDEND_CORE_COMPOUNDER",
    "core_growth_compounder": "DIVIDEND_CORE_COMPOUNDER",
    "income_add": "DIVIDEND_CORE_COMPOUNDER",
    "covered_call_income": "DIVIDEND_CORE_COMPOUNDER",
    "bond_income": "DIVIDEND_CORE_COMPOUNDER",
    "reit_income": "DIVIDEND_CORE_COMPOUNDER",
    "high_yield_income_bdc": "DIVIDEND_CORE_COMPOUNDER",
    "international_dividend": "DIVIDEND_CORE_COMPOUNDER",
    "defense_thesis": "DIVIDEND_CORE_COMPOUNDER",
    "cash_or_stable": "DIVIDEND_CORE_COMPOUNDER",
    "core_index": "DIVIDEND_CORE_COMPOUNDER",
    "tax_loss_harvest": "SHORT_SWING",
}

# Which candidate families are compatible with which strategy families
FAMILY_COMPATIBILITY = {
    "INTRADAY_MOMENTUM": {"INTRADAY_MOMENTUM", "GAP_EVENT"},
    "GAP_EVENT": {"INTRADAY_MOMENTUM", "GAP_EVENT", "SHORT_SWING", "EARNINGS_CATALYST"},
    "SHORT_SWING": {"SHORT_SWING", "SPECULATIVE_GROWTH", "RECOVERY_WATCH", "SECTOR_ROTATION"},
    "EARNINGS_CATALYST": {"EARNINGS_CATALYST", "SHORT_SWING", "SPECULATIVE_GROWTH"},
    "SPECULATIVE_GROWTH": {"SHORT_SWING", "SPECULATIVE_GROWTH", "RECOVERY_WATCH"},
    "RECOVERY_WATCH": {"SHORT_SWING", "RECOVERY_WATCH", "SPECULATIVE_GROWTH"},
    "SECTOR_ROTATION": {"SHORT_SWING", "SECTOR_ROTATION", "RECOVERY_WATCH"},
    "DIVIDEND_CORE_COMPOUNDER": {"DIVIDEND_CORE_COMPOUNDER", "SECTOR_ROTATION"},
    "UNKNOWN": None,  # None = allow all (conservative)
}


def classify_candidate_family(candidate: dict) -> dict:
    """Classify a candidate into a strategy family based on characteristics."""
    rvol = float(candidate.get("rvol") or 0)
    gap = abs(float(candidate.get("gap_pct") or 0))
    price = float(candidate.get("price") or candidate.get("proposed_entry") or 0)
    catalyst = candidate.get("catalyst_verified")
    earnings = candidate.get("earnings_proximity") or candidate.get("has_earnings")
    float_m = float(candidate.get("float_m") or 0)

    # Classification heuristic
    if rvol >= 3.0 and price < 25 and gap >= 3.0:
        family = "GAP_EVENT"
    elif rvol >= 2.0 and price < 25:
        family = "INTRADAY_MOMENTUM"
    elif earnings:
        family = "EARNINGS_CATALYST"
    elif price > 30 and float_m > 100:
        family = "DIVIDEND_CORE_COMPOUNDER"
    elif catalyst and rvol >= 1.5:
        family = "SHORT_SWING"
    elif rvol >= 1.0 or gap >= 2.0:
        family = "SHORT_SWING"
    else:
        family = "UNKNOWN"

    return {
        "candidate_family": family,
        "classification_inputs": {"rvol": rvol, "gap_pct": gap, "price": price,
                                   "catalyst_verified": catalyst, "float_m": float_m},
    }


def strategy_family_for_config(strategy_config: dict) -> str:
    """Get the strategy family from a YAML config."""
    sid = strategy_config.get("strategy_id", "")
    return STRATEGY_FAMILY_MAP.get(sid, "UNKNOWN")


def family_gate_allows_strategy(candidate: dict, strategy_config: dict) -> dict:
    """Check whether a candidate's family is compatible with a strategy's family."""
    cf = classify_candidate_family(candidate)
    candidate_family = cf["candidate_family"]
    strategy_family = strategy_family_for_config(strategy_config)
    sid = strategy_config.get("strategy_id", "?")

    # Get compatible families for this candidate
    compatible = FAMILY_COMPATIBILITY.get(candidate_family)

    if compatible is None:
        # UNKNOWN candidate — allow all strategies (conservative)
        return {
            "allowed": True, "candidate_family": candidate_family,
            "strategy_family": strategy_family, "strategy_id": sid,
            "status": "PASS", "reason": "unknown_candidate_allows_all",
            "family_gate_version": "family_gate_v1",
        }

    allowed = strategy_family in compatible
    return {
        "allowed": allowed,
        "candidate_family": candidate_family,
        "strategy_family": strategy_family,
        "strategy_id": sid,
        "status": "PASS" if allowed else "BLOCK",
        "reason": f"{candidate_family} compatible with {strategy_family}" if allowed else f"{candidate_family} incompatible with {strategy_family}",
        "family_gate_version": "family_gate_v1",
    }


def allowed_strategy_families(candidate: dict) -> dict:
    """Return which strategy families a candidate is compatible with."""
    cf = classify_candidate_family(candidate)
    candidate_family = cf["candidate_family"]
    compatible = FAMILY_COMPATIBILITY.get(candidate_family)

    return {
        "candidate_family": candidate_family,
        "allowed_families": sorted(compatible) if compatible else sorted(FAMILY_COMPATIBILITY.keys()),
        "blocked_families": sorted(set(FAMILY_COMPATIBILITY.keys()) - compatible) if compatible else [],
        "family_gate_version": "family_gate_v1",
    }
```
