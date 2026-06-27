import { useState } from 'react'
import { useApi } from '../../hooks/useApi'

export default function AdvancedReportsPanel({ account, days }: { account?: string; days: number }) {
  const [rowDim, setRowDim] = useState('setup_family')
  const [colDim, setColDim] = useState('market_regime')
  const mcQ = `/api/v2/journal/monte-carlo?days=${days}${account ? `&account=${account}` : ''}`
  const pvQ = `/api/v2/journal/pivot?days=${days}&row=${rowDim}&col=${colDim}${account ? `&account=${account}` : ''}`
  const { data: mc } = useApi<any>(mcQ, 120_000)
  const { data: pv } = useApi<any>(pvQ, 120_000)
  const m = mc?.data ?? mc
  const p = pv?.data ?? pv

  const exportTax = async () => {
    const r = await fetch(`/api/v2/journal/export?tax=1&days=${days}${account ? `&account=${account}` : ''}`).then(x => x.json())
    if (r?.csv) {
      const blob = new Blob([r.csv], { type: 'text/csv' })
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'trade_in_view_tax.csv'; a.click()
    }
  }

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Monte Carlo (bootstrap)</div>
        {m?.ok ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, fontSize: 10 }}>
            <div><div style={{ color: 'var(--text3)' }}>Median</div><div style={{ fontWeight: 700 }}>${m.median_pnl}</div></div>
            <div><div style={{ color: 'var(--text3)' }}>P10</div><div style={{ fontWeight: 700, color: '#ef4444' }}>${m.p10}</div></div>
            <div><div style={{ color: 'var(--text3)' }}>P90</div><div style={{ fontWeight: 700, color: '#22c55e' }}>${m.p90}</div></div>
            <div><div style={{ color: 'var(--text3)' }}>Prob profit</div><div style={{ fontWeight: 700 }}>{m.prob_profit}%</div></div>
          </div>
        ) : <div style={{ fontSize: 10, color: 'var(--text3)' }}>{m?.error || 'Need more trades'}</div>}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>{m?.simulations} sims × {m?.trades_per_path} trades from {m?.sample_size} historical</div>
      </div>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, fontWeight: 700 }}>Pivot grid</span>
          <select value={rowDim} onChange={e => setRowDim(e.target.value)} style={{ fontSize: 9, padding: 4 }}>{['setup_family', 'market_regime', 'timeframe', 'emotion_before'].map(x => <option key={x} value={x}>{x}</option>)}</select>
          <span style={{ fontSize: 9 }}>×</span>
          <select value={colDim} onChange={e => setColDim(e.target.value)} style={{ fontSize: 9, padding: 4 }}>{['market_regime', 'setup_family', 'direction', 'timeframe'].map(x => <option key={x} value={x}>{x}</option>)}</select>
        </div>
        <div style={{ maxHeight: 200, overflow: 'auto', fontSize: 9 }}>
          {(p?.cells || []).slice(0, 40).map((c: any, i: number) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', borderBottom: '1px solid var(--border)' }}>
              <span>{c.row} × {c.col}</span>
              <span>{c.trades}t · {c.win_rate}% · ${c.net_pnl}</span>
            </div>
          ))}
          {(p?.cells || []).length === 0 && <div style={{ color: 'var(--text3)' }}>Annotate trades to populate pivot</div>}
        </div>
      </div>
      <button onClick={exportTax} style={{ fontSize: 10, padding: '6px 14px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>⬇ Export tax CSV (wash-sale flags)</button>
    </div>
  )
}