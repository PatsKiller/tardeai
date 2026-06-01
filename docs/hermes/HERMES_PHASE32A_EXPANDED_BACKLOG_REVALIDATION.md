# Hermes Phase 32A — Expanded Backlog Candidate Revalidation

**Date:** 2026-06-01
**Status:** COMPLETE — 5 candidates selected (de-duplicated from 11)

---

## De-duplication

The Phase 30 dry-run produced 11 raw candidates, but several are duplicates (4 × BT-5 n=1 items). Per Phase 30D mapping, the n=1 items should be consolidated into a single "insufficient backtest samples" row.

## Selected Candidates (5, de-duplicated)

| # | Title | Source Surface | Priority | Check |
|---|-------|---------------|----------|-------|
| 1 | Journal learning system empty — thesis reviews not generated | journal | medium | JRN-ALL |
| 2 | momentum_scalp 30% win rate across 20 trades | backtest | high | BT-1 |
| 3 | all_signals aggregate 33.9% win rate across 59 trades | backtest | high | BT-1 |
| 4 | Multiple strategies with insufficient backtest samples (n≤2) | backtest | low | BT-5 (consolidated) |
| 5 | Generic catalyst classification gap — 25+ events typed 'other' | catalyst | medium | CAT-2 |

## Duplicate Check Against Existing Backlog

| Candidate | Existing Backlog Match? |
|-----------|----------------------|
| Journal empty | NO — no existing backlog covers journal |
| momentum_scalp 30% WR | NO — no existing backlog covers strategy WR |
| all_signals 33.9% WR | NO — no existing backlog covers aggregate WR |
| Insufficient samples | NO — no existing backlog covers sample warnings |
| Generic catalysts | NO — no existing backlog covers catalyst classification |

Zero duplicates with existing backlog rows (ids 19–23).

## Validation Checks

| Check | Result |
|-------|--------|
| Trade instructions | ZERO |
| Broker/proposal/journal mutation language | ZERO |
| Clear research question | YES (all 5) |
| Clear source finding | YES (all from Phase 30B) |
| owner_agent set | YES |
| priority set | YES |
| advisory_only | YES |
| not_execution | YES |
| operator_review_required | YES |

## Rollback Plan

```sql
DELETE FROM hermes_research_intelligence
WHERE research_type = 'research_backlog'
  AND hermes_agent_name = 'expanded_librarian_agent'
  AND tags @> ARRAY['phase_32B'];
```
