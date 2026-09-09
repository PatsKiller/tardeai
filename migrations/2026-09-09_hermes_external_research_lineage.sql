-- 2026-09-09_hermes_external_research_lineage.sql
-- Curation lineage: every new hermes_external_research row is a versioned, GUID-linked curation.
--   research_guid       stable UUID for THIS row (new on every insert)
--   prior_research_guid research_guid of the immediately prior (symbol, lane) curation, when present
--
-- ADDITIVE ONLY. No DROP / rename / destructive DDL.
-- READ_ONLY_ADVISORY relative to broker/order/stop/proposal paths.

BEGIN;

ALTER TABLE hermes_external_research
    ADD COLUMN IF NOT EXISTS research_guid uuid;

ALTER TABLE hermes_external_research
    ADD COLUMN IF NOT EXISTS prior_research_guid uuid;

COMMENT ON COLUMN hermes_external_research.research_guid IS
  'stable UUID for this curation row (new on every insert).';
COMMENT ON COLUMN hermes_external_research.prior_research_guid IS
  'research_guid of the immediately prior (symbol, lane) curation; NULL on first curation.';

CREATE INDEX IF NOT EXISTS idx_hermes_external_research_research_guid
    ON hermes_external_research (research_guid);

CREATE INDEX IF NOT EXISTS idx_hermes_external_research_prior_guid
    ON hermes_external_research (prior_research_guid);

COMMIT;
