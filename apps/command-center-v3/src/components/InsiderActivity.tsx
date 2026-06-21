import { useApi } from '../hooks/useApi'

export default function InsiderActivity({ symbol }: { symbol: string }) {
  const { data } = useApi<any>(`/api/v2/insider-activity?symbol=${encodeURIComponent(symbol)}`, 300_000)
  const items: any[] = data?.items ?? []
  if (!data) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading…</div>
  if (items.length === 0) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>No recent SEC Form-4 insider filings.</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {items.slice(0, 12).map((it, i) => {
        const buy = /buy|purchase|acqui/i.test(it.transaction_type || '')
        const sell = /sell|sale|dispos/i.test(it.transaction_type || '')
        const c = buy ? '#22c55e' : sell ? '#ef4444' : 'var(--text3)'
        return (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '5px 8px', borderRadius: 6, background: 'var(--bg2)', borderLeft: `3px solid ${c}` }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.filer_name || 'Insider'}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>{it.filer_relation || '—'}{it.transaction_type ? ` · ${it.transaction_type}` : ''}</div>
            </div>
            <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
              {it.total_value ? <div style={{ fontSize: 11, fontWeight: 700, color: c }}>${Number(it.total_value).toLocaleString()}</div> : null}
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>{String(it.filing_date || '').slice(0, 10)}{it.sec_url ? <> · <a href={it.sec_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>SEC</a></> : null}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
