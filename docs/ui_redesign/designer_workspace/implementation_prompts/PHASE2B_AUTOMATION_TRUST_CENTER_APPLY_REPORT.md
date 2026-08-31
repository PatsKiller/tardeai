# Phase 2b Automation Trust Center — Apply Report

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

## Summary
4 pages redesigned as the Automation Trust Center family. All use shared primitives.

| Field | Value |
|-------|-------|
| Timestamp | 2026-05-25T14:00:01-04:00 |
| Git commit before | 52601c8 |
| Files changed | 4 page files |
| Build | PASS (259ms, 0 errors) |
| Smoke test | PASS (9/9 routes return 200) |
| Playwright | PASS (47/47 screenshots) |

## Files Changed

| File | Old Hash | New Size |
|------|----------|----------|
| OpsHub.tsx | 662fa85e... | 1,204 bytes |
| PipelineHub.tsx | 58a46df8... | 909 bytes |
| SystemHealth.tsx | f2ed0311... | 9,420 bytes |
| AgentPipeline.tsx | 184f18a8... | 28,645 bytes |

## Changes Per Page

| Page | Title Before | Title After | Primitives Used |
|------|-------------|-------------|-----------------|
| OpsHub | Operations | **Automation Trust Center** | (tab wrapper) |
| PipelineHub | Pipeline Operations | **Pipeline Health** | (tab wrapper) |
| SystemHealth | System Health | **System Health & Services** | StatusBadge, ActionButton |
| AgentPipeline | Agent Pipeline | **Agent Pipeline & Queue** | StatusBadge, SeverityBadge, AgentChip, ActionButton, StateCard |

## Build Fix Applied
Agent created replacements used wrong prop names (label= instead of children, agent= instead of name=). Fixed during apply:
- AgentChip: agent= → name= (13 occurrences)
- ActionButton: label= → children (3 occurrences)
- StateCard: label= → title= (4 occurrences)

## Rollback
```bash
git checkout HEAD -- apps/command-center-v2/src/pages/{OpsHub,PipelineHub,SystemHealth,AgentPipeline}.tsx
cd apps/command-center-v2 && npm run build
```
