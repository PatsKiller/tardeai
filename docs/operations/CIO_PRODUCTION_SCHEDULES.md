# CIO Production Schedules — Operations Plan

**Document ID:** CIO-OPS-SCHED-001  
**Version:** 1.0.0  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08  
**Status:** AWAITING AUTHORIZE_P2_SHADOW_AUTONOMY

## 1. Active Financial Schedules (Trade AI)

| Schedule ID | Type | Slot | Trigger | Wake Dispatch | Run Worker | Autonomy | Max Cost |
|------------|------|------|---------|---------------|------------|----------|----------|
| `tradeai_cio_daily` | daily | 05:00 ET Mon-Fri | CIOEventDetector | CIOWakeDispatcher | daily_brief | shadow | $0.02 |
| `tradeai_cio_weekly` | weekly | 08:00 ET Sun | CIOEventDetector | CIOWakeDispatcher | weekly_review | shadow | $0.05 |
| `tradeai_cio_monthly` | monthly | 09:00 ET 1st | CIOEventDetector | CIOWakeDispatcher | monthly_review | shadow | $0.08 |
| Action follow-up | event-driven | On due | CIOEventDetector | CIOWakeDispatcher | action_followup | shadow | $0.02 |
| Material event | event-driven | On trigger | CIOEventDetector | CIOWakeDispatcher | material_event | shadow | $0.03 |
| Operator request | on-demand | On request | CIOEventDetector | CIOWakeDispatcher | operator_request | shadow | $0.05 |

## 2. Legacy Schedule Retirement Plan

| Legacy Schedule | Legacy Cron | Replacement | Status |
|----------------|-------------|-------------|--------|
| alex_daily | 0 5 * * 1-5 | tradeai_cio_daily | Awaiting auth |
| alex_weekly | 0 8 * * 0 | tradeai_cio_weekly | Awaiting auth |
| alex_monthly | 0 9 1 * * | tradeai_cio_monthly | Awaiting auth |
| alex_hygiene | 15 7 * * 1-5 | Health boundary continuous | Awaiting auth |
| alex_gov_research | 0 6 * * 1 | Hermes challenge on material | Awaiting auth |

## 3. Exclusions

- NO OpenClaw cron for any financial advisory schedule
- NO specialist independent cron — all routing via CIO run worker
- NO OpenClaw financial heartbeat
- NO direct model calls outside governed bridge

## 4. Rollback Procedure

1. Disable Trade AI wake dispatcher
2. Re-enable legacy crontab entries
3. Verify legacy scripts functional
4. Audit CIO wake store for in-flight wakes
5. Confirm zero cost for in-flight Trade AI runs

## 5. Config Diffs (Prepared, NOT Applied)

### Trade AI Financial Schedule Config
```
[cio.schedules]
tradeai_cio_daily.enabled = true
tradeai_cio_daily.trigger = "CIOEventDetector"
tradeai_cio_daily.dispatcher = "CIOWakeDispatcher"
tradeai_cio_daily.worker = "daily_brief"
tradeai_cio_weekly.enabled = true
tradeai_cio_monthly.enabled = true

[cio.schedules.legacy]
alex_daily.enabled = false
alex_weekly.enabled = false
alex_monthly.enabled = false
alex_hygiene.enabled = false
alex_gov_research.enabled = false
```

### Wake Dispatcher Config
```
[cio.dispatcher]
poll_interval_seconds = 60
max_dispatches_per_poll = 5
dispatch_ledger = "data/cio/cio_wake_dispatches.jsonl"
```

### Alex Governed Route Activation
```
CIO_BRIDGE_MODE = "canary"  # P-1.2B real provider
```

## 6. Canary Definitions

45 Phase 2 canaries defined. See PHASE_2_CANARY_MATRIX.md for full matrix.

Key categories:
- P2-RUN: CIO run lifecycle (deterministic)
- P2-SNAP: Financial snapshot (deterministic/static)
- P2-SPEC: Specialist routing (shadow)
- P2-HERMES: Hermes challenge (shadow)
- P2-COMMS: Communication delivery (shadow)
- P2-BUDGET: Budget enforcement (structural)
- P2-REC: Restart/recovery (structural)
- P2-PROD: Production schedules (structural)
