# Staging vs V2 bitemporal database — status report

```
Status: ACTIVE
as_of: 2026-09-20T17:50:00-04:00
Measured at: Docker tradeai-m2-shadow-v2 127.0.0.1:55432 / m2_shadow;
  sql/trade-ai-bitemporal-schema-v2.sql + sql/r10_m2_isolated_benchmark.sql;
  tests/test_bitemporal_correctness.py → 221 passed in 2.79s;
  hub HEAD / origin/main at measurement time
Canonical repo path: docs/STAGING_VS_V2_BITEMPORAL_STATUS_REPORT.md
Authority: READ_ONLY_ADVISORY audit of isolated staging; production :5432 cutover remains §17 DEFERRED
See also: docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md;
  docs/ops/PROPOSED_BITTEMPORAL_PROD_5432_2026-09-20-1051.md (Status: DEFERRED);
  docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md;
  docs/architecture/HONEST_MATURITY_ASSESSMENT_2026-09-20-1445.md
  (0945 package SUPERSEDED — do not treat as current maturity truth)
```

## Scope

| Label in directive | Concrete target this audit used |
|---|---|
| AS-IS staging database | `tradeai-m2-shadow-v2` on **`127.0.0.1:55432`**, database `m2_shadow` |
| TO-BE schema v2 | `sql/trade-ai-bitemporal-schema-v2.sql` (packaging delta) + prerequisite `sql/r10_m2_isolated_benchmark.sql` |
| Integrator | `scripts/lib/cio_memory_integration.py` (`scripts/cio_memory_integration.py` re-export) |
| Correctness suite | `tests/test_bitemporal_correctness.py` (**55432 only**; `:5432` refused) |

Production host Postgres **`17/main :5432`** is **out of apply scope** (operator **DEFER** 2026-09-20). Prior probe: `vector` extension unavailable + no `CREATEROLE` for `m2_agent`. This report does **not** apply DDL to `:5432`.

---

## Executive verdict

| Surface | Verdict |
|---|---|
| Staging shadow vs TO-BE v2 packaging | **ALIGNED after re-apply** of `trade-ai-bitemporal-schema-v2.sql` `[VERIFIED]` |
| Correctness harness | **221 passed / 0 failed** in 2.79s `[VERIFIED]` |
| Point-in-time planner | **Index Scan** (not Seq Scan); shared buffers hit; named index `idx_fact_version_bitemporal_gist` **does not exist** (architect used split GiST/btree set) |
| Production cutover | **§17 DEFERRED** — not OBSERVED_LIVE |
| Live CIO JSONL memory | **Still present** beside shadow (`aif_memory.jsonl` ~2.2M, `cio_theses.jsonl` ~5.4M) — flat AS-IS path not retired |

---

## Step 1 — Eight architectural dimensions

Legend: █ meets TO-BE on staging · ▓ partial / renamed by architect reconciliation · ⊠ missing or production-only gap

| # | Dimension | Staging AS-IS vs TO-BE | Evidence |
|---|---|---|---|
| 1 | **Storage topology** | ▓ Staging holds normalized `memory_r10_m2` tables (`memory_identity`, `memory_fact_version`, `adjudication_receipt`, `provenance_edge`, …) + `@v1/@v2` views after v2 apply. Live advisory path still appends **flat JSONL** under persistent-state. | `[VERIFIED]` `\dt memory_r10_m2.*`; JSONL paths under `persistent-state/data/cio/` |
| 2 | **Identity spine & canonical keys** | █ Columns `issuer_guid`, `security_guid`, `listing_guid` present. PK `(tenant_id, identity_guid)`. UNIQUE `(tenant_id, canonical_key)` — not the literal 4-tuple `(tenant_id, namespace, entity_type, canonical_natural_key)`; `namespace` + `identity_kind` exist as columns, uniqueness folded into `canonical_key`. | `[VERIFIED]` `\d memory_r10_m2.memory_identity` |
| 3 | **Temporal range mechanics** | █ `valid_period` and `tx_period` are native **`tstzrange`** (not strings / custom types). Empty-range CHECKs present. | `[VERIFIED]` information_schema + constraints |
| 4 | **System-time ownership** | █ `write_fact_version` / alias `save_bitemporal_fact_version` are SECURITY DEFINER; DB authors `tx_period`. Trigger `trg_block_fact_manipulation` + `block_bitemporal_manipulation()` block DELETE/UPDATE of closed versions. Companion `trg_no_agent_direct_insert` forbids client-authored `tx_period`. | `[VERIFIED]` after v2 re-apply; **note:** pytest destructive rebuild of `r10` alone **drops** v2 packaging until re-applied |
| 5 | **Predicate-aware concurrency exclusions** | ▓ Prompt names `row_kind` / `is_single_valued` / `exclude_bitemporal_overlap` were **REJECTED** in schema header. Staging uses `fact_single_valued_current_excl`: GiST exclude on `(tenant_id, identity_guid, predicate, valid_period)` **WHERE** `upper_inf(tx_period) AND temporal_policy = 'SINGLE_VALUED_CURRENT'`. Multi-valued policies may overlap. | `[VERIFIED]` `pg_constraint` + DDL comments |
| 6 | **Multi-tenant isolation (RLS)** | █ Composite FK `(tenant_id, identity_guid)` on fact versions. **FORCE ROW LEVEL SECURITY** on all six base tables; policies use `app.tenant_id`. | `[VERIFIED]` `relrowsecurity` / `relforcerowsecurity` = true |
| 7 | **Lineage & adjudication normalization** | █ Tables `adjudication_receipt` and `provenance_edge` exist (FK/tenant scoped). Views `AdjudicationReceipt@v1`, `ProvenanceEdge@v1` after v2 apply. Suite 4 DAG cases green. | `[VERIFIED]` schema + pytest Suite 4 |
| 8 | **Financial authority rail** | █ Integrator raises `FINANCIAL_TRUTH_REFUSED` on cash/position/qty keys; stamps `mbi_behavior: 0`. Cognitive-only contract in DDL header. | `[CODE]` `scripts/lib/cio_memory_integration.py`; suite rails green |

### Name map (directive → staging)

| Directive / prompt name | Staging object |
|---|---|
| `MemoryIdentity@v1` | view → `memory_r10_m2.memory_identity` |
| `MemoryFactVersion@v2` | view → `memory_r10_m2.memory_fact_version` |
| `AdjudicationReceipt@v1` | view → `memory_r10_m2.adjudication_receipt` |
| `ProvenanceEdge@v1` | view → `memory_r10_m2.provenance_edge` |
| `save_bitemporal_fact_version()` | alias of `write_fact_version` |
| `trg_block_fact_manipulation` | present after v2 packaging apply |
| `exclude_bitemporal_overlap` | `fact_single_valued_current_excl` |
| `idx_fact_version_bitemporal_gist` | **not created** — use `fact_valid_gist` / `fact_tx_gist` / `fact_id_pred_valid_gist` / `fact_current_idx` |

---

## Step 2 — Test harness & planner

### Pytest `[VERIFIED]` 2026-09-20

```text
M2_DSN=postgresql://m2:***@127.0.0.1:55432/m2_shadow
.venv/bin/python -m pytest tests/test_bitemporal_correctness.py -v
============================= 221 passed in 2.79s ==============================
```

Includes 200 matrix cases + rails (prod-port refusal, destructive-reset guards, EXPLAIN companion, authorization flags).

### EXPLAIN (ANALYZE, BUFFERS) `[VERIFIED]`

Query (after v2 views restored):

```sql
SET search_path TO memory_r10_m2, public;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT * FROM "MemoryFactVersion@v2"
WHERE tenant_id = 'bench'
  AND valid_period @> clock_timestamp()
  AND tx_period @> clock_timestamp();
```

Observed plan (empty result set at measurement):

```text
Index Scan using fact_subject_pred_btree on memory_fact_version
  Index Cond: (tenant_id = 'bench'::text)
  Filter: ((valid_period @> clock_timestamp()) AND (tx_period @> clock_timestamp()))
  Buffers: shared hit=2
Planning: Buffers: shared hit=298
Planning Time: ~0.7 ms
Execution Time: ~0.04 ms
```

Companion base-table form used `fact_current_idx` with `Buffers: shared hit=2`. **No sequential scan** of the fact table. Early temporal pruning via the fictional single `idx_fact_version_bitemporal_gist` name is **not** how this schema is built; planner still chooses index access.

`test_explain_bitemporal_pit_uses_index` **PASSED** (asserts Index/Bitmap Index Scan in JSON EXPLAIN).

---

## Operational finding — v2 packaging vs test reset

`[VERIFIED]` Order of operations:

1. Before this audit, staging had **base `r10` tables + RLS + exclusion**, but **missing** `save_bitemporal_fact_version`, `block_bitemporal_manipulation`, `trg_block_fact_manipulation`, and `@v*` views.
2. Applying `sql/trade-ai-bitemporal-schema-v2.sql` restored packaging.
3. Running the correctness suite (which may rebuild `r10` under `m2.allow_destructive_reset`) **cleared the packaging again**.
4. Re-applying v2 after tests restored aliases/views/trigger.

**Gap:** harness / CI should apply **`r10` then `trade-ai-bitemporal-schema-v2.sql`** on every isolated bootstrap, or packaging drifts silently while tables still look “present.”

---

## Cutover gaps (remain)

| Gap | Owner | Blocker |
|---|---|---|
| Production `:5432` schema apply | §17 (DEFERRED) | `vector` on PG17 + `m2_agent` CREATEROLE |
| Retire / dual-write flat JSONL CIO memory | product | shadow OBSERVED ≠ live readers switched |
| Named composite GiST `idx_fact_version_bitemporal_gist` | n/a | architect chose split indexes — do not invent |
| Auto-apply v2 packaging after destructive test reset | engineering | CI/harness wiring |

---

## Inputs referenced

| Artifact | Role |
|---|---|
| `sql/trade-ai-bitemporal-schema-v2.sql` | TO-BE packaging |
| `scripts/lib/cio_memory_integration.py` | Python integration + financial refuse |
| `tests/test_bitemporal_correctness.py` | 200+ case harness |
| `docs/architecture/HONEST_MATURITY_ASSESSMENT_2026-09-20-0945.md` | **SUPERSEDED** by `…-1445.md` — maturity parks already recorded DEFER for prod bitemporal |

---

## One-sentence version

Isolated staging on `:55432` matches the v2 bitemporal substrate (with architect renames) and is **221/221 green**; production cutover stays **DEFERRED**, flat JSONL memory still runs live, and v2 packaging must be re-applied after destructive `r10` resets.
