# ADR-006 — Memory is a platform dependency, not a service

Status: PROPOSED (package `cognitive_transformation_20260927`, 2026-09-27) · extends v3.3 §10 (Knowledge brain) and §3 (laws); supersedes nothing.
Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No financial authority is created by this record.

## Context
About 30 memory and research stores exist and nearly all are written hourly, yet memory changed 0 of 22,392 wake decisions, M2 has one reader, and 0 of 586 lessons were promoted (09-27 due diligence §1–§2 `[DOC-CLAIM]`). A `MemoryProvider` contract and factory exist and most readers bypass them `[CODE: agent_memory_provider.py]`. The 09-27 remedy — a Company Intelligence Record read API — makes intelligence available; nothing obliges a caller to use it.

## Decision
1. One façade, `scripts/lib/intelligence_client.py`, is the only import path for memory, research, belief and graph reads and writes. It wraps existing stores; it adds no storage.
2. Every actor opens a `MemoryContext@v1` before acting and commits a `MemoryCommit@v1` after; the façade writes the consumption receipt.
3. Three rings enforce it: a chokepoint linter with a shrink-only baseline; runtime refusal at `gate_and_generate`, `accept_research_result` and `create_cio_action` for work without a `context_id`; a nightly `MemoryCompliance@v1` audit.
4. Decisions and advice fail closed when memory is unreachable (`HOLD_MEMORY_UNAVAILABLE`); monitors run degraded and say so. No actor may substitute a raw store for memory.
5. The unconditional behaviour rail is untouched: memory reaches cognition and advice, never sizing, orders, stops, weights or a broker.

## Consequences
- Adoption is measured, not assumed: read_before_act / write_after_act per lane are published daily and gate promotion (ADR-009, package 05).
- Cost: bounded context open (2 s p95 SLA); the offset is duplicate generation removed (ADR-007).
- Rollback: revert the façade PR and baselines; every silo returns to its present behaviour.

## Rejected alternatives
- Keep the CIR as an optional read API (the present failure mode).
- Merge the nine memory silos into one store (violates §0 rule 5; a migration, not an obligation).
- Enforce only by code review (unmeasurable; regressions were silent for weeks).
