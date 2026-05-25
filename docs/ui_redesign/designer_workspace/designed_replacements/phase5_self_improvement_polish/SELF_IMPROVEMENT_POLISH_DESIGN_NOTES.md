# Self-Improvement Polish -- Design Notes

**Phase:** 5 -- Self-Improvement Polish
**Type:** Polish (not rebuild)
**Original:** `apps/command-center-v2/src/pages/SelfImprovement.tsx` (173 lines)
**Original hash:** `fc411dfaa7f87fbbaf82f89cb6476cbe79d19d4aa9213c68e4eb90adc44e4831`

---

## What Changed

### 1. Title and subtitle updated
- **Before:** "Self-Improvement Command Center" / "Unified operator view -- read-only aggregation across all intelligence layers"
- **After:** "Self-Improvement Center" / "Learning loops, calibration health, improvement backlog, and evidence that the system is getting better"

### 2. Inline `btn` style replaced with ActionButton
- The `const btn: React.CSSProperties` block is removed entirely
- All `<button style={btn}>` instances replaced with `<ActionButton>` using `children` (NOT `label=`)
- Refresh button in header: `<ActionButton variant="secondary" size="sm">`
- Subsystem dashboard links: `<ActionButton variant="secondary" size="sm">`
- Review queue navigation links: `<ActionButton variant="ghost" size="sm">`

### 3. Inline status dots replaced with StatusBadge
- Component health section: `dot(c.status)` replaced with `<StatusBadge status={mappedStatus} label={c.status} />`
- Warning items: `dot(...)` replaced with `<StatusBadge status="warning">`
- Safety banner guard status: inline text replaced with `<StatusBadge>` for PASS/FAIL
- Status mapping table converts API values (healthy/degraded/failed) to StatusBadge-compatible keys (fresh/stale/blocked)

### 4. Review queue severity dots replaced with SeverityBadge
- `dot(q.severity)` replaced with `<SeverityBadge severity={...} />`
- Mapping table converts API values (urgent/important/normal/info) to SeverityBadge keys (critical/high/medium/info)
- `requires_action` flag shown as `<StatusBadge status="warning" label="ACTION" />`

### 5. Overview cards replaced with StateCard
- All 9 overview metric cards now use `<StateCard title=... value=... status=... compact />`
- Uses `title=` (NOT `label=`) per StateCard API
- Status-driven left stripe replaces inline background color logic
- `actionLabel="View"` with `onClick` for navigable cards
- Badge text moved to `description` prop

### 6. Cross-link navigation added
- New row of ActionButton ghost links: Agent Calibration, Weekly Learning, Automation Trust (/ops)
- Placed between overview cards and review queue for quick access

### 7. Empty states added
- Review queue: "No items require operator review. The queue is clear."
- Component health: "Run the health snapshot first to populate component status."
- Warnings (when loaded but empty): "No active warnings. All subsystems operating normally."

---

## What Was Preserved (Unchanged)

- All 3 `useApi()` calls with exact same endpoints and cache-bust pattern
- All data destructuring: `s.safety`, `s.paper_trading`, `s.learning`, `s.agent_calibration`, etc.
- `queueItems` and `components` array extraction with same fallback logic
- Safety banner structure, colors, and conditional logic
- Component health route mapping (expanded to handle both underscore and hyphen keys)
- Warning route inference logic (exact same string matching)
- Subsystem dashboards link list (same 8 routes)
- `useState(0)` for refresh key
- `useNavigate()` for client-side routing
- Page layout: 16px/24px padding, 1200px max-width
- Card component wrapping for sections
- Mouse hover interactions on clickable rows
- No new API endpoints -- strictly read-only

---

## Shared Primitives Used

| Primitive | Import | Usage |
|-----------|--------|-------|
| `StatusBadge` | `../components/StatusBadge` | Component health status, warning type badges, safety guard PASS/FAIL |
| `SeverityBadge` | `../components/SeverityBadge` | Review queue item severity |
| `ActionButton` | `../components/ActionButton` | Refresh, subsystem links, queue navigation, cross-links |
| `StateCard` | `../components/StateCard` | All 9 overview metric cards |

**Not used (not needed for this page):**
- `AgentChip` -- no agent-specific display on this page

---

## Safety Constraints

- No trading or approval actions added
- No new API endpoints
- Read-only page -- no mutations
- No modifications to production source files
- PAPER MODE ACTIVE banner preserved exactly
