-- Active Trader Stage 1 · 0005 feature flags, notifications, drive manifest, checkpoints (up)
-- Feature flags are APPEND-ONLY versioned rows (audit built in); current value =
-- highest version per (flag_name, scope_key). Flags can never authorize trading.

CREATE TABLE active_trader_feature_flags (
    flag_name           TEXT NOT NULL,
    scope_key           TEXT NOT NULL DEFAULT 'global',  -- e.g. global | env:production | broker:alpaca | account:<label> | operator:<id>
    version             INTEGER NOT NULL CHECK (version >= 1),
    mode                TEXT NOT NULL CHECK (mode IN ('OFF','READ_ONLY','SHADOW','SIMULATION','LIVE_CANARY')),
    scope               JSONB NOT NULL DEFAULT '{}'::jsonb,
    expires_at          TIMESTAMPTZ,
    reason              TEXT NOT NULL,
    changed_by          TEXT NOT NULL,
    changed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    rollback_mode       TEXT NOT NULL DEFAULT 'OFF' CHECK (rollback_mode IN ('OFF','READ_ONLY','SHADOW','SIMULATION','LIVE_CANARY')),
    PRIMARY KEY (flag_name, scope_key, version)
);

CREATE TRIGGER trg_feature_flags_append_only
    BEFORE UPDATE OR DELETE ON active_trader_feature_flags
    FOR EACH ROW EXECUTE FUNCTION active_trader_forbid_mutation();

CREATE TABLE active_trader_notification_events (
    notification_event_id UUID PRIMARY KEY,
    environment         TEXT NOT NULL CHECK (environment IN ('SHADOW','SIMULATION','LIVE')),
    severity            TEXT NOT NULL CHECK (severity IN ('INFO','WARN','BLOCKING','CRITICAL')),
    category            TEXT NOT NULL,           -- rejection | fallback | session | protection | parity | run
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    requires_operator_action BOOLEAN NOT NULL DEFAULT false,
    channels            JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ui/telegram/email dispatch record (names only)
    related_ref         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by     TEXT
);

CREATE TABLE active_trader_drive_sync_manifest (
    manifest_id         UUID PRIMARY KEY,
    run_id              TEXT NOT NULL,
    stage               INTEGER NOT NULL,
    local_path          TEXT NOT NULL,
    github_path         TEXT NOT NULL,
    git_ref             TEXT,                    -- commit or blob sha
    drive_file_id       TEXT,
    sha256              TEXT NOT NULL,
    upload_state        TEXT NOT NULL CHECK (upload_state IN ('PENDING','UPLOADED','FAILED')),
    verified            BOOLEAN NOT NULL DEFAULT false,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, stage, local_path)
);

CREATE TABLE active_trader_run_checkpoints (
    run_id              TEXT PRIMARY KEY,
    architecture_version TEXT NOT NULL,
    program_version     TEXT NOT NULL,
    base_sha            TEXT NOT NULL,
    branch              TEXT NOT NULL,
    current_stage       INTEGER NOT NULL,
    state               TEXT NOT NULL CHECK (state IN ('NOT_STARTED','RUNNING','GREEN_CLOSED','FAILED','BLOCKED','PAUSED')),
    last_green_stage    INTEGER,
    stage_commits       JSONB NOT NULL DEFAULT '[]'::jsonb,
    drive_artifacts     JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_operator_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    test_summary        TEXT,
    failure             TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    version             INTEGER NOT NULL CHECK (version >= 1)   -- optimistic concurrency
);
