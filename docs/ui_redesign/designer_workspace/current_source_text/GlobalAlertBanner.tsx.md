# Source Export: GlobalAlertBanner.tsx

- **Original path:** apps/command-center-v2/src/components/GlobalAlertBanner.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 544858eebee22b5522ba0025192b09acd2dbf8d4189361afdf62eda747611182
- **File size:** 3139 bytes
- **Exists:** YES

```tsx
/* TODO Session 32: wire alert_dispatcher.py dedup gate to suppress duplicate stop alerts
   Root cause: portfolio_orchestrator.py fires both urgent_alert + draft_alert for same stop condition.
   Fix: add sent_today check in alert_dispatcher.py before sending */
import { useApi } from '../hooks/useApi'
import { useNavigate } from 'react-router-dom'

interface Alert {
  severity: 'critical' | 'warning' | 'info'
  message: string
  action: string
  link?: string
}

interface AlertData {
  alerts: Alert[]
  count: number
  has_critical: boolean
  freshness: { last_refresh: string; status: string }
}

const SEVERITY_STYLES: Record<string, { bg: string; border: string; icon: string }> = {
  critical: { bg: 'rgba(246,70,93,.08)', border: '#f6465d', icon: '!!' },
  warning: { bg: 'rgba(240,185,11,.06)', border: '#f0b90b', icon: '!' },
  info: { bg: 'rgba(74,144,244,.05)', border: '#4a90f4', icon: 'i' },
}

export default function GlobalAlertBanner() {
  const { data } = useApi<AlertData>('/api/v2/global-alerts', 60000)
  const navigate = useNavigate()

  // Deduplicate alerts by message to prevent identical banners stacking
  const seen = new Set<string>()
  const alerts = (data?.alerts || []).filter(a => {
    if (seen.has(a.message)) return false
    seen.add(a.message)
    return true
  })

  if (alerts.length === 0) return null

  return (
    <div style={{ padding: '0 16px', marginBottom: 8 }}>
      {alerts.map((a, i) => {
        const s = SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.info
        const clickable = !!a.link
        return (
          <div
            key={i}
            onClick={clickable ? () => navigate(a.link!) : undefined}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '6px 12px',
              marginBottom: 4,
              background: s.bg,
              border: `1px solid ${s.border}`,
              borderRadius: 4,
              fontSize: 11,
              cursor: clickable ? 'pointer' : 'default',
              transition: 'background 120ms ease',
            }}
            onMouseEnter={clickable ? (e) => { e.currentTarget.style.background = s.bg.replace(/[\d.]+\)$/, '0.15)') } : undefined}
            onMouseLeave={clickable ? (e) => { e.currentTarget.style.background = s.bg } : undefined}
          >
            <span style={{
              width: 18, height: 18, borderRadius: '50%',
              background: s.border, color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 9, fontWeight: 700, flexShrink: 0,
            }}>
              {s.icon}
            </span>
            <span style={{ color: 'var(--text1)', flex: 1 }}>{a.message}</span>
            <span style={{
              color: clickable ? s.border : 'var(--text3)',
              fontSize: 10,
              fontWeight: clickable ? 600 : 400,
              textDecoration: clickable ? 'underline' : 'none',
            }}>
              {a.action} {clickable ? '→' : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}
```
