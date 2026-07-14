# P0 Data-Integrity Audit — Redeploy Desk Test-Fixture Pollution

**Date:** 2026-07-13 · **Severity:** P0 · **Status:** Confirmed — quarantine deployed, deletion awaiting operator approval
**Scope:** Production Postgres `trade_ai` + `state/hermes/outcome_bus.json`

## Verdict

The three identical JEPQ stage-1 fills visible on event #144's Monitoring tab are
**production pollution, not operator evidence**. They were written by the test
suite itself.

## Root cause

`tests/test_redeploy_phase_e.py::test_idempotent_record_fill` (as shipped in
commit `fdfa2199`, Phase E) connected to the **production database** via
`db_adapter.get_connection()`, called `record_stage_fill(cur, 144, …)` against
the live FCNTX $107,023 sale event, and **committed**. Its idempotency key was
`test-<random uuid>` — new on every run — so each test run permanently added one
more identical fill. The test ran three times on 2026-07-13 between 23:19 and
23:23 ET. It performed no cleanup. A fourth run would have added a fourth row.

The reported "$3,246 deployed / 3% restoration" on the Monitoring tab is exactly
3 × 18 sh × $60.12 = $3,246.48 of synthetic fills against $107k of real proceeds.

## Contamination inventory (8 locations)

| # | Location | Rows | Detail |
|---|----------|------|--------|
| 1 | `redeploy_stage_fills` | ids 1–3 | JEPQ stage-1, 18 sh @ $60.12, note `phase_e test fixture`, keys `test-*` |
| 2 | `redeploy_monitor_snapshots` | ids 1–3 | restoration_pct 1.0 / 2.0 / 3.0, hermes ids {77573},{77574},{77575} |
| 3 | `redeploy_monitor_audit` | ids 1–5 | 3× `record_fill` (test-* keys), 1× `lock_plan` (`test-lock-79ff5cc63c1a`), 1× `oversight` |
| 4 | `hermes_outcome_ledger` | ids 77573–77575 | subject_type `redeploy_fill`, claim `redeploy_fill:→JEPQ stage1 planF $1082 manual`, **verdict still `pending`** — caught before grading fed Hermes learning |
| 5 | `deploy_events` id 144 | 1 | test lock mutated live event: `operator_status='reviewing'`, `locked_plan_id=8`, `locked_plan_version=2`, `plan_locked_at` set, `metadata.phase_e` = {fill_count: 3, restoration_pct: 3.0} |
| 6 | `deploy_plans` id 8 (F v2) | 1 | `locked_at`/`locked_by='operator'` from test lock; `oversight_status='failed'` from test-triggered oversight |
| 7 | `deploy_oversight_runs` | ids 1–2 | grok=pass / chatgpt=fail, ran 23:21:37 — triggered by the test `lock_plan` call |
| 8 | `state/hermes/outcome_bus.json` | 6 entries | 3× `by_symbol.JEPQ.redeploy_events` + 3× `feedback_to_governor` (`"Manual redeploy fill stage 1 for None sale"`) |

**Blast-radius notes**

- Hermes learning: the three ledger rows are `verdict='pending'` and unactioned —
  they had **not yet** been graded into learning when caught. The outcome-bus
  governor feedback (3 entries) was live, however.
- The `sold_symbol: null` / "for None sale" in the bus exposed an incidental bug:
  `record_stage_fill` built its event dict without the event's symbol.
  Fixed alongside the guards.
- No fixture/synthetic markers found in `deploy_events`, `deploy_plans`, or
  `redeploy_plan_legs` (full-row scans, 0 hits). Pollution is confined to the
  Phase E fill/monitoring/oversight chain for event 144.

## Remediation

### Deployed now (this PR — reversible quarantine + permanent guards)

1. **Migration `2026_07_19_redeploy_data_integrity.sql`**
   - `environment` column on `redeploy_stage_fills` (`production` | `test`),
     default `production`.
   - `broker_confirmation_id` column for legitimately identical fills.
   - **Quarantine:** rows carrying fixture markers re-labeled `environment='test'`
     (the 3 known rows). Reversible; no deletion.
   - Content-level unique index `(event, plan, version, ticker, stage, shares,
     price, broker_confirmation_id)` on production rows — duplicate manual fills
     rejected at the database even if application checks are bypassed.
2. **`record_stage_fill` guards** (`scripts/lib/redeploy_monitor.py`)
   - `environment='test'` rejected unless `REDEPLOY_ALLOW_TEST_FILLS=1`
     (never set on the production box).
   - Production fills rejected if `evidence_note` / `recorded_by` /
     `idempotency_key` contain fixture markers (word-boundary match on
     fixture|synthetic|dummy|fake|test, or `test-` key prefix).
   - Content-duplicate pre-check with actionable hint (supply
     `broker_confirmation_id` for a genuinely separate execution).
   - Test fills that are allowed (test environments only) skip Hermes ledger,
     outcome bus, and event-metadata updates entirely.
3. **`list_fills` filters `environment='production'`** — restoration metrics,
   fill summaries, monitoring state, snapshots, and UI all exclude quarantined
   rows from the moment the migration runs.
4. **Test suite fixed** — the polluting test is replaced by four guard tests
   that always roll back and stub the JSON bus write; the committing pattern is
   gone.

### Awaiting operator approval (NOT executed)

- `scripts/maintenance/redeploy_fixture_cleanup_2026_07_13.sql` — single
  transaction deleting rows in locations 1–5/7 above, resetting the test lock and
  oversight verdict on plan 8, restoring event 144 to `operator_status='open'`,
  and stripping `metadata.phase_e`. Pre/post verification queries included.
- `scripts/maintenance/redeploy_fixture_cleanup_outcome_bus.py` — dry-run by
  default; `--apply` removes the 6 JSON bus entries.

### Until the cleanup is approved

Live monitoring (`GET /api/v2/deploy/monitoring`) already reads clean (0 fills,
0% restoration) because of the quarantine. Two stale surfaces remain until the
deletion runs: `deploy_events.metadata.phase_e.restoration_pct=3.0` (shown on
the Redeploy panel list) and the historical snapshot rows 1–3, plus the
`reviewing`/locked state on event 144.
