# ATM Lifecycle v1.2 Queue UX Fix Report

**Date:** 2026-05-26  

## Root Cause

The original overdue decision queue showed all 10 positions in a single flat list regardless
of decision status. After decisions were recorded, the row stayed in the same position with
a decision badge, but the header still counted it as part of the active queue. Combined with
browser caching of the pre-decision API response, this created confusion about whether
decisions were actually recorded.

## Fix Applied

### API: Split response into `needs_decision` / `reviewed` arrays

`GET /api/v2/atm/overdue-decisions` now returns:

```json
{
  "summary": {
    "total_overdue": 10,
    "needs_decision_count": 0,
    "reviewed_count": 10,
    "high_risk_count": 10,
    "stop_missing_count": 2
  },
  "needs_decision": [],
  "reviewed": [/* 10 items */],
  "all_overdue": [/* 10 items */]
}
```

Each position includes `decision_status: "needs_decision" | "reviewed"`.

### UI: Three tabs replacing flat list

| Tab | Content |
|-----|---------|
| **Needs Decision (0)** | Empty — shows "All overdue positions have been reviewed." |
| **Reviewed (10)** | All 10 positions with their recorded decisions |
| **All (10)** | Complete list |

Default tab is **Needs Decision** so the operator sees the action queue first.

### Header adapts to state

- When needs_decision > 0: Red border, "(N need decisions)"
- When all reviewed: Green border, "(all N reviewed)"

## GCTS Duplicate Explanation

GCTS has 3 paper trades (#20, #22, #23) all momentum_scalp, all overdue. Each has its own
decision record. FLYW #19 has 3 duplicate decision records (operator submitted form 3 times)
but the API correctly joins by `paper_trade_id` and shows the latest.

## Before/After

| Metric | Before | After |
|--------|--------|-------|
| Needs Decision tab | N/A (no tabs) | 0 |
| Reviewed tab | N/A | 10 |
| "none" decisions visible in active queue | possible | impossible |

## Safety

- No orders placed
- No positions modified
- No stops changed
- ALPACA_MODE=paper, LLM_DISABLE=true

## Screenshots

- `atm_overdue_needs_decision_empty_v1_2_fix.png` — shows empty needs-decision tab with green message
