# Phase 209B — v3 Hermes Graph Node Inventory (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:28:03-04:00
Measured at: efcc51365 / not measured

Source: HermesHub.tsx `HERMES_AGENTS` (graph) + `/api/v2/hermes/infra` (live health) + owner matrix (209C).
Script: `scripts/audit_hermes_workflow_owners.py`; data: `data/hermes/hermes_graph_node_inventory_latest.json`.

| Node | Owner (script/trigger) | DB | Clickable in v3 |
|------|------------------------|----|-----------------|
| Chief Hermes Coordinator | hermes_coordinator.py (cron */15) | hermes_memory_events | yes (node drawer) |
| Source Discovery | hermes_scheduled_source_discovery_dryrun.py (timer) | hermes_research_intelligence (staged) | yes |
| Hermes Librarian | hermes_autonomous_librarian_backlog_loop.py (timer) | hermes_research_intelligence (status) | yes |
| Embedding Curator | hermes_embedding_promotion_reviewer.py (timer) | hermes_embedding_queue | yes |
| Promotion Review | hermes_embedding_promotion_reviewer.py (timer) | hermes_promotion_audit (advisory) | yes |
| Research Backlog Manager | hermes_backlog_health_check.py (timer) | hermes_research_intelligence (backlog-tagged) | yes |
| Autonomous Research Manager | hermes_autonomous_loop.py (timer) | hermes_research_intelligence (staged) | yes |
| SearXNG | docker :18888 | n/a (search) | infra strip |
| TradeAI safe views | read-only WALL (13 hermes_v_*/safe views) | inputs only | n/a |

All nodes back to live systemd-timer jobs (project .venv + scripts/), not the retired sidecar. SearXNG UP.
