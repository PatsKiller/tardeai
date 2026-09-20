# DEFERRED — operator continue-park (AGENTS.md §17)

```
Status: DEFERRED
Effective-Date: 2026-09-20T17:15:00-04:00
as_of: 2026-09-20T17:15:00-04:00
Measured at: docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md (probe rolled back; production_sql_applied=false)
Canonical repo path: docs/ops/PROPOSED_BITTEMPORAL_PROD_5432_2026-09-20-1051.md
Authority: propose-and-stop — production DB extension/role install and cutover are operator-only
Supersedes: prior DEFERRED stamp 2026-09-20T14:45 (Grok/email provenance — not a kit-valid Operator-Token)
See also: docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md, docs/remediation-plan.md § Stage 3, ledger DARK-bitemporal-m2-substrate
Operator-Token: DEFER
Operator-Token-Surface: cursor_chat|operator|2026-09-20T17:15:00-04:00
Operator-Token-as_of: 2026-09-20T17:15:00-04:00
Operator-Token-Evidence: "i approve or send telegram grant request" (verbatim Cursor chat; no Telegram PMID invented)
Operator-decision: DEFER (continue-park; no prod cutover; never touch :5432)
```

## Finding

Bitemporal memory schema v2 is **OBSERVED on isolated shadow only** (`tradeai-m2-shadow-v2` `:55432`).
A production `:5432` cutover was attempted 2026-09-19T20:34 ET under operator grant and
**could not execute**. The probe transaction was rolled back; production is unchanged.

| probe on production PG 17.10 | result |
|---|---|
| `CREATE EXTENSION btree_gist` / `pgcrypto` / `uuid-ossp` | OK |
| `CREATE EXTENSION vector` | **BLOCKED** — extension not available (pgvector not installed on host) |
| `CREATE ROLE m2_agent` | **BLOCKED** — `trade_ai` lacks `CREATEROLE` |

`postgresql-17-pgvector` is **not** in the default Ubuntu archive (only
`postgresql-18-pgvector` appears); production is the **17/main** cluster. Supported path:
add PGDG apt repo, then install `postgresql-17-pgvector` — see
`docs/remediation-plan.md` § "Getting pgvector onto PG17".

**CASCADE:** `sql/r10_m2_isolated_benchmark.sql` now refuses un-opted-in
`DROP SCHEMA … CASCADE` (`M2_DESTRUCTIVE_RESET_REFUSED`). Do **not** apply any
production cutover that re-enables unconditional CASCADE.

## Exact operator decision ask

Reply with one of:

1. **APPROVE_BITTEMPORAL_PROD_PREREQS** — operator (or OS superuser) will:
   - install pgvector for PG17 (PGDG → `postgresql-17-pgvector`) and
     `CREATE EXTENSION vector` on the production DB;
   - create role `m2_agent` (`NOSUPERUSER`, `NOBYPASSRLS`; **do not** reuse the
     shadow `m2agent` password);
   - confirm **no CASCADE** destructive reset on production apply.
2. **DEFER** — leave `production_sql_applied: false`; keep shadow-only.
3. **REJECT** — abandon production bitemporal cutover; document alternative.

Until (1), agents must **not** apply schema to `:5432`, must **not** flip
`production_sql_applied`, and must **not** re-point CI at production.

## Why not auto-close

§17 — host package install, Postgres role creation, and production schema apply are
operator-only. This file proposes and stops. Nothing was applied.

## Proof already measured

- Shadow suite green (`tests/test_bitemporal_correctness.py`, port **55432 only**).
- Production probe quoted in `docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md`.
- Destructive-reset guard landed 2026-09-20; appliers refuse port 5432.

---

## Operator decision (recorded)

```
token: DEFER
decided_on: 2026-09-20T17:15:00-04:00
surface: cursor_chat|operator (no Telegram PMID invented)
evidence: "i approve or send telegram grant request" (verbatim Cursor chat ~17:15 ET)
effect: CONTINUE-PARK; no :5432 work; shadow :55432 remains the only OBSERVED substrate
supersedes: 2026-09-20T14:45 DEFER stamp (Grok/email — not kit-valid Operator-Token)
```

Prior propose text above is retained for history. A later `APPROVE_BITTEMPORAL_PROD_PREREQS` may reopen this park.
