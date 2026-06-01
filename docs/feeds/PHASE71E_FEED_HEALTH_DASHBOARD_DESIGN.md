# Phase 71E — Feed Health Dashboard Design

**Status:** DESIGN ONLY

## Proposed Card: "Data Feed Health"

| Field | Source |
|-------|--------|
| Finviz status | HEALTHY / DEGRADED / DOWN |
| Cookie age | days since FINVIZ_COOKIE_SET_DATE |
| Last successful screener | screener_run_health max(created_at) WHERE status='RUN_HEALTHY' |
| Failure streak | consecutive RUN_FAILED count |
| News pipeline | last news_articles insert timestamp |
| Catalyst pipeline | last catalyst_events insert timestamp |

No action buttons. Read-only.
