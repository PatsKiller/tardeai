# ADR-007 — Retrieval before generation: research is never done twice

Status: PROPOSED (package `cognitive_transformation_20260927`, 2026-09-27) · extends v3.3 §12 and 09-27 §11; supersedes nothing.
Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.

## Context
Research is produced by seven producers; 61 symbols sat in ≥ 4 stores in 7 days; the same question goes to 2–3 lanes without reconciliation; the governed producer re-fetched one name's pages 180 times in 72 h (09-27 §3, §10 `[DOC-CLAIM]`). Pre-generation lookups exist but are local to one producer each and keyed differently `[CODE]`; the external lanes have none.

## Decision
1. `intelligence_client.retrieve_or_generate` runs a seven-step ladder — deterministic key, thesis, evidence, contradiction, citation, version, semantic — before any research-class generation, and writes a `RetrievalReceipt@v1`.
2. `gate_and_generate` refuses a research-class call without a receipt; `accept_research_result` refuses a delta without one.
3. HIT_FRESH answers from the record; HIT_STALE/PARTIAL generate a delta prompt referencing the current version; MISS generates with the ladder as evidence of the miss. A semantic hit alone is never HIT_FRESH.
4. Every source URL becomes an evidence node with a per-day extraction; a contradiction hit forces a two-sided prompt or routes to adjudication.
5. The measure is the duplicate generation rate from receipts, with a named residual; the path is shadow → enforced → refresh → semantic (package 03 §7).

## Consequences
- The six non-Hermes producers need adapters (an operator DSA item each).
- Semantic lookup needs a local embedding model; pgvector is already on production.
- Cost per useful answer falls; the effect is measured monthly from the consumption log, not asserted.

## Rejected alternatives
- One write path only (stops divergence, not duplication).
- Semantic-first retrieval (false hits become false answers).
- A shared cache per producer (seven caches, seven keys — the present state).
