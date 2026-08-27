# Time-Stop Review Workflow Design

## Current State
- Time-stop defined per strategy family in strategy_trailing_policy.py
- P0.5B surfaces time-stop status in API/dashboard
- Overdue decision workflow exists (from v1.2)
- No auto-close — review-only

## v3.5 Enhancement
- Include time-stop status in StopTrailingControlPanel
- Link to existing overdue decision workflow
- Show days_held, max_hold_days, overdue_by, strategy time-stop type
- No new auto-close or order placement
