# New Component: SeverityBadge.tsx

Status:      HISTORICAL
as_of:       2026-05-25T13:05:19-04:00
Measured at: efcc51365 / not measured

- **Target repo path:** apps/command-center-v2/src/components/SeverityBadge.tsx
- **Design purpose:** Replace inline severity `<span>` elements with a shared component. Used for alert severity, mission priority, risk level, and blocker importance across Agent Collaboration, Alerts, Risk, and Pipeline pages.

## Acceptance Checklist

- [ ] Renders all 5 severity levels with correct colors
- [ ] Accepts label override
- [ ] Accepts title/tooltip
- [ ] Uses CSS variables from theme.css
- [ ] No new dependencies

```tsx
import type { CSSProperties } from 'react'

type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical'

const SEVERITY_COLORS: Record<Severity, { bg: string; fg: string; border: string }> = {
  info:     { bg: 'rgba(88,101,120,.10)', fg: 'var(--text2)',  border: 'transparent' },
  low:      { bg: 'var(--accent-dim)',    fg: 'var(--accent)', border: 'transparent' },
  medium:   { bg: 'var(--amber-dim)',     fg: 'var(--amber)',  border: 'transparent' },
  high:     { bg: 'rgba(249,115,22,.10)', fg: '#f97316',       border: 'transparent' },
  critical: { bg: 'var(--red-dim)',       fg: 'var(--red)',    border: 'rgba(246,70,93,.25)' },
}

const SEVERITY_LABELS: Record<Severity, string> = {
  info: 'Info', low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
}

interface SeverityBadgeProps {
  severity: Severity | string
  label?: string
  title?: string
  size?: 'sm' | 'md'
  style?: CSSProperties
}

export function SeverityBadge({ severity, label, title, size = 'sm', style }: SeverityBadgeProps) {
  const key = (severity || 'info').toLowerCase() as Severity
  const colors = SEVERITY_COLORS[key] || SEVERITY_COLORS.info
  const displayLabel = label || SEVERITY_LABELS[key] || key

  const base: CSSProperties = {
    display: 'inline-block',
    padding: size === 'sm' ? '1px 7px' : '2px 10px',
    borderRadius: 10,
    fontSize: size === 'sm' ? 8 : 10,
    fontWeight: 800,
    textTransform: 'uppercase',
    letterSpacing: '.3px',
    lineHeight: size === 'sm' ? '16px' : '20px',
    background: colors.bg,
    color: colors.fg,
    border: colors.border !== 'transparent' ? `1px solid ${colors.border}` : 'none',
    whiteSpace: 'nowrap',
    ...style,
  }

  return <span style={base} title={title || `Severity: ${displayLabel}`}>{displayLabel}</span>
}

export default SeverityBadge
```
