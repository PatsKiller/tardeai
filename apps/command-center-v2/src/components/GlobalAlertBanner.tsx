/* TODO Session 32: wire alert_dispatcher.py dedup gate to suppress duplicate stop alerts
   Root cause: portfolio_orchestrator.py fires both urgent_alert + draft_alert for same stop condition.
   Fix: add sent_today check in alert_dispatcher.py before sending */
import { useApi } from '../hooks/useApi'

interface Alert {
  severity: 'critical' | 'warning' | 'info'
  message: string
  action: string
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
        return (
          <div
            key={i}
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
            }}
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
            <span style={{ color: 'var(--text3)', fontSize: 10 }}>{a.action}</span>
          </div>
        )
      })}
    </div>
  )
}
