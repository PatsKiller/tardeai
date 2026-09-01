# UX Issues Observed

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Critical

### 1. `/alerts` Route Defined Twice (BUG)
- Line 187: renders AlertsDashboard
- Line 206: renders Inbox
- React Router matches first, so AlertsDashboard wins
- The Inbox redirect is dead code
- **Impact:** No user-facing bug currently, but confusing code and potential future breakage

### 2. Admin Nav Group Has 17 Items
- Unusable dropdown on desktop
- Excessive scrolling on mobile drawer
- Mixes trading, analytics, governance, and system tools
- **Impact:** Users cannot find pages; key tools hidden in noise

---

## High

### 3. Overview Page Makes 18 API Calls
- Each call is independent (no batching)
- On slow connections, page loads piecemeal
- useApi retries once after 2s on failure, potentially 36 requests
- **Impact:** Slow initial load, especially on mobile

### 4. No Loading States for Hub Tabs
- Hub pages (GovernanceHub, OpsHub, etc.) lazy-load tab components
- The "Loading..." fallback is plain text with no skeleton or shimmer
- **Impact:** Perceived slowness when switching tabs

### 5. Monospace Body Font
- The entire UI uses monospace as the body font
- While thematically appropriate for a trading terminal, it reduces readability for long text
- Intelligence, Research, and Journal pages have paragraphs of text that suffer from monospace
- **Impact:** Reading fatigue

### 6. No Search / Command Palette
- 55+ routes with no global search
- Users must navigate through dropdowns to find pages
- **Impact:** Slow navigation, especially for infrequent pages

---

## Medium

### 7. Color Inconsistency in Pages
- `theme.css` defines tokens (`--green`, `--red`, etc.)
- Many pages use hardcoded hex values instead of tokens
- Example: SelfImprovement uses `'#0ecb81'` directly instead of `var(--green)`
- **Impact:** If palette changes, many pages won't update

### 8. No Dark/Light Mode Toggle
- Only dark theme available
- All colors are hardcoded dark-mode values
- **Impact:** Accessibility for users in bright environments

### 9. Journal Reports Nav Item is Redundant
- "Journal Reports" in Reports nav redirects to `/journal?tab=reports`
- Same as clicking "Trade Journal" and selecting Reports tab
- **Impact:** Nav clutter

### 10. Backup Files in Pages Directory
- 4 `.bak` files exist alongside production components
- Could confuse IDE imports or future developers
- **Impact:** Code hygiene

### 11. Legacy Redirects Still Active
- 25+ legacy route redirects maintained in App.tsx
- Some render the target component directly (no URL change)
- Some use Navigate (URL changes)
- **Impact:** Inconsistent behavior; code bloat

### 12. No Breadcrumbs
- Deep pages like `/watchlist/AAPL` or `/agent-dashboard/maria` have no breadcrumb trail
- User must use browser back or nav to return
- **Impact:** Lost context in deep navigation

---

## Low

### 13. Tape Metrics Click to Same Page
- 4 of 8 tape metrics click to `/trade-ai`
- Clicking multiple metrics feels redundant
- Consider varying the targets or making metrics informational only

### 14. No Keyboard Shortcuts
- No Cmd+K or keyboard navigation
- Tab focus order not optimized

### 15. Bot Morning Brief Orphaned
- `/bot-morning-brief` exists but is not in any nav group
- Accessible only by direct URL

### 16. Mobile Grid Overrides Are Aggressive
- The CSS forces 2-column grids on all multi-column layouts
- Some pages (like Risk with 3 equal cards) might benefit from single-column on mobile
- The `!important` overrides make per-page optimization impossible

### 17. No Error Recovery for Failed API Calls
- `useApi` retries once, then shows error string
- No "retry" button on the page level (only the ErrorBoundary "Try Again" for render errors)
- Stale data continues showing while error is set
