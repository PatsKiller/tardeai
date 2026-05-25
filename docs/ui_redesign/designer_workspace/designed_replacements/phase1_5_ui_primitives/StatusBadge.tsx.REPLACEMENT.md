# New Component: StatusBadge.tsx

- **Target repo path:** apps/command-center-v2/src/components/StatusBadge.tsx
- **Design purpose:** Replace 20+ inline status `<span>` elements scattered across pages with a single shared component. Standardizes colors, sizing, pill shape, and tooltip behavior for system states.

## Acceptance Checklist

- [ ] Renders all 10 states with correct colors
- [ ] Accepts label override
- [ ] Accepts title/tooltip
- [ ] Uses CSS variables from theme.css
- [ ] No new dependencies
- [ ] Named export for tree-shaking

```tsx
import type { CSSProperties } from 'react'

type Status = 'fresh' | 'stale' | 'warning' | 'blocked' | 'ready' | 'waiting' | 'running' | 'complete' | 'paused' | 'unknown'

const STATUS_COLORS: Record<Status, { bg: string; fg: string }> = {
  fresh:    { bg: 'var(--green-dim)',  fg: 'var(--green)' },
  ready:    { bg: 'var(--green-dim)',  fg: 'var(--green)' },
  complete: { bg: 'rgba(14,203,129,.12)', fg: '#0ba868' },
  running:  { bg: 'var(--accent-dim)', fg: 'var(--accent)' },
  waiting:  { bg: 'var(--amber-dim)',  fg: 'var(--amber)' },
  paused:   { bg: 'var(--amber-dim)',  fg: '#d4a30b' },
  warning:  { bg: 'var(--amber-dim)',  fg: 'var(--amber)' },
  stale:    { bg: 'rgba(249,115,22,.10)', fg: '#f97316' },
  blocked:  { bg: 'var(--red-dim)',    fg: 'var(--red)' },
  unknown:  { bg: 'rgba(88,101,120,.12)', fg: 'var(--text3)' },
}

interface StatusBadgeProps {
  status: Status | string
  label?: string
  title?: string
  size?: 'sm' | 'md'
  style?: CSSProperties
}

export function StatusBadge({ status, label, title, size = 'sm', style }: StatusBadgeProps) {
  const key = (status || 'unknown').toLowerCase() as Status
  const colors = STATUS_COLORS[key] || STATUS_COLORS.unknown
  const displayLabel = label || key.replace(/_/g, ' ')

  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: size === 'sm' ? '1px 7px' : '2px 10px',
    borderRadius: 10,
    fontSize: size === 'sm' ? 8 : 10,
    fontWeight: 800,
    textTransform: 'uppercase',
    letterSpacing: '.3px',
    lineHeight: size === 'sm' ? '16px' : '20px',
    background: colors.bg,
    color: colors.fg,
    whiteSpace: 'nowrap',
    ...style,
  }

  return (
    <span style={base} title={title || `Status: ${displayLabel}`}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: colors.fg, flexShrink: 0 }} />
      {displayLabel}
    </span>
  )
}

export default StatusBadge
```
