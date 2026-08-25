# M2 production shadow migration — DESIGN ONLY

**Date:** 2026-08-24  
**Status:** SOURCE/DESIGN + **ISOLATED IMPLEMENTATION TESTED** (`:55432`). Production `:5432` **not executed.** `production_executed=false`  
**Authorized only after CIO L5 natural proof (2026-08-24 23:17 ET material_scan SCHD).**  
**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`

Architectural winner remains `POSTGRES_PGVECTOR` (`provisional=false`). This document does **not** apply SQL to production `:5432`, does **not** enable a dual writer, does **not** retire JSONL, and does **not** let CIO read the shadow.

## Authority model

Canonical stores stay sole authority:

- `ticker_research_state.jsonl`
- `hermes_curation_summary.jsonl`
- `ticker_research_graph.jsonl`
- `cio_theses.jsonl` / SymbolThesis
- AIF memory JSONL (classified, not deleted)

Shadow: one-way idempotent projection into isolated-then-production-adjacent Postgres/pgvector `MemoryFact@v2`.

Shadow can be destroyed and rebuilt. It has **zero** authority.

## Projection contract

Each shadow row must carry:

| field | purpose |
|---|---|
| source_event_id | originating JSONL line / fact id |
| source_sha | SOURCE_COMMIT of projector |
| security_guid / identity kind | ticker is alias |
| tenant_id | composite FK |
| projection_version | projector schema |
| idempotency_key | `(tenant, source_event_id, projection_version)` |

Replay is insert-or-skip. Never update canonical JSONL.

## Sequence (future program — not this session)

1. Isolated schema already proven (`sql/r10_m2_isolated_benchmark.sql` on `:55432`).
2. Projector dry-run against a copy of JSONL → isolated DB.
3. 100% projected-row accounting.
4. Zero canonical-source mutation (byte/SHA of JSONL before/after).
5. Zero duplicate shadow versions (exclusion + idempotency key).
6. Point-in-time parity for a held set (SCHD/SCHG/NOC/CSCO/ANET).
7. security_guid parity (PRSO remains unresolved until identity program).
8. Tenant isolation after restore.
9. Rebuild from zero.
10. Backup/restore (isolated dump already PASS).
11. Rollback = stop projection / `DROP SCHEMA` shadow. Canonical untouched.
12. Dark read comparison (CIO still reads JSONL).
13. Separate gate before any CIO consumption from shadow.

## Rollback

Rollback is **not** a reverse ETL. Discard shadow. Canonical JSONL remains.

## Explicitly forbidden until a later gate

- Production `r10_memory_shadow.sql` apply
- Dual authoritative writers
- CIO/Advisory/Telegram reading M2 as truth
- JSONL retirement
- Agent BYPASSRLS / owner writes
