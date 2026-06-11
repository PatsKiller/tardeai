-- Cross-system arbitration layer: per-source/per-list performance -> bounded weights consumed by scoring.
-- Populated by compute_source_weights.py from ATTRIBUTED data (screener_label flows as of 2026-06-11).
CREATE TABLE IF NOT EXISTS source_weights (
    id BIGSERIAL PRIMARY KEY,
    source_key TEXT NOT NULL,            -- screener name / 'hermes' / 'social' ...
    window_days INT NOT NULL,
    candidates INT, gos INT, proposals INT, trades INT, wins INT,
    realized_pnl NUMERIC,
    hit_rate NUMERIC,                    -- trades>0: wins/trades, else gos/candidates
    weight NUMERIC NOT NULL DEFAULT 1.0, -- bounded 0.9..1.1, consumed by scoring
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_key, window_days)
);
