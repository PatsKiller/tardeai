# System

- **Page id:** `system`
- **Route:** `/v3/system`
- **Nav group:** Ops
- **Component:** `apps/command-center-v3/src/pages/SystemHub.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** v001
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

System administration, LLM settings and schedules.

## Data sources

- `/api/v2/admin/accounts`
- `/api/v2/admin/alert/ack`
- `/api/v2/admin/alert/resolve`
- `/api/v2/admin/audit-log`
- `/api/v2/admin/cron-retryable`
- `/api/v2/admin/cron/retry`
- `/api/v2/admin/risk-config`
- `/api/v2/admin/strategy-enablement`
- `/api/v2/admin/strategy/enablement`
- `/api/v2/atm/config`
- `/api/v2/live-trading-gate`
- `/api/v2/llm-health`
- `/api/v2/local-llm-status`
- `/api/v2/risk`
- `/api/v2/system/access-links`
- `/api/v2/system/applications`
- `/api/v2/system/broker-connectors`
- `/api/v2/system/cron-compression`
- `/api/v2/system/pipeline-health`
- `/api/v2/system/queue-control-tower`
- `/api/v2/system/siem`
- `/api/v2/system/youtube-cookies`
- `/api/v2/trade-integrity-audit`

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v001 | APPROVED | 2026-10-24 | Board 16 Jobs & health (embedded) (back-filled from the handoff) |

How to change this page: design/README.md (propose a new version; never edit an approved one).
