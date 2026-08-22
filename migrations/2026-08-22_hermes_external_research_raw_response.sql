-- 2026-08-22_hermes_external_research_raw_response.sql
-- P1 write-path: always-on raw store for governed external research.
-- Parser slices (recommendation/dissent/learning_candidate/operator_action) are no longer the only copy.
--
-- ADDITIVE ONLY. No DROP / rename / destructive DDL.
-- READ_ONLY_ADVISORY relative to broker/order/stop/proposal paths.

BEGIN;

ALTER TABLE hermes_external_research
    ADD COLUMN IF NOT EXISTS raw_response TEXT;

COMMENT ON COLUMN hermes_external_research.raw_response IS
  'always-on raw store; parser slices no longer the only copy.';

COMMIT;
