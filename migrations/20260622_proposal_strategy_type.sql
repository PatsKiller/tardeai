-- Stamp canonical strategy type (INTRADAY, SHORT_SWING, etc.) on proposals
ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS strategy_type TEXT;

CREATE INDEX IF NOT EXISTS idx_ptp_strategy_type
    ON paper_trade_proposals (strategy_type)
    WHERE strategy_type IS NOT NULL;