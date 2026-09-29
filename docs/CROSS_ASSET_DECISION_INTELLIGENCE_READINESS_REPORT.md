# Cross-Asset Decision Intelligence Readiness Report

Status: INTERIM — NOT READY (acceptance gates green; product readiness gates remain open)
Owner: QA / CIO operations
as_of: 2026-09-29
Measured at: repair working tree after full acceptance rerun; commit recorded below
Authority: advisory only; no broker, order, sizing, deployment, or trade authority

## Decision

**Go-live recommendation: NOT READY.**

The contract, identity conflict handling, routing primitives, deterministic
ranking, offline replay, and offline shadow harness are implemented and tested.
The system is not ready for production because the routing layer is not yet
connected to every live signal producer, the API/UI are not integrated, the
continuous scheduler-backed shadow run is not installed or proven, and 30/60/90
day historical validation has not been run against authoritative data.

## Gate status

| Gate | Result | Evidence |
|---|---|---|
| Architecture contract | PASS — Phase 1 slice | `4e39b4103` |
| Identity linking | PASS — library slice | `511d8dda2` |
| Options routing | PASS — offline matrix | `511d8dda2` |
| Event reevaluation | NOT COMPLETE | No governed live consumer lane |
| Missed-opportunity accounting | PASS — initial coverage row | `511d8dda2` |
| Ranking | PASS — deterministic fact-gated ranking | `511d8dda2` |
| UI/API integration | NOT COMPLETE | No runtime surface change |
| Offline shadow harness | PASS | `f1d5b1546`; 11 tests |
| Continuous shadow mode | NOT COMPLETE | Scheduler not installed/observed |
| Historical 30/60/90 replay | NOT RUN | Runtime/API/database data unavailable |
| Production recommendation | NOT READY | Required gates remain open |

## Tests and metrics

- Cross-asset targeted tests: 11 passed.
- Python compilation: passed.
- Ruff on changed Python: passed.
- New test registration: 0 unlisted tests.
- Documentation index test: 7 passed.
- Documentation index check: passed.
- Secret scan: passed across 9,271 files.
- Full local acceptance: all selected gates pass after repairing two
  environment-sensitive tests. The full profile reported 2,068 maturity tests
  passed, 2 skipped, `cc_header_truth_v2` 119 passed, and
  `overnight_g6_missing_stores` 7 passed. The dedicated repaired-failure set
  passed 23/23. The host `notifications.outbox` file was preserved; G6 now
  verifies read-only reporting and no revival rather than treating pre-existing
  host state as a test failure.

## Known risks

- The comparison engine currently receives caller-supplied facts; it is not yet
  the authoritative consumer of live portfolio/watchlist/CIO/research events.
- A score is only as trustworthy as its supplied facts; no production calibrated
  expected-value model is claimed by this tranche.
- No historical outcome metrics exist for this feature.
- The local API socket was unavailable from the sandbox and the host crontab was
  unreadable, so live cadence and runtime coverage were not independently proven.

## Required before readiness can change

1. Connect canonical identity and signal producers.
2. Register and observe the event-consumer lane.
3. Add API projection and Command Center UI with freshness/conflict states.
4. Run continuous shadow mode with durable receipts and zero side effects.
5. Replay authoritative 30/60/90-day snapshots without future leakage.
6. Keep the full acceptance environment reproducible, including canonical Ruff
   discovery and read-only host-state checks.
7. Obtain independent review of the ranking and governance boundaries.
