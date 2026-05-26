# ATM Lifecycle v1.4 — Manual Close UX Clarity Report

**Date:** 2026-05-26  

## Root Issue

The Manual Close Review section was unclear:
- No explanation of what it represents or why positions are there
- No workflow description
- Columns too thin — no "why here" or "risk issue"
- Action button just said "Review" — unclear if it places orders
- No tabs to separate pending from reviewed
- 6 rows unexplained (was expected 5)

## Why 6 Rows

6 distinct `paper_trade_id` values have `review_for_manual_close` decisions:
- SMX #1, MNKD #2, EVC #4, INFU #9 (4 unique symbols)
- GCTS #20 and GCTS #23 (same symbol, separate paper trades — #23 also has missing stop)

This is correct. GCTS has two separate paper trade entries.

## UX Changes

| Change | Before | After |
|--------|--------|-------|
| Title | "Manual Close Review" | "Manual Close Review Queue — No Orders Placed" |
| Subtitle | None | Full explanation paragraph |
| Workflow | None | Collapsible 6-step explanation |
| Tabs | None | Pending Review / Reviewed / All |
| Columns | Symbol, Strategy, Days, Entry, Stop, Shares, Account | Symbol, #, Why Here, Days, Stop, Risk Issue, Recommended, Status |
| Button | "Review" | "Review Position" |
| Submit | "Record Review Decision" | "Record Decision — No Order" |
| Safety text | None | "Recording this review does not close, sell, cancel, replace, or submit any order." |

## API Fields Added

- `why_here` — e.g. "Intraday held 19d" or "Intraday held 13d + missing stop"
- `risk_issue` — e.g. "Time-stop overdue +19d" or "Missing DB stop"
- `recommended_review_action` — e.g. "Review for manual close" or "Verify stop before action"
- `pending` and `reviewed` arrays for tab filtering

## Safety

No orders placed. No positions modified. ALPACA_MODE=paper.

## Screenshot

`screenshots/manual_close_review_pending_clarity_v1_4.png`
