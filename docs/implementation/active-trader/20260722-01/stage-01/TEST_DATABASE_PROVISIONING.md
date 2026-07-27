# Test Database Provisioning — Stage 1

**Run ID:** 20260722-01 · **Date:** 2026-07-22

## What was provisioned
- A **completely separate, user-owned PostgreSQL 17.10 lab cluster** — not a sibling
  database inside the production cluster:
  - data dir `~/tradeai-lab/pg17` (mode 0700, owner johnclaw), port **5433**, socket dir
    `~/tradeai-lab/sock`, listen 127.0.0.1 only
  - database **trade_ai_test**, owned by role **trade_ai_lab** (LOGIN only; NOSUPERUSER,
    NOCREATEDB, NOCREATEROLE)
- Provisioning script (committed, idempotent, secret-free): `scripts/active_trader/provision_test_db.sh`
  (`--rotate` re-generates the password and updates the Bitwarden secret).
- DSN stored ONLY in Bitwarden Secrets Manager project `trade-ai-lab`
  (id 1b0a478d-87a3-4e2d-85f6-b4900015afa0) as secret **ACTIVE_TRADER_TEST_DATABASE_DSN**.
  The value was never printed, committed, uploaded, or emailed.

## Rationale for the separate-cluster design
Creating `trade_ai_test` inside the production cluster requires the `postgres` superuser
(the app role `trade_ai` has no CREATEDB/CREATEROLE; passwordless sudo unavailable). A
user-owned cluster needs no admin action and is strictly stronger isolation: the
`trade_ai_lab` role does not exist in the production cluster at all.

## Required proofs (all executed 2026-07-22)
1. **Reachable:** connected as `trade_ai_lab` to `trade_ai_test` ✔
2. **Migration rights:** CREATE/ALTER/DROP table in `trade_ai_test` ✔
3. **Cannot write production:** authentication as `trade_ai_lab` against the production
   cluster (localhost:5432/trade_ai) is DENIED — role does not exist there ✔
   Additionally the migration runner hard-refuses any DSN naming `trade_ai` or targeting
   port 5432 (tested: `test_runner_refuses_production_targets`).
4. **Production schema hash unchanged:** sha256 over ordered
   information_schema.columns of production `trade_ai` =
   `da4405cf8519821fc2c1d02b4f25ce1c542f04db08b4dcf2dfe339c7722ea4bc`
   — identical before provisioning and after all Stage 1 test runs ✔

## Operational notes
- Start (if stopped): `/usr/lib/postgresql/17/bin/pg_ctl -D ~/tradeai-lab/pg17 -l ~/tradeai-lab/pg17.log -w start`
  (or re-run the provisioning script, which starts it when needed). No systemd unit was
  installed; the lab cluster is on-demand and never part of production services.
- Tests export the DSN from Bitwarden into `ACTIVE_TRADER_TEST_DATABASE_DSN` and are
  skipped with an explicit reason when it is absent.
