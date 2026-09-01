# Phase 68D — Alert-to-Hermes Backlog Design

Status:      HISTORICAL
as_of:       2026-06-01T11:52:54-04:00
Measured at: efcc51365 / not measured

## Mapping

| Alert Type | Backlog Type | Owner |
|-----------|-------------|-------|
| credential_expired | finviz_cookie_expired | hermes_librarian_agent |
| ingestion_failed | finviz_screener_degraded | source_discovery_agent |
| agent_stale (repeated) | agent_staleness_unresolved | hermes_librarian_agent |
| false_fixed | repeated_false_fixed | hermes_librarian_agent |
| model_execution_failed | model_contention_unresolved | hermes_librarian_agent |

## Target

- hermes_research_intelligence
- research_type='ops_backlog'
- advisory_only=true, not_execution=true, operator_review_required=true

## No DB Writes in Phase 68D
