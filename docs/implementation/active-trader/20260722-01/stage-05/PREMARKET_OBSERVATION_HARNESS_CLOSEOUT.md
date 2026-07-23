# Premarket Observation Harness — Closeout

**Run:** 20260722-01 · **Branch:** feat/active-trader-next · **Date:** 2026-07-23
**Controller:** BUILD THE PREMARKET OBSERVATION HARNESS v1.1

## State: GREEN_OBSERVATION_HARNESS_READY

The missing Stage 5 premarket + open observation infrastructure is built, tested, and safe. This does
NOT complete Stage 5 validation and does NOT change Stage 12 (CONDITIONAL_PASS) or Stage 13
(GREEN_CLOSED_PROMOTION_BLOCKED). No live evidence is claimed.

## Delivered
- **Exchange calendar** (2026-2027, fail-closed, DST-aware, early-close labeled, observation
  qualification): `market_calendar.py`.
- **Observation core** (windows, extended event envelope, Level 2 metrics with labeled inferred
  replenishment/cancellation, cross-checks, versioned verdict policy + 3-verdict engine, data-only
  adapter Protocol, exact-SDK extended-hours request, deterministic controller state machine):
  `premarket_observation.py`.
- **Representative-symbol selector** (pure, read-only, informational): `premarket_symbol_selector.py`.
- **Scheduler renderer + authorization marker** (dry-run only; live refuses without owner marker):
  `premarket_observation_schedule.py`.
- **Thin composition root**: `run_active_trader_premarket_observation.py`.
- **Tests**: 55 focused (calendar/observation/selector/schedule) + WAL/Parquet round-trip.

## Verification
- Focused: 55 passed (prod venv); 63 passed / 1 skipped (lab venv, incl. pyarrow round-trip).
- Full Active Trader regression: 216 passed, 53 skipped, 0 failed.
- Trade-API AST scan: 35 modules + run-root -> 0 findings. Network + production-target scans clean.
- run-root: `--mode dry-run` renders without scheduling; `--execute-schedule` ->
  NOT_AUTHORIZED_BY_BUILD_TRANSACTION; `--mode live` -> BLOCKED_OWNER_AUTHORIZATION_REQUIRED.

## Boundaries held
No Moomoo network/OpenD/login/subscribe/SMS/trade context/order/unlock; no scheduler invocation; no
timer created; no production change; no /v3 change; no PR merge; Stage 12/13 untouched; no Stage 14.

## Current gate posture (unchanged by this build)
Session 1 NOT_RUN · completed sessions 0/5 · continuous capture PENDING · premarket suitability
UNPROVEN · Stage 9 promotion BLOCKED · Stage 10 promotion BLOCKED · BF-1 UNPROVEN · live Moomoo
scalping BLOCKED.

## Next action
A separately authorized observation prompt supplies the owner authorization marker and (only then)
schedules + runs Session 1 during an open, qualifying trading session.
