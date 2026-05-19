# JOURNAL-UX-1B — Postmortem Model Upgrade

## New Fields Added

| Field | Type | Purpose |
|-------|------|---------|
| dashboard_verdict | CLEAN_WIN / GOOD_EXIT / ACCEPTABLE_LOSS / RULE_BASED_LOSS / BAD_ENTRY / BAD_EXIT / EARLY_EXIT / LATE_EXIT / DATA_OR_BROKER_REVIEW / NEEDS_REVIEW | Clear operator-facing verdict |
| mistake_type | none / chased_entry / spread_slippage / stop_too_tight / stop_too_wide / stale_manual_exit / time_stop_drag / broker_sync_issue | What went wrong |
| action_priority | none / low / medium / high / urgent | Review urgency |
| action_owner | operator / system / strategy_review / data_pipeline / broker_sync | Who should act |
| next_operator_action | specific sentence | Concrete instruction |
| rule_feedback | specific sentence | Impact on rules/filters/gates |
| better_exit_possible | yes / no / unknown | Could we have exited better |
| post_exit_review_needed | boolean | Needs follow-up |
| confidence_delta | positive / neutral / negative | Strategy confidence change |
| improved_lesson | specific sentence | Never generic |

## New Function: build_daily_summary()

Returns dashboard-ready daily summary with:
- closed_today_count, wins, losses, flats
- total_realized_pnl, daily_avg_r
- best_trade, worst_trade
- top_lesson, top_action_item
- trades_needing_review (sorted by priority)
- strategy_confidence_changes
- repeated_failure_patterns

## Lesson Quality Rules Enforced

- Every lesson includes what happened, why it matters, what to check next
- manual_stale_close: mentions need for explicit stale-exit rule
- stop_hit_instant: mentions entry/spread/slippage/stop placement
- position_closed_in_alpaca: mentions broker sync / manual close review
- target_hit: mentions target discipline and strategy plan execution
- time_stop: mentions capital protection vs cutting valid setup early
- No lesson is just "Review" or "Check stop distance"
