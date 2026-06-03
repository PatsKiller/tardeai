import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'
const trendColor = (t?: string) => (t || '').toLowerCase().includes('up') ? '#22c55e' : (t || '').toLowerCase().includes('down') ? '#ef4444' : 'var(--text2)'

export default function WatchlistHub({ onDrill }: Props) {
  const { data: wl } = useApi<any>('/api/v2/watchlist/items?status=active', 60_000)
  const { data: summary } = useApi<any>('/api/v2/watchlist/summary', 120_000)
  const { data: adv } = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)

  const items: any[] = wl?.items ?? []
  const advMap: Record<string, any> = {}
  for (const a of (adv?.advisories ?? [])) advMap[a.symbol] = a
  const advisories: any[] = adv?.advisories ?? []
  const cautionN = advisories.filter(a => a.advisory_flag === 'caution').length
  const favorableN = advisories.filter(a => a.advisory_flag === 'favorable').length
  const byStatus = summary?.by_status ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Watchlist</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{byStatus.active ?? items.length} active · {byStatus.researched ?? 0} researched · {byStatus.removed ?? 0} removed</div>
        </div>
      </div>

      {/* Setup-quality advisory strip (advisory-only, never gates) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Active items', value: items.length, color: 'var(--text0)' },
          { label: 'With setup advisory', value: advisories.length, color: '#60a5fa' },
          { label: '⚠ Caution band', value: cautionN, color: '#ef4444' },
          { label: 'Favorable band', value: favorableN, color: '#22c55e' },
        ].map(k => (
          <div key={k.label} style={{ ...card, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 12, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)', borderRadius: 6 }}>
        ⚠ {adv?.disclaimer ?? 'Advisory only — current technical posture vs the post-trade prior. Never gates promotion/scoring.'} A "caution" badge means the symbol's current RSI sits in a band that historically produced weak entries.
      </div>

      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Active watchlist ({items.length})</div>
        {items.length === 0 ? (
          <div style={{ color: 'var(--text3)', fontSize: 12, padding: 16 }}>No active watchlist items.</div>
        ) : (
          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr 0.8fr 0.8fr 1.4fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
              <span>Symbol</span><span>Source · bucket</span><span>Score</span><span>Trend</span><span>Setup advisory</span>
            </div>
            {items.map((it: any) => {
              const a = advMap[it.symbol]
              return (
                <div key={it.id}
                  onClick={() => onDrill({ title: it.symbol, subtitle: `${it.source ?? ''} · ${it.bucket ?? ''} · ${it.status}`, endpoint: '/api/v2/watchlist/items',
                    rows: [a ? { ...it, setup_advisory: a.note, setup_advisory_flag: a.advisory_flag, setup_prior_score: a.prior_score, current_rsi: a.rsi, rsi_band: a.band } : it] })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr 0.8fr 0.8fr 1.4fr', padding: '7px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{it.symbol}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{it.source ?? '—'}{it.bucket ? ` · ${it.bucket}` : ''}</span>
                  <span style={{ color: 'var(--text2)' }}>{it.score != null ? Number(it.score).toFixed(0) : '—'}</span>
                  <span style={{ color: trendColor(it.trend), fontSize: 10 }}>{it.trend ?? '—'}</span>
                  <span>
                    {a ? (
                      <span title={a.note} style={{ fontSize: 9, padding: '2px 7px', borderRadius: 4, background: 'var(--bg2)', color: advColor(a.advisory_flag), border: `1px solid ${advColor(a.advisory_flag)}33` }}>
                        {a.advisory_flag === 'caution' ? '⚠ ' : ''}RSI {Number(a.rsi).toFixed(0)} ({a.band}) · ~{a.prior_score != null ? Number(a.prior_score).toFixed(0) : '—'}
                      </span>
                    ) : <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>}
                  </span>
                </div>
              )
            })}
          </div>
        )}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/watchlist/items + /api/v2/setup-advisory/candidates (setup-quality prior). Advisory-only — read-only, never gates.</div>
      </div>
    </div>
  )
}
