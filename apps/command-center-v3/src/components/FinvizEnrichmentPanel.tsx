import { useApi } from '../hooks/useApi'

// color cue for percent-style values where sign matters
function valColor(label: string, v: any): string {
  if (typeof v !== 'number') return 'var(--text0)'
  if (label === 'RSI') return v >= 70 ? '#ef4444' : v <= 30 ? '#22c55e' : 'var(--text0)'
  if (/%$/.test(label) && /(Week|Month|Quarter|Half|YTD|Year|SMA|52w high|52w low)/.test(label))
    return v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : 'var(--text0)'
  return 'var(--text0)'
}
function fmt(v: any): string {
  if (v == null) return '—'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return String(v)
}

export default function FinvizEnrichmentPanel({ symbol }: { symbol: string }) {
  const { data } = useApi<any>(`/api/v2/finviz-enrichment?symbol=${encodeURIComponent(symbol)}`, 300_000)
  if (!data) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading…</div>
  if (!data.found) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>No Finviz enrichment cached for {symbol}.</div>
  const groups: any[] = data.groups ?? []
  return (
    <div>
      <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 8 }}>
        {data.sector}{data.industry ? ` · ${data.industry}` : ''}{data.cached_at ? ` · as of ${String(data.cached_at).slice(0, 10)}` : ''}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
        {groups.map(g => (
          <div key={g.group} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px' }}>
            <div style={{ fontSize: 10.5, fontWeight: 800, color: '#60a5fa', marginBottom: 5 }}>{g.group}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {g.items.map((it: any, i: number) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 10.5 }}>
                  <span style={{ color: 'var(--text3)' }}>{it.label}</span>
                  <span style={{ fontWeight: 700, fontFamily: 'monospace', color: valColor(it.label, it.value) }}>{fmt(it.value)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/finviz-enrichment (Finviz daily, ~60 fields) · advisory</div>
    </div>
  )
}
