# Cross-Asset Decision Intelligence Readiness Report

Status: INTERIM — NOT READY
Owner: QA / CIO operations
as_of: 2026-09-29
Measured at: local branch `d7d86a29ba99ec647a3a7a5b7c47fe6f36e3d7f6` before this evidence update
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
- Full local acceptance: not green for two unrelated environment/host-state
  gates. With the process restriction lifted, the bridge regression passed 11/11
  and the full maturity suite passed 2,068 tests. Remaining failures were:
  - `cc_header_truth_v2`: `/usr/bin/python3 -m ruff` unavailable; Ruff passed
    from the tooling virtualenv and no changed API file was implicated.
  - `overnight_g6_missing_stores`: host persistent state contains
    `notifications.outbox`; this is pre-existing host state and was not deleted.
  The docs-index failures were corrected and the dedicated docs suite passed 7/7.

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
6. Resolve the full-acceptance environment failures or prove they are unrelated
   in a separately recorded acceptance environment.
7. Obtain independent review of the ranking and governance boundaries.
