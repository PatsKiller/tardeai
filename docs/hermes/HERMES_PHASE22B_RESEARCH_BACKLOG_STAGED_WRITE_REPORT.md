# Hermes Phase 22B — Research Backlog Staged-Write Report

**Date:** 2026-06-01
**Status:** COMPLETE — 5 rows staged

## Inserted Rows

| ID | Symbol | Title | Priority | Source |
|----|--------|-------|----------|--------|
| 19 | SYSTEM | Income-rotation candidates for $40,519 gap | medium | Telegram weekly review |
| 20 | TELO | Strengthen TELO thesis or reject | medium | Librarian BKL-1 (id=9) |
| 21 | APAM | Enrich APAM source discovery with earnings | low | Librarian BKL-1 (id=14) |
| 22 | FJSCX | Enrich FJSCX source discovery with holdings | low | Librarian BKL-1 (id=15) |
| 23 | SYSTEM | Validate Telegram actionability standard | medium | Phase 20E gate |

## Target Table

`hermes_research_intelligence` with `research_type='research_backlog'`, `hermes_agent_name='research_backlog_manager'`

## Post-Write State

| Metric | Before | After |
|--------|--------|-------|
| Total rows | 18 | 23 |
| Staged | 8 | 13 |
| Promoted | 10 | 10 (unchanged) |
| research_backlog type | 0 | 5 |
| Embeddings | 7 | 7 (unchanged) |
| Cache sections | 10 | 10 (unchanged) |

## Safety

- [x] Exactly 5 rows inserted (at cap)
- [x] All status='staged'
- [x] All research_type='research_backlog'
- [x] All advisory_only=true in evidence_json
- [x] All not_execution=true in evidence_json
- [x] All operator_review_required=true in evidence_json
- [x] No production writes
- [x] No embeddings
- [x] No promotions
- [x] Rollback SQL ready

## Rollback

```bash
PGPASSWORD='...' psql -h localhost -U trade_ai -d trade_ai -f docs/hermes/HERMES_PHASE22B_RESEARCH_BACKLOG_STAGED_WRITE_ROLLBACK.sql
```
