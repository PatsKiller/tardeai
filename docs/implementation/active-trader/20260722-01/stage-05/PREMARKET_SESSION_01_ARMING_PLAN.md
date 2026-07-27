# Premarket Observation — Session 1 Arming Plan

**Run:** 20260722-01 · **Session:** 1 of 5 · **Authorized:** 2026-07-23 (owner Session 1 execute prompt)
**Target trading date:** 2026-07-24 (Fri; qualifies — normal 09:30 open, 16:00 close)
**Current time at arming:** 2026-07-23 ~10:10 ET (past today's premarket window -> schedule tomorrow)

## Disposition: SCHEDULE_NEXT_TRADING_DAY (2026-07-24)
Today's premarket window (07:00-09:30) has passed, so Session 1 is scheduled for the next qualifying
session at preflight 06:55 ET / capture 07:00-10:05 ET on 2026-07-24.

## What is armed
- **Live capture wiring** (`premarket_observation_live.py`) — validated on real data (see
  LIVE_WIRING_VALIDATION). Data-only push handlers -> checksummed WAL -> zstd Parquet -> replay ->
  three-verdict evaluate. Self-cleaning teardown.
- **Owner authorization marker** (state dir, outside git; no secret) binding the exact scheduling
  HEAD, run_id, session 1, target 2026-07-24, window 07:00-10:05, symbols policy (US.AAPL baseline;
  representative rank source not wired under current entitlement -> suitability INSUFFICIENT_EVIDENCE
  expected), created/expires, owner_authorization_version.
- **One-shot transient user timer** at 06:55 ET 2026-07-24 running the launcher `--mode live` with the
  marker, under the isolated moomoo venv. User-level, transient, one-shot, no linger, no boot
  persistence, bounded runtime, logs in the lab state path.

## Symbols
US.AAPL (baseline). Representative momentum symbol NOT AVAILABLE (no accessible premarket-rank endpoint
under current data entitlement) -> LEVEL2_MOMENTUM_SUITABILITY will be INSUFFICIENT_EVIDENCE for
Session 1, which does NOT invalidate PREMARKET_TRANSPORT / RTH_CONTINUOUS_CAPTURE (the counting gates).

## Counting
Session 1 counts toward the five-session gate only if PREMARKET_TRANSPORT=PASS,
RTH_CONTINUOUS_CAPTURE=PASS, WAL/Parquet/replay=PASS, and safety/teardown=PASS. Verdict + closeout are
produced AFTER the capture completes (~10:05 ET 2026-07-24).

## Boundaries
Data-only. No trade context/account/order/unlock, no real 2FA, no SMS, no quote-right grab. No Session
2. Stages 12-13 untouched. Stage 14 not started.
