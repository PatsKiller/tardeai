-- Hermes Discovery Inbox (Stage 1): candidate intake, clustering, audit, feedback.
-- Advisory-only surface — no broker/execution linkage. Additive-only, IF NOT EXISTS throughout.

CREATE TABLE IF NOT EXISTS hermes_discovery_candidates (
    id BIGSERIAL PRIMARY KEY,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN (
        'SOURCE_CANDIDATE', 'TREND_CANDIDATE', 'TICKER_CANDIDATE',
        'TOPIC_CANDIDATE', 'CONNECTOR_CANDIDATE')),
    normalized_key TEXT NOT NULL,
    label TEXT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'DISCOVERED' CHECK (status IN (
        'DISCOVERED', 'CLUSTERED', 'NEEDS_VALIDATION', 'NEEDS_MORE_DATA',
        'READY_FOR_REVIEW', 'APPROVED_RESEARCH_ONLY', 'APPROVED_SOURCE',
        'APPROVED_WATCH_DIRECTIVE', 'STAGED_TICKER_REVIEW',
        'PROMOTED_TO_WATCH_EVALUATION', 'REJECTED', 'MERGED_DUPLICATE',
        'BLOCKED', 'ARCHIVED_COLD')),
    safe_action_level TEXT NOT NULL DEFAULT 'OPERATOR_REVIEW_REQUIRED' CHECK (safe_action_level IN (
        'OBSERVE_ONLY', 'RESEARCH_ONLY', 'OPERATOR_REVIEW_REQUIRED',
        'AUTO_STAGE_INSIDE_RAILS', 'BLOCKED')),
    source_domain TEXT,
    source_url TEXT,
    seed_symbols TEXT[] DEFAULT '{}',
    extracted_symbols TEXT[] DEFAULT '{}',
    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    discovery_score NUMERIC,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    duplicate_cluster_id BIGINT,
    is_operator BOOLEAN NOT NULL DEFAULT FALSE,   -- operator-created rows are NEVER auto-merged
    seen_count INT NOT NULL DEFAULT 1,
    ttl_days INT NOT NULL DEFAULT 30,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    decided_by TEXT,
    decision_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hermes_disc_cand_type_key
    ON hermes_discovery_candidates (candidate_type, normalized_key);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_cand_status
    ON hermes_discovery_candidates (status);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_cand_source_domain
    ON hermes_discovery_candidates (source_domain);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_cand_cluster
    ON hermes_discovery_candidates (duplicate_cluster_id);

CREATE TABLE IF NOT EXISTS hermes_discovery_clusters (
    id BIGSERIAL PRIMARY KEY,
    candidate_type TEXT NOT NULL,
    cluster_key TEXT NOT NULL UNIQUE,             -- normalized_key of the cluster anchor
    label TEXT,
    anchor_candidate_id BIGINT,
    member_count INT NOT NULL DEFAULT 1,
    centroid_tokens TEXT[] DEFAULT '{}',
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_clusters_type
    ON hermes_discovery_clusters (candidate_type);

CREATE TABLE IF NOT EXISTS hermes_discovery_audit (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT,
    action TEXT NOT NULL,                          -- CREATE | UPSERT_BUMP | TRANSITION | DECIDE | CLUSTER_ASSIGN | FEEDBACK
    actor TEXT NOT NULL DEFAULT 'system',
    before_json JSONB,
    after_json JSONB,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_audit_candidate
    ON hermes_discovery_audit (candidate_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hermes_discovery_feedback (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT,
    feedback_type TEXT NOT NULL,                   -- useful | noise | approved | rejected | blocked | note
    actor TEXT NOT NULL DEFAULT 'operator',
    weight_delta NUMERIC,                          -- delta applied to source/trend weights (bounded ±0.3 cumulative)
    notes TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hermes_disc_feedback_candidate
    ON hermes_discovery_feedback (candidate_id, created_at DESC);
