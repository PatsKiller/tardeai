# Redeploy institutional rebuild — Phase-0 report (2026-07-14)

Read-only audit run against the production DB on 2026-07-14 before any functional rebuild change.
Scope per operator directive: cleanup, freeze, and truth. **No production rows were modified.**

## 1. Files removed from tracked documentation

`docs/redeploy_review_2026-07-14/` (37 PNGs + README, 4.6 MB) — removed in
`chore(docs): remove temporary redeploy visual-review captures`. Operator had already deleted the
Drive copies; the Drive-sync manifest is hash-based, so the deleted Drive files will NOT be
re-uploaded while the local files are unchanged/removed.

## 2. Artifact-retention policy (implemented this branch)

Captures now go to `artifacts/playwright/<tool>/<run_id>/` — gitignored, hard-excluded from
`sync-docs-to-drive.sh` (`*/artifacts/*`, `*redeploy_review*`, `*_review_20*/*.png`), 7-day default
retention via `scripts/artifacts_retention.sh` (smoke-tested). Runbook:
`docs/runbooks/PLAYWRIGHT_ARTIFACTS_POLICY.md`.

## 3. Git / Drive source-of-truth differences

| Surface | Claim | Truth status |
|---|---|---|
| `main` CHANGELOG/ops log (PR-4/PR-5 era commits) | "complete institutional desk" | **OVERSTATED** — workflow prototype; reopened by operator verdict 2026-07-13 |
| Drive copy of design doc | "design pending / no implementation" | **STALE** — Phase A data-truth + plan/monitor infrastructure exist |
| PR #143 (unmerged) | per-layer implementation-truth matrix, status REOPENED_FOR_REBUILD | **CORRECT** — becomes canonical when the stack merges; hourly Drive sync then heals the drift |

Drift root cause: the reconciliation lives in the **unmerged** stack (#142→#146) while Drive mirrors
`main`. No manual Drive edits were made (protocol: Drive mirrors merged main only).

## 4. Actual current capabilities (capability-status vocabulary)

| Capability | On `main` (deployed) | In unmerged stack #142–#146 |
|---|---|---|
| Sale detection + proceeds reconciliation (Phase A) | IMPLEMENTED_AND_VERIFIED | unchanged |
| Plan generation (A–G archetypes) | PARTIAL — templated menu, FCNTX only | PARTIAL — engine reworked (#145); breadth still limited |
| Capital allocation book (portfolio-wide) | MISSING | IMPLEMENTED_NOT_VERIFIED (#144: `redeploy_capital_book.py`, `/api/v2/redeploy/book` et al.) |
| Exposure decomposition / look-through pro-forma | UI_SHELL | IMPLEMENTED_NOT_VERIFIED (#145: `redeploy_pro_forma.py` three-state) |
| Candidate research universe | MISSING (hardcoded menu) | IMPLEMENTED_NOT_VERIFIED (#145: `redeploy_candidate_research.py`) |
| Performance/risk analytics (5Y local price cache) | MISSING | IMPLEMENTED_NOT_VERIFIED (#144/#145: `redeploy_price_history.py`, 87k closes) |
| Full-page workstation UI (11 tabs, typography floor) | MISSING (780px drawer) | IMPLEMENTED_NOT_VERIFIED (#146: `/redeploy`, drawer retired) |
| Data-integrity guards (environment column, fixture rejection) | PARTIAL — `environment` column self-healed onto `redeploy_stage_fills`; guard **code** unmerged | IMPLEMENTED_NOT_VERIFIED (#142) |
| Scheduled recompute / monitoring cron | DOCUMENTED_ONLY — **no redeploy cron installed** in live crontab | cron installer in stack, not installed |
| Fixture cleanup of event #144 | REOPENED_FOR_REBUILD — SQL staged, **awaits operator approval** | `scripts/maintenance/redeploy_fixture_cleanup_2026_07_13.sql` + `redeploy_fixture_cleanup_outcome_bus.py --apply` |

## 5. Database inventory (2026-07-14, production)

| Table | Rows | Notes |
|---|---|---|
| deploy_events | 144 | 31 open ($107,023 net on #144 + 30 smaller), 113 dismissed |
| deploy_plans | 21 | ALL on event #144 (FCNTX) — every other open event has **0 plans** |
| redeploy_plan_legs | 72 | |
| redeploy_stage_fills | 3 | all three = identical JEPQ 18sh @ $60.12 `phase_e test fixture`, now `environment=test`, keys `test-*` |
| deploy_oversight_runs | 2 | |
| redeploy_exposure_loss / _holding / _sector | 4 / 40 / 44 | |
| redeploy_monitor_snapshots / _audit | 3 / 5 | |
| redeploy_portfolio_context_snapshots | 4 | |

## 6. API endpoints

- Live on `main`: `/api/v2/deploy/{events,detect,recompute,dismiss,restore,plans,monitoring,lock,oversight,record-fill,export}`, `/api/v2/rotation/propose-etf`.
- In stack (unmerged): `/api/v2/redeploy/{book,history,capital-pools,opportunity-set,candidates,portfolio-pro-forma,performance,audit}` (disk-cached 30 m). New GET routes need a **full server restart** on deploy (hot-reload gotcha).

## 7. Cron entries

**None installed** for redeploy (verified `crontab -l`). The PR-5-era "cron complete" claim on main is
DOCUMENTED_ONLY; installer ships with the stack.

## 8. Open events + plan counts (top by recency)

#144 FCNTX $107,023 (open, **locked plan 8 v2 by a test lock, operator_status=reviewing — stale**),
#142 ARKQ $12,196, #143 LGPS $1,282, #141 NEE $900, #140 ELAB $1,433, #139 PFLT $7,374,
#138 ARKG $12,271, #134 SMCI $12,915 (fidelity), #135–#137 BJDX $4,470 total, #133 PEW $1,347 …
31 open total; **only #144 has any plans.**

## 9. Test/synthetic evidence contamination (read-only scan)

| Location | Finding | State |
|---|---|---|
| redeploy_stage_fills #1–#3 | 3 identical JEPQ fixture fills (`test_idempotent_record_fill` hit prod DB) | quarantined `environment=test`; **rows still present** |
| deploy_events #144 metadata | fixture marker + test plan-lock (locked_plan 8 v2, `reviewing`) | present — makes restoration metric (3%) and lock state **false** |
| hermes_outcome_ledger #77573–75 | 3 `redeploy_fill:→JEPQ stage1 planF` claims | verdict=pending — caught **before** learning graded them |
| deploy_plans | 0 fixture markers | clean |

**Cleanup is staged, not executed** — `scripts/maintenance/redeploy_fixture_cleanup_2026_07_13.sql`
+ `redeploy_fixture_cleanup_outcome_bus.py --apply` await explicit operator approval. Until then
event #144 shows stale restoration/lock state.

## 10. Operator decisions required

1. **Approve or amend the fixture cleanup** (unblocks event #144 truth).
2. **Merge the stack in order** #142 → #143 → #144 → #145 → #146 (all CI-green) — this is the
   platform your review found missing on main; re-review lands on the merged `/redeploy` workstation.
3. Then: full server restart (new GET routes), cron install, and acceptance re-verification against
   the Phase 11/13 gates (FCNTX A–G, ARKQ/ARKG/SMCI plans-or-blocked-state, fixture-free monitoring).
