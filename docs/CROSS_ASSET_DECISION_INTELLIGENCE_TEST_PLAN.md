# Cross-Asset Decision Intelligence Test Plan

Status: PROPOSED — baseline before implementation
Owner: QA / platform intelligence
as_of: 2026-09-29
Measured at: `5ba5d99ec06568f61f4db3a7010f01343023104`

## Test policy

All tests are local, deterministic, network-free, broker-free, and isolated from
live stores. Every stateful producer requires behaviour, refusal, and
preservation-on-failure coverage. Historical tests use frozen fixtures and must
prove no future observation is read.

## Unit tests

- `SymbolDecisionObject@v1` required fields, enums, timestamps, and versioning.
- Identity normalization, unresolved identity, conflicting identity, and alias handling.
- Signal normalization for BUY, STRONG_BUY, ADD, ADD_ON_PULLBACK, REENTRY,
  ENTRY_NEAR, CONVICTION, HOLD, MONITOR, HEDGE, SELL, TRIM, REDUCE, EXIT.
- Expression candidate generation and unsupported-structure refusal.
- Deterministic evaluation IDs and stable ranking ties.
- Explicit unavailable/stale data propagation.

## Integration tests

- Portfolio + watchlist + re-entry + thesis records produce one joined object.
- Source disagreement produces a conflict state rather than silent precedence.
- Options proposal facts enter the comparison without creating an approval.
- CIO and Hermes references remain traceable to source IDs.
- Aegis advisory output cannot become CIO approval.

## Scheduler tests

- Trigger intake is idempotent.
- Duplicate events do not create duplicate evaluations.
- Out-of-order events preserve latest valid state and record the conflict.
- Scheduler refusal is durable and observable.
- Lane registry entry names owner, cadence, state, and output store.

## Persistence tests

- Append-only writes and hash-chain continuity.
- Replay from empty store reproduces the same projection.
- Corrupt row fails closed without truncating prior rows.
- Failed write preserves the prior valid projection.
- Tests cannot write production state roots or live M2.

## CIO and research tests

- Missing thesis creates research work, not an approval.
- `MORE_RESEARCH` schedules a follow-up at 24 hours.
- `MONITOR_ONLY` schedules a 24-hour re-review.
- `REJECT` remains final.
- Hermes completion changes the next evaluation and cites the research ID.
- Aegis disagreement is visible but non-authoritative.

## Option-routing tests

- BUY: shares/CSP/long call/bull call spread comparison.
- HOLD: shares/covered call/protective put/collar comparison.
- REENTRY: shares/CSP/spread comparison.
- HEDGE: protective put/put spread/collar comparison.
- SELL/TRIM: sell/collar/protective structure comparison.
- Liquidity, OI, spread, earnings, IV, position-size, and quote-age gates fail closed.
- Estimated quotes cannot become live-eligible.
- No candidate is ranked as winner if it is hard-blocked.

## Re-entry and watchlist tests

- Re-entry event links to prior ownership and exit evidence.
- ENTRY_NEAR and ADD_ON_PULLBACK route to the expected comparison set.
- WATCH/MONITOR produces a review/no-action comparison rather than an implicit buy.
- Watchlist membership changes trigger reevaluation.

## Historical replay tests

- 30-, 60-, and 90-day fixtures replay with no future leakage.
- Same input snapshot produces byte-equivalent output.
- Missing source rows are counted as missing coverage.
- Outcomes are joined only after their observation timestamp.
- Historical comparisons do not mutate live stores.

## Regression and acceptance gates

- Existing options, CIO, research, re-entry, watchlist, identity, and authority suites remain green.
- New tests are registered in `scripts/run_cio_hardening_ci.py` and `scripts/check_test_coverage.py`.
- Changed Python files pass Ruff directly.
- `git diff --check` passes.
- `scripts/check_no_secrets.py --tree` passes.
- Relevant local acceptance passes; environment-dependent failures are recorded, not hidden.

## Evidence artifacts

- `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`
- `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`
- `docs/CROSS_ASSET_DECISION_INTELLIGENCE_READINESS_REPORT.md`
- `reports/cross_asset_decision_intelligence/` replay and shadow receipts
- append-only shadow evaluation receipt with input/output hashes

## Phase 1 execution record

Status: COMPLETE
Date: 2026-09-29
Commit: `4e39b4103193784950377d8c00a5fc1d05c096fd`

Evidence:

- 6/6 Phase 1 tests passed.
- Python compilation passed.
- Ruff passed on changed Python files.
- New test was registered in the CIO hardening gate; coverage reported 0 new unlisted tests.
- Diff hygiene passed.

## Extended implementation record

Status: COMPLETE for offline contract/routing/replay slice
Date: 2026-09-29
Commits: `511d8dda2da78925fa987b9b40fd4ca957bf07ac`, `1d440dd2382555541aad60cae21e740f41c47b9b`

Evidence:

- 10/10 cross-asset tests passed.
- Source conflicts fail visibly instead of selecting a winner silently.
- Hard liquidity, OI, spread, earnings, quote-age, and position-size facts block candidates.
- Unblocked scored candidates are ranked deterministically.
- Offline replay sorts events by observation time and requires identity coverage.
- Replay writes only the explicitly requested output path.

Not yet evidenced: live scheduler consumption, API/UI integration, and 30/60/90-day
production-history replay.
