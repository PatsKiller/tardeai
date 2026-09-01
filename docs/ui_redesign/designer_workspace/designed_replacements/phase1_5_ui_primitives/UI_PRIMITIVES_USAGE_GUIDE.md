# Phase 1.5 UI Primitives — Usage Guide

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

## Import Pattern

```tsx
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { AgentChip, agentColor } from '../components/AgentChip'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'
```

---

## StatusBadge

Shows system state as a colored pill with dot indicator.

```tsx
// Basic usage
<StatusBadge status="ready" />
<StatusBadge status="blocked" />
<StatusBadge status="stale" />
<StatusBadge status="running" />

// Custom label
<StatusBadge status="complete" label="Done" />

// With tooltip
<StatusBadge status="waiting" title="Waiting for Steph technical review" />

// Medium size
<StatusBadge status="fresh" size="md" />

// Unknown/fallback — renders gray
<StatusBadge status="some_new_status" />
```

### Agent Collaboration example:
```tsx
// Thread status in mission group list
<StatusBadge status={mission.status} />

// Chevron stage status
<StatusBadge status={stage.status} label={stage.label} />
```

---

## SeverityBadge

Shows priority/severity level.

```tsx
<SeverityBadge severity="critical" />
<SeverityBadge severity="high" />
<SeverityBadge severity="medium" />
<SeverityBadge severity="low" />
<SeverityBadge severity="info" />

// Custom label
<SeverityBadge severity="critical" label="URGENT" />
```

### Agent Collaboration example:
```tsx
// Mission group severity
<SeverityBadge severity={mission.severity} />

// John's next actions
{johnActions.map(a => (
  <div>
    <SeverityBadge severity={a.severity} />
    <span>{a.label}</span>
  </div>
))}
```

---

## AgentChip

Shows agent identity with color-coded dot and role tooltip.

```tsx
// Basic
<AgentChip name="Maria" />
<AgentChip name="risk_agent" />  {/* Renders as "Risk" */}
<AgentChip name="Aegis" />

// Medium size
<AgentChip name="Steph" size="md" />

// Show role text
<AgentChip name="Maria" showRole />
// Renders: "Maria (Risk & Portfolio Impact)"

// Unknown agent — renders gray
<AgentChip name="new_agent_v2" />

// Get just the color (for borders, charts)
import { agentColor } from '../components/AgentChip'
<div style={{ borderLeft: `3px solid ${agentColor('Maria')}` }}>
```

### Agent Collaboration example:
```tsx
// Agent list in thread card
{thread.agents.map(a => <AgentChip key={a} name={a} />)}

// Agent contribution in detail drawer
{contributions.map(c => (
  <div style={{ borderLeft: `3px solid ${agentColor(c.agent)}` }}>
    <AgentChip name={c.agent} size="md" showRole />
    <p>{c.summary}</p>
  </div>
))}
```

---

## ActionButton

Styled button with variants. Does NOT execute actions itself.

```tsx
// Primary (accent blue, white text)
<ActionButton variant="primary" onClick={handleApprove}>Approve</ActionButton>

// Secondary (subtle, bordered)
<ActionButton onClick={handleRefresh}>Refresh</ActionButton>

// Danger (red background)
<ActionButton variant="danger" onClick={handleReject}>Reject Proposal</ActionButton>

// Ghost (transparent, text only)
<ActionButton variant="ghost" onClick={handleDismiss}>Dismiss</ActionButton>

// Loading
<ActionButton variant="primary" loading>Saving...</ActionButton>

// Disabled
<ActionButton disabled>Not Available</ActionButton>

// Sizes
<ActionButton size="sm">Small</ActionButton>
<ActionButton size="md">Medium</ActionButton>
<ActionButton size="lg">Large</ActionButton>
```

### Agent Collaboration example:
```tsx
// John's action buttons in detail drawer
<ActionButton variant="primary" onClick={() => navigate('/v2/paper-proposals')}>
  Approve Proposal
</ActionButton>
<ActionButton variant="secondary" onClick={handleRerun}>
  Re-run Agent Analysis
</ActionButton>
<ActionButton variant="danger" onClick={handleReject}>
  Reject
</ActionButton>
```

---

## StateCard

Dashboard summary card with status stripe, value, description, and optional action.

```tsx
// Basic metric card
<StateCard title="Active Threads" value={62} status="running" />

// With description
<StateCard title="Blocked" value={8} status="blocked"
  description="5 stops + 2 risk-gated + 1 stale" />

// With severity
<StateCard title="Portfolio Heat" value="7.2%" severity="high"
  description="Above 5% threshold" />

// Clickable with action
<StateCard title="Ready for John" value={4} status="ready"
  actionLabel="Review now" onClick={() => setFilter('ready')} />

// Compact variant
<StateCard compact title="VIX" value="16.9" status="warning" />

// With children
<StateCard title="System Trust" status="fresh">
  <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--green)' }}>FRESH</div>
  <div style={{ fontSize: 9, color: 'var(--text2)' }}>Aegis: 3h ago</div>
</StateCard>
```

### Agent Collaboration example:
```tsx
// Command strip
<div style={{ display: 'flex', gap: 8 }}>
  <StateCard compact title="Active Threads" value={summary.active_threads} status="running" />
  <StateCard compact title="Ready for John" value={summary.ready_for_operator} status="ready"
    actionLabel="Review" onClick={() => setStatusFilter('ready')} />
  <StateCard compact title="Blocked" value={summary.blocked_threads} status="blocked" />
  <StateCard compact title="Stale" value={summary.stale_missions} status="stale" />
</div>
```

---

## Combining Components

```tsx
// Mission group card in Agent Collaboration
<div style={{ padding: 12, borderRadius: 8, background: 'var(--bg1)', border: '1px solid var(--border)' }}>
  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
    <span style={{ fontWeight: 700 }}>{mission.title}</span>
    <SeverityBadge severity={mission.severity} />
    <StatusBadge status={mission.status} />
  </div>
  <div style={{ display: 'flex', gap: 3, marginTop: 4 }}>
    {mission.agents.map(a => <AgentChip key={a} name={a} />)}
  </div>
  <div style={{ marginTop: 8 }}>
    <ActionButton size="sm" onClick={() => select(mission)}>
      {mission.next_action.label}
    </ActionButton>
  </div>
</div>
```
