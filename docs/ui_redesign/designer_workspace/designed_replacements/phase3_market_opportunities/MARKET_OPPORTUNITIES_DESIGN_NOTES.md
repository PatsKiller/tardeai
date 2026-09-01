# Market Opportunities Phase 3 - Design Notes

Status:      HISTORICAL
as_of:       2026-05-25T14:16:20-04:00
Measured at: efcc51365 / not measured

## Overview

Phase 3 replaces two pages under the "Market Opportunities" umbrella:

1. **TradeAI.tsx** (565 lines) -> "Market Opportunities" - the primary signal/ranking view
2. **Prospects.tsx** (458 lines) -> "Prospect Discovery" - the candidate filtering/graduation view

## What Changed

### TradeAI.tsx

- **Title**: "Trade AI" -> "Market Opportunities"
- **Subtitle**: Now includes purpose description: "Trade AI signals, regime context, opportunity ranking, and next actions"
- **Summary row**: Added a grid of `StateCard` components at the top showing GO/WAIT/NO GO counts, VIX, Regime, Last Run, Top Ticker, and Deltas. Uses `title=` prop (not `label=`).
- **Decision badges in table**: Replaced inline-styled `<span>` decision badges with `StatusBadge` using mapped status values (GO->ready, WAIT->waiting, NO GO->blocked).
- **Run health banner**: Added `StatusBadge` inside the run health banner for the status indicator.
- **Filter buttons**: Replaced raw `<button>` elements with `ActionButton` using children pattern.
- **Copy buttons**: Replaced raw `<button>` with `ActionButton variant="ghost"`.
- **Drawer drillthrough**: Replaced raw `<button>` with `ActionButton variant="secondary"` for Open Research and Open Watchlist.
- **Disqualification**: Uses `SeverityBadge severity="critical"` for DQ warnings.
- **Critic verdict**: Uses `SeverityBadge` with mapped severity (BLOCK->critical, DOWNGRADE->high, CONFIRM->low).
- **Catalyst verified/unverified**: Uses `StatusBadge` (blocked for unverified, complete for verified).
- **Industry unclassified**: Uses `StatusBadge status="warning"`.
- **Foreign issuer warning**: Uses `SeverityBadge severity="medium"`.
- **Delta drift indicators**: Uses `StatusBadge` for score change indicators at bottom.
- **Empty states**: Added for no tickers, no sector data, and improved loading state.

### Prospects.tsx

- **Title**: "PROSPECTS" -> "Prospect Discovery"
- **Subtitle**: "Pre-trade candidate discovery" -> "Filtered candidates, missing evidence, and graduation path"
- **Summary row**: Added `StateCard` grid (Total Prospects, GO, WAIT, AVOID, Last Scan, Strategy).
- **Run health badge**: Replaced inline-styled span with `StatusBadge` in header.
- **Decision badges in table**: Replaced inline `<span>` with `StatusBadge`.
- **HELD badge**: Replaced inline span with `StatusBadge status="complete"`.
- **Incubator lifecycle badges**: Replaced inline spans with `StatusBadge` using mapped statuses.
- **Catalyst indicator**: Replaced inline span with `StatusBadge`.
- **Tab bar buttons**: Replaced raw `<button>` with `ActionButton`.
- **Clear filter button**: Replaced raw `<button>` with `ActionButton variant="ghost"`.
- **Watchlist buttons**: Replaced raw `<button>` with `ActionButton variant="primary"` and `variant="secondary"`.
- **Close button**: Replaced raw `<button>` with `ActionButton variant="ghost"`.
- **Confluence tier in side panel**: Uses `SeverityBadge` with mapped severity.
- **Added to watchlist**: Uses `StatusBadge status="complete"` confirmation.
- **Empty states**: Enhanced loading state (shows endpoint), no results (includes clear-filter action button), no pipeline sources message.

## What Did NOT Change

### TradeAI.tsx

- `useApi('/api/v2/trade-ai')` hook call - identical
- `fetch('/api/v2/iris/integrity')` side effect - identical
- `fetch('/api/v2/indicators/batch')` POST for confluence - identical
- All TypeScript interfaces (`Ticker`, `RunHistoryItem`, `TradeAIData`) - identical
- All `useState` declarations - identical
- All `useEffect` hooks (iris, confluence, URL params) - identical
- `DataGrid` columns structure, sortKeys, and render functions - preserved
- `DetailDrawer` with all `DrawerSection`/`DrawerStat` content - preserved
- `ConfluenceBadge` rendering in confluence column - identical
- `BarChartJS` run history chart - identical
- Sector distribution bar chart - identical
- `ScalpLiveFeed` component - identical
- Position sizing calculations - identical
- Grade legend tooltip content - identical
- TOS export clipboard copy logic - identical
- URL param sync for selected ticker - identical
- `MetricTile` row (kept alongside StateCards for detailed metrics)

### Prospects.tsx

- `fetch('/api/v2/prospects')` with URLSearchParams - identical
- `fetch('/api/v2/incubator')` side effect - identical
- `fetch('/api/v2/prospects/add-to-watchlist')` POST - identical
- All `useState` hooks (prospects, loading, activeTab, minPrice, maxPrice, minScore, selected, addedSymbols, incubatorMap, runHealth) - identical
- `useCallback` for `fetchProspects` - identical
- `switchTab` function - identical
- `addToWatchlist` function - identical
- `Prospect` interface - identical
- All constant maps (`PRICE_DEFAULTS`, `SOURCE_COLORS`, `TIER_COLORS`, `DECISION_COLORS`) - identical
- Filter bar inputs and logic - identical
- Table column structure - identical
- Side panel sections (Trade Setup, Confluence, Pipeline Sources, Incubator) - preserved
- Incubator grid in side panel - identical

## Primitives Used

| Primitive | Props Used | Where |
|-----------|-----------|-------|
| `StatusBadge` | `status`, `label`, `title`, `size`, `style` | Decision badges, run health, catalyst verified, HELD badge, lifecycle state, delta indicators |
| `SeverityBadge` | `severity`, `label`, `size`, `style` | DQ warning, critic verdict, foreign issuer, confluence tier |
| `ActionButton` | `variant`, `size`, `onClick`, `style`, `children` | Filter buttons, copy buttons, tab buttons, watchlist buttons, clear buttons, drillthrough buttons |
| `StateCard` | `title`, `value`, `status`, `description`, `compact` | Summary metric rows on both pages |

## How the Two Pages Relate

- **Market Opportunities** (TradeAI.tsx) is the primary ranked signal view. It shows the full scored universe from the screener pipeline with real-time regime context, VIX, and per-ticker decisions. It is the "what should I trade today" view.
- **Prospect Discovery** (Prospects.tsx) is the candidate filter view. It shows prospects by strategy type (scalp/swing/income/position) with trade setups, confluence analysis, and incubator tracking. It is the "what could graduate to a position" view.
- Both share the same backend signal pipeline but serve different stages of the trade lifecycle.
- Both pages are read-only/informational - no trade execution buttons.

## Safety Constraints

- No trading execution buttons on either page
- No `useApi` conversion on Prospects (kept direct fetch)
- All API endpoints preserved exactly
- No prop signature violations:
  - `AgentChip` uses `name=` (not used in these pages but rule enforced)
  - `ActionButton` uses `children` (never `label=`)
  - `StateCard` uses `title=` (never `label=`)
  - `StatusBadge` uses `status=`
  - `SeverityBadge` uses `severity=`
