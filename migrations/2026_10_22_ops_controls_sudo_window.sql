-- Ops -> Controls sudo window (operator decision 2026-10-22 "approve sudo window"; policy text in AGENTS.md 20.0.0 §28.5):
-- let ops_applier_requests.stepup_factor record 'sudo_window' for a risky act stepped up inside an open window.
--
-- NEEDS OPERATOR. Written, not applied. Apply AFTER migrations/2026_10_22_ops_controls.sql. Until it runs, a step-up
-- inside a sudo window is refused by the database CHECK (the window fails closed; nothing else changes). The window
-- itself is also inert until AGENTS.md >= 20.0.0 is ACTIVE and ops_controls.sudo_window_enabled is true.
--
-- Widens one CHECK constraint ('passkey', 'totp') -> ('passkey', 'totp', 'sudo_window'). No row is read, changed or
-- removed; no table, column or grant changes. Idempotent (the constraint is replaced by name each run).
-- Plan (dry run):     psql "$DB" -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--                                    WHERE conname = 'ops_applier_requests_factor_ck'"
-- Apply (operator):   psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_ops_controls_sudo_window.sql
-- Verify (operator):  the plan query above shows 'sudo_window' in the definition.
-- Reverse (operator): migrations/2026_10_22_ops_controls_sudo_window.down.sql

BEGIN;

ALTER TABLE ops_applier_requests DROP CONSTRAINT IF EXISTS ops_applier_requests_factor_ck;
ALTER TABLE ops_applier_requests ADD CONSTRAINT ops_applier_requests_factor_ck
    CHECK (stepup_factor IS NULL OR stepup_factor IN ('passkey', 'totp', 'sudo_window'));

COMMIT;
