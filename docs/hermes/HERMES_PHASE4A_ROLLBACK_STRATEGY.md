# Phase 4A Rollback Strategy

Status:      HISTORICAL
as_of:       2026-05-31T09:56:33-04:00
Measured at: efcc51365 / not measured

## Phase 4A: No rollback needed
No DB writes occurred. Dry-run outputs are in docs/hermes/phase4a_dryrun/ only.

## Future Phase 4B+ Rollback

```sql
-- Delete promoted rows from llm_intelligence_cache
DELETE FROM llm_intelligence_cache WHERE section LIKE 'hermes_%';

-- Reset source rows to staged
UPDATE hermes_research_intelligence SET status='staged', promoted_to_table=NULL, promoted_to_id=NULL
WHERE status='promoted';

-- Delete promotion audit records
DELETE FROM hermes_promotion_audit WHERE source_table='hermes_research_intelligence';
```
