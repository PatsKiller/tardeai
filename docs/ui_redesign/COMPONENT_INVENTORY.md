# Component Inventory

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25
Source: `apps/command-center-v2/src/components/`

---

## Shared Components (Top-Level)

| Component | File | Purpose | Used By |
|-----------|------|---------|---------|
| Shell | Shell.tsx + Shell.module.css | App shell: header tape, nav bar, drawer, mobile responsive | App.tsx (root layout) |
| AdminModals | AdminModals.tsx | Personal situation modal (age, SSDI, accounts) | Shell |
| AgentModal | AgentModal.tsx | Agent detail modal popup | Various agent pages |
| BarChart | BarChart.tsx | Simple bar chart component | Various |
| Card | Card.tsx | Standard card wrapper with border/background | ~20+ pages |
| ConfluenceBadge | ConfluenceBadge.tsx | Signal confluence indicator badge | TradeAI, Prospects |
| DataGrid | DataGrid.tsx | Sortable data grid/table | Multiple pages |
| DetailDrawer | DetailDrawer.tsx | Slide-out detail panel (DrawerStat, DrawerSection) | TradeAI, PaperProposals |
| EscalationLadder | EscalationLadder.tsx | Risk escalation visualization | Agent pages |
| FreshnessBadge | FreshnessBadge.tsx | Data freshness indicator | Intelligence pages |
| GlobalAlertBanner | GlobalAlertBanner.tsx | Top-of-page alert banner | Shell (always rendered) |
| ImportModal | ImportModal.tsx | Data import modal | Intelligence |
| MetricTile | MetricTile.tsx | KPI metric display tile | Overview, TradeAI, Risk |
| OpenTradesCard | OpenTradesCard.tsx | Open paper trades card | Paper pages |
| PageHeader | PageHeader.tsx | Page title + subtitle + actions bar | ~30+ pages |
| PeriodReturnBars | PeriodReturnBars.tsx | Period return bar visualization | Returns, Portfolio |
| ProgressBar | ProgressBar.tsx | Progress bar component | Various |
| ProposalDetailDrawer | ProposalDetailDrawer.tsx | Paper proposal detail panel | PaperProposals |
| RACIMatrix | RACIMatrix.tsx | RACI responsibility matrix | Agent pages |
| ScalpLiveFeed | ScalpLiveFeed.tsx | Live scalp feed ticker | TradeAI |
| ScreenerConfigModal | ScreenerConfigModal.tsx | Screener configuration editor | Intelligence |
| SectionHeader | SectionHeader.tsx | Section divider with title | Multiple |
| TabPage | TabPage.tsx | Tab container for hub pages | 8 hub pages |
| TaskDetailDrawer | TaskDetailDrawer.tsx | Task detail slide-out | ActionCenter |
| ToastProvider | ToastProvider.tsx | Toast notification system | Various |
| Tooltip | Tooltip.tsx | Hover tooltip component | Various |
| WatchlistSymbolPanel | WatchlistSymbolPanel.tsx | Watchlist symbol detail panel | Watchlist |
| AccountBadge | AccountBadge.tsx | Account type badge (Roth/SSDI/etc.) | Portfolio, Proposals |

## Sub-Component Directories

### components/charts/
| Component | Purpose |
|-----------|---------|
| BarChartJS.tsx | Chart.js bar chart wrapper |
| DoughnutChart.tsx | Chart.js doughnut chart |
| LineChart.tsx | Chart.js line chart |
| index.ts | Re-exports |

### components/morning-brief/
| Component | Purpose |
|-----------|---------|
| DecisionQueueRail.tsx | Decision queue sidebar rail |
| MorningBrief.module.css | Morning brief styles |
| MorningCommandStrip.tsx | Morning command strip component |
| OpportunityPanel.tsx | Opportunity display panel |
| PriorityActionBoard.tsx | Priority action board |
| RiskExposurePanel.tsx | Risk exposure panel |
| TrustStrip.tsx | Trust/confidence strip |
| types.ts | Morning brief type definitions |

### components/ai-analyst/
| Component | Purpose |
|-----------|---------|
| PositionCard.tsx | AI analyst position card |
| StrategyCard.tsx | AI analyst strategy card |

### components/shared/
| Component | Purpose |
|-----------|---------|
| AddYouTubeChannelModal.tsx | YouTube channel addition modal |
| SmartTextarea.tsx | LLM-enhanced textarea with rewrite |

## Hooks

| Hook | File | Purpose |
|------|------|---------|
| useApi | hooks/useApi.ts | API fetch with envelope unwrap, retry, polling |
| useFetch | hooks/useFetch.ts | Generic fetch hook |

## Lib

| Module | File | Purpose |
|--------|------|---------|
| format | lib/format.ts | Dollar formatting, delta colors, number formatting |
| types | lib/types.ts | Shared type definitions |

## Types

| File | Purpose |
|------|---------|
| types/speech.d.ts | Web Speech API type declarations |

## Page Components (89 files in pages/)

Active page components: ~55
Legacy/unused: ~5
Backup files (.bak): 4

## Component Usage Patterns

### Most Used Shared Components
1. **Card** -- used by nearly every page
2. **PageHeader** -- used by ~30+ pages
3. **useApi** -- used by every data-fetching page
4. **MetricTile** -- used by dashboard pages
5. **DataGrid** -- used by table-heavy pages
6. **TabPage** -- used by 8 hub pages
7. **DetailDrawer** -- used by detail-heavy pages

### Components That Could Be Extracted
- Many pages inline their own styled tables (not using DataGrid)
- Several pages have their own status badge logic (could use a shared StatusBadge)
- Chart usage is inconsistent: some pages use Chart.js components, others use inline SVG
