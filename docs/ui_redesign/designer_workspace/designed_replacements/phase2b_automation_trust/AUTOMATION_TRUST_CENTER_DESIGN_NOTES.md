# Automation Trust Center -- Design Notes

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

## Phase 2b: Automation Trust Center Family

This phase redesigns 4 pages that together form the "Automation Trust Center" -- the operational backbone of the Command Center. These pages let the operator verify that automation (crons, agents, LLM queue, pipelines) is running correctly and trustworthy.

---

## What Changed Per Page

### OpsHub.tsx (hub wrapper)
- Title renamed from "Operations" to "Automation Trust Center"
- Tab labels clarified: "Trust Overview", "Cron & Jobs", "LLM Queue", "Orchestration"
- Added subtitle via fragment wrapper (TabPage does not currently accept subtitle prop)
- No logic changes. Same 4 lazy-loaded child components.

### PipelineHub.tsx (hub wrapper)
- Title renamed from "Pipeline Operations" to "Pipeline Health"
- Tab label "Health Overview" renamed to "Stage Health"
- Added subtitle via fragment wrapper
- No logic changes. Same 2 lazy-loaded child components.

### SystemHealth.tsx (147 lines)
- Title renamed from "System Health" to "System Health & Services"
- Subtitle updated to describe scope
- Inline `const btn` CSS object replaced with `ActionButton` component
- Data Product Health section: hardcoded hex colors replaced with `StatusBadge`
- Added empty state for when `data?.data_freshness` is not yet loaded
- Weekend/holiday stale reason logic fully preserved (`weekend_market_closed`)
- All other sections (LLM Router, DB State, CIO Decisions, Finviz Screeners, system footer) unchanged in logic

### AgentPipeline.tsx (493 lines)
- Title renamed from "Agent Pipeline" to "Agent Pipeline & Queue"
- Subtitle expanded
- Inline `Badge` function replaced with `StatusBadge` primitive
- Inline agent name rendering (`color: 'var(--accent)'`) replaced with `AgentChip`
- Summary status dots replaced with `StateCard` components
- Failed job error badges use `SeverityBadge` instead of inline `Badge`
- Filter chip buttons use `ActionButton` with variant switching
- Agent health section uses `AgentChip` for agent names
- Added empty states for jobs table, results table, and events table
- All helper functions preserved exactly (parsePeerNotes, getRagDisplay, getTierBadge, getErrorBadge, getEventTypeStyle, parseContentGapSymbol)

---

## What Did NOT Change

### API Endpoints (zero changes)
- `/api/v2/system-health` -- SystemHealth, AgentPipeline
- `/api/v2/finviz-screeners` -- SystemHealth
- `/api/v2/agent-pipeline?limit=50` -- AgentPipeline
- `/api/v2/agent-health` -- AgentPipeline

### Data Access Patterns (zero changes)
- `data?.llm`, `data?.db_tables`, `data?.cio_decisions`, `data?.data_freshness`
- `data.jobs`, `data.results`, `data.handoffs`, `data.events`, `data.proposals`, `data.debates`, `data.summary`
- `healthData?.llm`, `agentHealthData?.agents`

### TypeScript Interfaces (zero changes)
All 11 interfaces in AgentPipeline.tsx preserved verbatim: Job, RagSource, Result, Handoff, Event, Proposal, Debate, Summary, PipelineData, LlmProvider, SystemHealth, AgentHealthEntry, AgentHealthData.

### Polling Intervals (zero changes)
- agent-pipeline: 30s
- system-health: 60s
- agent-health: 60s

---

## How the 4 Pages Relate as a Family

```
Automation Trust Center (OpsHub)
  |-- Trust Overview (SystemHealth) .... services, LLM, data freshness
  |-- Cron & Jobs (Ops) ................ cron schedules, job history
  |-- LLM Queue (LLMQueue) ............ queue depth, routing, costs
  |-- Orchestration .................... scheduled tasks, workflows

Pipeline Health (PipelineHub)
  |-- Stage Health (PipelineHealthMaster) ... per-stage status
  |-- Stage Controller (PipelineController) . manual triggers

Agent Pipeline & Queue (AgentPipeline) ..... standalone page
  |-- job queue, results, handoffs, events, proposals, debates
```

The "Trust" framing emphasizes that these pages exist to build operator confidence that automation is working. They answer: "Can I trust what the system did overnight?"

---

## Shared Primitives Used

| Primitive | Used In | Replaces |
|-----------|---------|----------|
| `StatusBadge` | SystemHealth, AgentPipeline | Inline Badge function, hardcoded status colors |
| `SeverityBadge` | AgentPipeline | Inline error badge function |
| `AgentChip` | AgentPipeline | Inline agent name + accent color |
| `StateCard` | AgentPipeline | Inline summary dot + count tiles |
| `ActionButton` | SystemHealth, AgentPipeline | Inline `const btn` CSS, filter chip buttons |

**Prerequisite**: These shared primitives must be created before applying phase2b replacements. They are defined in the phase2a primitive designs (StatusBadge.tsx, SeverityBadge.tsx, AgentChip.tsx, StateCard.tsx, ActionButton.tsx in `../components/`).

### Expected Primitive APIs

```tsx
// StatusBadge: renders a small colored pill
<StatusBadge status="green" label="Fresh" />
// status: 'green' | 'red' | 'amber' | 'info' | 'muted'

// SeverityBadge: similar to StatusBadge but for error severity
<SeverityBadge severity="critical" label="BUDGET" />
// severity: 'critical' | 'warning' | 'muted'

// AgentChip: renders agent name with consistent color
<AgentChip agent="maria" />

// StateCard: summary tile with dot, label, value
<StateCard label="Queued" value={12} color="var(--amber)" />

// ActionButton: styled button with variants
<ActionButton label="Refresh" onClick={fn} variant="secondary" />
// variant: 'primary' | 'secondary' | 'ghost'
// size?: 'sm' | 'md'
```

---

## Safety Constraints Preserved

1. **No trading or approval execution** -- these pages are read-only operational views
2. **No new API endpoints** -- all data comes from existing endpoints
3. **No new npm packages** -- only existing dependencies
4. **All theme.css variables used** -- no hardcoded colors outside the design system
5. **All polling intervals unchanged** -- no added load on backend
6. **Lazy loading preserved** -- OpsHub and PipelineHub still use `React.lazy`

---

## Known Risks

1. **AgentPipeline is the largest and riskiest change** (493 lines). Every table column must be visually verified. The `getTierBadge` and `getErrorBadge` functions now return different JSX (StatusBadge/SeverityBadge instead of inline Badge), so their visual sizing may differ slightly.

2. **Shared primitives must exist first**. If StatusBadge/AgentChip/etc. are not created before applying these replacements, the build will fail with import errors.

3. **TabPage does not support subtitle**. The OpsHub and PipelineHub replacements use a fragment wrapper with a `<p>` tag above TabPage. This creates a slight visual gap that should be verified. A cleaner approach would be to extend TabPage with an optional `subtitle` prop.

4. **StatusBadge status key mapping**. The `statusKey()` helper function maps status strings to StatusBadge status props. If the StatusBadge component uses different prop values than expected ('green', 'red', 'amber', 'info', 'muted'), this mapping must be updated.

5. **ActionButton variant for filter chips**. The filter chips in AgentPipeline use `variant="primary"` for active and `variant="ghost"` for inactive. The visual distinction depends on ActionButton's implementation having clearly different styles for these variants. The `textTransform: 'capitalize'` from the original is now the responsibility of ActionButton.

6. **color-mix CSS function**. The original AgentPipeline Badge used `color-mix(in srgb, ...)` which has good browser support but should be verified. StatusBadge should handle this internally.
