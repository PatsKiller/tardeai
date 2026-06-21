import { useApi } from '../hooks/useApi'

const STATUS: Record<string, { c: string; bg: string; label: string }> = {
  live:  { c: '#22c55e', bg: 'rgba(34,197,94,.12)',  label: 'LIVE' },
  slow:  { c: '#f59e0b', bg: 'rgba(245,158,11,.12)', label: 'SLOW' },
  stale: { c: '#f97316', bg: 'rgba(249,115,22,.14)', label: 'STALE' },
  dead:  { c: '#ef4444', bg: 'rgba(239,68,68,.14)',  label: 'DEAD' },
  error: { c: '#a855f7', bg: 'rgba(168,85,247,.14)', label: 'ERROR' },
}
const CATS: Record<string, string> = {
  news: 'News / RSS / API', websearch: 'Web Search', finviz: 'Finviz', macro: 'Macro', research: 'Research',
}

export default function DataSourceHealth() {
  const { data } = useApi<any>('/api/v2/data-source-health', 60_000)
  if (!data) return <div style={{ padding: 20, color: 'var(--text3)' }}>Loading data-source health…</div>
  const sources: any[] = data.sources ?? []
  const summary: Record<string, number> = data.summary ?? {}
  const cats = Array.from(new Set(sources.map(s => s.category)))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)' }}>Data Source Health</div>
          <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 2 }}>
            Per-source freshness vs expected cadence — catches silent sub-source failures (e.g. a search lane returning 0 while the job still "succeeds"). {data.total} sources.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {['dead', 'stale', 'slow', 'live', 'error'].filter(k => summary[k]).map(k => (
            <span key={k} style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6, color: STATUS[k].c, background: STATUS[k].bg }}>
              {summary[k]} {STATUS[k].label}
            </span>
          ))}
        </div>
      </div>

      {cats.map(cat => (
        <div key={cat} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', margin: '4px 0 6px' }}>{CATS[cat] ?? cat}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 8 }}>
            {sources.filter(s => s.category === cat).map(s => {
              const st = STATUS[s.status] ?? STATUS.error
              return (
                <div key={s.source} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: `3px solid ${st.c}`, borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>{s.source}</span>
                    <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 5, color: st.c, background: st.bg }}>{st.label}</span>
                  </div>
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 10 }}>
                    <span>last: {s.age_hours == null ? '—' : s.age_hours < 48 ? `${s.age_hours}h` : `${Math.round(s.age_hours / 24)}d`} ago</span>
                    <span>recent: {s.recent_count ?? '—'}</span>
                    <span>exp ≤{s.expected_fresh_h}h</span>
                  </div>
                  {s.error && <div style={{ fontSize: 9, color: '#ef4444', marginTop: 3 }}>{s.error}</div>}
                </div>
              )
            })}
          </div>
        </div>
      ))}
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/data-source-health · live=within cadence · slow=1–2× late · stale=2–4× late · dead=&gt;4× late or no data</div>
    </div>
  )
}
