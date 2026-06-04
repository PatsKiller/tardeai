-- admin_write_surface_migration.sql — STEP 1 foundation for the v3 admin/config write surface.
-- Idempotent. Tier-2/3 config/operational writes only; NO Tier-1 (live-execution) control.

-- 1. Append-only audit log — the independent record of every guarded write.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          bigserial PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    operator    text,
    action      text NOT NULL,
    target      text,
    old_value   jsonb,                 -- IRON-RULE backup: the value before the write
    new_value   jsonb,
    result      text NOT NULL,         -- applied | failed | rejected
    detail      text
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_ts ON admin_audit_log(ts DESC);

-- Append-only enforced by TRIGGER (works even for the table owner, unlike REVOKE FROM PUBLIC).
CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'admin_audit_log is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_admin_audit_append_only ON admin_audit_log;
CREATE TRIGGER trg_admin_audit_append_only
    BEFORE UPDATE OR DELETE ON admin_audit_log
    FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only();

-- 2. Alert lifecycle (no ack/resolve state existed) — for the SIEM ack/resolve action.
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS lifecycle_state text DEFAULT 'active';
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS acknowledged_at timestamptz;
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS acknowledged_by text;
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS resolved_by text;
ALTER TABLE system_health_events ADD COLUMN IF NOT EXISTS lifecycle_state text DEFAULT 'active';
ALTER TABLE system_health_events ADD COLUMN IF NOT EXISTS acknowledged_at timestamptz;
ALTER TABLE system_health_events ADD COLUMN IF NOT EXISTS acknowledged_by text;
ALTER TABLE system_health_events ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE system_health_events ADD COLUMN IF NOT EXISTS resolved_by text;
