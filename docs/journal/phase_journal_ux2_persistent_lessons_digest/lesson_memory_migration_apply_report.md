  [SQL] CREATE TABLE IF NOT EXISTS trade_lesson_memory
  [SQL] CREATE TABLE IF NOT EXISTS strategy_lesson_rollup
  [SQL] CREATE TABLE IF NOT EXISTS closed_trade_digest_log
  [SQL] CREATE INDEX IF NOT EXISTS idx_tlm_symbol ON trade_lesson_memory
  [SQL] CREATE INDEX IF NOT EXISTS idx_tlm_strategy_id ON trade_lesson_memory
  [SQL] CREATE INDEX IF NOT EXISTS idx_tlm_lesson_category ON trade_lesson_memory
  [SQL] CREATE INDEX IF NOT EXISTS idx_tlm_repeated_pattern_key ON trade_lesson_memory
[OK] Migration applied: 7 statements executed.
