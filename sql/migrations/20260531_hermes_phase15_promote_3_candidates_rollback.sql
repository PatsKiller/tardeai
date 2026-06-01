-- Hermes Phase 15 Rollback — Remove 3 promoted candidates
-- Date: 2026-05-31
-- Candidates: FJSCX (id=8), APAM (id=10), TRX (id=11)
-- Run this to undo Phase 15 promotion

BEGIN;

-- Remove from intelligence cache
DELETE FROM llm_intelligence_cache WHERE section IN (
  'hermes_ticker_thesis_challenge_FJSCX',
  'hermes_ticker_thesis_challenge_APAM',
  'hermes_ticker_thesis_challenge_TRX'
);

-- Remove promotion audit records
DELETE FROM hermes_promotion_audit WHERE source_id IN (8, 10, 11);

-- Revert research rows to staged
UPDATE hermes_research_intelligence
SET status = 'staged', promoted_to_table = NULL, promoted_to_id = NULL
WHERE id IN (8, 10, 11);

COMMIT;
