# Phase 36D — Low-Latency vs Batch Scheduler Recommendation

**Date:** 2026-06-01
**Status:** COMPLETE — design only

---

## Low-Latency Workflows (Need Sub-Minute Response)

| Workflow | Current | Recommended | Reason |
|----------|---------|-------------|--------|
| Quote refresh during market | Cron every 15 min | Cron acceptable / systemd timer | 15-min latency OK for paper |
| Catalyst/news on arrival | Cron every 30 min | Future: PG LISTEN/NOTIFY | Real-time catalyst matters |
| Momentum scout refresh | Cron pre-market | Cron acceptable | Once-daily is fine |
| Research backlog events | Manual | Future: event queue | Librarian should react to new findings |
| Dashboard status updates | API call | Already real-time (API reads DB) | No change needed |

## Batch Workflows (Can Run on Schedule)

| Workflow | Current | Recommended | Frequency |
|----------|---------|-------------|-----------|
| Daily portfolio report | systemd timer | Keep | Daily |
| Weekly review | systemd timer | Keep | Weekly |
| Backup | systemd timer | Keep | Daily |
| Deep LLM analysis | Cron (Friday) | Keep cron | Weekly |
| DB retention cleanup | systemd timer | Keep | Weekly |
| Drive doc sync | Cron hourly | Keep cron | Hourly |
| Hermes observation | systemd timer | Keep | Daily |
| Hermes backlog health | systemd timer | Keep | Daily |
| Hermes autonomous loop | systemd timer | Keep | Daily |

## Recommended Architecture

| Layer | Technology | Use |
|-------|-----------|-----|
| Infrastructure | Docker Compose | SearXNG, future contained services |
| Durable scheduled | systemd user timers | Hermes loops, observation, portfolio |
| Simple recurring | cron | Legacy 140+ jobs pending migration |
| Pipeline batches | Python controller scripts | Screener, agent dispatch, quote refresh |
| Event-driven (future) | PG LISTEN/NOTIFY or Redis | Catalyst arrival, backlog events |

## Not Recommended

- Kubernetes (overkill for single-server)
- External scheduler (Airflow, Prefect — adds operational complexity)
- Message broker (RabbitMQ, Kafka — too heavy)
