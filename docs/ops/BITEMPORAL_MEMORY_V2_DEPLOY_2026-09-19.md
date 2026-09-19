# Bitemporal Memory Substrate v2 — deploy receipt

Status: ACTIVE (isolated only)
as_of: 2026-09-19T17:40:00Z
Measured at: worktree cursor/aec-rail-full-667c + Docker tradeai-m2-shadow-v2 :55432
Canonical repo path: sql/trade-ai-bitemporal-schema-v2.sql
Authority: READ_ONLY_ADVISORY / MBI_BEHAVIOR=0
Supersedes: none (packages existing sql/r10_m2_isolated_benchmark.sql)
See also: docs/ops/TRADE_AI_M2_MEMORY_SUBSTRATE_BENCHMARK_2026-08-24.md, AGENTS.md §7 identity spine

## Deploy (isolated — production :5432 refused)

- Container: `tradeai-m2-shadow-v2` (pgvector/pgvector:pg16) on `127.0.0.1:55432`
- Applied: `sql/r10_m2_isolated_benchmark.sql` + `sql/trade-ai-bitemporal-schema-v2.sql`
- Verified tables/views: MemoryIdentity@v1, MemoryFactVersion@v2, AdjudicationReceipt@v1, ProvenanceEdge@v1
- Verified functions: `save_bitemporal_fact_version` (alias), `write_fact_version`, `block_bitemporal_manipulation`, `trg_block_fact_manipulation`
- Verified exclusion: `fact_single_valued_current_excl` (GiST, CURRENT + SINGLE_VALUED_CURRENT)
- `production_sql_applied`: **false**

## Integration

- `scripts/lib/cio_memory_integration.py` — `CIOEnvelopeIntegrator`
- CLI: `scripts/cio_memory_integration.py --dry-run|--apply|--apply-schema`
- Package path: `trade_ai.memory` re-exports (no duplicate writer)
- AEC cycle dry-runs cognitive envelope on every cycle (apply=False)

## Correctness

- `tests/test_bitemporal_correctness.py`: **211 passed**
  - 200-case in-process oracle
  - a–e Docker categories (exclusion, multi-valued, version closure, RLS via m2_agent, audit immutability)
- EXPLAIN (ANALYZE, BUFFERS): **Index Scan** on `fact_valid_spgist` (not Seq Scan); Shared Hit Blocks; 0 disk reads

## Constitutional rails observed

- Financial keys refused (`FINANCIAL_TRUTH_REFUSED`)
- GUID spine linkage on identity rows
- DB-owned `tx_period` via SECURITY DEFINER writer
- Composite `(tenant_id, guid)` + FORCE RLS (proven as non-superuser `m2_agent`)
