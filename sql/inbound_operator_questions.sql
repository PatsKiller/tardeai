-- Inbound operator questions, tagged to the identity spine.  ADDITIVE ONLY.
--
-- Closes the loop that was one-way: research and news carried subject_guid and
-- issuer_guid; the inbound path carried nothing and stored nothing at all — only
-- communication_inbound_checkpoint holding the last update_id. So asking "Alex,
-- what's the analyst target for Visa?" left no trace an agent could later join to
-- the research that would answer it.
--
-- GRAIN: one row per (question, resolved entity).
-- A question resolving to two symbols writes two rows; a question resolving to
-- none still writes ONE row with null guids, because an unanswerable question is
-- the measurement of what the spine cannot reach and dropping it would make
-- coverage look better than it is.

CREATE TABLE IF NOT EXISTS inbound_operator_questions (
    id                  BIGSERIAL PRIMARY KEY,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- provenance of the message itself
    channel             TEXT        NOT NULL DEFAULT 'telegram',
    chat_id             TEXT,
    message_id          BIGINT,
    question_text       TEXT        NOT NULL,

    -- identity, from the spine. NULL means unresolved, not zero.
    symbol              TEXT,
    subject_guid        UUID,
    issuer_guid         UUID,
    identity_status     TEXT,

    -- HOW it resolved: a deterministic ticker hit and a company-name lookup are
    -- not equally strong evidence, and a reader must not have to re-derive which.
    matched_via         TEXT,        -- 'ticker' | 'company_name' | NULL
    matched_text        TEXT,        -- the operator's own words that matched

    -- what was asked ABOUT the issuer, not merely that it was mentioned
    topics              TEXT[]      NOT NULL DEFAULT '{}',

    -- names the feed does not carry: the measured shortfall
    unresolved_mentions TEXT[]      NOT NULL DEFAULT '{}',

    schema_version      TEXT        NOT NULL DEFAULT 'InboundOperatorQuestion@v1',
    authority           TEXT        NOT NULL DEFAULT 'READ_ONLY_ADVISORY'
);

-- The access paths an agent actually uses: everything asked about an issuer,
-- everything asked about a topic, and recent history.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ioq_issuer_guid  ON inbound_operator_questions (issuer_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ioq_subject_guid ON inbound_operator_questions (subject_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ioq_received_at  ON inbound_operator_questions (received_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ioq_topics       ON inbound_operator_questions USING GIN (topics);
