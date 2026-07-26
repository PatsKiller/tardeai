import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE, numStyle } from '../lib/watchTokens'

function bar(pct: number | null) {
  const v = pct ?? 0
  const c = v > 0 ? BB.green : v < 0 ? BB.red : BB.text3
  const w = Math.min(Math.abs(v) * 12, 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 130 }}>
      <div style={{ flex: 1, height: 6, background: BB.bgShift, borderRadius: 2, position: 'relative' }}>
        <div style={{ position: 'absolute', left: v < 0 ? `${50 - w / 2}%` : '50%', width: `${w / 2}%`, height: 6, background: c, borderRadius: 2 }} />
      </div>
      <span style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 700, color: c, width: 52, textAlign: 'right' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>
    </div>
  )
}

export default function FinvizSectorPanel() {
  const [type, setType] = useState<'sector' | 'industry'>('sector')
  const { data } = useApi<any>(`/api/v2/sector-performance?type=${type}`, 300_000)
  const items: any[] = data?.items ?? []
  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 12, marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>Single-vendor performance tape</div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>
            Finviz {type} snapshot · {data?.count ?? 0} rows · as of {data?.as_of || 'not reported'} · ranking lens, not a recommendation
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['sector', 'industry'] as const).map(t => (
            <button key={t} onClick={() => setType(t)} style={{
              padding: '3px 10px', fontSize: TYPE.xs, borderRadius: 2, cursor: 'pointer',
              border: `1px solid ${type === t ? T.link : BB.border}`, background: type === t ? BB.bgShift : 'transparent',
              color: type === t ? T.link : BB.text3, fontWeight: type === t ? 800 : 500, textTransform: 'capitalize',
            }}>{t}</button>
          ))}
        </div>
      </div>
      {!data && <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>Loading…</div>}
      <div style={{ display: 'grid', gridTemplateColumns: type === 'industry' ? 'repeat(auto-fill, minmax(290px, 1fr))' : '1fr', gap: 3 }}>
        {(type === 'industry' ? items.slice(0, 30) : items).map((it, i) => (
          <div key={`${it.name}-${i}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '4px 6px', borderBottom: `1px solid ${BB.borderHair}` }}>
            <span style={{ fontSize: TYPE.sm, color: BB.text1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
            {bar(it.change_pct)}
          </div>
        ))}
      </div>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 7 }}>
        Source: Finviz group export via /api/v2/sector-performance. Use this panel to confirm broad direction; use the deterministic rotation brief for relative state, portfolio context and governed candidates.
      </div>
    </div>
  )
}
