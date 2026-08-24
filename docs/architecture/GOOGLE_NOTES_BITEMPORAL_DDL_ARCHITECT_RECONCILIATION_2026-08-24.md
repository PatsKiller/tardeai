# Google Notes bitemporal DDL — architect reconciliation

**Date:** 2026-08-24  
**Status:** DESIGNED + TESTED isolated. Not applied to production.  
**Authority:** `READ_ONLY_ADVISORY`

Google Notes DDL is **design input only**. Isolated schema: `sql/r10_m2_isolated_benchmark.sql` on Docker `:55432`.

| proposition | verdict | note |
|---|---|---|
| Custom `temporal_range` type | **REJECTED** | Use built-in `tstzrange` (`valid_period`, `tx_period`) |
| Closed-open `[from,to)` | **ACCEPTED** | PostgreSQL range default `[)` |
| Composite tenant FK `(tenant_id, identity_guid)` | **ACCEPTED** | RLS is defense in depth, not a substitute |
| Hash unique UUID as logical dedupe | **REJECTED** | Unique `(tenant_id, canonical_key)` from semantic fields |
| Reuse issuer/security/listing GUIDs | **ACCEPTED** | Columns on `memory_identity`; ticker remains alias |
| Callers author `tx_from` | **REJECTED** | `write_fact_version()` assigns `clock_timestamp()` |
| Direct historical DELETE by agents | **REJECTED** | Agent has no DELETE; tx close is interval shrink |
| Mutable `row_kind=current` | **REJECTED** | `CURRENT := upper_inf(tx_period)` |
| Universal overlap/continuity trigger | **REJECTED** | `PredicateTemporalPolicy@v1` |
| Exclusion for every predicate | **MODIFIED** | Exclusion only `SINGLE_VALUED_CURRENT` (`DATABASE_ENFORCED_TEMPORAL_INVARIANT`) |
| btree_gist for scalar equality in GiST | **ACCEPTED** | Required for tenant/identity/predicate `=` |
| One composite GiST always wins | **BENCHMARK_REQUIRED** | Separate GiST valid, GiST tx, SP-GiST valid, B-tree metadata; EXPLAIN ANALYZE captured |
| Temporal pruning before vector | **BENCHMARK_REQUIRED** | Not claimed without plan |
| RLS without FORCE | **MODIFIED** | `FORCE ROW LEVEL SECURITY` |
| Agent as table owner / BYPASSRLS | **REJECTED** | `m2_agent` NOSUPERUSER NOBYPASSRLS; not owner |
| SECURITY DEFINER on agent routes | **MODIFIED** | Only trusted `write_fact_version` |
| JSONB `provenance_dag` as canonical | **REJECTED** | Normalized `provenance_edge` |
| Adjudication receipt | **ACCEPTED** | Normalized; no chain-of-thought |
| SERIALIZABLE everywhere | **REJECTED** | Exclusion + DB-owned tx; SERIALIZABLE not global |
| ANN cosine 0.75 self-edge | **REJECTED** | Similarity → CANDIDATE only |
| Titan / 1024-d cloud embed | **REJECTED** | LOCAL_ONLY, model-agnostic `vector(768)` optional |
| HNSW / 10× overfetch as architecture | **REJECTED** | Indexes created for measurement only |
| Neo4j required | **REJECTED** unless Postgres fails graph queries | `POSTGRES_SUFFICIENT` this round |
| pgmnemo as default | **BENCHMARK_REQUIRED** | v0.20.0 current stable; UNMEASURED_INSTALL on image |

## Isolated measurements (this host)

- Tenant leakage: 0
- Agent direct INSERT blocked
- SINGLE_VALUED_CURRENT overlap rejected by exclusion
- MULTI_VALUED opinions allowed
- EXPLAIN: Index Scan on current/valid/tx queries
- Storage decision remains **POSTGRES_PGVECTOR**
- Production SQL: **not applied**
