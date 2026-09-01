# New Component: StateCard.tsx

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

- **Target repo path:** apps/command-center-v2/src/components/StateCard.tsx
- **Design purpose:** Reusable summary card for dashboards showing a metric + status + optional action. Replaces the pattern of `<div style={{...}}><div style={{...}}>label</div><div style={{...}}>value</div></div>` found in Agent Collaboration summary strip, Self-Improvement component health cards, System Health tiles, and Pipeline status cards.

## Acceptance Checklist

- [ ] Renders title, value, description, status, severity
- [ ] Accepts optional action label + onClick
- [ ] Accepts children for custom content
- [ ] Clickable when onClick provided
- [ ] Status/severity border stripe
- [ ] Uses CSS variables from theme.css
- [ ] No new dependencies

```tsx
import type { CSSProperties, ReactNode, MouseEvent } from 'react'

type CardStatus = 'fresh' | 'stale' | 'warning' | 'blocked' | 'ready' | 'waiting' | 'running' | 'complete' | 'unknown'
type CardSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical'

const STATUS_STRIPE: Record<string, string> = {
  fresh: 'var(--green)', ready: 'var(--green)', complete: '#0ba868',
  running: 'var(--accent)', waiting: 'var(--amber)', warning: 'var(--amber)',
  stale: '#f97316', blocked: 'var(--red)', unknown: 'var(--border)',
}

const SEVERITY_STRIPE: Record<string, string> = {
  info: 'var(--text3)', low: 'var(--accent)', medium: 'var(--amber)',
  high: '#f97316', critical: 'var(--red)',
}

interface StateCardProps {
  title: string
  value?: string | number | null
  description?: string
  status?: CardStatus | string
  severity?: CardSeverity | string
  actionLabel?: string
  onClick?: (e: MouseEvent<HTMLDivElement>) => void
  children?: ReactNode
  compact?: boolean
  style?: CSSProperties
}

export function StateCard({
  title, value, description, status, severity,
  actionLabel, onClick, children, compact = false, style,
}: StateCardProps) {
  const stripe = severity
    ? SEVERITY_STRIPE[severity] || 'var(--border)'
    : status
      ? STATUS_STRIPE[status] || 'var(--border)'
      : 'var(--border)'

  const base: CSSProperties = {
    padding: compact ? '8px 12px' : '12px 16px',
    borderRadius: 'var(--radius)',
    background: 'var(--bg1)',
    border: '1px solid var(--border)',
    borderLeft: `3px solid ${stripe}`,
    cursor: onClick ? 'pointer' : 'default',
    transition: 'var(--transition)',
    ...style,
  }

  return (
    <div style={base} onClick={onClick} title={actionLabel}>
      <div style={{ fontSize: compact ? 8 : 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.4px', fontWeight: 700 }}>
        {title}
      </div>

      {value != null && (
        <div style={{ fontSize: compact ? 20 : 24, fontWeight: 800, color: stripe !== 'var(--border)' ? stripe : 'var(--text0)', marginTop: 2 }}>
          {value}
        </div>
      )}

      {description && (
        <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>
          {description}
        </div>
      )}

      {children}

      {actionLabel && onClick && (
        <div style={{ fontSize: 10, color: 'var(--accent)', fontWeight: 600, marginTop: compact ? 4 : 8, cursor: 'pointer' }}>
          {actionLabel} &rarr;
        </div>
      )}
    </div>
  )
}

export default StateCard
```
