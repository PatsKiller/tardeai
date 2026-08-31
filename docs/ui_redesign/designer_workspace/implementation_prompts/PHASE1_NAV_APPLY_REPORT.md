# Phase 1 Navigation Apply Report

Status:      HISTORICAL
as_of:       2026-05-25T12:05:53-04:00
Measured at: efcc51365 / not measured

## Summary
Phase 1 navigation restructure applied successfully.

| Field | Value |
|-------|-------|
| Timestamp | 2026-05-25T12:05:42-04:00 |
| Git commit before | 17e3741fedb809e24f1b3c1d4b892480311f7c61 |
| Files changed | 1 (Shell.tsx) |
| Backup path | docs/ui_redesign/designer_workspace/backups/phase1_nav_apply_20260525_* |
| Old Shell.tsx SHA256 | 19ffdc2faf4b23533ea8f7edcf816730134bf39478385582157ac7a95b3b65b7 |
| New Shell.tsx SHA256 | 260cd8790336773cda4c35e854ea8b9e587ba89274b74421f74cc37bb41e1621 |
| Build result | PASS (321ms, 0 errors) |
| Route smoke test | PASS (11/11 routes return 200) |
| Playwright screenshots | PASS (47/47 captured) |

## Nav Before → After

| Before (10 groups) | After (12 groups) |
|---------------------|-------------------|
| Command (3) | Command (4) — +Agent Collaboration |
| — | **Trading (5)** — NEW |
| Portfolio (4) | Portfolio (4) |
| Risk & Alerts (4) | Risk & Alerts (4) |
| AI Analyst (4) | AI Analyst (4) |
| Research (5) | Research (5) |
| Pipeline & Health (4) | System & Pipeline (4) — renamed, +Ops, -Agent Collab |
| Paper Trading (5) | Paper Trading (5) — +Exec Quality, +Proposal Alerts, -Incubator, -ATM |
| Tax & Rebalance (3) | Tax & Rebalance (3) |
| Reports (3) | Reports (4) — +Backtesting |
| Admin (17) | **Learning & Improvement (3)** — NEW |
| — | Governance & Admin (7) — reduced from 17 |

## Pages Moved

| Page | From | To |
|------|------|----|
| Trade AI | Admin | Trading |
| Prospects | Admin | Trading |
| Strategy Desk | Admin | Trading |
| Incubator | Paper Trading | Trading |
| ATM Mode | Paper Trading | Trading |
| Self-Improvement | Admin | Learning & Improvement |
| Agent Calibration | Admin | Learning & Improvement |
| Weekly Learning | Admin | Learning & Improvement |
| Ops | Admin | System & Pipeline |
| Backtesting | Admin | Reports |
| Execution Quality | Admin | Paper Trading |
| Proposal Alerts | Admin | Paper Trading |
| Agent Collaboration | Pipeline & Health | Command |

## Rollback Commands

```bash
cp docs/ui_redesign/designer_workspace/backups/phase1_nav_apply_*/Shell.tsx apps/command-center-v2/src/components/Shell.tsx
cd apps/command-center-v2 && npm run build
```
