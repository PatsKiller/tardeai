-- Config Documents: generic DB-backed config storage with history
-- 2026-05-09 Hardening Sprint Workstream A

CREATE TABLE IF NOT EXISTS config_documents (
    id              BIGSERIAL PRIMARY KEY,
    config_key      TEXT UNIQUE NOT NULL,
    source_path     TEXT,
    config_type     TEXT NOT NULL,
    content         JSONB NOT NULL,
    checksum        TEXT,
    schema_version  TEXT DEFAULT '1',
    active          BOOLEAN DEFAULT true,
    migrated_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS config_document_history (
    id              BIGSERIAL PRIMARY KEY,
    config_key      TEXT NOT NULL,
    source_path     TEXT,
    config_type     TEXT,
    old_checksum    TEXT,
    new_checksum    TEXT,
    content         JSONB,
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    changed_by      TEXT DEFAULT 'migration_script',
    notes           TEXT
);

-- Holdings mirror: read-only DB copy of holdings.json for cross-referencing
-- This is a MIRROR. holdings.json remains the file-of-record.
CREATE TABLE IF NOT EXISTS holdings_json_mirror (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_at     TIMESTAMPTZ DEFAULT NOW(),
    content         JSONB NOT NULL,
    checksum        TEXT NOT NULL,
    portfolio_value NUMERIC,
    position_count  INTEGER,
    source          TEXT DEFAULT 'holdings.json'
);

COMMENT ON TABLE holdings_json_mirror IS 'READ-ONLY mirror of holdings.json. File remains authority. Never overwrite file from this table.';

CREATE INDEX IF NOT EXISTS idx_config_docs_key ON config_documents(config_key) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_config_docs_type ON config_documents(config_type);
CREATE INDEX IF NOT EXISTS idx_config_history_key ON config_document_history(config_key, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_mirror_time ON holdings_json_mirror(snapshot_at DESC);
