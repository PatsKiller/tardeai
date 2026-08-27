# JOURNAL-UX-2 — Lesson Memory Data Model

## Tables

### trade_lesson_memory
Per-trade lesson records with repeated pattern detection.
- UNIQUE(trade_id, lesson_category, source_payload_hash) — idempotent
- human_review_only always TRUE
- operator_review_status: pending/accepted/rejected/converted_to_rule_review

### strategy_lesson_rollup
Strategy-level aggregation of lessons.
- wins/losses/avg_r/pnl per strategy
- repeated_mistakes, positive/negative patterns
- review_recommendation: no_action/review_exit_rule/review_entry_filter/pause_strategy/monitor
- UNIQUE(strategy_id, period_start, period_end)

### closed_trade_digest_log
Tracks digest delivery to prevent duplicates.
- digest_date, route_level, delivery_status, test_mode
