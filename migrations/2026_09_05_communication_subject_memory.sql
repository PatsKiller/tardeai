-- Trade AI Communications Gateway — Subject Memory / SubjectThread@v1.
-- Answers "What happened previously on this exact subject?" before curation.
-- Cross-channel thread membership. Policy-eligible retrieval only.
-- Additive only. Does not modify broker/order/2FA/guardrail tables.
-- Distinct from cio_rehydrate instrument cognition.

CREATE TABLE IF NOT EXISTS communication_subjects (
    subject_key           TEXT PRIMARY KEY,
    domain                TEXT NOT NULL
                          CHECK (domain IN (
                              'symbol', 'account', 'incident', 'proposal',
                              'research', 'system', 'operator'
                          )),
    canonical_entities    JSONB NOT NULL DEFAULT '{}'::jsonb,
    aliases               JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_activity_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    latest_state          JSONB NOT NULL DEFAULT '{}'::jsonb,
    open_questions        JSONB NOT NULL DEFAULT '[]'::jsonb,
    operator_decisions    JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcomes              JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS communication_subjects_last_activity_idx
    ON communication_subjects (last_activity_at DESC);
CREATE INDEX IF NOT EXISTS communication_subjects_domain_idx
    ON communication_subjects (domain, last_activity_at DESC);

CREATE TABLE IF NOT EXISTS communication_thread_membership (
    subject_key           TEXT NOT NULL
                          REFERENCES communication_subjects(subject_key) ON DELETE CASCADE,
    event_id              TEXT NOT NULL,
    channel               TEXT,
    provider_coordinates  JSONB NOT NULL DEFAULT '{}'::jsonb,
    joined_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_key, event_id)
);

CREATE INDEX IF NOT EXISTS communication_thread_membership_event_idx
    ON communication_thread_membership (event_id);
CREATE INDEX IF NOT EXISTS communication_thread_membership_joined_idx
    ON communication_thread_membership (subject_key, joined_at DESC);
