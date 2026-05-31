-- Phase 2C Rollback: Remove 5 remaining embeddings
DELETE FROM content_embeddings WHERE source_type='hermes_research' AND source_id IN (2,3,4,6,7) AND id IN (26885,26886,26887,26888,26889);
UPDATE hermes_embedding_queue SET embedding_status='pending', embedded_id=NULL, embedded_at=NULL WHERE id IN (3,4,5,6,7) AND source='hermes';
