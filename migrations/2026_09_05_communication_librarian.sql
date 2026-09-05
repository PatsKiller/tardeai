-- Trade AI Communications Gateway — Librarian retention (Phase 6).
-- RetentionDecision@v1: lifecycle classification for communications — NOT source truth.
-- Knowledge promotion requires provenance/evidence/ownership/review — never auto-promote chat.
-- Additive only. Does not modify broker/order/2FA/guardrail tables.

CREATE TABLE IF NOT EXISTS communication_retention_decisions (
    decision_id             TEXT PRIMARY KEY,
    event_id                TEXT NOT NULL,
    retention_class         TEXT NOT NULL,
    content_ttl_seconds     INTEGER,
    metadata_ttl_seconds    INTEGER,
    embedding_ttl_seconds   INTEGER,
    attachment_ttl_seconds  INTEGER,
    legal_hold              BOOLEAN NOT NULL DEFAULT FALSE,
    reason                  TEXT,
    decided_by              TEXT NOT NULL DEFAULT 'comms.librarian',
    policy_version          TEXT NOT NULL DEFAULT 'RetentionDecision@v1',
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at              TIMESTAMPTZ,
    action                  TEXT NOT NULL
                            CHECK (action IN (
                                'KEEP',
                                'COMPACT',
                                'REDACT',
                                'DELETE_CONTENT_KEEP_TOMBSTONE',
                                'DELETE_ALL_ALLOWED',
                                'HOLD'
                            )),
    receipt                 JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS communication_retention_decisions_event_idx
    ON communication_retention_decisions (event_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS communication_retention_decisions_expires_idx
    ON communication_retention_decisions (expires_at)
    WHERE expires_at IS NOT NULL AND legal_hold = FALSE;

CREATE TABLE IF NOT EXISTS communication_tombstones (
    event_id                TEXT PRIMARY KEY,
    purged_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    action                  TEXT NOT NULL,
    content_hash            TEXT,
    decided_by              TEXT,
    note                    TEXT
);

CREATE TABLE IF NOT EXISTS communication_knowledge_candidates (
    candidate_id            TEXT PRIMARY KEY,
    event_id                TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'CANDIDATE'
                            CHECK (status IN (
                                'CANDIDATE',
                                'ACCEPTED',
                                'DISPUTED',
                                'SUPERSEDED',
                                'RETRACTED',
                                'REJECTED'
                            )),
    assertion_text          TEXT NOT NULL,
    evidence_refs           JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner                   TEXT NOT NULL,
    review_path             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS communication_knowledge_candidates_event_idx
    ON communication_knowledge_candidates (event_id, created_at DESC);
CREATE INDEX IF NOT EXISTS communication_knowledge_candidates_status_idx
    ON communication_knowledge_candidates (status, created_at DESC);
