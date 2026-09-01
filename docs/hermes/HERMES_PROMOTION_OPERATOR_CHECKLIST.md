# Hermes Promotion Operator Checklist

Status:      ACTIVE
as_of:       2026-05-31T16:29:03-04:00
Measured at: efcc51365 / not measured

Use before every promotion batch.

## Pre-Promotion

- [ ] Identify candidate rows (status=staged, confidence >= 0.3)
- [ ] Exclude TELO id=9 (confidence 0.2)
- [ ] Exclude smoke/test rows
- [ ] Verify no duplicates against already-promoted sections
- [ ] Create rollback SQL BEFORE applying
- [ ] Run dry-run first

## During Promotion

- [ ] Promote only to llm_intelligence_cache (hermes_* sections)
- [ ] Max 4 rows per batch
- [ ] All content prefixed "[Hermes Advisory — Not Execution]"
- [ ] All metadata includes source=hermes, source_id, confidence
- [ ] Write hermes_promotion_audit records
- [ ] Update source row status to 'promoted'

## Post-Promotion

- [ ] Verify inserted cache row count matches expected
- [ ] Verify audit record count matches
- [ ] Verify no forbidden tables touched
- [ ] Verify paper_trades/proposals unchanged
- [ ] Verify dashboard shows new promoted rows
- [ ] Save rollback SQL to docs/hermes/

## Rollback (if needed)

- [ ] DELETE promoted sections from llm_intelligence_cache
- [ ] UPDATE source rows back to status='staged'
- [ ] DELETE audit records
