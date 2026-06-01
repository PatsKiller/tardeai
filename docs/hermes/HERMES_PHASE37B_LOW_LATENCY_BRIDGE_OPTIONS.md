# Hermes Phase 37B — Low-Latency Bridge Options Analysis

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Options Compared

### 1. PostgreSQL LISTEN/NOTIFY

| Dimension | Value |
|-----------|-------|
| Latency | <1 sec |
| Complexity | LOW — built into PG, no external deps |
| Safety | HIGH — no data in notification payload, just channel+id |
| Rollback | Remove trigger, stop listener |
| Observability | LOW — no built-in queue depth, missed notifications not recoverable |
| Failure mode | Missed if listener disconnected (PG drops notifications) |
| Duplicate handling | Listener must be idempotent |
| Fit for Hermes | GOOD — but needs queue table fallback for missed events |

### 2. Dedicated Queue Table (hermes_advisory_events)

| Dimension | Value |
|-----------|-------|
| Latency | 1–5 sec (polling) or <1 sec (with LISTEN/NOTIFY trigger) |
| Complexity | LOW — simple table + poll or trigger |
| Safety | HIGH — full audit trail, replayable |
| Rollback | DELETE from queue, disable worker |
| Observability | HIGH — queue depth, processed count, latency visible in DB |
| Failure mode | Recoverable — unprocessed events remain in queue |
| Duplicate handling | Built-in via status column + source_id unique constraint |
| Fit for Hermes | **BEST** — durable, auditable, recoverable |

### 3. Lightweight Event Bus Table

Same as #2 but thinner schema. Essentially the same recommendation.

### 4. Systemd Path/Timer Hybrid

| Dimension | Value |
|-----------|-------|
| Latency | 1–5 sec (path watch) |
| Complexity | MEDIUM — file-based signaling |
| Safety | HIGH |
| Rollback | Disable path unit |
| Observability | LOW — file-based, no queue depth |
| Failure mode | File watch can miss rapid changes |
| Fit for Hermes | ACCEPTABLE but fragile for DB events |

### 5. Dashboard Polling (Short Interval)

| Dimension | Value |
|-----------|-------|
| Latency | Polling interval (currently on-demand) |
| Complexity | NONE — already exists |
| Safety | HIGH |
| Rollback | N/A |
| Observability | N/A |
| Failure mode | N/A |
| Fit for Hermes | Already works for dashboard, doesn't solve pipeline gap |

### 6. Pipeline Controller Hook

| Dimension | Value |
|-----------|-------|
| Latency | Variable (when pipeline runs) |
| Complexity | MEDIUM — modify existing pipeline |
| Safety | MEDIUM — changes existing code |
| Fit for Hermes | LOW priority — pipelines run on cron schedules |

---

## Recommendation Matrix

| Option | Latency | Durability | Observability | Complexity | **Recommended** |
|--------|---------|-----------|--------------|-----------|:---:|
| Queue table + LISTEN/NOTIFY | <1 sec | HIGH | HIGH | LOW | **YES** |
| Queue table only (polling) | 1–5 sec | HIGH | HIGH | LOW | Fallback |
| LISTEN/NOTIFY only | <1 sec | LOW | LOW | LOW | NO (missed events) |
| Systemd path | 1–5 sec | MEDIUM | LOW | MEDIUM | NO |
| Dashboard polling | On-demand | N/A | N/A | NONE | Already exists |
| Pipeline hook | Variable | LOW | LOW | MEDIUM | NO |

**Winner: Queue table + optional LISTEN/NOTIFY trigger**
