-- Reverse of 2026_10_22_ops_controls.sql. Archives by RENAME; never drops (AGENTS.md section 0 rule 6).
-- After this runs, GET /api/v2/ops/controls/state reports store.state = "NOT_MIGRATED" and every POST is refused.
-- The refuse-mutation triggers stay attached to the archived tables, so the archives stay immutable / undeletable.
-- trade_ai keeps SELECT on the archives and loses every write. Each step is guarded, so a second run is a no-op.
-- Apply (operator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_ops_controls.down.sql

BEGIN;

ALTER TABLE IF EXISTS operator_settings RENAME TO operator_settings_archived_20261022;
ALTER TABLE IF EXISTS operator_settings_history RENAME TO operator_settings_history_archived_20261022;
ALTER TABLE IF EXISTS ops_audit RENAME TO ops_audit_archived_20261022;
ALTER TABLE IF EXISTS ops_applier_requests RENAME TO ops_applier_requests_archived_20261022;
ALTER TABLE IF EXISTS ops_webauthn_challenges RENAME TO ops_webauthn_challenges_archived_20261022;
ALTER TABLE IF EXISTS webauthn_credentials RENAME TO webauthn_credentials_archived_20261022;
ALTER TABLE IF EXISTS totp_recovery RENAME TO totp_recovery_archived_20261022;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['operator_settings_archived_20261022', 'operator_settings_history_archived_20261022',
                             'ops_audit_archived_20261022', 'ops_applier_requests_archived_20261022',
                             'ops_webauthn_challenges_archived_20261022', 'webauthn_credentials_archived_20261022',
                             'totp_recovery_archived_20261022'] LOOP
        IF to_regclass('public.' || t) IS NOT NULL AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trade_ai') THEN
            EXECUTE format('REVOKE INSERT, UPDATE ON %I FROM trade_ai', t);
        END IF;
    END LOOP;
END
$$;

COMMIT;
