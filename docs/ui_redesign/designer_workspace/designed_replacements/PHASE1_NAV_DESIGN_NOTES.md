# Phase 1 Navigation Redesign — Design Notes

## Date
2026-05-25

## Summary
Reorganized NAV_GROUPS from 10 groups (with a 17-item Admin dumping ground) to 12 focused groups. No other code was changed — imports, API calls, NavDropdown, TapeMetric, GlobalAlertBanner, AdminModals, and all styling are identical.

## What Changed
Only the `NAV_GROUPS` constant array (lines 21-95 of original Shell.tsx).

- **Before:** 10 groups, 52 nav items, Admin had 17 items
- **After:** 12 groups, 52 nav items, Governance & Admin has 7 items

## What Did NOT Change
- Imports (all identical)
- Type definitions (OverviewMini, NavItem, NavGroup)
- fmtDollar utility function
- NavDropdown component (all behavior preserved)
- Shell component (layout, header, tape, drawer, all identical)
- TapeMetric component
- GlobalAlertBanner
- AdminModals
- Shell.module.css (not touched)
- Route paths (every `/to` value is unchanged)
- API calls (/api/v2/overview, /api/v2/risk-regime/status)
- Approvals badge behavior

## Pages Moved Out of Admin (17 → 7)

| Page | Was In | Now In |
|------|--------|--------|
| Trade AI Live | Admin | **Trading** |
| Prospects | Admin | **Trading** |
| Strategy Desk | Admin | **Trading** |
| Self-Improvement | Admin | **Learning & Improvement** |
| Agent Calibration | Admin | **Learning & Improvement** |
| Weekly Learning | Admin | **Learning & Improvement** |
| Operations (Ops) | Admin | **System & Pipeline** |
| Backtesting | Admin | **Reports** |
| Execution Quality | Admin | **Paper Trading** |
| Proposal Alerts | Admin | **Paper Trading** |

## Pages Moved Into Trading (NEW group)

| Page | Source |
|------|--------|
| Trade AI | was Admin |
| Prospects | was Admin |
| Strategy Desk | was Admin |
| Incubator | was Paper Trading |
| ATM Mode | was Paper Trading |

## Pages Moved Into Learning & Improvement (NEW group)

| Page | Source |
|------|--------|
| Self-Improvement | was Admin |
| Agent Calibration | was Admin |
| Weekly Learning | was Admin |

## Pages Moved Into System & Pipeline (renamed from Pipeline & Health)

| Page | Source |
|------|--------|
| Ops Center | was Admin |
| Pipeline Stages | was Pipeline & Health |
| System Health | was Pipeline & Health |
| Agent Pipeline | was Pipeline & Health |

Note: Agent Collaboration moved OUT of Pipeline & Health into Command.

## Pages Moved Into Reports

| Page | Source |
|------|--------|
| Backtesting | was Admin |

## Pages Moved Into Paper Trading

| Page | Source |
|------|--------|
| Execution Quality | was Admin |
| Proposal Alerts | was Admin |

## What Stayed in Governance & Admin (7 items)

| Page | Reason |
|------|--------|
| Governance Hub | Policy/rules — low-frequency |
| Strategy Admin | Config — low-frequency |
| Strategy Analytics | Analytics — low-frequency |
| Correlation | Analysis tool — low-frequency |
| Forecast | Analysis tool — low-frequency |
| Broker Recon | Reconciliation — low-frequency |
| Plan vs Perf | Analysis — low-frequency |

## Command Group Changes

| Page | Change |
|------|--------|
| Command Center | renamed from "Morning Command" |
| Agent Collaboration | moved here from Pipeline & Health |
| Inbox | stayed |
| Daily Brief | stayed |

## Route Path Verification

Zero route paths changed. Every `/to` value in the new NAV_GROUPS matches an existing `<Route path="">` in App.tsx. No broken links.

## Production Source Status

**Production file NOT changed.** The replacement exists only at:
`docs/ui_redesign/designer_workspace/designed_replacements/Shell.tsx.REPLACEMENT.md`

To apply, use the implementation prompt template at:
`docs/ui_redesign/designer_workspace/implementation_prompts/CLAUDE_APPLY_DESIGNER_REPLACEMENTS_TEMPLATE.md`
