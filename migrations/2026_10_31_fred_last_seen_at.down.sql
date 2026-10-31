-- Down for 2026_10_31_fred_last_seen_at.sql. Never drops data (AGENTS §0 rule 6): the column is renamed aside.
BEGIN;
ALTER TABLE fred_economic_series ALTER COLUMN last_seen_at DROP DEFAULT;
ALTER TABLE fred_economic_series RENAME COLUMN last_seen_at TO last_seen_at_retired_20261031;
COMMIT;
