-- Phase 54 Rollback
BEGIN;
DROP TABLE IF EXISTS high_llm_job_results;
DROP TABLE IF EXISTS high_llm_job_queue;
COMMIT;
