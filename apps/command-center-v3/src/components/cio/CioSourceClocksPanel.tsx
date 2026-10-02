import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

/** CIOSourceClocks@v1 — one data clock per CIO source (GET /api/v3/cio/source-clocks).
 *
 * source_as_of is the source's own data clock; composition_as_of is only when
 * this projection was read. A source with no trustworthy clock is UNKNOWN,
 * never FRESH.
 */
type SourceClock = {
  source: string
  producer?: string
  source_ref?: string | null
  source_version?: string | null
  source_as_of?: string | null
  clock_field?: string | null
  composition_as_of?: string | null
  age_seconds?: number | null
  stale_after_seconds?: number | null
  freshness?: string
  evidence_class?: string
  reason?: string | null
  note?: string
}

type Payload = {
  ok?: boolean
  schema?: string
  composition_as_of?: string
  compose_ms?: number
  sources?: SourceClock[]
  counts?: Record<string, number>
  not_fresh?: string[]
  freshness_rule?: string
  error?: string
}

const LABELS: Record<string, string> = {
  portfolio_cash: 'Portfolio / cash',
  decision: 'Decision',
  research: 'Research',
  memory: 'Memory',
  analyst_data: 'Analyst data',
  technicals: 'Technicals',
  hermes_research: 'Hermes research',
  outcome_belief: 'Outcome / belief',
}

function tone(state?: string): string {
  const s = String(state || '').toUpperCase()
  if (s === 'FRESH') return 'var(--green)'
  if (s === 'STALE' || s === 'UNKNOWN') return 'var(--amber)'
  if (s === 'UNAVAILABLE') return 'var(--red)'
  return 'var(--text3)'
}

function stamp(value?: string | null): string {
  return value ? String(value).replace('T', ' ').slice(0, 19) : 'none'
}

function dur(seconds?: number | null): string {
  if (seconds == null) return 'UNKNOWN'
  const s = Math.max(0, Math.round(seconds))
  if (s < 90) return `${s}s`
  if (s < 90 * 60) return `${Math.round(s / 60)}m`
  if (s < 48 * 3600) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

export default function CioSourceClocksPanel() {
  const { data, loading, error } = useApi<Payload>('/api/v3/cio/source-clocks', 120_000)
  const rows = data?.sources || []
  return (
    <section data-testid="cio-source-clocks" style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)', marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text1)', letterSpacing: '.35px' }}>CIO source clocks — each source's own data time</div>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>
          composed {stamp(data?.composition_as_of)}
          {Object.entries(data?.counts || {}).map(([k, v]) => <span key={k} style={{ marginLeft: 8, color: tone(k), fontWeight: 800 }}>{k} {v}</span>)}
        </div>
      </div>
      {loading && !data && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading source clocks…</div>}
      {(error || data?.ok === false) && <div style={{ fontSize: 11, color: 'var(--red)' }}>Source clocks unavailable: {String(error || data?.error || 'error')}</div>}
      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: 'var(--text3)', fontSize: 10, textAlign: 'left' }}>
                <th style={{ padding: '3px 6px' }}>SOURCE</th>
                <th style={{ padding: '3px 6px' }}>FRESHNESS</th>
                <th style={{ padding: '3px 6px' }}>SOURCE AS OF</th>
                <th style={{ padding: '3px 6px' }}>AGE / BUDGET</th>
                <th style={{ padding: '3px 6px' }}>PRODUCER</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.source} data-testid={`cio-source-clock-${r.source}`} style={{ borderTop: '1px solid var(--border-subtle)' }} title={`${r.source_ref || ''}${r.source_version ? ` · ${r.source_version}` : ''}${r.note ? ` · ${r.note}` : ''}`}>
                  <td style={{ padding: '4px 6px', fontWeight: 700 }}>{LABELS[r.source] || r.source}</td>
                  <td style={{ padding: '4px 6px', color: tone(r.freshness), fontWeight: 800 }}>{r.freshness || 'UNKNOWN'}</td>
                  <td style={{ padding: '4px 6px' }}>
                    {r.source_as_of ? stamp(r.source_as_of) : <span style={{ color: 'var(--amber)' }}>no trustworthy clock</span>}
                    {r.clock_field ? <span style={{ color: 'var(--text3)', fontSize: 10 }}> · {r.clock_field}</span> : null}
                    {!r.source_as_of && r.reason ? <span style={{ color: 'var(--text3)', fontSize: 10 }}> · {r.reason}</span> : null}
                  </td>
                  <td style={{ padding: '4px 6px' }}>{dur(r.age_seconds)} / {dur(r.stale_after_seconds)}</td>
                  <td style={{ padding: '4px 6px', color: 'var(--text2)' }}>{r.producer || 'UNKNOWN'}<div style={{ color: 'var(--text3)', fontSize: 10 }}>{r.evidence_class || ''}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text3)' }}>
        {data?.freshness_rule || 'FRESH only within each source’s stale budget; composition time is never a source clock.'}
      </div>
    </section>
  )
}
