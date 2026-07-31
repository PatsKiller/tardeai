-- Intelligence item operator state (dismiss / reviewed) + auto-archive metadata
CREATE TABLE IF NOT EXISTS intelligence_item_state (
    item_id     TEXT PRIMARY KEY,
    item_type   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dismissed', 'reviewed')),
    note        TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT NOT NULL DEFAULT 'operator'
);
CREATE INDEX IF NOT EXISTS idx_intelligence_item_state_status ON intelligence_item_state (status);
CREATE INDEX IF NOT EXISTS idx_intelligence_item_state_updated ON intelligence_item_state (updated_at DESC);

-- Remediation run ledger (automation maturity metrics for Learning tab)
CREATE TABLE IF NOT EXISTS intelligence_remediation_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    gaps_enqueued   INT NOT NULL DEFAULT 0,
    items_archived  INT NOT NULL DEFAULT 0,
    ensemble_queued INT NOT NULL DEFAULT 0,
    watch_critics   INT NOT NULL DEFAULT 0,
    note            TEXT
);
