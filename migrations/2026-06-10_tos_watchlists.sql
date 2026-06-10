-- ToS (thinkorswim) watchlist ingestion + management. Inbound from imports/tos_watchlists/.
-- Schwab Trader API has no watchlist endpoint (confirmed live) — this is the fallback route.
CREATE TABLE IF NOT EXISTS tos_watchlists (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,          -- canonical name (from the export filename)
    display_name TEXT,                  -- operator rename (shown in UI)
    strategy_match TEXT,                -- matched strategy id
    notes TEXT,
    source_file TEXT,
    symbol_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_imported_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS tos_watchlist_members (
    id BIGSERIAL PRIMARY KEY,
    watchlist_id BIGINT NOT NULL REFERENCES tos_watchlists(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    notes TEXT,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    removed_at TIMESTAMPTZ,             -- NULL = active; set = removed (date tracked)
    UNIQUE (watchlist_id, symbol)
);
-- full add/delete audit trail (every add & removal, with date)
CREATE TABLE IF NOT EXISTS tos_watchlist_events (
    id BIGSERIAL PRIMARY KEY,
    watchlist_id BIGINT, symbol TEXT, event TEXT,   -- added | removed
    at TIMESTAMPTZ DEFAULT NOW(), source TEXT DEFAULT 'tos_import'
);
CREATE INDEX IF NOT EXISTS idx_tos_mem_active ON tos_watchlist_members (watchlist_id) WHERE removed_at IS NULL;
