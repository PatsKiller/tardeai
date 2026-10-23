-- Ops -> Controls (AGENTS.md 19.0.0 §27.2-§27.3, PROPOSED): the operator settings store, the controls audit, the
-- passkey and TOTP-recovery stores, and the governed host applier's request queue.
--
-- NEEDS OPERATOR. Written, not applied. Creating these tables is a §17 act (a new authoritative store and its writer;
-- the registry row `operator_settings` is proposed by the AGENTS 19.0.0 package, not by this file). Until it runs,
-- GET /api/v2/ops/controls/state reports store.state = "NOT_MIGRATED" and every POST is refused.
--
-- Plan (dry run, prints what would be created and what already exists; writes nothing):
--     .venv/bin/python scripts/ops/ops_controls_migration_plan.py            (offline: parses this file)
--     .venv/bin/python scripts/ops/ops_controls_migration_plan.py --probe    (read-only to_regclass probe)
-- Apply (operator):   psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_ops_controls.sql
-- Verify (operator):  psql "$DB" -c "SELECT to_regclass('public.operator_settings'), to_regclass('public.ops_audit')"
-- Reverse (operator): migrations/2026_10_22_ops_controls.down.sql (archives by rename; never drops).
--
-- Seven NEW tables. Nothing existing is altered, so this migration is additive by construction.
--
--   operator_settings          current value per key; a row overrides the repository default (config/ops_controls.json
--                              settings_catalog). Unset = active false (the row is kept). Writer: the host applier.
--   operator_settings_history  APPEND-ONLY. One row per change: who, when, which key, old and new value, request id.
--   ops_audit                  APPEND-ONLY, hash-chained. One row per controls action and refusal.
--   ops_applier_requests       the change-request queue (preview, phrase, step-up binding, HMAC-signed approval,
--                              result). Mutable status; never deleted.
--   ops_webauthn_challenges    single-use WebAuthn challenges, each bound to one request and purpose, 2-minute TTL.
--   webauthn_credentials       named passkeys (public keys only), sign counter, revocation. Never deleted.
--   totp_recovery              TOTP RECOVERY metadata only (label, secret fingerprint, last accepted time step). The
--                              secret itself is never in the database: it lives in a 0600 file outside the repository.
--
-- Every table refuses DELETE and TRUNCATE by trigger (AGENTS.md §0 rule 6: never delete); the two append-only tables
-- also refuse UPDATE. Triggers bind the table owner too.
-- Idempotent: CREATE ... IF NOT EXISTS; triggers created only when absent (no DROP anywhere).

BEGIN;

CREATE TABLE IF NOT EXISTS operator_settings (
    key          TEXT PRIMARY KEY,
    value        JSONB,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by   TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    CONSTRAINT operator_settings_key_ck CHECK (key ~ '^[a-z][a-z0-9_.]{1,95}$')
);

CREATE TABLE IF NOT EXISTS operator_settings_history (
    seq          BIGSERIAL PRIMARY KEY,
    key          TEXT NOT NULL,
    op           TEXT NOT NULL,
    old_value    JSONB,
    old_active   BOOLEAN,
    new_value    JSONB,
    new_active   BOOLEAN NOT NULL,
    actor        TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operator_settings_history_op_ck CHECK (op IN ('set', 'unset'))
);
CREATE INDEX IF NOT EXISTS operator_settings_history_key_idx ON operator_settings_history (key, seq);

CREATE TABLE IF NOT EXISTS ops_audit (
    seq          BIGSERIAL PRIMARY KEY,
    at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    kind         TEXT,
    request_id   TEXT,
    outcome      TEXT NOT NULL,
    detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_hash    TEXT,
    row_hash     TEXT NOT NULL,
    CONSTRAINT ops_audit_detail_ck CHECK (jsonb_typeof(detail) = 'object')
);
CREATE INDEX IF NOT EXISTS ops_audit_request_idx ON ops_audit (request_id, seq);

CREATE TABLE IF NOT EXISTS ops_applier_requests (
    request_id             TEXT PRIMARY KEY,
    idempotency_key        TEXT NOT NULL,
    kind                   TEXT NOT NULL,
    direction              TEXT NOT NULL,
    executor               TEXT NOT NULL,
    params                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    phrase                 TEXT,
    preview                JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_state_digest  TEXT,
    actor                  TEXT NOT NULL,
    status                 TEXT NOT NULL,
    status_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    stepup_token_hash      TEXT,
    stepup_expires_at      TIMESTAMPTZ,
    stepup_factor          TEXT,
    stepup_credential_id   TEXT,
    stepup_used_at         TIMESTAMPTZ,
    approved_at            TIMESTAMPTZ,
    approval_sig           TEXT,
    applied_at             TIMESTAMPTZ,
    result                 JSONB,
    undo_of                TEXT,
    undone_by              TEXT,
    CONSTRAINT ops_applier_requests_idem_uq UNIQUE (idempotency_key),
    CONSTRAINT ops_applier_requests_direction_ck CHECK (direction IN ('safe', 'risky')),
    CONSTRAINT ops_applier_requests_executor_ck CHECK (executor IN ('applier', 'cc')),
    CONSTRAINT ops_applier_requests_status_ck CHECK (status IN (
        'PREVIEWED', 'AWAITING_STEP_UP', 'STEP_UP_VERIFIED', 'APPROVED', 'APPLYING', 'APPLIED', 'FAILED', 'REFUSED',
        'EXPIRED', 'CANCELLED')),
    CONSTRAINT ops_applier_requests_factor_ck CHECK (stepup_factor IS NULL OR stepup_factor IN ('passkey', 'totp'))
);
CREATE INDEX IF NOT EXISTS ops_applier_requests_status_idx ON ops_applier_requests (status, approved_at);

CREATE TABLE IF NOT EXISTS ops_webauthn_challenges (
    challenge_id  TEXT PRIMARY KEY,
    request_id    TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    challenge     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    used_at       TIMESTAMPTZ,
    CONSTRAINT ops_webauthn_challenges_purpose_ck CHECK (purpose IN ('step_up', 'register'))
);
CREATE INDEX IF NOT EXISTS ops_webauthn_challenges_req_idx ON ops_webauthn_challenges (request_id, purpose);

CREATE TABLE IF NOT EXISTS webauthn_credentials (
    credential_id      TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    public_key         TEXT NOT NULL,
    sign_count         BIGINT NOT NULL DEFAULT 0,
    transports         JSONB NOT NULL DEFAULT '[]'::jsonb,
    aaguid             TEXT,
    user_handle        TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         TEXT NOT NULL,
    created_request_id TEXT NOT NULL,
    last_used_at       TIMESTAMPTZ,
    revoked_at         TIMESTAMPTZ,
    revoked_by         TEXT,
    revoke_request_id  TEXT,
    CONSTRAINT webauthn_credentials_name_ck CHECK (length(name) BETWEEN 1 AND 64)
);

CREATE TABLE IF NOT EXISTS totp_recovery (
    id                  BIGSERIAL PRIMARY KEY,
    label               TEXT NOT NULL,
    secret_fingerprint  TEXT NOT NULL,
    enrolled_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    enrolled_by         TEXT NOT NULL,
    last_used_step      BIGINT,
    last_used_at        TIMESTAMPTZ,
    revoked_at          TIMESTAMPTZ
);

COMMENT ON TABLE operator_settings IS
    'Ops Controls (AGENTS 19.0.0 §27.2): current operator settings; a row overrides the repository default. '
    'Writer: scripts/ops/operator_controls_applier.py only. Unset keeps the row (active=false).';
COMMENT ON TABLE operator_settings_history IS 'Append-only history of operator_settings (one row per change).';
COMMENT ON TABLE ops_audit IS 'Append-only, hash-chained audit of every Ops Controls action and refusal.';
COMMENT ON TABLE ops_applier_requests IS 'Ops Controls change requests; applied only by the host applier.';
COMMENT ON TABLE webauthn_credentials IS 'Operator passkeys (public keys only). Revoked, never deleted.';
COMMENT ON TABLE totp_recovery IS 'TOTP recovery metadata only; the secret is a 0600 file outside the repository.';

CREATE OR REPLACE FUNCTION ops_controls_refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '%: % refused (Ops Controls stores are never deleted; append-only tables are never updated)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'AGENTS.md section 0 rule 6: archive, never delete. Append a compensating row instead.';
END
$$;

DO $$
DECLARE
    t TEXT;
BEGIN
    -- Append-only: refuse UPDATE and DELETE (row) and TRUNCATE (statement).
    FOREACH t IN ARRAY ARRAY['operator_settings_history', 'ops_audit'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_no_update_delete' AND tgrelid = t::regclass) THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW '
                           'EXECUTE FUNCTION ops_controls_refuse_mutation()', t || '_no_update_delete', t);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_no_truncate' AND tgrelid = t::regclass) THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT '
                           'EXECUTE FUNCTION ops_controls_refuse_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
    -- Never deleted: refuse DELETE (row) and TRUNCATE (statement); UPDATE allowed.
    FOREACH t IN ARRAY ARRAY['operator_settings', 'ops_applier_requests', 'ops_webauthn_challenges',
                             'webauthn_credentials', 'totp_recovery'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_no_delete' AND tgrelid = t::regclass) THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE DELETE ON %I FOR EACH ROW '
                           'EXECUTE FUNCTION ops_controls_refuse_mutation()', t || '_no_delete', t);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = t || '_no_truncate' AND tgrelid = t::regclass) THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT '
                           'EXECUTE FUNCTION ops_controls_refuse_mutation()', t || '_no_truncate', t);
        END IF;
    END LOOP;
END
$$;

-- Least privilege for trade_ai (the role both the Command Center and the applier connect as; scripts/session13_db.py).
-- No DELETE, TRUNCATE, REFERENCES, TRIGGER or DDL anywhere. PUBLIC gets nothing.
REVOKE ALL ON operator_settings, operator_settings_history, ops_audit, ops_applier_requests, ops_webauthn_challenges,
    webauthn_credentials, totp_recovery FROM PUBLIC;
REVOKE ALL ON SEQUENCE operator_settings_history_seq_seq, ops_audit_seq_seq, totp_recovery_id_seq FROM PUBLIC;
GRANT SELECT, INSERT ON operator_settings_history, ops_audit TO trade_ai;
GRANT SELECT, INSERT, UPDATE ON operator_settings, ops_applier_requests, ops_webauthn_challenges, webauthn_credentials,
    totp_recovery TO trade_ai;
GRANT USAGE ON SEQUENCE operator_settings_history_seq_seq, ops_audit_seq_seq, totp_recovery_id_seq TO trade_ai;

COMMIT;
