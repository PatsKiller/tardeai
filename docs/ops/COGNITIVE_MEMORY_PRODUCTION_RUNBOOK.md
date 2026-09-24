# Cognitive memory in production: runbook

Status:      ACTIVE
as_of:       2026-09-24
Measured at: 8a95e30c1 (cutover script, PR #1218), writes enabled 2026-09-24 ~15:55 ET; FOR UPDATE fix in this PR
Authority:   AGENTS.md §0 (MBI_BEHAVIOR=0, never delete), AI_WORK_POLICY.md, operator decisions 2026-09-24 ("go on memory", "turn on")
See also:    scripts/apply_memory_prod_cutover.py, scripts/lib/memory_prod_cutover.py, scripts/lib/cio_memory_integration.py,
             sql/r10_m2_isolated_benchmark.sql, sql/trade-ai-bitemporal-schema-v2.sql, docs/ops/BITEMPORAL_MEMORY_V2_DEPLOY_2026-09-19.md

## What it is

The CIO's cognitive memory is a bitemporal fact store in Postgres schema `memory_r10_m2`.
It holds beliefs (for example a subject's current `thesis`), never financial truth: prices,
positions, sizes, orders and stops are refused at write time (`FINANCIAL_TRUTH_REFUSED`).
It has no influence on broker writes, sizing or execution (`MBI_BEHAVIOR = 0`).

| Object | Role |
|---|---|
| `memory_identity` | One row per (tenant, subject, predicate). Carries subject/issuer/security/listing GUIDs. |
| `memory_fact_version` | Every version of every belief. `valid_period` = when it is true in the world; `tx_period` = when the system believed it. Both `tstzrange`, closed-open `[)`. |
| `adjudication_receipt` | Why a belief changed: candidates, selected, rejected, deterministic policy, `source_sha`. Written in the same transaction as the fact, before it. |
| `provenance_edge`, `relationship_candidate`, `predicate_temporal_policy` | Supporting tables. |
| `"MemoryFactVersion@v2"` view | Facts plus computed `row_kind`: `current` when `upper_inf(tx_period)`, else `audit`. |
| `"MemoryIdentity@v1"`, `"AdjudicationReceipt@v1"`, `"ProvenanceEdge@v1"` views | Read surfaces. |

**How a belief changes.** SINGLE_VALUED predicates (`thesis`) are written by
`supersede_single_valued_fact`: a newer assertion closes the overlapping current version in
transaction time (it stays as an `audit` row) and re-asserts its non-overlapping remnant(s) as
current; an identical re-assertion writes nothing (`IDENTICAL_REASSERTION_NOOP`). MULTI_VALUED
predicates use `save_bitemporal_fact_version`. Closed versions can never be updated or deleted
(`trg_block_fact_manipulation` → `BITEMPORAL_AUDIT_IMMUTABLE`).

**Isolation.** Every table has `FORCE ROW LEVEL SECURITY` with a tenant policy
(`tenant_id = current_setting('app.tenant_id')`). Views are `security_invoker`, so RLS applies
to whoever reads them. The default tenant is `tradeai:tenant:primary`.

**Who writes.** Production writes run as the login role `m2_agent` (not superuser, no
BYPASSRLS). Its privileges are deliberately narrow:

| Table | m2_agent |
|---|---|
| `memory_fact_version` | SELECT only. All fact writes go through SECURITY DEFINER functions. |
| `memory_identity`, `predicate_temporal_policy` | INSERT, SELECT, UPDATE |
| `adjudication_receipt`, `provenance_edge`, `relationship_candidate` | INSERT, SELECT |
| Functions | EXECUTE on `write_fact_version`, `save_bitemporal_fact_version`, `supersede_single_valued_fact` |

The writer is the hourly AEC cycle (`tradeai-aec-command-center-cycle.timer` →
`scripts/aec_command_center_cycle.py --apply` → `integrate_wake_envelope`).

## The 2026-09-24 production cutover

Production had the base tables only (0 rows, comment "Do not apply to production"). The v2
packaging was applied with the dedicated, additive-only cutover:

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/apply_memory_prod_cutover.py                      # dry run (default, read-only session)
TRADEAI_M2_PROD_CUTOVER_CONFIRM=trade_ai \
  .venv/bin/python scripts/apply_memory_prod_cutover.py --apply            # needs a db-write guard grant
```

- The script parses the existing `sql/` files unchanged and marks each statement RUN or SKIP
  against the live catalog. It never runs DROP / TRUNCATE / DELETE and never creates or alters
  a role; an unrecognised statement refuses the whole plan.
- `--apply` runs in one transaction (lock_timeout 5 s, statement_timeout 60 s), refuses if the
  memory tables hold rows (unless `--allow-existing-rows`), asserts 22 post-conditions, and
  runs a smoke test inside a SAVEPOINT that is always rolled back (two thesis assertions →
  2 current + 1 audit; editing a closed version refused). Any failure rolls everything back.
- Result on 2026-09-24 15:51 ET: plan 33 RUN / 42 SKIP; committed; 22/22 checks true;
  smoke ok; 0 rows. Receipt: `~/.local/state/tradeai/memory_prod_cutover_receipts.jsonl`
  (`source_sha` 8a95e30c1). Re-running the dry run afterwards is safe (the created extension,
  trigger and indexes are skipped; reviewed functions and views are re-applied unchanged).
- Backup taken first: `~/db_backups/m5_pre_memory_cutover_20260924T155109/memory_r10_m2_schema.dump`
  (schema only). A data dump fails because `pg_dump` is subject to `FORCE ROW LEVEL SECURITY`
  ("query would be affected by row-level security policy"); the tables were empty, so the
  schema dump is a complete backup of that moment. For a future data backup, dump per tenant
  with `app.tenant_id` set, or have a superuser run it.

## Enabling production writes

Two settings are required. The integrator refuses any production DSN
(`M2_DSN_PRODUCTION_PORT_FORBIDDEN`) unless the authorization flag is set, and it connects
with `M2_DSN`. The destructive schema reset stays refused on production regardless.

Drop-in `~/.config/systemd/user/tradeai-aec-command-center-cycle.service.d/m2-production.conf`:

```ini
[Service]
Environment=TRADEAI_M2_PRODUCTION_MEMORY_AUTHORIZED=1
ExecStart=
ExecStart=/bin/sh -c 'M2_DSN="$$M2_AGENT_DSN" exec /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/aec_command_center_cycle.py --apply'
```

then `systemctl --user daemon-reload`. It takes effect at the next hourly run.

- **Where the credential comes from.** `M2_AGENT_DSN` is a Bitwarden Secrets Manager secret,
  rendered by `tradeai-sm-render.service` into `/run/user/<uid>/tradeai/env` (tmpfs), which the
  unit loads with `EnvironmentFile=`. The drop-in never contains the password.
- **Why `$$`.** systemd expands `$VAR` in `ExecStart` itself, which would place the DSN
  (password included) in the `sh` process's argv, visible to `ps`. `$$M2_AGENT_DSN` passes a
  literal `$M2_AGENT_DSN` to `sh`, which reads it from its environment. Check with
  `systemctl --user show tradeai-aec-command-center-cycle.service -p ExecStart` — it must show `$$`.

## Verifying

```sql
SET app.tenant_id = 'tradeai:tenant:primary';      -- without it RLS shows 0 rows
SELECT row_kind, count(*) FROM memory_r10_m2."MemoryFactVersion@v2" GROUP BY 1;
SELECT count(*), max(recorded_at) FROM memory_r10_m2."AdjudicationReceipt@v1";
```

Each cycle's JSON output (journal: `journalctl --user -u tradeai-aec-command-center-cycle.service`)
has a `"bitemporal"` block with the receipt: `memory_version_id`, `reason`
(`SINGLE_VALUED_SUPERSEDED`, `IDENTICAL_REASSERTION_NOOP`), `writer`, or `error`.

**Fail-soft.** A memory error never aborts the cycle: it is logged as
`"via": "aec_bitemporal_fail_soft"` with the error, and the rest of the cycle completes.
A run of fail-soft blocks means memory is not being written; it does not mean the cycle is down.

## Known issues and history

- **2026-09-24 16:00 ET — first production cycle failed soft** with
  `InsufficientPrivilege: permission denied for table memory_fact_version`. The overlap read in
  `CIOEnvelopeIntegrator._scan_conflicts` used `SELECT … FOR UPDATE`, which needs UPDATE
  privilege; m2_agent has SELECT only. Every earlier test ran as the shadow superuser. Fixed by
  replacing the row lock with a transaction-scoped advisory lock
  (`pg_advisory_xact_lock(hashtextextended('m2:<tenant>:<subject>|<predicate>', 0))`) taken
  before the read, which serializes writers for one belief without widening grants.
  `tests/test_memory_agent_least_privilege_20260924.py` now runs the lifecycle as a role with
  exactly m2_agent's production grants and fails on the old code.
- Beliefs written before the fix: none (every production attempt before it failed soft).
- The shadow database (`:55432`) has its own `m2_agent` with the old repo password; it holds
  no production data. Rotation there is optional.

## Rollback

```bash
rm ~/.config/systemd/user/tradeai-aec-command-center-cycle.service.d/m2-production.conf
systemctl --user daemon-reload
```

The next cycle writes to the isolated shadow again. Rows already written in production stay
(AGENTS.md §0 rule 6: never delete; closed versions are immutable by trigger). The cutover
itself is additive and needs no rollback.

## Rotating the m2_agent password

Use the existing script; it never prints the password.

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/secrets/ensure_m2_agent_dsn.py --dry-run
.venv/bin/python scripts/secrets/ensure_m2_agent_dsn.py            # new password → Bitwarden SM M2_AGENT_DSN, 0600 SQL file under /run/user/<uid>/tradeai
sudo -u postgres psql -d trade_ai -v ON_ERROR_STOP=1 -f - < /run/user/$(id -u)/tradeai/m2_agent_role.sql
.venv/bin/python scripts/secrets/ensure_m2_agent_dsn.py --verify --shred
```

The next cycle picks up the new DSN from the re-rendered env. Postgres listens on 127.0.0.1
only, so the role is not reachable from the network.
