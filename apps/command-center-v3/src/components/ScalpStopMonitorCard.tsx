/** Risk-tab card: live stop/risk monitoring for OPEN momentum_scalp paper trades.
 *  Advisory/read-only — source: /api/v2/scalp/stop-monitor (scalp_stop_monitor.py). */
import { useApi } from '../hooks/useApi'

const LVL: Record<string, string> = { red: '#ef4444', amber: '#f59e0b', yellow: '#eab308' }

export default function ScalpStopMonitorCard() {
  const { data } = useApi<any>('/api/v2/scalp/stop-monitor', 30_000)
  const d = data?.data ?? data
  if (!d) return null
  const scalps: any[] = d.open_scalps ?? []
  const alerts: any[] = d.alerts ?? []
  const heat = d.portfolio_heat_pct
  const heatCol = heat == null ? 'var(--text3)' : heat > (d.limits?.heat_kill_pct ?? 4.5) ? '#ef4444' : heat > 3.0 ? '#f59e0b' : '#22c55e'

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>🎯 Scalp Stop Monitor</span>
        <span style={{ fontSize: 11, color: 'var(--text2)' }}>{d.count ?? 0} open · open risk ${d.open_risk_usd ?? 0}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, fontWeight: 800, color: heatCol }}
          title={`portfolio heat = open risk / paper equity · kill at ${d.limits?.heat_kill_pct}%`}>
          heat {heat == null ? '—' : `${heat}%`}
        </span>
      </div>

      {alerts.length > 0 && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {alerts.map((a, i) => (
            <div key={i} style={{ fontSize: 10.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5,
              color: LVL[a.level] ?? 'var(--text2)', background: `${LVL[a.level] ?? '#888'}1a`, border: `1px solid ${LVL[a.level] ?? '#888'}40` }}>
              ▲ {a.msg}
            </div>
          ))}
        </div>
      )}

      {scalps.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>No open scalps. Layer-3 trailing is config-OFF (backtest net-negative for momentum).</div>
      ) : (
        <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr auto auto auto auto', gap: '3px 10px', fontSize: 10.5 }}>
          <span style={{ color: 'var(--text3)', fontWeight: 700 }}>symbol</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>cur R</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>to stop</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>to BE</span>
          <span style={{ color: 'var(--text3)', fontWeight: 700, textAlign: 'right' }}>risk $</span>
          {scalps.map((s, i) => {
            const rCol = s.current_R == null ? 'var(--text3)' : s.current_R >= 0 ? '#22c55e' : '#ef4444'
            const nearStop = s.stop_distance_R != null && s.stop_distance_R < 0.3
            return [
              <span key={`s${i}`} style={{ fontWeight: 700, color: 'var(--text1)' }}>{s.symbol}
                {!s.breakeven_secured && <span style={{ color: '#f59e0b', fontSize: 8.5 }}> ·no BE</span>}</span>,
              <span key={`r${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: rCol, fontWeight: 700 }}>{s.current_R ?? '—'}</span>,
              <span key={`d${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: nearStop ? '#ef4444' : 'var(--text2)' }}>{s.stop_distance_R ?? '—'}R</span>,
              <span key={`b${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text2)' }}>{s.dist_to_breakeven_R ?? '—'}R</span>,
              <span key={`u${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--text3)' }}>{s.risk_usd ?? '—'}</span>,
            ]
          })}
        </div>
      )}
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 8 }}>{d.note}</div>
    </div>
  )
}
