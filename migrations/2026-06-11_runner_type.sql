-- Classify missed-runners: sustained_trend (holding captures real upside) vs parabolic_pump (spike that
-- faded back — holding is a trap). Additive, read-only analytics.
ALTER TABLE trade_execution_quality ADD COLUMN IF NOT EXISTS runner_type TEXT;
ALTER TABLE trade_execution_quality ADD COLUMN IF NOT EXISTS post_exit_gave_back_ratio NUMERIC;
