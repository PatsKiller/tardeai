# Hermes Phase 22A — Research Backlog Target Revalidation

**Date:** 2026-06-01
**Status:** COMPLETE — hermes_research_intelligence fits with research_type='research_backlog'

---

## Table Assessment

| Option | Table | Fit? | Decision |
|--------|-------|------|----------|
| 1 | Existing backlog table | Does not exist | N/A |
| 2 | hermes_research_intelligence | YES with constraints | SELECTED |
| 3 | Future hermes_research_backlog | Deferred | Not needed for 5-row pilot |

## Why hermes_research_intelligence Fits

- `research_type='research_backlog'` is a new type — cleanly separable from existing types (`ticker_thesis_challenge`, `source_discovery`, etc.)
- `status='staged'` fits — backlog items are staged work awaiting research
- `hermes_agent_name='research_backlog_manager'` identifies the owner agent
- `tags` array carries backlog metadata (priority, owner, finding source)
- `evidence_json` holds structured research questions and candidate buckets
- `source='hermes'` satisfies CHECK constraint
- No schema changes needed
- Rollback is clean: `DELETE WHERE research_type='research_backlog'`

## Status Constraint Note

The CHECK constraint allows: staged, reviewed, promoted, rejected, archived. For backlog lifecycle:
- `staged` = needs_research (initial state)
- `reviewed` = research completed, awaiting curation
- `rejected` = research not justified
- `archived` = research completed and used

This maps cleanly without schema modification.

---

## Selected Backlog Items (5 max)

| # | Title | Symbol | Source | Priority |
|---|-------|--------|--------|----------|
| 1 | Research income-rotation candidates for $40,519 gap | SYSTEM | Telegram weekly review | medium |
| 2 | Strengthen TELO thesis or reject | TELO | Librarian BKL-1 (id=9) | medium |
| 3 | Enrich APAM source discovery with earnings detail | APAM | Librarian BKL-1 (id=14) | low |
| 4 | Enrich FJSCX source discovery with holdings analysis | FJSCX | Librarian BKL-1 (id=15) | low |
| 5 | Validate Telegram income-shift actionability | SYSTEM | Phase 20E actionability gate | medium |

## Rollback Plan

```sql
DELETE FROM hermes_research_intelligence
WHERE research_type = 'research_backlog'
  AND hermes_agent_name = 'research_backlog_manager';
```
