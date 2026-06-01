# Phase 50A — Level 5 State Inventory

**Date:** 2026-06-01
**Status:** COMPLETE

## Hermes Timers (5)

| Timer | Schedule | Status |
|-------|----------|--------|
| hermes-autonomous-loop | 01:00 UTC | active |
| hermes-observation-check | 06:30 UTC | active (ran overnight) |
| hermes-backlog-health-check | 06:45 UTC | active (ran overnight) |
| hermes-source-discovery-dryrun | 07:15 UTC | active (first auto-run pending) |
| hermes-librarian-backlog-loop | 07:45 UTC | active (first auto-run pending) |

## Hermes Tables

| Table | Rows | Purpose |
|-------|------|---------|
| hermes_research_intelligence | 34 | Research staging (10 promoted, 24 staged, 13 backlog) |
| hermes_advisory_events | 7 | Event queue (7 pending, 0 completed) |
| hermes_embedding_queue | 9 | Embedding queue (9 completed) |
| hermes_validation_findings | 6 | Pipeline quality findings |
| hermes_promotion_audit | 10 | Promotion audit trail |
| hermes_memory_events | ~1 | Smoke/coordinator logs |
| hermes_alerts | 0 | Reserved |
| content_embeddings (hermes) | 9 | RAG embeddings |
| llm_intelligence_cache (hermes) | 10 | Promoted advisory sections |

## Kill Switch Files

- hermes_sidecar/.hermes/DISABLED — global kill
- hermes_sidecar/.hermes/LIBRARIAN_DISABLED — librarian-specific kill

## Rollback Files (7)

All present in docs/hermes/ or sql/migrations/.

## Dashboard Visibility

- Hermes Intelligence page: rows, backlog, pipeline, promotion review
- Research Backlog card: 10+ items with priorities
- System Applications: SearXNG, Docker, scheduled jobs
- Scheduled Jobs card: timer status, cron count, health timestamps
