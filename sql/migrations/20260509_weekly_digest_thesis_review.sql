-- Weekly Learning Digest + Post-Trade Thesis Review: Session 30
-- 2026-05-09 Idempotent: safe to re-run

-- A. Trade Thesis Reviews
CREATE TABLE IF NOT EXISTS trade_thesis_reviews (
    id                      BIGSERIAL PRIMARY KEY,
    review_id               TEXT UNIQUE NOT NULL,
    paper_trade_id          BIGINT,
    proposal_id             BIGINT,
    symbol                  TEXT NOT NULL,
    strategy_id             TEXT,
    trade_status            TEXT,
    review_type             TEXT NOT NULL,
    original_thesis         TEXT,
    original_entry_plan     JSONB,
    original_risk_plan      JSONB,
    original_catalyst       JSONB,
    original_agent_views    JSONB,
    actual_outcome          JSONB,
    thesis_validity         TEXT,
    thesis_score            NUMERIC,
    execution_score         NUMERIC,
    risk_management_score   NUMERIC,
    agent_alignment_score   NUMERIC,
    source_quality_score    NUMERIC,
    outcome_score           NUMERIC,
    lesson_summary          TEXT,
    mistake_tags            JSONB DEFAULT '[]'::jsonb,
    strength_tags           JSONB DEFAULT '[]'::jsonb,
    evidence                JSONB DEFAULT '{}'::jsonb,
    low_sample_size         BOOLEAN DEFAULT true,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ttr_symbol ON trade_thesis_reviews(symbol);
CREATE INDEX IF NOT EXISTS idx_ttr_trade ON trade_thesis_reviews(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_ttr_proposal ON trade_thesis_reviews(proposal_id);

-- B. Weekly Learning Digests
CREATE TABLE IF NOT EXISTS weekly_learning_digests (
    id                      BIGSERIAL PRIMARY KEY,
    digest_id               TEXT UNIQUE NOT NULL,
    period_start            DATE NOT NULL,
    period_end              DATE NOT NULL,
    status                  TEXT DEFAULT 'draft',
    generated_at            TIMESTAMPTZ DEFAULT now(),
    generated_by            TEXT DEFAULT 'weekly_learning_digest',
    holdings_value          NUMERIC,
    paper_trades_open       INTEGER DEFAULT 0,
    paper_trades_closed     INTEGER DEFAULT 0,
    proposals_created       INTEGER DEFAULT 0,
    proposals_approved      INTEGER DEFAULT 0,
    proposals_rejected      INTEGER DEFAULT 0,
    win_rate                NUMERIC,
    profit_factor           NUMERIC,
    expectancy_r            NUMERIC,
    low_sample_size         BOOLEAN DEFAULT true,
    top_lessons             JSONB DEFAULT '[]'::jsonb,
    risk_alerts             JSONB DEFAULT '[]'::jsonb,
    agent_summary           JSONB DEFAULT '{}'::jsonb,
    source_summary          JSONB DEFAULT '{}'::jsonb,
    strategy_summary        JSONB DEFAULT '{}'::jsonb,
    execution_summary       JSONB DEFAULT '{}'::jsonb,
    thesis_summary          JSONB DEFAULT '{}'::jsonb,
    recommendations         JSONB DEFAULT '[]'::jsonb,
    human_review_items      JSONB DEFAULT '[]'::jsonb,
    digest_markdown         TEXT,
    digest_payload          JSONB DEFAULT '{}'::jsonb,
    delivered_telegram      BOOLEAN DEFAULT false,
    delivered_dashboard     BOOLEAN DEFAULT false,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_wld_period ON weekly_learning_digests(period_start, period_end);

-- C. Weekly Learning Digest Items
CREATE TABLE IF NOT EXISTS weekly_learning_digest_items (
    id                      BIGSERIAL PRIMARY KEY,
    digest_id               TEXT NOT NULL,
    item_id                 TEXT UNIQUE NOT NULL,
    item_type               TEXT NOT NULL,
    severity                TEXT DEFAULT 'info',
    title                   TEXT NOT NULL,
    summary                 TEXT,
    symbol                  TEXT,
    strategy_id             TEXT,
    agent_name              TEXT,
    source_key              TEXT,
    linked_table            TEXT,
    linked_id               TEXT,
    payload                 JSONB DEFAULT '{}'::jsonb,
    requires_human_review   BOOLEAN DEFAULT false,
    review_status           TEXT DEFAULT 'pending',
    created_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_wldi_digest ON weekly_learning_digest_items(digest_id);
CREATE INDEX IF NOT EXISTS idx_wldi_type ON weekly_learning_digest_items(item_type);

-- D. Thesis Learning Evidence Links
CREATE TABLE IF NOT EXISTS thesis_learning_evidence_links (
    id                      BIGSERIAL PRIMARY KEY,
    link_id                 TEXT UNIQUE NOT NULL,
    review_id               TEXT NOT NULL,
    evidence_id             TEXT,
    hypothesis_id           TEXT,
    recommendation_id       TEXT,
    symbol                  TEXT,
    strategy_id             TEXT,
    agent_name              TEXT,
    source_key              TEXT,
    link_type               TEXT,
    link_confidence         NUMERIC DEFAULT 1.0,
    payload                 JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tlel_review ON thesis_learning_evidence_links(review_id);

-- E. Learning Digest Delivery Log
CREATE TABLE IF NOT EXISTS learning_digest_delivery_log (
    id                      BIGSERIAL PRIMARY KEY,
    delivery_id             TEXT UNIQUE NOT NULL,
    digest_id               TEXT NOT NULL,
    channel                 TEXT NOT NULL,
    recipient               TEXT,
    status                  TEXT,
    error_message           TEXT,
    sent_at                 TIMESTAMPTZ,
    payload                 JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lddl_digest ON learning_digest_delivery_log(digest_id);
