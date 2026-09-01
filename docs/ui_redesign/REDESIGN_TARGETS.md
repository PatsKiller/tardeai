# Redesign Targets

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Priority 1: Navigation Overhaul

### Goal
Reduce Admin group from 17 to 6 items. Create a "Trading" group.

### Changes
1. Extract Trading group: Trade AI, Prospects, Strategy Desk, Incubator, ATM Mode
2. Move Execution Quality, Proposal Alerts to Paper Trading
3. Remove redundant nav items: Approvals (redirect), Journal Reports (redirect)
4. Move Correlation, Forecast to Research or keep in Admin

### Files to Modify
- `apps/command-center-v2/src/components/Shell.tsx` (NAV_GROUPS array)

### Risk: LOW
- Nav-only change, no component changes needed
- Legacy routes still work

---

## Priority 2: Fix `/alerts` Route Conflict

### Goal
Remove duplicate route definition.

### Changes
- Remove line 206 in App.tsx: `<Route path="alerts" element={<SafePage><Inbox /></SafePage>} />`
- AlertsDashboard at line 187 is the correct definition

### Files to Modify
- `apps/command-center-v2/src/App.tsx`

### Risk: LOW

---

## Priority 3: Page Consolidation

### Goal
Reduce 55 routes to ~45 by merging related pages into hubs.

### Candidates
| Merge | Into | New Tabs |
|-------|------|----------|
| System Health | PipelineHub | Add "System Health" tab |
| Agent Pipeline + Agent Collaboration | New AgentOpsHub | 2 tabs |
| Strategy Admin + Strategy Analytics + Agent Calibration | StrategyAdminHub | 3 tabs |
| Correlation + Forecast | AnalysisHub (or add to Research) | 2 tabs |

### Risk: MEDIUM
- Need to maintain legacy redirects
- Tab deep-linking via query params

---

## Priority 4: Loading & Error UX

### Goal
Better loading states and error recovery.

### Changes
1. Replace "Loading..." text with skeleton/shimmer components
2. Add page-level retry buttons for failed API calls
3. Add stale data indicators when polling fails

### Risk: LOW

---

## Priority 5: Design Token Consistency

### Goal
Eliminate hardcoded colors; use CSS custom properties everywhere.

### Changes
1. Audit all pages for hardcoded hex values
2. Add font-size tokens: `--text-xs: 9px`, `--text-sm: 11px`, `--text-base: 12px`, `--text-lg: 14px`
3. Add spacing tokens: `--space-1: 4px` through `--space-8: 32px`
4. Standardize card backgrounds to `--bg-card`

### Risk: LOW (cosmetic only)

---

## Priority 6: Command Palette / Search

### Goal
Add Cmd+K search to find any page quickly.

### Changes
1. New component: CommandPalette.tsx
2. Index all routes with labels
3. Keyboard shortcut listener in Shell

### Risk: MEDIUM (new feature)

---

## Priority 7: Overview Page Performance

### Goal
Reduce 18 API calls to fewer, or add a combined endpoint.

### Options
1. Create `/api/v2/overview-full` that bundles all overview data
2. Add a shared data context for commonly-used data
3. Use SWR or React Query for cross-page caching

### Risk: MEDIUM-HIGH (API changes + hook changes)

---

## Priority 8: Cleanup

### Goal
Remove dead code and backup files.

### Changes
1. Delete 4 `.bak` files from pages/
2. Review and remove unused legacy redirects
3. Remove orphaned `/bot-morning-brief` route (or add to nav)

### Risk: LOW

---

## Out of Scope for Near-Term

- Light mode (would require full palette overhaul)
- SSR / Next.js migration
- Global state management (Redux/Zustand)
- API framework migration (Flask/FastAPI)
- Mobile app / PWA
