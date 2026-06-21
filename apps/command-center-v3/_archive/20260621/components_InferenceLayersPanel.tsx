import { useApi } from '../hooks/useApi'
import { EnsembleValidationInline } from './EnsembleValidationCard'

// Inference Layers — higher-order reasoning surface.
// Reads /api/v2/inference/* (latest run + regional signals + sizing). Read-only, advisory.

const SEV_COLOR: Record<string, string> = {
  critical: '#ef4444', high: '#f59e0b', medium: '#facc15', low: '#64748b',
}
const TYPE_ICON: Record<string, string> = {
  regional_impact: '🌏', journal_pattern: '📓', nav_signal: '💰', opportunity: '🎯',
  risk: '⚠️', sizing: '📐', market_regime: '🌡️', data_gap: '🕳️',
}
const REGIME_COLOR: Record<string, string> = {
  risk_on: '#22c55e', neutral: '#94a3b8', risk_off: '#f59e0b', high_vol: '#ef4444',
}

function pct(v: any) { return v == null ? '—' : `${Math.round(Number(v) * 100)}%` }

export default function InferenceLayersPanel() {
  const { data, stale } = useApi<any>('/api/v2/inference/latest', 120_000)
  const { data: regional } = useApi<any>('/api/v2/inference/regional', 300_000)
  const { data: sizing } = useApi<any>('/api/v2/inference/sizing', 300_000)

  const run = data?.run
  const results: any[] = data?.results ?? []
  const regimes = run?.regime ?? 'unknown'
  const regSignals: any[] = regional?.data ?? []
  const sizeRecs: any[] = sizing?.data ?? []

  const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Header / regime */}
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>
            Inference Layers {stale && <span style={{ fontSize: 9, color: '#f59e0b' }}>· stale</span>}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {run ? `run #${run.id} · ${run.trigger} · ${results.length} inferences` : 'no runs yet'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>Regime</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: REGIME_COLOR[regimes] ?? 'var(--text1)' }}>
            {String(regimes).replace('_', ' ')}
          </div>
        </div>
      </div>

      {/* Top inferences */}
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
          Top Inferences
        </div>
        {results.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No inferences in the latest cycle.</div>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {results.slice(0, 14).map((r, i) => (
            <div key={i} style={{
              display: 'flex', gap: 10, padding: '8px 10px', borderRadius: 6,
              background: 'var(--bg2)', borderLeft: `3px solid ${SEV_COLOR[r.severity] ?? '#64748b'}`,
            }}>
              <div style={{ fontSize: 16 }}>{TYPE_ICON[r.inference_type] ?? '•'}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{r.title}</div>
                {r.body && <div style={{ fontSize: 10.5, color: 'var(--text2)', marginTop: 2, lineHeight: 1.4 }}>
                  {String(r.body).split('\n')[0].slice(0, 220)}
                </div>}
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>
                  {r.inference_type} · {r.subject} · {r.layer} · lane {r.source_lane}
                </div>
                {r.id && (r.severity === 'high' || r.severity === 'critical') && (
                  <EnsembleValidationInline
                    targetType="inference"
                    targetId={r.id}
                    subject={r.subject}
                    content={`${r.title}\n${r.body ?? ''}`}
                  />
                )}
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: SEV_COLOR[r.severity] ?? 'var(--text2)', whiteSpace: 'nowrap' }}>
                {pct(r.confidence)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Cross-regional signals */}
      {regSignals.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
            🌏 Cross-Regional Signals
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {regSignals.slice(0, 8).map((s, i) => (
              <div key={i} style={{ fontSize: 11, color: 'var(--text2)', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{s.region}</span>
                <span style={{ color: 'var(--text3)' }}> · {s.theme} · </span>
                <span style={{ color: s.direction === 'bearish' ? '#ef4444' : s.direction === 'bullish' ? '#22c55e' : '#94a3b8' }}>
                  {s.direction}
                </span>
                <span style={{ color: 'var(--text3)' }}> · {pct(s.confidence)}</span>
                {s.us_impact && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{String(s.us_impact).slice(0, 200)}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risk-appropriate sizing */}
      {sizeRecs.length > 0 && (
        <div style={card}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
            📐 Risk-Adjusted Sizing (advisory)
          </div>
          <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                <th style={{ padding: 4 }}>Symbol</th><th>Strategy</th><th>Base</th>
                <th>Rec</th><th>Tilt</th><th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {sizeRecs.slice(0, 12).map((s, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--border)', color: 'var(--text1)' }}>
                  <td style={{ padding: 4, fontWeight: 700 }}>{s.symbol}</td>
                  <td style={{ color: 'var(--text3)' }}>{s.strategy_id}</td>
                  <td>{s.base_shares}</td>
                  <td style={{ fontWeight: 700, color: s.recommended_shares === 0 ? '#ef4444' : 'var(--text0)' }}>{s.recommended_shares}</td>
                  <td>{Number(s.tilt).toFixed(2)}</td>
                  <td style={{ color: s.risk_gate_result === 'APPROVED' ? '#22c55e' : '#f59e0b' }}>{s.risk_gate_result ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
