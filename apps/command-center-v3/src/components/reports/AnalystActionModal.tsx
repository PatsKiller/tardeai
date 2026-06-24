/** AnalystActionModal — addressable action popup from analyst reports. */
import type { DeckAction } from './ActionDeck'

const SEV: Record<string, string> = {
  critical: '#ef4444', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa',
}
const ACT_ROUTE: Record<string, string> = {
  stop_triggered: '/v3/risk', unprotected_position: '/v3/risk', risk_review: '/v3/risk',
  approval_needed: '/v3/trading', broker_manual: '/v3/trading', hermes_review: '/v3/hermes',
  system_health: '/v3/system', cron_or_backup: '/v3/system', llm_review: '/v3/system',
  research_needed: '/v3/intelligence', portfolio_review: '/v3/portfolio', recovery: '/v3/risk',
}

function actionRoute(a: DeckAction): string {
  if (a.route) {
    if (a.symbol && !a.route.includes('symbol=')) {
      const sep = a.route.includes('?') ? '&' : '?'
      return `${a.route}${sep}symbol=${a.symbol}`
    }
    return a.route
  }
  const base = ACT_ROUTE[a.action_class || ''] || '/v3/'
  if (a.symbol) return `${base}?symbol=${a.symbol}`
  return base
}

export default function AnalystActionModal({ action, onClose }: {
  action: DeckAction | null
  onClose: () => void
}) {
  if (!action) return null
  const sev = (action.severity || 'info').toLowerCase()
  const color = SEV[sev] || '#60a5fa'
  const href = actionRoute(action)

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,.65)', zIndex: 1100,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg1)', border: `1px solid ${color}55`, borderRadius: 12,
          padding: 20, width: 480, maxWidth: '94vw', boxShadow: '0 12px 40px rgba(0,0,0,.4)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 800, color, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              {(action.action_class || 'action').replace(/_/g, ' ')}
            </div>
            <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', marginTop: 4, lineHeight: 1.4 }}>
              {action.symbol && (
                <span style={{ fontFamily: 'monospace', color: '#60a5fa', marginRight: 8 }}>{action.symbol}</span>
              )}
              Address this item
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: 'var(--text3)', fontSize: 18, cursor: 'pointer', lineHeight: 1,
          }}>×</button>
        </div>

        <div style={{
          fontSize: 12, color: 'var(--text1)', lineHeight: 1.55, padding: '12px 14px',
          background: 'var(--bg2)', borderRadius: 8, borderLeft: `4px solid ${color}`, marginBottom: 14,
        }}>
          {action.text}
        </div>

        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 14 }}>
          Severity: <b style={{ color }}>{sev}</b>
          {action.source && <> · Source: {action.source}</>}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button onClick={onClose} style={{
            fontSize: 11, padding: '7px 14px', borderRadius: 6, cursor: 'pointer',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)',
          }}>Dismiss</button>
          {action.symbol && (
            <a href={`/v3/risk?symbol=${action.symbol}`} style={{
              fontSize: 11, fontWeight: 700, padding: '7px 14px', borderRadius: 6, textDecoration: 'none',
              border: '1px solid var(--border)', background: 'var(--bg2)', color: '#f59e0b',
            }}>Risk ↗</a>
          )}
          <a href={href} style={{
            fontSize: 11, fontWeight: 800, padding: '7px 16px', borderRadius: 6, textDecoration: 'none',
            background: '#1d4ed8', color: '#fff',
          }}>
            {action.route_label || 'Open'} &amp; address →
          </a>
        </div>
      </div>
    </div>
  )
}