-- Phase A — Redeploy data truth (advisory only)
-- Exposure decomposition + portfolio context snapshots + proceeds reconciliation

ALTER TABLE deploy_events
  ADD COLUMN IF NOT EXISTS net_proceeds_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS deployable_cash_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS reconciliation_status TEXT NOT NULL DEFAULT 'unsettled',
  ADD COLUMN IF NOT EXISTS policy_version TEXT,
  ADD COLUMN IF NOT EXISTS generator_version TEXT,
  ADD COLUMN IF NOT EXISTS holdings_snapshot_id TEXT;

DO $$ BEGIN
  ALTER TABLE deploy_events
    ADD CONSTRAINT chk_deploy_reconciliation_status
    CHECK (reconciliation_status IN ('unsettled', 'partial', 'verified'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS redeploy_exposure_loss (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    version INT NOT NULL DEFAULT 1,
    asset_class TEXT,
    income_annual_usd NUMERIC,
    income_status TEXT NOT NULL DEFAULT 'unknown',
    income_source TEXT,
    income_as_of DATE,
    benchmark TEXT,
    residual_sector_pct NUMERIC,
    residual_sector_usd NUMERIC,
    policy_version TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    holdings_snapshot_id TEXT,
    input_hash TEXT NOT NULL,
    source_as_of DATE,
    created_by TEXT NOT NULL DEFAULT 'redeploy_phase_a',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (deploy_event_id, version)
);

DO $$ BEGIN
  ALTER TABLE redeploy_exposure_loss
    ADD CONSTRAINT chk_redeploy_income_status
    CHECK (income_status IN ('known', 'unknown', 'estimated'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS redeploy_exposure_loss_sector (
    id BIGSERIAL PRIMARY KEY,
    exposure_loss_id BIGINT NOT NULL REFERENCES redeploy_exposure_loss(id) ON DELETE CASCADE,
    sector TEXT NOT NULL,
    weight_pct NUMERIC NOT NULL,
    usd_removed NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS redeploy_exposure_loss_holding (
    id BIGSERIAL PRIMARY KEY,
    exposure_loss_id BIGINT NOT NULL REFERENCES redeploy_exposure_loss(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    holding_name TEXT,
    weight_pct NUMERIC NOT NULL,
    usd_removed NUMERIC NOT NULL,
    share_class_note TEXT
);

CREATE TABLE IF NOT EXISTS redeploy_portfolio_context_snapshots (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    version INT NOT NULL DEFAULT 1,
    portfolio_equity_usd NUMERIC NOT NULL,
    portfolio_total_with_cash_usd NUMERIC NOT NULL,
    sale_account TEXT NOT NULL,
    deployable_cash_usd NUMERIC NOT NULL,
    net_proceeds_usd NUMERIC NOT NULL,
    reconciliation_status TEXT NOT NULL,
    is_major_sale BOOLEAN NOT NULL DEFAULT FALSE,
    major_sale_reason TEXT,
    overlap_analysis JSONB NOT NULL DEFAULT '{}'::jsonb,
    concentration_limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    regime_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_version TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    holdings_snapshot_id TEXT,
    input_hash TEXT NOT NULL,
    source_as_of TIMESTAMPTZ,
    created_by TEXT NOT NULL DEFAULT 'redeploy_phase_a',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (deploy_event_id, version)
);

CREATE INDEX IF NOT EXISTS idx_redeploy_exposure_event ON redeploy_exposure_loss(deploy_event_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_redeploy_context_event ON redeploy_portfolio_context_snapshots(deploy_event_id, version DESC);