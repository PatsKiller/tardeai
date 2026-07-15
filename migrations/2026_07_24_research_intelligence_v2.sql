-- Research Intelligence v2 — operator feedback, notes, stars; archive remains searchable.
-- Safe to re-run (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS research_intelligence_feedback (
    id              BIGSERIAL PRIMARY KEY,
    item_id         TEXT NOT NULL,              -- e.g. hermes:12345 | urt:9 | tm:roth_ladder
    source_system   TEXT,
    source_table    TEXT,
    source_id       TEXT,
    starred         BOOLEAN NOT NULL DEFAULT FALSE,
    vote            SMALLINT,                   -- +1 useful, -1 not useful, NULL none
    note            TEXT,
    categories      TEXT[] DEFAULT '{}',
    symbol          TEXT,
    meta_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (item_id)
);

CREATE INDEX IF NOT EXISTS idx_ri_feedback_starred
    ON research_intelligence_feedback (starred) WHERE starred = TRUE;
CREATE INDEX IF NOT EXISTS idx_ri_feedback_vote
    ON research_intelligence_feedback (vote) WHERE vote IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ri_feedback_updated
    ON research_intelligence_feedback (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ri_feedback_symbol
    ON research_intelligence_feedback (symbol) WHERE symbol IS NOT NULL;

-- Helpful archive / freshness indexes on Hermes (no-op if already present)
CREATE INDEX IF NOT EXISTS idx_hri_status_created
    ON hermes_research_intelligence (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hri_archived
    ON hermes_research_intelligence (created_at DESC)
    WHERE status = 'archived';

COMMENT ON TABLE research_intelligence_feedback IS
  'Operator stars, thumbs, and notes on Research Intelligence feed items (closed-loop learning).';
