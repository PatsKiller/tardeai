# New Component: AgentChip.tsx

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

- **Target repo path:** apps/command-center-v2/src/components/AgentChip.tsx
- **Design purpose:** Replace 6+ per-page inline agent chip implementations with a shared component. Each agent has a stable color and role tooltip. Unknown agents get a neutral style instead of crashing.

## Acceptance Checklist

- [ ] All known agents render with correct colors
- [ ] Unknown agents render gracefully (gray)
- [ ] Tooltip shows agent role
- [ ] Accepts size variant
- [ ] No new dependencies

```tsx
import type { CSSProperties } from 'react'

interface AgentDef {
  color: string
  role: string
}

const AGENTS: Record<string, AgentDef> = {
  maria:      { color: '#fb7185', role: 'Risk & Portfolio Impact' },
  Maria:      { color: '#fb7185', role: 'Risk & Portfolio Impact' },
  steph:      { color: '#2dd4bf', role: 'Technical & Timing' },
  Steph:      { color: '#2dd4bf', role: 'Technical & Timing' },
  alex:       { color: '#a855f7', role: 'Retirement & Income' },
  Alex:       { color: '#a855f7', role: 'Retirement & Income' },
  risk_agent: { color: '#f97316', role: 'Stop & Risk Gate' },
  Risk:       { color: '#f97316', role: 'Stop & Risk Gate' },
  tax_agent:  { color: '#0ecb81', role: 'Tax & Lots' },
  Tax:        { color: '#0ecb81', role: 'Tax & Lots' },
  aegis:      { color: '#eab308', role: 'Synthesis & Surveillance' },
  Aegis:      { color: '#eab308', role: 'Synthesis & Surveillance' },
  synthesis:  { color: '#eab308', role: 'Cross-agent Synthesis' },
  iris:       { color: '#00d2d3', role: 'Content & Hygiene' },
  Iris:       { color: '#00d2d3', role: 'Content & Hygiene' },
  cio_engine: { color: '#4a90f4', role: 'CIO Decision Engine' },
  system:     { color: '#586578', role: 'System / Automated' },
  operator:   { color: '#c4cdd8', role: 'Human Operator' },
  human_review: { color: '#c4cdd8', role: 'Human Review Queue' },
}

const DEFAULT_AGENT: AgentDef = { color: '#586578', role: 'Agent' }

function rgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

interface AgentChipProps {
  name: string
  size?: 'sm' | 'md'
  showRole?: boolean
  style?: CSSProperties
}

export function AgentChip({ name, size = 'sm', showRole = false, style }: AgentChipProps) {
  const def = AGENTS[name] || DEFAULT_AGENT
  const displayName = name === 'human_review' ? 'Operator' : name === 'risk_agent' ? 'Risk' : name === 'tax_agent' ? 'Tax' : name

  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 3,
    padding: size === 'sm' ? '1px 6px' : '2px 8px',
    borderRadius: 3,
    fontSize: size === 'sm' ? 9 : 11,
    fontWeight: 700,
    background: rgba(def.color, .15),
    color: def.color,
    whiteSpace: 'nowrap',
    cursor: 'default',
    ...style,
  }

  return (
    <span style={base} title={`${displayName} — ${def.role}`}>
      <span style={{ width: size === 'sm' ? 5 : 7, height: size === 'sm' ? 5 : 7, borderRadius: '50%', background: def.color, flexShrink: 0 }} />
      {displayName}
      {showRole && <span style={{ fontWeight: 400, opacity: .7, marginLeft: 2 }}>({def.role})</span>}
    </span>
  )
}

/** Get agent color by name (for charts, borders, etc.) */
export function agentColor(name: string): string {
  return (AGENTS[name] || DEFAULT_AGENT).color
}

/** Get agent role by name */
export function agentRole(name: string): string {
  return (AGENTS[name] || DEFAULT_AGENT).role
}

export default AgentChip
```
