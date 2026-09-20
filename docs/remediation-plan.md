# Remediation plan — 5-stage hardening, governance and bitemporal cutover

```
Status: 4 of 5 stages CLOSED; Stage 3 production cutover BLOCKED (two SQL statements, operator)
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
| `vector` extension absent | `pg_available_extensions` has no `vector` row — pgvector is not installed on the production server. `memory_fact_version.embedding` and the `write_fact_version(...)` signature both require type `vector`. **No `postgresql-17-pgvector` package exists in the configured Ubuntu repos** — only `postgresql-18-pgvector`, and production is the PG **17** cluster. `postgresql-server-dev-17` is also unavailable and no PGDG repo is configured. | Add the PGDG apt repo (ships `postgresql-17-pgvector`), then `CREATE EXTENSION vector` as superuser. See "Getting pgvector onto PG17" below. |
| cannot `CREATE ROLE` | `trade_ai` is `rolsuper=f, rolcreaterole=f`. `CREATE ROLE m2_agent` → `permission denied to create role`. The RLS isolation proof depends on a non-owner, non-BYPASSRLS role. | superuser, or `CREATEROLE` granted to `trade_ai` |

Production is **PostgreSQL 17.10**, satisfying the ≥14 requirement. `btree_gist`,
`pgcrypto` and `uuid-ossp` are all creatable by `trade_ai` (trusted in PG17) and are *not*
blockers. `memory_r10_m2` does not exist in production; `trade_ai` does hold `CREATE` on
the database, so schema creation itself is permitted.

**Nothing was applied to production.** The probe ran inside a transaction that was rolled
back; `production_sql_applied` remains `false`.

### Getting pgvector onto PG17

The obvious `apt install postgresql-17-pgvector` **will fail** — that package is not in the
Ubuntu archive. Measured on this host: `apt-cache search pgvector` returns only
`postgresql-18-pgvector`; `postgresql-server-dev-17` has no candidate; `pg_lsclusters` shows
a single cluster, `17/main` on `:5432`. PG18 packages are installed but run no cluster.

Two options, in order of preference:

1. **Add the PGDG apt repo**, which ships `postgresql-17-pgvector` built against PG17:
   ```
   sudo install -d /usr/share/postgresql-common/pgdg
   sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc
   sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
       https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list'
   sudo apt update && sudo apt install postgresql-17-pgvector
   ```
   Adding PGDG makes newer PG17 point releases available too, so pin or review before a
   later `apt upgrade` moves the production server version.
2. **Build pgvector from source** against PG17 — needs `postgresql-server-dev-17`, which is
   itself only in PGDG, so this does not avoid step 1's repo addition.

Do **not** "solve" this by moving production to the PG18 cluster to use
`postgresql-18-pgvector`. That is a major-version migration of a 26 GB live database and is
out of scope for a memory-substrate cutover.

### Destructive-reset hazard — FIXED 2026-09-20

`sql/r10_m2_isolated_benchmark.sql` began with an unguarded
`DROP SCHEMA IF EXISTS memory_r10_m2 CASCADE;`. Safe on a per-run shadow and on a first
production apply, but **destructive on re-run** — a second `psql -f` would have
CASCADE-dropped live cognitive memory.

Now opt-in. The drop only runs when the session sets
`m2.allow_destructive_reset = 'on'`; otherwise, if the schema already exists, the file
raises `M2_DESTRUCTIVE_RESET_REFUSED` and changes nothing. All three in-repo appliers
(`memory_m2_benchmark.apply_schema`, `memory_m2_v2.apply_schema`,
`cio_memory_integration.apply_bitemporal_schema_v2`) set the flag explicitly, and each is
behind an isolated-DSN assertion. A manual or production `psql -f` does not set it, so a
re-run refuses.

`apply_bitemporal_schema_v2` previously only *claimed* "Isolated DSN only" in its docstring
while accepting any caller-supplied connection; it now enforces that with
`_assert_isolated_conn` (refuses port 5432) before opting in.

Covered by `test_schema_file_refuses_destructive_reset_without_optin` — asserts the refusal,
asserts the schema survives it, and asserts an opted-in rebuild still works.

### Cutover path

1. Operator installs pgvector on the production host and creates the extension as superuser.
2. Operator creates role `m2_agent` (or grants `CREATEROLE`). Do **not** reuse the shadow's
   `m2agent` literal password in production.
3. ~~Guard the `DROP SCHEMA ... CASCADE` line~~ — **done 2026-09-20**; the file now refuses an un-opted-in re-run.
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


---

## 2026-09-20 wave — hardening landed; cutover still operator-blocked

The 5-stage directive closed on 2026-09-19. This wave hardened everything the cutover
would have made reachable, and fixed defects that were harmless only because production
was unreachable.

### Landed

| PR | change |
|---|---|
| #1111 | destructive reset made opt-in; isolated-DSN claim enforced rather than asserted |
| #1132 | production memory behind `TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1`; fail-safe commit ordering |
| #1135 | the 3 undeclared schedulers declared — `ai_local_acceptance.sh` exits 0 for the first time since 09-18 |
| #1136 | ledger split so its append log union-merges; the status table stays hand-merged |
| #1137 | spoofable host check fixed; `M2_ALLOW_NONDEFAULT_PORT` → `MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT` |
| #1138 | AEC dual module identity ended; constitutional rails re-raise instead of being swallowed |

### Defects found that the plan did not anticipate

- **`--dry-run` was inert.** Declared and never read, so `--apply-schema --dry-run`
  applied the schema. An operator rehearsing the cutover would have performed it.
- **`PRIVATE_COT_FORBIDDEN` was swallowed.** Found by the test written for the financial
  rail, not by reading. A constitutional rail that fires invisibly cannot be audited.
- **The projector's allowlist was spoofable.** `"55432" in dsn` matched a credential
  containing those digits, so `…:pass55432word@127.0.0.1:5433/…` passed while pointing
  elsewhere. That guard had no test at all.
- **`FORBIDDEN_PORTS` is a mutable module-level set**, so under the dual import identity
  the production-port refusal was per-module-object.
- **Relative `output_signal` paths read the wrong file.** They resolve under
  `persistent-state`, not the code tree: measured 7.32h stale for the watchdog and absent
  for disk-cleanup. A lane declared that way alarms on a healthy job.

### Still blocked — operator only

The cutover needs two SQL statements run inside a superuser `psql` session; see
`docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md`. pgvector is installed;
`CREATE EXTENSION vector` and `CREATE ROLE m2_agent` are not done, and
`memory_r10_m2` does not exist in `trade_ai`.

Also operator-only (AGENTS §17, branch-protection/required-context): repointing the
required check at a fast always-reporting gate (PHASE D in
`docs/ops/GITHUB_ACTIONS_COST_REDUCTION_PLAN.md`). `allow_auto_merge` and
`allow_update_branch` are now enabled, but auto-merge does not update a behind branch,
so with `strict: true` and `cio-hardening` at 10-16 minutes a PR can still be invalidated
faster than it can merge. That is the remaining structural cost.
