# Phase 6A Dashboard/API Response Audit

**Date:** 2026-05-15

## API Response Fields Returned

The `/api/v2/paper-proposals/approve` endpoint returns:

| Field | Type | Included |
|-------|------|----------|
| ok | bool | YES |
| message | string | YES — includes revalidation summary |
| blockers | array | YES — list of block reasons |
| market_revalidation.passed | bool | YES |
| market_revalidation.live_price | number | YES |
| market_revalidation.provider | string | YES |
| market_revalidation.quote_age_seconds | number | YES |
| market_revalidation.price_drift_pct | number | YES |
| market_revalidation.live_rr | number | YES |
| market_revalidation.live_spread_pct | number | YES |
| market_revalidation.adjusted_entry | number | YES (null if no adjustment) |
| market_revalidation.warnings | array | YES |
| market_revalidation.blockers | array | YES |
| market_revalidation.message | string | YES |

## Dashboard Display

**File:** `apps/command-center-v2/src/pages/PaperProposals.tsx`

### Before Phase 6A

- **Error case:** Browser `alert()` with `d.message` or `d.error`
- **Success case:** `console.log()` only — operator never saw confirmation
- **No market revalidation details displayed**

### After Phase 6A Patch

- **Error case (blocked):** Browser `alert()` with:
  - Block reason message
  - Live price, drift %, R:R, spread % on second line
- **Success case (approved):** Browser `alert()` with:
  - Approval confirmation message (includes market conditions)
  - Live price, drift %, R:R
  - Warnings (e.g., price adjusted) if any
- **Page auto-refreshes** after action to update proposal list

### What the Operator Sees

**When blocked:**
```
Not a good trade under current conditions: AAPL is now $294.22,
50.9% above proposed entry $195.00. Trade parameters are stale.

Live: $294.22 | Drift: 50.9% | R:R: ? | Spread: 10.57%
```

**When approved:**
```
PAPER TRADE #123 opened from proposal #45. Market conditions confirmed:
AAPL at $150.50 (drift 0.3%), R:R=2.1:1. Approved.

Live: $150.50 | Drift: 0.3% | R:R: 2.1
```

**When approved with adjustment:**
```
PAPER TRADE #123 opened from proposal #45. Approved with adjustment:
AAPL moved 2.1% above proposed entry. Entry recalibrated from
$147.00 to $150.08. R:R=1.9:1.

Live: $150.08 | Drift: 2.1% | R:R: 1.9
Warnings: price_adjusted: 2.1% above, entry recalibrated to $150.08
```

## UI Patch Safety

| Concern | Status |
|---------|--------|
| No execution controls added | CONFIRMED |
| No live trading controls added | CONFIRMED |
| Change is display-only (alert) | CONFIRMED |
| Existing approval flow unchanged | CONFIRMED |
| Frontend build not required for patch | N/A — TSX files served by dev/build |

## Frontend Build Status

The frontend has pre-existing dirty files from prior sessions:
- `apps/command-center-v2/src/pages/Overview.tsx`
- `apps/command-center-v2/src/pages/PaperJournal.tsx`
- `apps/command-center-v2/src/pages/PaperOutcomes.tsx`
- `apps/command-center-v2/tsconfig.app.tsbuildinfo`

Phase 6A patch to `PaperProposals.tsx` is isolated and safe to stage separately.
