# Phase 208E — Live Hermes Research Fleet Health (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T11:30:00-04:00
Measured at: efcc51365 / not measured

Script: `scripts/audit_hermes_live_fleet_health.py` → `data/hermes/hermes_live_fleet_health_latest.json` (read-only).

## Fleet data flow (DB-backed, live)
- hermes_research_intelligence: **1958 rows**; last write **2026-06-07 11:15 EDT**; **476 writes/24h, 1947/7d**; 190 trade_instance-linked.
- Supporting tables present: hermes_alerts, hermes_validation_findings, hermes_memory_events, hermes_embedding_queue.

## Timer health — ALL 9 last result = success
hermes-autonomous-loop · source-discovery-dryrun · librarian-backlog-loop · embedding-promotion-review ·
backlog-health-check · shadow-scorer · observation-check · advisory-cache-worker · momentum-catalyst-morning.

## Per-agent (graph → runtime)
| Agent | Runner | Status |
|-------|--------|--------|
| Chief Hermes Coordinator | cron */15 + hermes_coordinator.py | live (orchestration) |
| Source Discovery | hermes-source-discovery-dryrun.timer | success; stages candidates via SearXNG (UP) |
| Hermes Librarian | hermes-librarian-backlog-loop.timer | success; status updates |
| Embedding Curator / Promotion Review | hermes-embedding-promotion-review.timer | success; advisory/staging |
| Research Backlog Manager | hermes-backlog-health-check.timer | success |
| Autonomous Research Manager | hermes-autonomous-loop.timer (ticker_challenger) | success; staged writes |
| SearXNG | docker :18888 | UP (HTTP health) |
| TradeAI safe views | read-only inputs | the WALL — no core mutation |

## Conclusions
- Live fleet is **functioning properly** — writing continuously (476/24h), all timers succeeding.
- Uses active runtime (project .venv + scripts/hermes_*.py + Ollama gemma3). Retired sidecar irrelevant.
- v3 graph counts reconcile with DB activity (research rows growing; SearXNG up).
