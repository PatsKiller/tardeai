# Remediation plan — 5-stage hardening, governance and bitemporal cutover

```
Status: 4 of 5 stages CLOSED; Stage 3 production cutover BLOCKED (infrastructure)
as_of: 2026-09-19T20:34:54-04:00
Measured at: dev tree 170532178 (= origin/main after #1095); live trade_ai DB; shadow tradeai-m2-shadow-v2 :55432
Authority: READ_ONLY_ADVISORY / MBI_BEHAVIOR=0 — operator grant required for production memory writes
Canonical: docs/remediation-plan.md
See also: docs/GROUNDING_SLO_2026-09-18.md, docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md,
          docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md
```

## Scope correction

The directive that drove this plan described the system as of **2026-09-18**. Stages 1, 2,
4 and 5 were already remediated by the PR wave that landed on **2026-09-19**
(#1078, #1081, #1082, #1087, #1088, #1090, #1091). This document records what was verified,
not what was re-implemented. **No stage was re-done to satisfy the directive's narrative.**

## Stage status

| stage | requirement | status | evidence |
|---|---|---|---|
| 1 | `risk_agent` grounding SLO below 0.15 soft share | **CLOSED** | `soft_unsupported_share=0.003` (998 results); `risk_agent` 1/173 = 0.006; `breaches: []` |
| 2 | Merge + promote #1081, #1082; 3-promote pin soak | **CLOSED** | both MERGED 2026-09-19 18:09Z / 18:35Z; `soak_ready=YES streak=4 need=3` |
| 3 | Bitemporal substrate v2 on PostgreSQL ≥14 | **PARTIAL — production BLOCKED** | shadow `:55432` ACTIVE; production `:5432` `production_sql_applied=false` |
| 4 | 200-case correctness suite | **CLOSED** | `tests/test_bitemporal_correctness.py` — **205 passed** (re-run 2026-09-19) |
| 5 | Scale benchmark + EXPLAIN proof | **CLOSED** | Index Scan on `fact_valid_spgist`, Shared Hit Blocks, **0 disk reads** |

## Stage 1 — grounding SLO

Full write-up in `docs/GROUNDING_SLO_2026-09-18.md`. Summary: 0.22 → **0.003** overall;
`risk_agent` 0.913 → **0.006**. The pre-emit gate (`apply_number_grounding`, demotion to
`RESEARCH_MORE`) was already wired at `scripts/process_watchlist_agent_jobs.py:3075`; the
breach was a mix of genuinely ungrounded R/ATR multiples (#1078) and a report double-count
(#1087), not a missing gate.

## Stage 2 — governance PRs

- **#1081** `fix(ops): align governed-bridge pin with portfolio-server promote` — merged 18:09Z.
  Eliminates release pin drift by deriving `cio-governed-bridge.service` from the
  `portfolio-server.service` pin rather than a second independent pin.
- **#1082** `fix(telegram): hard-gate investment sends on CIO stance conflict` — merged 18:35Z.
  Interdicts `BUY` / `Accumulate` / `GO` sends while `cio_decisions` holds an active `AVOID`.

Soak exceeds requirement (`need=3`, observed streak **4**), last match
`2026-09-19T20:02:08Z`, server and bridge both pinned to
`4bafd6f83-main-exact-phase2-20260919-153247`.
Ledger row `PARTIAL-bridge-pin-soak` is **CLOSED**.

**Residual:** `PARTIAL-telegram-CIO-stance` stays PARTIAL until a *live* hold receipt is
observed from CURRENT. Code is merged; the proof bar is an observed interdiction, not a
passing test.

## Stage 3 — bitemporal substrate (the open item)

Applied and proven on the isolated shadow only:

- Container `tradeai-m2-shadow-v2` (pgvector/pgvector:pg16) on `127.0.0.1:55432`
- `sql/r10_m2_isolated_benchmark.sql` + `sql/trade-ai-bitemporal-schema-v2.sql`
- Views `MemoryIdentity@v1`, `MemoryFactVersion@v2`, `AdjudicationReceipt@v1`, `ProvenanceEdge@v1`
- DB-owned `tx_period` via SECURITY DEFINER `save_bitemporal_fact_version`
- `trg_block_fact_manipulation` hard-stops UPDATE/DELETE on closed versions
- Composite `(tenant_id, guid)` + FORCE RLS, proven as non-superuser `m2_agent`
- Constitutional rail holds: financial keys refused (`FINANCIAL_TRUTH_REFUSED`)

### Why production is not cut over

Operator granted the production cutover on 2026-09-19. It could not be executed. Two hard
blockers were measured against the live database (probe transaction, rolled back):

| blocker | detail | needs |
|---|---|---|
| `vector` extension absent | `pg_available_extensions` has no `vector` row — pgvector is not installed on the production server. `memory_fact_version.embedding` and the `write_fact_version(...)` signature both require type `vector`. | OS package install (e.g. `postgresql-17-pgvector`) + `CREATE EXTENSION vector` as superuser |
| cannot `CREATE ROLE` | `trade_ai` is `rolsuper=f, rolcreaterole=f`. `CREATE ROLE m2_agent` → `permission denied to create role`. The RLS isolation proof depends on a non-owner, non-BYPASSRLS role. | superuser, or `CREATEROLE` granted to `trade_ai` |

Production is **PostgreSQL 17.10**, satisfying the ≥14 requirement. `btree_gist`,
`pgcrypto` and `uuid-ossp` are all creatable by `trade_ai` (trusted in PG17) and are *not*
blockers. `memory_r10_m2` does not exist in production; `trade_ai` does hold `CREATE` on
the database, so schema creation itself is permitted.

**Nothing was applied to production.** The probe ran inside a transaction that was rolled
back; `production_sql_applied` remains `false`.

### Additional hazard before any cutover

`sql/r10_m2_isolated_benchmark.sql:9` begins
`DROP SCHEMA IF EXISTS memory_r10_m2 CASCADE;`. That is safe on a shadow that is rebuilt
per run and safe on first application to production (the schema is absent), but it makes
the file **destructive on re-run**. A production runbook must either split the DDL or
guard that line before it is applied a second time.

### Cutover path

1. Operator installs pgvector on the production host and creates the extension as superuser.
2. Operator creates role `m2_agent` (or grants `CREATEROLE`). Do **not** reuse the shadow's
   `m2agent` literal password in production.
3. Guard or remove the `DROP SCHEMA ... CASCADE` line for the production apply.
4. Apply both SQL files in one transaction; verify the four views, the writer function, the
   trigger and `fact_single_valued_current_excl`.
5. Re-run `tests/test_bitemporal_correctness.py` against the production DSN — the CI
   workflow currently refuses `:5432` by design and must be explicitly re-pointed.
6. Flip `production_sql_applied: true` in `docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md`
   only after the ledger's stated bar is met: **OBSERVED unattended write from served**.

## Stages 4 and 5 — correctness and scale

`tests/test_bitemporal_correctness.py` re-run 2026-09-19: **205 passed in 3.13s** against
`tradeai-m2-shadow-v2`. Covers the five required criteria — single-valued overlap exclusion
raises, multi-valued overlap permitted, automatic version closure with `tx_period` closed by
the DB, RLS tenant isolation proven as `m2_agent`, and direct `UPDATE`/`DELETE` on fact rows
rejected.

`EXPLAIN (ANALYZE, BUFFERS)` on the point-in-time query resolves via **Index Scan** on
`fact_valid_spgist` — not a Seq Scan — with Shared Hit Blocks and **0 disk reads**.

**Honesty note:** the architect reconciliation **rejected** the directive's `row_kind` and
`is_single_valued` column names. CURRENT is expressed as `upper_inf(tx_period)` and
single-valued behaviour via `temporal_policy = 'SINGLE_VALUED_CURRENT'`. Tests assert the
reconciled semantics, not the directive's column names. The index proven is
`fact_valid_spgist`; the directive named `idx_fact_version_bitemporal_gist`, which does not
exist under that name.

## Open items

| item | owner | bar |
|---|---|---|
| Production bitemporal cutover | operator | pgvector installed + `m2_agent` role created |
| `PARTIAL-telegram-CIO-stance` | schedule | live hold receipt observed from CURRENT |
| SLO ratification | operator | `slo_status: PROPOSED` → ratified floors |
| `risk_agent` stale residual (157) | time | ages out of the 7-day window |
