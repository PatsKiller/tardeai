# Premarket Observation Harness — Plan

**Run:** 20260722-01 · **Branch:** feat/active-trader-next · **Controller:** BUILD THE PREMARKET OBSERVATION HARNESS v1.1 · **Date:** 2026-07-23

## Purpose
Build the missing Stage 5 premarket + open observation infrastructure so the five-RTH observation
(the hard gate for Stage 9 acceptance / Stage 10 promotion) can later be run. This transaction is a
BUILD ONLY: it does not schedule Session 1, start OpenD, log in, subscribe live, or count a session.

## Deliverables
- Exchange-calendar gate (2026-2027, fail-closed) with observation qualification.
- 07:00-10:05 ET observation controller state machine (deterministic, injected deps).
- P1/P2/P3/R1/R2 window accounting with stale/gap/startup/cached exclusions.
- Extended-hours quote/ticker/kline subscription request (exact pinned SDK args).
- Level 2 quality metrics + quote/ticker/kline cross-checks.
- Representative-symbol selector (pure, read-only, informational).
- WAL/Parquet/replay integration (reuses Stage 5 replay module).
- One-shot transient user-timer RENDERER (dry-run only; never schedules).
- Live executable that refuses without an owner authorization marker.
- Fixture-based tests + documentation.

## Non-goals (hard prohibitions honored)
No Moomoo network/OpenD/login/subscribe/SMS/trade context/order/unlock; no scheduler invocation;
no transient/persistent timer creation; no production DB/service/flag change; no /v3 change; no PR
merge; no Stage 12/13 rerun; no Stage 14.

## Layout (flat scripts/active_trader/ per controller §5; reuses moomoo/ subpackage)
- scripts/active_trader/market_calendar.py
- scripts/active_trader/premarket_observation.py
- scripts/active_trader/premarket_symbol_selector.py
- scripts/active_trader/premarket_observation_schedule.py
- scripts/run_active_trader_premarket_observation.py (thin composition root)
- tests/test_active_trader_{market_calendar,premarket_observation,premarket_symbol_selector,premarket_schedule}.py

## Terminal state
GREEN_OBSERVATION_HARNESS_READY (does NOT change Stage 12 CONDITIONAL_PASS or Stage 13
GREEN_CLOSED_PROMOTION_BLOCKED; does NOT claim any live evidence).
