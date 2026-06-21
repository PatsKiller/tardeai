import { useState } from 'react'
import { useApi } from '../hooks/useApi'

function bar(pct: number | null) {
  const v = pct ?? 0
  const c = v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : 'var(--text3)'
  const w = Math.min(Math.abs(v) * 12, 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 120 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--bg2)', borderRadius: 3, position: 'relative' }}>
        <div style={{ position: 'absolute', left: v < 0 ? `${50 - w / 2}%` : '50%', width: `${w / 2}%`, height: 6, background: c, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color: c, width: 46, textAlign: 'right' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>
    </div>
  )
}

export default function FinvizSectorPanel() {
  const [type, setType] = useState<'sector' | 'industry'>('sector')
  const { data } = useApi<any>(`/api/v2/sector-performance?type=${type}`, 300_000)
  const items: any[] = data?.items ?? []
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)' }}>Finviz {type} performance <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 500 }}>· {data?.count ?? 0} · {data?.as_of ?? ''}</span></div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['sector', 'industry'] as const).map(t => (
            <button key={t} onClick={() => setType(t)} style={{ padding: '3px 10px', fontSize: 10, borderRadius: 5, border: 'none', cursor: 'pointer', background: type === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: type === t ? '#60a5fa' : 'var(--text3)', fontWeight: type === t ? 700 : 400 }}>{t}</button>
          ))}
        </div>
      </div>
      {!data && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading…</div>}
      <div style={{ display: 'grid', gridTemplateColumns: type === 'industry' ? 'repeat(auto-fill, minmax(280px, 1fr))' : '1fr', gap: 3 }}>
        {(type === 'industry' ? items.slice(0, 30) : items).map((it, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontSize: 11, color: 'var(--text1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
            {bar(it.change_pct)}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/sector-performance (Finviz grp_export) · advisory macro/rotation lens</div>
    </div>
  )
}
