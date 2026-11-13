SET lock_timeout = '3s';
ALTER TABLE alert_incidents DROP COLUMN IF EXISTS blocks_trading;
