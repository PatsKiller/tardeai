# Agent Collaboration → Decision Operations Cockpit — Design Notes

## What Changed

1. **Title:** "Agent Collaboration" → "Decision Operations"
2. **Subtitle:** Generic mission text → "Agent mission control — blockers, decisions, and evidence"
3. **Summary strip:** Raw inline divs → shared `StateCard` components with clickable filters
4. **John's Actions:** Kept but uses `SeverityBadge` + `ActionButton` instead of inline spans
5. **Filter bar:** NEW — client-side status filter chips (All/Ready/Blocked/Waiting/Stale/Running)
6. **Mission queue:** Uses `StatusBadge`, `SeverityBadge`, `AgentChip` instead of inline implementations
7. **Mission inspector:** Uses shared primitives, better visual hierarchy, "Next Action" panel prominent
8. **Auto-select:** First/highest-priority mission auto-selected on load
9. **Empty state:** Clear message with filter-aware text
10. **Agent network section:** REMOVED from this page (belongs in a dedicated Agent Pipeline or telemetry view)

## What Did NOT Change

- API endpoint: `/api/v2/agent-collaboration` — identical
- Data shape: summary, john_next_actions, mission_groups — all same
- Polling interval: 60s — same
- Route path: `/v2/agent-collaboration` — same
- No backend changes
- No new API calls
- No trading/approval execution

## Shared Primitives Used

| Component | Usage |
|-----------|-------|
| StatusBadge | Mission status pills, thread status in items list |
| SeverityBadge | Mission severity, action severity |
| AgentChip | Agent chips in queue cards and inspector (with showRole in inspector) |
| ActionButton | Refresh button, filter chips, "Open Page" navigation, "Show all" |
| StateCard | Summary strip cards (Ready, Blocked, Active, Stale, System Trust) |

## Removed Inline Code

These inline implementations were deleted from this page:
- `const G, R, Y, B, DIM, CYAN, PURPLE, ROSE, ORANGE, TEAL, GOLD` — color constants
- `const rgba()` — rgba helper function
- `const AGENT_CLR, ac()` — agent color map
- `const SEV_CLR, STATUS_CLR` — severity/status color maps
- `function AgentChip()` — inline agent chip
- `function SevStripe()` — inline severity badge
- `function StatusPill()` — inline status pill
- `function timeAgo()` — KEPT (only non-shared utility still needed)

## Safety Constraints Preserved

- No trading actions executed
- No approval mutations
- ActionButton "Open Page" uses `window.location.href` for navigation only
- No `fetch` or `POST` calls added
- No new API endpoints required

## Build/Test Instructions

```bash
cd apps/command-center-v2 && npm run build
# Verify: 0 errors, build passes
# Verify: /v2/agent-collaboration loads
# Verify: StateCard, StatusBadge, AgentChip render correctly
# Verify: filter chips work
# Verify: mission selection works
# Verify: inspector shows correct data
```

## Rollback

```bash
git checkout HEAD -- apps/command-center-v2/src/pages/AgentCollaboration.tsx
cd apps/command-center-v2 && npm run build
```
