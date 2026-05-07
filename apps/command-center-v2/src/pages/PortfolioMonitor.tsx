import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import WatchlistSymbolPanel from '../components/WatchlistSymbolPanel'

interface MonitorItem {
  symbol: string; sources: string[]; in_portfolio: boolean
  in_ai_watchlist: boolean; in_personal_watchlist: boolean
  strategy_type: string | null; latest_price: number | null
  stop_loss: number | null; ideal_entry: number | null
  target_price: number | null; risk_reward: number | null
  account_fit: string | null; analysis_stage: string | null
  latest_recommendation: string | null; research_confidence: number | null
  synthesis_recommendation: string | null; synthesis_confidence: number | null
  total_market_value: number; portfolio_weight: number
  last_recommendation: string | null; last_confidence: number | null
}

const REC_COLORS: Record<string, string> = {
  TRIM: '#D97706', SELL: '#DC2626', ADD: '#0D9488', BUY: '#16A34A',
  HOLD: '#2E86D4', RESEARCH_MORE: '#6B7280', REBALANCE_TRIM: '#D97706',
}

function sortByUrgency(items: MonitorItem[]) {
  const urgency: Record<string, number> = {
    SELL: 0, TRIM: 1, REBALANCE_TRIM: 1, ADD: 2, BUY: 2,
    HOLD: 3, RESEARCH_MORE: 4,
  }
  return [...items].sort((a, b) => {
    const ua = urgency[a.synthesis_recommendation || a.latest_recommendation || ''] ?? 9
    const ub = urgency[b.synthesis_recommendation || b.latest_recommendation || ''] ?? 9
    if (ua !== ub) return ua - ub
    return (b.portfolio_weight || 0) - (a.portfolio_weight || 0)
  })
}

function RecBadge({ rec, conf }: { rec: string; conf: number }) {
  const color = REC_COLORS[rec] || '#6B7280'
  return (
    <div>
      <span style={{ color, fontFamily: 'monospace', fontSize: 13, fontWeight: 700 }}>{rec}</span>
      {conf > 0 && <span style={{ color: '#6B7280', fontSize: 11, marginLeft: 4 }}>{Math.round(conf * 100)}%</span>}
    </div>
  )
}

function StopIndicator({ stop, price }: { stop: number | null; price: number | null }) {
  if (!stop || !price) return <span style={{ color: '#374151', fontFamily: 'monospace', fontSize: 12 }}>—</span>
  const pct = ((price - stop) / price) * 100
  const color = pct < 3 ? '#DC2626' : pct < 8 ? '#D97706' : '#6B7280'
  return (
    <div>
      <span style={{ fontFamily: 'monospace', fontSize: 12, color }}>${stop.toFixed(2)}</span>
      <div style={{ color, fontSize: 9, marginTop: 1 }}>{pct.toFixed(1)}% away</div>
    </div>
  )
}

export default function PortfolioMonitor() {
  const navigate = useNavigate()
  const [items, setItems] = useState<MonitorItem[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [filterRec, setFilterRec] = useState('all')
  const [pendingTasks, setPendingTasks] = useState<Record<string, number>>({})

  useEffect(() => {
    fetch('/api/v2/watchlist/symbols?source=portfolio&limit=200')
      .then(r => r.json())
      .then(d => { setItems(sortByUrgency(d.data?.symbols || [])); setLoading(false) })
      .catch(() => setLoading(false))
    // Fetch pending tasks for cross-linking
    fetch('/api/v2/tasks/pending')
      .then(r => r.json())
      .then(d => {
        const map: Record<string, number> = {}
        ;(d.tasks || []).forEach((t: any) => { if (t.symbol) map[t.symbol] = t.id })
        setPendingTasks(map)
      })
      .catch(() => {})
  }, [])

  const getRec = (i: MonitorItem) => i.synthesis_recommendation || i.latest_recommendation || ''
  const getConf = (i: MonitorItem) => i.synthesis_confidence || i.research_confidence || i.last_confidence || 0

  const filtered = filterRec === 'all' ? items : items.filter(i => {
    const rec = getRec(i)
    if (filterRec === 'TRIM') return rec === 'TRIM' || rec === 'SELL' || rec === 'REBALANCE_TRIM'
    if (filterRec === 'ADD') return rec === 'ADD' || rec === 'BUY'
    return rec === filterRec
  })

  const trimItems = items.filter(i => { const r = getRec(i); return r === 'TRIM' || r === 'SELL' || r === 'REBALANCE_TRIM' })
  const addItems = items.filter(i => { const r = getRec(i); return r === 'ADD' || r === 'BUY' })
  const holdItems = items.filter(i => getRec(i) === 'HOLD')
  const reviewItems = items.filter(i => getRec(i) === 'RESEARCH_MORE' || getRec(i) === '')
  const totalValue = items.reduce((s, i) => s + (i.total_market_value || 0), 0)
  const trimValue = trimItems.reduce((s, i) => s + (i.total_market_value || 0), 0)

  if (loading) return <div style={{ padding: 24, color: '#94A3B8' }}>Loading portfolio positions...</div>

  const th: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', fontSize: 10, color: '#64748B', fontFamily: 'monospace', fontWeight: 600, whiteSpace: 'nowrap' }
  const td: React.CSSProperties = { padding: '10px 10px', verticalAlign: 'middle' }

  return (
    <div style={{ padding: '0 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 0', marginBottom: 8, borderBottom: '1px solid #1E293B' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#E2EAF4', margin: 0 }}>Portfolio Monitor</h1>
        <span style={{ color: '#64748B', fontSize: 13 }}>{items.length} positions · ${Math.round(totalValue).toLocaleString()} tracked</span>
        <a href="/v2/watchlist" style={{ marginLeft: 'auto', color: '#2E86D4', fontSize: 12, textDecoration: 'none', padding: '4px 10px', border: '1px solid #2E86D4', borderRadius: 4 }}>Watchlist Candidates</a>
      </div>

      {/* Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'TRIM / SELL', value: trimItems.length, color: '#DC2626', sub: `$${Math.round(trimValue / 1000)}K flagged`, filter: 'TRIM' },
          { label: 'ADD / BUY', value: addItems.length, color: '#16A34A', sub: addItems.map(i => i.symbol).join(', ') || 'none', filter: 'ADD' },
          { label: 'HOLD', value: holdItems.length, color: '#2E86D4', sub: 'maintain position', filter: 'HOLD' },
          { label: 'NEEDS REVIEW', value: reviewItems.length, color: '#D97706', sub: 'conflicts / errors', filter: 'RESEARCH_MORE' },
        ].map(tile => (
          <div key={tile.label}
            onClick={() => setFilterRec(filterRec === tile.filter ? 'all' : tile.filter)}
            style={{
              background: filterRec === tile.filter ? `color-mix(in srgb, ${tile.color} 12%, transparent)` : '#0F172A',
              border: `1px solid ${filterRec === tile.filter ? tile.color : '#1E293B'}`,
              borderRadius: 8, padding: 14, cursor: 'pointer',
            }}>
            <div style={{ fontSize: 11, color: '#64748B', fontFamily: 'monospace', marginBottom: 4 }}>{tile.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: tile.color, lineHeight: 1 }}>{tile.value}</div>
            <div style={{ fontSize: 11, color: '#6B7280', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tile.sub}</div>
          </div>
        ))}
      </div>

      {/* Table + panel */}
      <div style={{ display: 'flex', gap: 0, position: 'relative' }}>
        <div style={{ flex: 1, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1E293B' }}>
                {['SYMBOL', 'REC', 'WEIGHT', 'VALUE', 'ACCOUNT', 'STOP', 'STAGE'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, idx) => {
                const rec = getRec(item)
                const conf = getConf(item)
                return (
                  <tr key={item.symbol}
                    onClick={() => setSelectedSymbol(selectedSymbol === item.symbol ? null : item.symbol)}
                    style={{
                      borderBottom: '1px solid #0F172A',
                      background: selectedSymbol === item.symbol ? 'rgba(46,134,212,0.08)' : idx % 2 === 0 ? '#0D1424' : 'transparent',
                      cursor: 'pointer',
                    }}>
                    <td style={td}>
                      <a href={`/v2/watchlist/${item.symbol}`} onClick={e => e.stopPropagation()}
                        style={{ color: '#2E86D4', fontFamily: 'monospace', fontWeight: 700, fontSize: 14, textDecoration: 'none' }}>
                        {item.symbol}
                      </a>
                      <div style={{ display: 'flex', gap: 4, marginTop: 3 }}>
                        {item.in_ai_watchlist && <span style={{ fontSize: 8, color: '#0D9488', border: '1px solid #0D9488', padding: '1px 4px', borderRadius: 2, fontFamily: 'monospace' }}>AI</span>}
                        {item.in_personal_watchlist && <span style={{ fontSize: 8, color: '#7C3AED', border: '1px solid #7C3AED', padding: '1px 4px', borderRadius: 2, fontFamily: 'monospace' }}>PER</span>}
                      </div>
                    </td>
                    <td style={td}><RecBadge rec={rec || '—'} conf={conf} /></td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 13, color: (item.portfolio_weight || 0) > 10 ? '#D97706' : '#E2EAF4' }}>
                      {item.portfolio_weight ? `${item.portfolio_weight.toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 13, color: '#E2EAF4' }}>
                      {item.total_market_value ? `$${(item.total_market_value / 1000).toFixed(1)}K` : '—'}
                    </td>
                    <td style={{ ...td, fontSize: 11, color: '#94A3B8', maxWidth: 150 }}>{item.account_fit || '—'}</td>
                    <td style={td}>
                      <StopIndicator stop={item.stop_loss} price={item.latest_price} />
                      {pendingTasks[item.symbol] && (
                        <a href={`/v2/approvals`} onClick={e => e.stopPropagation()}
                          style={{ fontSize: 9, color: '#D97706', fontFamily: 'monospace', border: '1px solid #D97706', padding: '1px 5px', borderRadius: 3, textDecoration: 'none', display: 'inline-block', marginTop: 3 }}>
                          REVIEW
                        </a>
                      )}
                    </td>
                    <td style={td}>
                      <span style={{ fontSize: 10, fontFamily: 'monospace', color: item.analysis_stage === 'final_synthesis_complete' ? '#16A34A' : '#D97706' }}>
                        {item.analysis_stage === 'final_synthesis_complete' ? 'SYNTHESIZED' : (item.analysis_stage || '—')}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Side panel */}
        <WatchlistSymbolPanel symbol={selectedSymbol} onClose={() => setSelectedSymbol(null)} />
      </div>
    </div>
  )
}
