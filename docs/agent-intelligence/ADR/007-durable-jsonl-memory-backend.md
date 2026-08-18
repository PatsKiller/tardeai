# ADR-007 — Durable JSONL as the Program 3 memory backend

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

Program 3 requires durable governed memory that survives process restart,
portfolio-server restart, CURRENT flip, and host reboot. The memory contract
already exists (`MemoryProvider`, `MemoryRecord@v1`). Hosted memory SaaS is
forbidden. A new database product is not justified merely by fashion.

Inspection of the live host:

- PostgreSQL 17 is local, but **pgvector is not installed**.
- The `mem0` package is **not installed**.
- Shared `data/cio` is already the governed runtime root (lessons, promotions,
  reflection) and is a CURRENT symlink — it survives release flips.

## Decision

Use **`DurableJsonlMemoryProvider`** on shared `data/cio/aif_memory.jsonl`.

Do not force Mem0. Do not install pgvector solely for this program. Do not
egress operator/financial memory.

Ranking is lexical + confidence + recency. Vector search can be added later
behind the same `MemoryProvider` contract if a locally controlled vector
capability becomes operational.

`ACTIVE` remains the stored admission status for explicit/case/commitment
types. Command Center displays `ADMITTED` via a mapping. Historical statuses
are not rewritten.

## Consequences

- Memory is durable and locally controlled.
- Memory remains `NON_AUTHORITATIVE_CONTEXT`.
- `MEMORY_BEHAVIOR_INFLUENCE` stays `0`.
- SHADOW comparator records retrievals without changing production behavior.
- Rollback is `MEMORY_PROVIDER=null`; the JSONL is retained as evidence.
