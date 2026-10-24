-- Reverse of 2026_10_22_ops_controls_sudo_window.sql: narrow the factor CHECK back to ('passkey', 'totp') for NEW rows.
-- NOT VALID keeps every existing row (a 'sudo_window' row already written stays as history; never rewritten or
-- removed, AGENTS.md section 0 rule 6). Apply (operator only):
--     psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_ops_controls_sudo_window.down.sql

BEGIN;

ALTER TABLE ops_applier_requests DROP CONSTRAINT IF EXISTS ops_applier_requests_factor_ck;
ALTER TABLE ops_applier_requests ADD CONSTRAINT ops_applier_requests_factor_ck
    CHECK (stepup_factor IS NULL OR stepup_factor IN ('passkey', 'totp')) NOT VALID;

COMMIT;
