import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import MonteCarloPanel from './MonteCarloPanel'
import ReportingAuditPanel from './ReportingAuditPanel'
import AiCritiqueInsightsPanel from './AiCritiqueInsightsPanel'

export default function AdvancedReportsPanel({
  account,
  days,
  initialCritiqueQuery = '',
  onOpenTrade,
}: {
  account?: string
  days: number
  initialCritiqueQuery?: string
  onOpenTrade?: (tradeKey: string) => void
}) {
  const [rowDim, setRowDim] = useState('setup_family')
  const [colDim, setColDim] = useState('market_regime')
  const pvQ = `/api/v2/journal/pivot?days=${days}&row=${rowDim}&col=${colDim}${account ? `&account=${account}` : ''}`
  const { data: pv } = useApi<any>(pvQ, 120_000)
  const p = pv?.data ?? pv

  const exportTax = async () => {
    const r = await fetch(`/api/v2/journal/export?tax=1&days=${days}${account ? `&account=${account}` : ''}`).then(x => x.json())
    if (r?.csv) {
      const blob = new Blob([r.csv], { type: 'text/csv' })
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'trade_in_view_tax.csv'; a.click()
    }
  }

  const emptyPivot = !(p?.cells || []).some((c: any) => c.col && c.col !== '—')

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <AiCritiqueInsightsPanel days={days} initialQuery={initialCritiqueQuery} onOpenTrade={onOpenTrade} />
      <ReportingAuditPanel days={days} />
      <MonteCarloPanel account={account} days={days} />
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
          {(p?.cells || []).length > 0 && emptyPivot && (
            <div style={{ color: '#f59e0b', fontSize: 10, marginTop: 6, lineHeight: 1.4 }}>
              Rows exist but all market_regime columns are "—" — tag Market regime on trades in Tagging Queue to unlock cross-tabs.
            </div>
          )}
        </div>
      </div>
      <button onClick={exportTax} style={{ fontSize: 10, padding: '6px 14px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>⬇ Export tax CSV (wash-sale flags)</button>
    </div>
  )
}