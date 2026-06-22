import { useApi } from '../../hooks/useApi'
import type { DrillContext } from '../DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }

const DEG_COLOR: Record<string, string> = {
  triggered: '#ef4444', danger: '#ef4444', broken: '#ef4444',
  warning: '#f59e0b', weakening: '#94a3b8',
}

function fmtMoney(v?: number | null) {
  if (v == null || !Number.isFinite(v)) return '—'
  return `$${Math.round(v).toLocaleString()}`
}

export default function IntelligenceRotationTab({ onDrill }: Props) {
  const { data, loading, error } = useApi<any>('/api/v2/rotation/summary', 300_000)

  if (loading && !data) {
    return <div style={{ ...card, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>Loading rotation intelligence…</div>
  }
  if (error) {
    return <div style={{ ...card, padding: 16, color: '#ef4444', fontSize: 12 }}>Failed to load rotation summary: {error}</div>
  }

  const rs = data?.summary ?? {}
  const degraded = (data?.degraded_holdings ?? data?.top_candidates ?? []).filter((h: any) => h.degradation).slice(0, 8)
  const pairs = (data?.top_rotation_ideas ?? data?.top_pairs ?? data?.research_rotation_ideas ?? []).slice(0, 8)
  const over = (data?.sector_overweights ?? []).slice(0, 5)
  const under = (data?.sector_underweights ?? []).slice(0, 5)
  const research = (data?.research_candidates ?? []).slice(0, 6)

  const cells: [string, any, string][] = [
    ['Trim review', rs.trim_review, '#ef4444'],
    ['Add review', rs.add_review, '#22c55e'],
    ['Rotation ideas', rs.rotation_ideas, '#60a5fa'],
    ['Watch', rs.watch, '#f59e0b'],
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ ...card, padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>Rotation Intelligence</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
            Advisory only · portfolio {fmtMoney(data?.portfolio_total)}
            {data?.stale && <span style={{ color: '#f59e0b' }}> · cache stale ({Math.round((data.cache_age_sec ?? 0) / 60)}m)</span>}
          </div>
        </div>
        <a href="/v3/rotation" style={{
          padding: '5px 12px', fontSize: 11, fontWeight: 700, borderRadius: 6, textDecoration: 'none',
          background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid #60a5fa55',
        }}>Full Rotation Desk →</a>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        {cells.map(([label, val, c]) => (
          <div key={label} style={{ ...card, padding: '12px 10px', textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 800, color: c }}>{val ?? '—'}</div>
            <div style={{ fontSize: 8.5, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
          </div>
        ))}
      </div>

      {(over.length > 0 || under.length > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ ...card, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>Sector Overweights</div>
            {over.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>None flagged.</div> : over.map((s: any, i: number) => (
              <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{s.theme}</span>
                <span style={{ color: 'var(--text3)' }}> · {s.pct?.toFixed?.(1) ?? s.pct}% (target {s.target}%)</span>
                {s.excess_dollars != null && <span style={{ color: '#f59e0b' }}> · excess {fmtMoney(s.excess_dollars)}</span>}
              </div>
            ))}
          </div>
          <div style={{ ...card, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e', marginBottom: 8 }}>Sector Underweights</div>
            {under.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>None flagged.</div> : under.map((s: any, i: number) => (
              <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{s.theme}</span>
                <span style={{ color: 'var(--text3)' }}> · {s.pct?.toFixed?.(1) ?? s.pct}% (floor {s.floor}%)</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {degraded.length > 0 && (
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Degraded Holdings (rotate-out candidates)</div>
          {degraded.map((h: any, i: number) => {
            const d = h.degradation ?? {}
            const col = DEG_COLOR[d.thesis_status] ?? '#94a3b8'
            return (
              <div key={h.symbol ?? i}
                onClick={() => onDrill({ title: h.symbol, subtitle: d.thesis_status, endpoint: '/api/v2/rotation/summary', rows: [h] })}
                style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#60a5fa' }}>{h.symbol}</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: col }}>{d.thesis_status}</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{d.signal_source}{d.deterministic ? ' · deterministic' : ''}</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>{fmtMoney(h.current_value)}</span>
                </div>
                {(d.what_changed || d.escalation_reason) && (
                  <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3 }}>{d.what_changed || d.escalation_reason}</div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {pairs.length > 0 && (
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top Rotation Ideas</div>
          {pairs.map((p: any, i: number) => (
            <div key={i}
              onClick={() => onDrill({ title: `${p.from_symbol} → ${p.to_symbol}`, subtitle: p.action_class ?? 'ROTATE_REVIEW', endpoint: '/api/v2/rotation/summary', rows: [p] })}
              style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ fontFamily: 'monospace', color: '#ef4444' }}>{p.from_symbol}</span>
              <span style={{ color: 'var(--text3)' }}> → </span>
              <span style={{ fontFamily: 'monospace', color: '#22c55e' }}>{p.to_symbol}</span>
              <span style={{ color: 'var(--text3)', marginLeft: 8 }}>score {p.score ?? '—'}</span>
              {p.rationale && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3 }}>{String(p.rationale).slice(0, 160)}</div>}
            </div>
          ))}
        </div>
      )}

      {research.length > 0 && (
        <div style={{ ...card, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Research Rotate-In Candidates</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {research.map((r: any, i: number) => (
              <span key={r.symbol ?? i}
                onClick={() => onDrill({ title: r.symbol, subtitle: r.cio_view ?? '', endpoint: '/api/v2/rotation/summary', rows: [r] })}
                style={{
                  fontSize: 11, padding: '4px 10px', borderRadius: 5, cursor: 'pointer',
                  background: r.cio_endorsed ? 'rgba(34,197,94,.12)' : r.cio_avoid ? 'rgba(239,68,68,.1)' : 'var(--bg2)',
                  color: r.cio_endorsed ? '#22c55e' : r.cio_avoid ? '#ef4444' : 'var(--text2)',
                  border: '1px solid var(--border)',
                }}>
                {r.symbol}{r.analyst_upside_pct != null ? ` +${Math.round(r.analyst_upside_pct)}%` : ''}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}