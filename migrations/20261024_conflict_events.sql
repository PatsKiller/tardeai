-- PROPOSED: operator applies only after granting conflict_ledger domain.
-- No runtime import executes this migration. Mirror remains gated off by default.
CREATE TABLE IF NOT EXISTS conflict_events (
    event_id text PRIMARY KEY,
    sequence bigint NOT NULL UNIQUE,
    conflict_key text NOT NULL,
    subject_kind text NOT NULL,
    subject_id text NOT NULL,
    event_kind text NOT NULL,
    at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS conflict_events_subject_idx ON conflict_events(subject_kind, subject_id, sequence);
REVOKE UPDATE, DELETE, TRUNCATE ON conflict_events FROM PUBLIC;
