-- Down migration for 2026_11_09_market_event_lifecycle.sql — DROP only the one table that migration created.
-- Never run against a database whose market_event_lifecycle holds transitions that were never mirrored to a
-- runtime JSON: export them first (AGENTS.md rail 6, never delete). This file exists so a failed release can be
-- unwound before any transition exists.
BEGIN;
DROP TABLE IF EXISTS market_event_lifecycle;
COMMIT;
