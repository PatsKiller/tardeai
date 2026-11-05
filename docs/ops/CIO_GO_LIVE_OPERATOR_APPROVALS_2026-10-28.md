Status: ACTIVE
as_of: 2026-10-28T21:36:00Z
Canonical repo path: docs/ops/CIO_GO_LIVE_OPERATOR_APPROVALS_2026-10-28.md
Authority: operator 2026-10-28 in-session, verbatim: "No, I need total turn key. I authorize you to put those switches on now."
See also: docs/audits/CIO_READINESS_GO_LIVE_AUDIT_2026-10-28.md

# CIO review go-live — what is actually left (accurate)

## State after the audit, corrected

Two of the "switches" I originally listed are **already on**:

- ✅ **`cio_prospect` registry row: already granted** — `config/data_source_authority.json:3538-3542`
  (`approved_by: operator`, `approved_on: 2026-10-22`).
- ✅ **P1 migration grant: already recorded** — the sha256 in the grant (`6bac8924…`) matches the up-file
  exactly (verified by `scripts/cio_prospect_migration_plan.py`, "static checks: PASS", "registry row: GRANTED").

So only **three** things remain, and the operator has now authorized all three.

## The three remaining switches

### Switch 1 — create the two tables (apply the migration)

Nothing exists to write to until the tables are created. The file is **additive by construction** — idempotent
`CREATE TABLE IF NOT EXISTS`, no DROP/DELETE/ALTER, append-only triggers, least-privilege grants. Dry-run already
quoted (sha256 `6bac89245fd6b990dc8a59c8fa6aeb85f34e6a97a5dd61e2fd3fa9b6e861f2be`).

The migration plan has **no `--apply`** by design — it says "the operator applies the file with psql." This is the
one command an AI cannot run (it needs the production DB connection, and §24.7 forbids reading credentials):

```
psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_22_cio_prospect.sql
psql "$DB" -c "SELECT to_regclass('public.cio_prospect'), to_regclass('public.cio_prospect_events')"
```

### Switch 2 — turn on saving

```
TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1
```

in the CIO lanes' environment (the `cio-opportunity-curator`, `cio-entry-state`, `cio-prospect-shadow` lanes).
Until this is set, `InstrumentRecordStore.upsert_prospect` reports `pg.mode=inert` and nothing persists to the
table — which is exactly why decisions never land anywhere permanent.

### Switch 3 — activate the conflict rulebook (done in code, this repo)

`config/conflict_rulebook.json`: `status` PROPOSED → **APPROVED**, `live_enabled` false → **true**, `approval`
recorded with the operator's in-session authorization. This activates the one engine/rulebook (§28.10):
`safety > fact > policy > deterministic_gate > operator_decision > cio_decision > curator > opinion`.
Done in this worktree; goes live on merge + deploy.

## What the agents are building in parallel (no approval needed)

- `scripts/lib/data_broker/watch_review_status.py` — the missing module so a processed review outcome reaches the row.
- Watch STALE badge — stale reviews stop looking current.

## Honest sequencing

The code that points Watch at the canonical resolver and wires the conflict engine into the Watch read path must
land **after** Switches 1 + 2, or Watch would serve shadow data. So the turn-key order is:

```
[operator] Switch 1 (psql) + Switch 2 (env flag)   ← 2 terminal commands, 2 minutes
[agent]    push the already-built code (rulebook, watch_review_status, stale badge, wire-engine, point-Watch)
[operator] approve the PRs on Telegram → Mergify merges → deploy_on_main promotes
[result]   one record, one resolver, stale reviews visibly stale, review outcomes reach the row
```
