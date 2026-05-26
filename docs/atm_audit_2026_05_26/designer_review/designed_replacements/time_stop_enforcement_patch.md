# Designer Replacement: time_stop_enforcement_patch

**Status:** READY TO APPLY (review-only surfacing — no auto-close)  
**Git Baseline:** `c1286d314deb377df49713e1646f139db7f43643`  
**Created:** 2026-05-26  

## Problem

Time-stop policy is defined in `scripts/strategy_trailing_policy.py` with three types:
- `intraday` — close at 15:45 ET (momentum/gap strategies)
- `calendar` — max 21 hold days (swing strategies)
- `review` — alert at N days (income/position strategies, 30-180 days)

The `unified_stop_supervisor.py` does NOT currently enforce time stops — it only handles
trailing price stops. Time stop data exists in strategy config YAMLs (`stop_policy.time_stop`)
but is not surfaced to the operator for review.

## Design Principle

This patch adds **review-only surfacing** of time stop status. It does NOT auto-close
positions. The operator needs visibility into which positions have exceeded or are
approaching their time stop thresholds.

## Changes

### 1. Add time stop status to `/api/v2/atm/status` open positions

In the ATM status endpoint, for each open position, compute time stop status:

```python
from strategy_trailing_policy import get_trailing_policy
from datetime import datetime, timezone, timedelta

def compute_time_stop_status(trade):
    """Compute time stop status for a paper trade. Returns dict for API response."""
    policy = get_trailing_policy(trade["strategy_id"])
    ts_config = policy.get("time_stop", {})
    ts_type = ts_config.get("type", "review")
    
    entry_time = trade.get("entry_time")
    if not entry_time:
        return {"type": ts_type, "status": "unknown", "reason": "no entry_time"}
    
    now = datetime.now(timezone.utc)
    hold_days = (now - entry_time).days
    
    if ts_type == "intraday":
        close_at = ts_config.get("close_at", "15:45")
        return {
            "type": "intraday",
            "close_at": close_at,
            "status": "active",
            "hold_days": hold_days,
            "overdue": hold_days > 0,
        }
    elif ts_type == "calendar":
        max_days = ts_config.get("max_hold_days", 21)
        return {
            "type": "calendar",
            "max_hold_days": max_days,
            "hold_days": hold_days,
            "days_remaining": max(0, max_days - hold_days),
            "status": "overdue" if hold_days > max_days else "approaching" if hold_days > max_days * 0.8 else "ok",
            "overdue": hold_days > max_days,
        }
    elif ts_type == "review":
        review_days = ts_config.get("review_at_days", 90)
        return {
            "type": "review",
            "review_at_days": review_days,
            "hold_days": hold_days,
            "days_to_review": max(0, review_days - hold_days),
            "status": "review_due" if hold_days >= review_days else "ok",
            "overdue": hold_days >= review_days,
        }
    return {"type": ts_type, "status": "unknown"}
```

Add `time_stop_status` to each position in the API response.

### 2. Add time stop indicators to AutomatedTradeMode.tsx

In the open positions table, add a column showing time stop status:

- Green dot + "OK" for positions within their window
- Amber dot + "Approaching (N days left)" for positions > 80% of calendar time stop
- Red dot + "Review Due" for positions past review threshold
- Red dot + "Overdue (N days)" for positions past calendar max hold

### 3. Add time stop summary to system health

In the `/api/v2/system-health` response, add a `time_stop_summary`:

```python
{
    "time_stop_summary": {
        "total_open": 20,
        "overdue_count": 2,
        "approaching_count": 1,
        "overdue_positions": [
            {"symbol": "GCTS", "strategy": "momentum_scalp", "hold_days": 13, "type": "intraday"}
        ]
    }
}
```

## What This Does NOT Do

- Does NOT auto-close any position
- Does NOT modify stop prices
- Does NOT change trailing stop behavior
- Does NOT add any new cron jobs
- Is purely additive read-only visibility

## Testing

1. Load `/api/v2/atm/status` — verify each position has `time_stop_status`
2. Check GCTS (momentum_scalp, entered 2026-05-13) shows `overdue: true` for intraday
3. Check ASPN (swing_trade, entered 2026-05-21) shows calendar status with days remaining
4. Check FLYW (dividend_growth_compounder) shows review status
5. Verify no positions were closed or modified
6. Check ATM dashboard shows time stop column
7. Check SystemHealth dashboard shows time stop summary
