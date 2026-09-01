# Hermes Phase 1F Rollback SQL

Status:      HISTORICAL
as_of:       2026-05-30T19:38:32-04:00
Measured at: efcc51365 / not measured

**Source:** `docs/hermes/HERMES_PHASE1F_BATCH_RESEARCH_INGESTION_ROLLBACK.sql`

**WARNING:** Rollback only. Do not run without explicit operator approval.

```sql
-- Hermes Phase 1F Rollback: Remove batch research rows
-- Date: 2026-05-30
-- Removes Phase 1F rows (ids 2, 3, 4) from hermes_research_intelligence

DELETE FROM hermes_research_intelligence
WHERE id IN (2, 3, 4)
  AND source = 'hermes'
  AND status = 'staged';
```
