#!/usr/bin/env python3
"""phase6_proposal_staleness_policy.py — Classify proposal freshness.

Pure function, no side effects. Used by sweeper and approval endpoint.

Usage:
    .venv/bin/python scripts/phase6_proposal_staleness_policy.py --test
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Default stale thresholds in minutes
STALE_THRESHOLDS = {
    "momentum_scalp": 60, "gap_and_go": 60, "scalp": 60,
    "screener": 240,  # 4 hours
    "day_trade": 240, "intraday": 240,
    "momentum": 240, "momentum_breakout": 240,
    "swing": 4320, "swing_trade": 4320, "swing_breakout": 4320,  # 3 trading days
    "mean_reversion": 4320, "sector_rotation": 4320,
    "earnings_catalyst": 4320,
    "recovery_watch": 7200, "defense_thesis": 7200,  # 5 trading days
    "speculative_growth": 7200,
    "income": 14400, "income_add": 14400, "covered_call_income": 14400,  # 10 trading days
    "dividend_growth_compounder": 14400, "high_yield_income_bdc": 14400,
    "core_growth_compounder": 14400, "reit_income": 14400, "bond_income": 14400,
    "position": 14400, "dividend": 14400,
    "fib_retracement_bounce": 4320,
    "default": 1440,  # 24 hours
}

# Statuses that are terminal — sweeper and freshness gate should ignore
TERMINAL_STATUSES = {
    "APPROVED", "APPROVED_FOR_PAPER_TEST", "REJECTED", "EXPIRED",
    "RISK_BLOCKED", "CANCELLED", "CONVERTED", "expired",
}


def classify_proposal_staleness(proposal: dict, now=None) -> dict:
    """Classify whether a proposal is fresh, stale, or expired.

    Args:
        proposal: dict with at least id, status, strategy_id, created_at, expires_at
        now: UTC datetime for testing. Defaults to utcnow.

    Returns:
        dict with fresh, stale, expired, requires_refresh, status, reason, age_minutes, etc.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = {
        "fresh": False,
        "stale": False,
        "expired": False,
        "requires_refresh": False,
        "status": "unknown",
        "reason": "",
        "age_minutes": None,
        "threshold_minutes": None,
        "strategy_type": None,
        "created_at": None,
        "expires_at": None,
        "policy_source": "default",
    }

    status = proposal.get("status", "")
    if status in TERMINAL_STATUSES:
        result["status"] = "terminal"
        result["reason"] = f"Proposal is {status} — not subject to freshness check."
        return result

    # Get created_at
    created_at = proposal.get("created_at")
    if not created_at:
        result["status"] = "requires_review"
        result["requires_refresh"] = True
        result["reason"] = "Missing created_at — cannot determine age."
        return result

    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            result["status"] = "requires_review"
            result["requires_refresh"] = True
            result["reason"] = "Invalid created_at timestamp."
            return result

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    result["created_at"] = created_at.isoformat()

    # Check expires_at first (strategy-aware, already computed at proposal time)
    expires_at = proposal.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                expires_at = None
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            result["expires_at"] = expires_at.isoformat()
            if now > expires_at:
                age_min = int((now - created_at).total_seconds() / 60)
                result["expired"] = True
                result["stale"] = True
                result["status"] = "expired"
                result["age_minutes"] = age_min
                result["reason"] = f"Past expires_at ({expires_at.strftime('%Y-%m-%d %H:%M')} UTC)."
                return result

    # Strategy-based threshold
    strategy = proposal.get("strategy_id") or proposal.get("strategy_type") or "default"
    result["strategy_type"] = strategy
    threshold = STALE_THRESHOLDS.get(strategy, STALE_THRESHOLDS["default"])
    result["threshold_minutes"] = threshold

    age_sec = (now - created_at).total_seconds()
    age_min = int(age_sec / 60)
    result["age_minutes"] = age_min

    if age_min > threshold:
        result["stale"] = True
        result["status"] = "stale"
        result["reason"] = f"Age {age_min}min exceeds {strategy} threshold {threshold}min."
    else:
        result["fresh"] = True
        result["status"] = "fresh"
        remaining = threshold - age_min
        result["reason"] = f"Fresh ({age_min}min old, {remaining}min until stale)."

    return result


if __name__ == "__main__":
    # Quick self-test
    now = datetime.now(timezone.utc)
    # Fresh proposal
    r = classify_proposal_staleness({"status": "PENDING", "strategy_id": "swing_trade",
        "created_at": now - timedelta(minutes=30)}, now)
    print(f"Fresh swing: {r['status']} — {r['reason']}")
    # Stale momentum
    r2 = classify_proposal_staleness({"status": "PENDING", "strategy_id": "gap_and_go",
        "created_at": now - timedelta(minutes=90)}, now)
    print(f"Stale gap_and_go: {r2['status']} — {r2['reason']}")
    # Terminal
    r3 = classify_proposal_staleness({"status": "REJECTED"}, now)
    print(f"Terminal: {r3['status']} — {r3['reason']}")
