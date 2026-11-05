-- OPERATOR REVIEW/APPLY ONLY (AGENTS §17): existing store fred_economic_series, no new authority or writer.
-- Review of #2383, N5. fetched_at stays the FIRST time an observation was seen (look-ahead-safe replays, review of
-- #2362 M1). last_seen_at is the freshness signal: the FRED ingest sets it on every upsert, and health_agent,
-- the api_v2 FRED feed card and the runbook read it. Idempotent; never run from a lane or a test.
BEGIN;
ALTER TABLE fred_economic_series ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
UPDATE fred_economic_series SET last_seen_at = fetched_at WHERE last_seen_at IS NULL;
ALTER TABLE fred_economic_series ALTER COLUMN last_seen_at SET DEFAULT now();
COMMIT;
