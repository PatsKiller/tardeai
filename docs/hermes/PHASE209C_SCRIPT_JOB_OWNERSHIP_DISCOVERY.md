# Phase 209C — Script/Job Ownership Discovery (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:28:03-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_workflow_owners.py` → `data/hermes/hermes_workflow_owner_matrix_latest.json`.

## Summary
- Workflows mapped: **19** (9 hermes systemd timers + cron lines + helpers).
- **No job uses the tradeai/tradeai12b CLI profiles** (`any_cli_profile_in_jobs = false`) — fleet scripts
  call Ollama directly, not via chat profiles. → tradeai12b is NOT used by automation.
- Writers to Hermes staging: hermes_research_intelligence, hermes_memory_events, hermes_promotion_audit.

## Owners (systemd timers → scripts)
| Workflow | Owner script | Trigger |
|----------|-------------|---------|
| advisory-cache-worker | hermes_advisory_cache_worker.py | timer |
| autonomous-loop (ticker challenge) | hermes_autonomous_loop.py | timer |
| backlog-health-check | hermes_backlog_health_check.py | timer |
| embedding-promotion-review | hermes_embedding_promotion_reviewer.py | timer |
| librarian-backlog-loop | hermes_autonomous_librarian_backlog_loop.py | timer |
| momentum-catalyst-morning | hermes_momentum_catalyst_researcher.py | timer |
| observation-check | hermes_observation_check.py | timer |
| shadow-scorer | strategy_learning_shadow_scorer.py | timer |
| source-discovery-dryrun | hermes_scheduled_source_discovery_dryrun.py | timer |
| coordinator | hermes_coordinator.py | cron */15 |
| gateway | (disabled unit — no owner; not a workflow) | n/a |

All standalone Python (project .venv); none use the global chat profiles. Most write via the shared
hermes_staging_ingest module (so direct INSERT grep undercounts some writers; DB lineage in 209D is authoritative).
