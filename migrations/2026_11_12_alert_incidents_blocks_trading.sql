-- LQ-20261107-2145/2146 (Home v010 backend W0): an incident may override its class default for "blocks trading".
-- NULL = use the class default from the Home status registry. Nullable, no default: catalog-only, no table rewrite.
-- Apply off-hours: psql -f; capture \d alert_incidents BEFORE and AFTER.
SET lock_timeout = '3s';
ALTER TABLE alert_incidents ADD COLUMN IF NOT EXISTS blocks_trading BOOLEAN;
