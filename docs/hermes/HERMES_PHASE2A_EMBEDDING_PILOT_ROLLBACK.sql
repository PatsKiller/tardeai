-- Hermes Phase 2A Rollback: Remove pilot embeddings
-- Date: 2026-05-30

-- Remove from content_embeddings
DELETE FROM content_embeddings
WHERE source_type = 'hermes_research'
  AND source_id IN (1, 5)
  AND id IN (26858, 26859);

-- Reset queue status
UPDATE hermes_embedding_queue
SET embedding_status = 'pending', embedded_id = NULL, embedded_at = NULL
WHERE id IN (1, 2)
  AND source = 'hermes';
