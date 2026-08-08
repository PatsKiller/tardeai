# CIO Financial Schedule Policy

**Document ID:** CIO-FIN-SCHED-001  
**Version:** 1.0.0  
**Status:** DRAFT — AWAITING AUTHORIZE_P2_SHADOW_AUTONOMY  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08

## 1. Purpose

This document defines the authoritative Trade AI financial schedule policy. It replaces all legacy Alex cron schedules with Trade AI-governed wake-based scheduling. Every schedule has exactly one owner (Trade AI CIO Agent) and one trigger (CIO Event Detector).

## 2. Design Principle

**ONE trigger, ONE owner.** No financial advisory schedule is triggered by OpenClaw cron. No specialist has an independent cron schedule. All advisory cycles originate from the CIO wake store, are dispatched by the CIO Wake Dispatcher, and are executed by the CIO Run Worker.

## 3. Approved Schedule Classes

### 3.1 Daily CIO Brief (SCHEDULED_DAILY)

| Field | Value |
|-------|-------|
| **Schedule ID** | `tradeai_cio_daily` |
| **Trigger** | CIO Event Detector, daily at 05:00 ET Mon-Fri |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector._check_schedules()` |
| **Run Worker** | `CIORunWorker` (budget: `daily_brief`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.02 per run |
| **Domains** | portfolio, holdings, performance, risk |
| **Legacy Equivalent** | `alex_daily` (cron: `0 5 * * 1-5`) |
| **Retirement Plan** | Legacy cron disabled; Alex daily script retained as read-only reference |

### 3.2 Weekly CIO Review (SCHEDULED_WEEKLY)

| Field | Value |
|-------|-------|
| **Schedule ID** | `tradeai_cio_weekly` |
| **Trigger** | CIO Event Detector, weekly Sunday at 08:00 ET |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector._check_schedules()` |
| **Run Worker** | `CIORunWorker` (budget: `weekly_review`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.05 per run |
| **Domains** | portfolio, allocation, retirement |
| **Legacy Equivalent** | `alex_weekly` (cron: `0 8 * * 0`) |
| **Retirement Plan** | Legacy cron disabled; script preserved as reference |

### 3.3 Monthly Wealth Review (SCHEDULED_DAILY, monthly cadence)

| Field | Value |
|-------|-------|
| **Schedule ID** | `tradeai_cio_monthly` |
| **Trigger** | CIO Event Detector, 1st of month at 09:00 ET |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector._check_schedules()` |
| **Run Worker** | `CIORunWorker` (budget: `monthly_review`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.08 per run |
| **Domains** | tax, retirement, allocation, medicaid |
| **Legacy Equivalent** | `alex_monthly` (cron: `0 9 1 * *`) |
| **Retirement Plan** | Legacy cron disabled; script preserved as reference |

### 3.4 Action Follow-up (ACTION_FOLLOWUP_DUE — event-driven)

| Field | Value |
|-------|-------|
| **Schedule ID** | Event-driven — no fixed schedule slot |
| **Trigger** | CIO Event Detector detects due follow-up from action ledger |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector._check_action_followups()` |
| **Run Worker** | `CIORunWorker` (budget: `action_followup`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.02 per run |
| **Domains** | Determined by action domain |
| **Legacy Equivalent** | N/A (new capability) |

### 3.5 Material Event (HEALTH_EVENT — event-driven)

| Field | Value |
|-------|-------|
| **Schedule ID** | Event-driven — triggered by health boundary |
| **Trigger** | CIO Event Detector detects health block/clearance |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector` (health transitions — future) |
| **Run Worker** | `CIORunWorker` (budget: `material_event`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.03 per run |
| **Domains** | Affected health domains |
| **Legacy Equivalent** | N/A (new capability) |

### 3.6 Operator-Requested Review (OPERATOR_MESSAGE)

| Field | Value |
|-------|-------|
| **Schedule ID** | On-demand — operator message triggers handoff |
| **Trigger** | Inbound operator message creates a handoff from Alex |
| **Owner** | Trade AI CIO Agent |
| **Wake Detector** | `CIOEventDetector._check_handoff_completions()` |
| **Run Worker** | `CIORunWorker` (budget: `operator_request`) |
| **Allowed Autonomy** | Shadow advisory only (Phase 2) |
| **Max Cost** | $0.05 per run |
| **Domains** | As requested by operator |

## 4. Legacy Schedule Retirement Plan

| Legacy Schedule | Legacy Cron | Trade AI Replacement | Retirement Status |
|----------------|-------------|---------------------|-------------------|
| `alex_daily` | `0 5 * * 1-5` | `tradeai_cio_daily` | Pending P2 authorization |
| `alex_weekly` | `0 8 * * 0` | `tradeai_cio_weekly` | Pending P2 authorization |
| `alex_monthly` | `0 9 1 * *` | `tradeai_cio_monthly` | Pending P2 authorization |
| `alex_hygiene` | `15 7 * * 1-5` | Health boundary continuous (no cron) | Pending P2 authorization |
| `alex_gov_research` | `0 6 * * 1` | Hermes challenge on material events | Pending P2 authorization |

**Retirement procedure:**
1. Disable legacy crontab entry
2. Verify Trade AI wake detector produces equivalent wake
3. Run one cycle in shadow alongside legacy
4. Confirm no gaps for 3 cycles
5. Remove legacy script from active cron

## 5. Budget Caps

All runs are subject to the global daily cap of **$0.25**.

| Workload Class | Max Calls | Max Cost | Max Specialists | Max Hermes | Max Wall Time |
|---------------|-----------|----------|----------------|------------|---------------|
| daily_brief | 4 | $0.02 | 2 | 0 | 5 min |
| weekly_review | 8 | $0.05 | 4 | 2 | 10 min |
| monthly_review | 12 | $0.08 | 4 | 2 | 15 min |
| action_followup | 4 | $0.02 | 2 | 1 | 5 min |
| material_event | 6 | $0.03 | 3 | 2 | 8 min |
| operator_request | 8 | $0.05 | 4 | 2 | 10 min |

## 6. Excluded from This Policy

- **No OpenClaw cron** for any financial advisory schedule
- **No specialist independent cron** — all specialist routing goes through CIO run worker
- **No OpenClaw financial heartbeat** — health monitoring is through CIO health boundary
- **No direct model calls** outside the governed bridge

## 7. Rollback Procedure

1. Disable Trade AI wake dispatcher
2. Re-enable legacy crontab entries
3. Verify legacy Alex scripts functional
4. Audit CIO wake store for any in-flight wakes (complete or cancel them)
5. Confirm zero cost for in-flight Trade AI runs

## 8. Authorization Gates

| Gate | Status | Required For |
|------|--------|-------------|
| `AUTHORIZE_P2_SHADOW_AUTONOMY` | AWAITING | Shadow autonomous advisory cycles |
| `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY` | AWAITING | Live Telegram notification delivery |
| `AUTHORIZE_P2_RESTART_ACCEPTANCE` | AWAITING | Restart/recovery procedures |
