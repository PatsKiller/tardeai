# Phase 91B — Drill-Through UX Architecture

Status:      HISTORICAL
as_of:       2026-06-01T13:50:58-04:00
Measured at: efcc51365 / not measured

## Drill-Through Map

| Source | Click Action | Target View | Filters |
|--------|-------------|-------------|---------|
| Hermes Rows card | Click count | Full row list | status=all |
| Staged card | Click count | Row list | status=staged |
| Promoted card | Click count | Row list | status=promoted |
| Backlog card | Click count | Row list | type=research_backlog |
| Embeddings card | Click count | Embedded row list | embedded=true |
| Cache card | Click count | Cache section list | — |
| LLM Queue card | Click count | Queue job list | — |
| Events card | Click count | Event list | — |
| Promotion lane | Click lane | Candidate cards in lane | lane=X |
| Candidate card | Click card | Detail drawer | id=X |
| Agent name | Click agent | Agent activity/rows | agent=X |
| Age bucket | Click bucket | Rows in age range | age=X |
| Level 7 badge | Not clickable | — | — |

## Detail Drawer Fields

- ID, symbol, topic, research_type
- Source agent, last touched
- Evidence score, freshness, actionability
- Duplicate risk, execution contamination
- Source URLs, cache target
- Embedding status, promotion status
- Lane assignment, reason codes
- Lineage: who created → who reviewed → current state
- No action buttons
