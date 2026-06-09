-- 2026-06-09_time_exit_proposals.sql — max-hold close proposals (advisory, approval-gated). Additive.
-- NO auto-close: positions overdue past their strategy max_hold_days produce a PROPOSAL the operator
-- approves; approval routes through the paper-only interlock + the existing close_paper_trade path.
CREATE TABLE IF NOT EXISTS paper_time_exit_proposals (
    id                 BIGSERIAL PRIMARY KEY,
    trade_id           BIGINT NOT NULL,
    symbol             TEXT NOT NULL,
    strategy_id        TEXT,
    hold_days          INT,
    max_hold_days      INT,
    overdue_by_days    INT,
    entry_price        NUMERIC,
    current_price      NUMERIC,
    unrealized_pnl_pct NUMERIC,
    status             TEXT NOT NULL DEFAULT 'pending_review',  -- pending_review|approved|rejected|expired|applied|apply_failed
    apply_result       TEXT,
    decided_by         TEXT,
    decided_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_time_exit_trade ON paper_time_exit_proposals (trade_id, status);
