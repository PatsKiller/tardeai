-- Hermes Phase 31 Rollback — Remove pilot embeddings for SCHD id=12 and TRX id=13
-- Date: 2026-06-01

BEGIN;

-- Remove from content_embeddings
DELETE FROM content_embeddings
WHERE source_type = 'hermes_research'
  AND source_id IN (12, 13);

-- Remove from embedding queue
DELETE FROM hermes_embedding_queue
WHERE source_research_id IN (12, 13)
  AND source = 'hermes';

COMMIT;
