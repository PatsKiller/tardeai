import { useApi } from '../../hooks/useApi'
import SynthesizedReportCard from '../SynthesizedReportCard'

interface Props {
  query: string
  onSelect: (item: any) => void
  onArchive: () => void
}

export default function ReportSearch({ query, onSelect, onArchive }: Props) {
  const path = `/api/v2/reports/search?q=${encodeURIComponent(query)}&days=90&limit=20`
  const { data, loading, error } = useApi<any>(path, 0)

  const items = data?.items || []

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>
          Search results · <span style={{ color: '#60a5fa' }}>{query}</span>
        </div>
        <button onClick={onArchive} style={{ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>
          Open in Archive →
        </button>
      </div>
      {loading && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Searching Telegram, email, SIEM, and report stores…</div>}
      {error && <div style={{ fontSize: 11, color: '#ef4444' }}>Search failed: {error}</div>}
      {!loading && !error && items.length === 0 && (
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>No reports match. Try a ticker, sector, or topic keyword.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {items.map((it: any) => (
          <div key={`${it.source}-${it.id}`} onClick={() => onSelect(it)} style={{ cursor: 'pointer' }}>
            <SynthesizedReportCard item={it} compact />
            <div style={{ fontSize: 9, color: 'var(--text3)', margin: '-2px 0 4px 12px' }}>
              {it.category_label || it.category}
              {it.sector && <> · <span style={{ color: '#a855f7' }}>{it.sector}</span></>}
              {it.trend && <> · <span style={{ color: '#22c55e' }}>{it.trend}</span></>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}