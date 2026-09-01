# Designer Missing Files Report

Status:      HISTORICAL
as_of:       2026-05-25T11:54:23-04:00
Measured at: efcc51365 / not measured

## Summary

| Field | Value |
|-------|-------|
| Git branch | main |
| Git commit | d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421 |
| Export timestamp | 2026-05-25T11:42:04-04:00 |
| Total files requested | 52 |
| Total files exported | 43 |
| Total files missing | 9 |
| Total files empty | 0 |

## Exported Files

| Export Name | Original Path | Size | Purpose |
|-------------|---------------|------|---------|
| App.tsx.md | apps/command-center-v2/src/App.tsx | 14KB | Route registry, all lazy imports |
| main.tsx.md | apps/command-center-v2/src/main.tsx | 328B | React entry point |
| Shell.tsx.md | apps/command-center-v2/src/components/Shell.tsx | 13KB | Nav groups, sidebar, top bar, layout |
| theme.css.md | apps/command-center-v2/src/theme.css | 4.5KB | CSS variables, dark theme tokens |
| Shell.module.css.md | apps/command-center-v2/src/components/Shell.module.css | 6.3KB | Shell layout CSS modules |
| PageHeader.tsx.md | ...components/PageHeader.tsx | 847B | Page title + subtitle + actions |
| Card.tsx.md | ...components/Card.tsx | 1.9KB | Reusable card container |
| MetricTile.tsx.md | ...components/MetricTile.tsx | 2.6KB | Metric display tile |
| DetailDrawer.tsx.md | ...components/DetailDrawer.tsx | 2.4KB | Side drawer for details |
| GlobalAlertBanner.tsx.md | ...components/GlobalAlertBanner.tsx | 3.1KB | Top alert banners (stops, heat) |
| FreshnessBadge.tsx.md | ...components/FreshnessBadge.tsx | 1.8KB | Time-ago freshness indicator |
| TabPage.tsx.md | ...components/TabPage.tsx | 1.6KB | Tab container for hub pages |
| SectionHeader.tsx.md | ...components/SectionHeader.tsx | 960B | Section divider with title |
| Tooltip.tsx.md | ...components/Tooltip.tsx | 1.8KB | Hover tooltip |
| DataGrid.tsx.md | ...components/DataGrid.tsx | 4.3KB | Sortable data grid |
| ProgressBar.tsx.md | ...components/ProgressBar.tsx | 3.1KB | Progress bar component |
| ConfluenceBadge.tsx.md | ...components/ConfluenceBadge.tsx | 1.8KB | Confluence/agreement badge |
| AccountBadge.tsx.md | ...components/AccountBadge.tsx | 1.1KB | Account indicator |
| ToastProvider.tsx.md | ...components/ToastProvider.tsx | 1.9KB | Toast notification system |
| ProposalDetailDrawer.tsx.md | ...components/ProposalDetailDrawer.tsx | 13KB | Paper proposal detail drawer |
| AdminModals.tsx.md | ...components/AdminModals.tsx | 7.3KB | Admin action modals |
| AgentCollaboration.tsx.md | ...pages/AgentCollaboration.tsx | 17KB | Agent collaboration mission board |
| AgentPipeline.tsx.md | ...pages/AgentPipeline.tsx | 29KB | Agent pipeline dashboard |
| OpsHub.tsx.md | ...pages/OpsHub.tsx | 967B | Ops hub (tab container) |
| PipelineHub.tsx.md | ...pages/PipelineHub.tsx | 724B | Pipeline hub (tab container) |
| SystemHealth.tsx.md | ...pages/SystemHealth.tsx | 9.2KB | System health dashboard |
| TradeAI.tsx.md | ...pages/TradeAI.tsx | 40KB | Trade AI scored ticker view |
| Prospects.tsx.md | ...pages/Prospects.tsx | 25KB | Prospect discovery/filters |
| GovernanceHub.tsx.md | ...pages/GovernanceHub.tsx | 1.2KB | Governance hub (tab container) |
| SelfImprovement.tsx.md | ...pages/SelfImprovement.tsx | 9.8KB | Self-improvement command center |
| AgentCalibration.tsx.md | ...pages/AgentCalibration.tsx | 25KB | Agent calibration scorecards |
| useApi.ts.md | ...hooks/useApi.ts | 2.2KB | API fetch hook (unwraps envelope) |
| useFetch.ts.md | ...hooks/useFetch.ts | 720B | Simple fetch hook |
| format.ts.md | ...lib/format.ts | 1.9KB | Formatting utilities |
| types.ts.md | ...lib/types.ts | 1.9KB | Shared TypeScript types |
| morning-brief_*.md (8 files) | ...components/morning-brief/ | 26KB total | Morning brief sub-components |
| MorningBrief.module.css.md | ...morning-brief/MorningBrief.module.css | 4.7KB | Morning brief styles |

## Missing Files

These components do NOT exist as separate files. Badge/status/severity rendering is inline in each page component.

| Expected Path | Status | Notes |
|---------------|--------|-------|
| components/Badge.tsx | Does not exist | Badges are inline `<span>` in each page |
| components/StatusBadge.tsx | Does not exist | Status pills defined per-page |
| components/SeverityBadge.tsx | Does not exist | Severity colors hardcoded per-page |
| components/AgentChip.tsx | Does not exist | Agent chips defined inline in AgentCollaboration |
| components/Tabs.tsx | Does not exist | TabPage.tsx handles tab containers |
| components/Table.tsx | Does not exist | Tables are raw `<table>` in each page |
| components/Button.tsx | Does not exist | Buttons are inline `<button>` with per-page styles |
| components/Drawer.tsx | Does not exist | DetailDrawer.tsx is the closest |
| components/Modal.tsx | Does not exist | AdminModals.tsx handles modals |

**Key finding:** The app has NO shared badge/chip/status component library. Each page defines its own inline styles for badges, status indicators, severity colors, and agent chips. This is the #1 design system gap.

## Designer Instructions

1. Use files in `current_source_text/` as the source of truth for current implementation.
2. Put complete replacement files in `designed_replacements/`.
3. Do NOT edit production source files directly.
4. Each replacement must be a complete, working component — not a diff or partial.
5. Preserve all `useApi()` calls and endpoint paths unless backend changes are separately approved.
6. Preserve `import PageHeader`, `import Card`, and other shared component imports.
7. The `useApi` hook unwraps `{ ok, data }` envelopes — access data directly, NOT via `result?.data`.
