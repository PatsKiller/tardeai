-- v4.0 LLM Backtest Coverage — Schema Extension
-- Adds backtest trade support to trade_llm_reviews
-- Safety: DDL only, no data mutation

ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS backtest_trade_id BIGINT;
ALTER TABLE trade_llm_reviews ADD COLUMN IF NOT EXISTS source_table TEXT DEFAULT 'paper_trades';

CREATE INDEX IF NOT EXISTS idx_tlr_backtest ON trade_llm_reviews(backtest_trade_id);
CREATE INDEX IF NOT EXISTS idx_tlr_source ON trade_llm_reviews(source_table);
