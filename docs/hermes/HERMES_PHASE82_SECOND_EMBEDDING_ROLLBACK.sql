-- Phase 82 Rollback
BEGIN;
DELETE FROM content_embeddings WHERE source_type='hermes_research' AND source_id IN (17, 18, 16);
DELETE FROM hermes_embedding_queue WHERE source_research_id IN (17, 18, 16) AND source='hermes';
COMMIT;
