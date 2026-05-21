import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ReferenceLine, ResponsiveContainer, LineChart, Line,
  AreaChart, Area
} from 'recharts'

interface BtStatus { datasets_total: number; runs_total: number; trades_total: number; challengers_total: number }
interface BtRun { run_id: string; run_type: string; strategy_id: string; status: string; start_date: string; end_date: string }
interface BtResult { result_id: number; run_id: string; strategy_id: string; run_type: string; simulated_trades: number; wins: number; losses: number; win_rate: number; profit_factor: number; expectancy_r: number; total_pnl: number; avg_pnl: number; avg_r_multiple: number; max_drawdown_pct: number; equity_curve_json: string | null; equity_curve?: Array<{date: string; value: number}> }
interface BtTrade { simulated_trade_id: string; run_id: string; strategy_id: string; symbol: string; entry_price: number; exit_price: number; pnl: number; r_multiple: number; exit_reason: string }
interface MissedOpp { proposal_id: number; symbol: string; strategy_id: string; proposal_status: string; proposed_date: string; proposed_entry: number; proposed_target: number; proposed_stop: number; simulated_pnl: number | null; simulated_r: number | null; verdict: 'WOULD_WIN' | 'WOULD_LOSE' | null }
interface MissedData { total_missed: number; would_win: number; would_lose: number; pnl_left_on_table: number; opportunities: MissedOpp[] }

function wrColor(wr: number) { return wr >= 55 ? '#22c55e' : wr >= 35 ? '#f59e0b' : '#ef4444' }
function fmt$(n: number) { return (n >= 0 ? '+' : '-') + '$' + Math.abs(n).toFixed(2) }
function fmtR(n: number) { return (n >= 0 ? '+' : '') + n.toFixed(2) + 'R' }

const WrTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div style={{ background: 'rgba(20,20,30,0.95)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: '#e2e8f0' }}>{label?.replace(/_/g, ' ')}</div>
      {d && <>
        <div style={{ color: wrColor(d.win_rate || d.wr || 0), fontWeight: 600 }}>{(d.win_rate || d.wr || 0).toFixed(1)}% win rate</div>
        {d.trades != null && <div style={{ color: '#94a3b8' }}>n = {d.trades} trades</div>}
        {d.avg_r != null && <div style={{ color: '#94a3b8' }}>avg R {fmtR(d.avg_r)}</div>}
        {d.total_pnl != null && <div style={{ color: d.total_pnl >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(d.total_pnl)}</div>}
        <div style={{ color: '#64748b', fontSize: 11, marginTop: 6 }}>Click to filter trades</div>
      </>}
    </div>
  )
}

type TabId = 'overview' | 'strategy' | 'trades' | 'missed' | 'results' | 'runs'

export default function Backtesting() {
  const [status, setStatus] = useState<BtStatus | null>(null)
  const [runs, setRuns] = useState<BtRun[]>([])
  const [results, setResults] = useState<BtResult[]>([])
  const [trades, setTrades] = useState<BtTrade[]>([])
  const [missed, setMissed] = useState<MissedData | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<TabId>('overview')
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null)
  const [selectedResult, setSelectedResult] = useState<BtResult | null>(null)
  const [runFilter, setRunFilter] = useState('all')

  useEffect(() => {
    (async () => {
      setLoading(true)
      const [st, ru, re, tr, mi] = await Promise.allSettled([
        fetch('/api/v2/backtesting/status').then(r => r.json()),
        fetch('/api/v2/backtesting/runs').then(r => r.json()),
        fetch('/api/v2/backtesting/results').then(r => r.json()),
        fetch('/api/v2/backtesting/trades').then(r => r.json()),
        fetch('/api/v2/backtesting/missed-opportunities').then(r => r.json()),
      ])
      if (st.status === 'fulfilled') setStatus(st.value.data ?? st.value)
      if (ru.status === 'fulfilled') setRuns(ru.value.data ?? [])
      if (re.status === 'fulfilled') {
        const raw: BtResult[] = re.value.data ?? []
        setResults(raw.map(r => ({
          ...r,
          equity_curve: r.equity_curve_json ? (() => { try { return JSON.parse(r.equity_curve_json!) } catch { return [] } })() : [],
        })))
      }
      if (tr.status === 'fulfilled') setTrades(tr.value.data ?? [])
      if (mi.status === 'fulfilled' && mi.value.ok) setMissed(mi.value.data)
      setLoading(false)
    })()
  }, [])

  const strategyStats = useMemo(() => {
    const m: Record<string, { n: number; wins: number; pnl: number; rs: number[] }> = {}
    trades.forEach(t => {
      const s = t.strategy_id
      if (!s || s === 'unknown') return
      if (!m[s]) m[s] = { n: 0, wins: 0, pnl: 0, rs: [] }
      m[s].n++
      if ((t.pnl ?? 0) > 0) m[s].wins++
      m[s].pnl += Number(t.pnl ?? 0)
      if (t.r_multiple != null) m[s].rs.push(Number(t.r_multiple))
    })
    return Object.entries(m).map(([strategy, v]) => ({
      strategy, trades: v.n,
      win_rate: v.n > 0 ? Math.round(100 * v.wins / v.n) : 0,
      wr: v.n > 0 ? Math.round(100 * v.wins / v.n) : 0,
      total_pnl: Math.round(v.pnl * 100) / 100,
      avg_r: v.rs.length > 0 ? Math.round(v.rs.reduce((a, b) => a + b, 0) / v.rs.length * 100) / 100 : 0,
    })).sort((a, b) => b.win_rate - a.win_rate)
  }, [trades])

  const filteredTrades = useMemo(() => selectedStrategy ? trades.filter(t => t.strategy_id === selectedStrategy) : trades, [trades, selectedStrategy])

  const rBuckets = useMemo(() => {
    const src = selectedStrategy ? trades.filter(t => t.strategy_id === selectedStrategy) : trades
    return [
      { label: '<-2R', min: -99, max: -2 }, { label: '-2 to -1', min: -2, max: -1 },
      { label: '-1 to 0', min: -1, max: 0 }, { label: '0 to 1', min: 0, max: 1 },
      { label: '1 to 2', min: 1, max: 2 }, { label: '>2R', min: 2, max: 99 },
    ].map(b => ({ ...b, count: src.filter(t => t.r_multiple != null && t.r_multiple > b.min && t.r_multiple <= b.max).length }))
  }, [trades, selectedStrategy])

  const flagged = strategyStats.filter(s => s.win_rate < 35 && s.trades >= 3)

  const handleStrategyClick = useCallback((data: any) => {
    const name = data?.activePayload?.[0]?.payload?.strategy ?? data?.strategy
    if (!name) return
    setSelectedStrategy(prev => prev === name ? null : name)
    setTab('trades')
  }, [])

  const card: React.CSSProperties = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px' }
  const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }

  if (loading) return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: 'rgba(255,255,255,0.4)' }}>Loading backtest data...</div>

  const TABS: { id: TabId; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'strategy', label: `Strategy (${strategyStats.length})` },
    { id: 'trades', label: `Trades (${selectedStrategy ? `${filteredTrades.length}` : trades.length})` },
    { id: 'missed', label: `Missed (${missed?.total_missed ?? 0})` },
    { id: 'results', label: `Results (${results.length})` },
    { id: 'runs', label: `Runs (${runs.length})` },
  ]

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: 'rgba(255,255,255,0.9)' }}>Backtesting</h1>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', margin: '4px 0 0' }}>Simulated evidence — not live trading proof.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['Replay Trades', 'Replay Proposals'].map(label => (
            <button key={label} style={{ padding: '7px 14px', borderRadius: 8, fontSize: 12, fontWeight: 500, background: 'rgba(34,197,94,0.15)', color: '#4ade80', border: '1px solid rgba(34,197,94,0.3)', cursor: 'pointer' }}
              onClick={() => fetch('/api/v2/backtesting/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: label.toLowerCase().replace(' ', '_'), strategies: 'all' }) }).then(() => window.location.reload()).catch(console.error)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Datasets', value: status?.datasets_total ?? 0 },
          { label: 'Runs', value: status?.runs_total ?? 0 },
          { label: 'Sim Trades', value: (status?.trades_total ?? 0).toLocaleString() },
          { label: 'Results', value: results.length },
          { label: 'Flagged', value: flagged.length, accent: flagged.length > 0 },
          { label: 'Missed', value: missed?.total_missed ?? 0 },
        ].map(k => (
          <div key={k.label} style={{ ...card, padding: '14px 16px', textAlign: 'center', borderColor: (k as any).accent ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.08)' }}>
            <div style={{ fontSize: 24, fontWeight: 600, color: (k as any).accent ? '#f87171' : 'rgba(255,255,255,0.9)' }}>{k.value}</div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Alert */}
      {flagged.length > 0 && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 16px', marginBottom: 16, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 8, fontSize: 12, color: '#fca5a5' }}>
          <span style={{ color: '#f87171' }}>Warning</span>
          <span><strong>Low win rate: </strong>{flagged.map(s => `${s.strategy.replace(/_/g, ' ')} ${s.win_rate}%`).join(' | ')}</span>
        </div>
      )}

      {/* Filter chip */}
      {selectedStrategy && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 12px', marginBottom: 14, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.35)', borderRadius: 20, fontSize: 12, color: '#a5b4fc' }}>
          <span>Filtered: <strong>{selectedStrategy.replace(/_/g, ' ')}</strong></span>
          <button onClick={() => setSelectedStrategy(null)} style={{ background: 'none', border: 'none', color: '#a5b4fc', cursor: 'pointer', fontSize: 14, padding: 0 }}>x</button>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.08)', marginBottom: 24, overflowX: 'auto' }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '9px 18px', fontSize: 13, fontWeight: 500, background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: tab === t.id ? '2px solid rgba(100,170,255,0.8)' : '2px solid transparent',
            color: tab === t.id ? 'rgba(200,220,255,0.9)' : 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap', marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {/* OVERVIEW */}
      {tab === 'overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div style={card}>
            <div style={secTitle}>Win rate by strategy</div>
            <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', marginBottom: 10, marginTop: -8 }}>Click any bar to filter trades</p>
            <ResponsiveContainer width="100%" height={Math.max(240, strategyStats.length * 30 + 20)}>
              <BarChart data={strategyStats} layout="vertical" margin={{ top: 0, right: 50, bottom: 0, left: 150 }} onClick={handleStrategyClick} style={{ cursor: 'pointer' }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(255,255,255,0.06)" />
                <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.4)' }} axisLine={{ stroke: 'rgba(255,255,255,0.1)' }} tickLine={false} />
                <YAxis dataKey="strategy" type="category" tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.6)' }} width={148} tickFormatter={s => s.replace(/_/g, ' ')} axisLine={false} tickLine={false} />
                <Tooltip content={<WrTooltip />} />
                <ReferenceLine x={50} stroke="rgba(245,158,11,0.4)" strokeDasharray="4 2" />
                <Bar dataKey="win_rate" radius={[0, 4, 4, 0]}>
                  {strategyStats.map((s, i) => <Cell key={i} fill={s.strategy === selectedStrategy ? '#818cf8' : wrColor(s.win_rate)} opacity={selectedStrategy && s.strategy !== selectedStrategy ? 0.35 : 1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={card}>
              <div style={secTitle}>R-multiple distribution</div>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={rBuckets} margin={{ top: 4, right: 4, bottom: 20, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.4)' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.4)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {rBuckets.map((b, i) => <Cell key={i} fill={b.min >= 0 ? 'rgba(34,197,94,0.8)' : 'rgba(239,68,68,0.7)'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={{ ...card, cursor: 'pointer' }} onClick={() => setTab('missed')}>
              <div style={secTitle}>Missed proposals impact</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {[
                  { label: 'Would win', value: missed?.would_win ?? 0, color: '#4ade80' },
                  { label: 'Would lose', value: missed?.would_lose ?? 0, color: '#f87171' },
                  { label: 'Left on table', value: `$${(missed?.pnl_left_on_table ?? 0).toFixed(2)}`, color: '#fbbf24' },
                ].map(k => (
                  <div key={k.label} style={{ textAlign: 'center', padding: '10px 8px', background: 'rgba(255,255,255,0.04)', borderRadius: 8 }}>
                    <div style={{ fontSize: 22, fontWeight: 600, color: k.color }}>{k.value}</div>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 3 }}>{k.label}</div>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', marginTop: 10, marginBottom: 0 }}>Click to view table</p>
            </div>
          </div>
        </div>
      )}

      {/* STRATEGY */}
      {tab === 'strategy' && (
        <div style={card}>
          <div style={secTitle}>Strategy performance — click row to filter trades</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              {['Strategy', 'Trades', 'Win rate', 'Avg R', 'Total P&L'].map(h => <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'right', padding: '8px 12px', fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase' }}>{h}</th>)}
            </tr></thead>
            <tbody>{strategyStats.map(s => (
              <tr key={s.strategy} onClick={() => { setSelectedStrategy(p => p === s.strategy ? null : s.strategy); setTab('trades') }}
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', cursor: 'pointer', background: selectedStrategy === s.strategy ? 'rgba(99,102,241,0.1)' : 'transparent' }}>
                <td style={{ padding: '10px 12px', fontWeight: 500, color: 'rgba(255,255,255,0.85)' }}>{s.strategy.replace(/_/g, ' ')}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right', color: 'rgba(255,255,255,0.4)', fontSize: 12 }}>{s.trades}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
                    <div style={{ width: 60, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${s.win_rate}%`, borderRadius: 2, background: wrColor(s.win_rate) }} />
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 600, color: wrColor(s.win_rate) }}>{s.win_rate}%</span>
                  </div>
                </td>
                <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 13, fontWeight: 500, color: s.avg_r >= 0 ? '#4ade80' : '#f87171' }}>{fmtR(s.avg_r)}</td>
                <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 13, fontWeight: 500, color: s.total_pnl >= 0 ? '#4ade80' : '#f87171' }}>{fmt$(s.total_pnl)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {/* TRADES */}
      {tab === 'trades' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={secTitle}>R-multiple distribution{selectedStrategy ? ` — ${selectedStrategy.replace(/_/g, ' ')}` : ''}</div>
              {selectedStrategy && <button onClick={() => setSelectedStrategy(null)} style={{ fontSize: 11, color: 'rgba(160,160,255,0.7)', background: 'none', border: '1px solid rgba(100,100,255,0.3)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>Clear filter</button>}
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={rBuckets} margin={{ top: 4, right: 4, bottom: 20, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'rgba(255,255,255,0.4)' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'rgba(255,255,255,0.4)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>{rBuckets.map((b, i) => <Cell key={i} fill={b.min >= 0 ? 'rgba(34,197,94,0.8)' : 'rgba(239,68,68,0.7)'} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={card}>
            <div style={secTitle}>{filteredTrades.length} sim trades</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  {['Symbol', 'Strategy', 'Entry', 'Exit', 'P&L', 'R', 'Exit reason'].map(h => <th key={h} style={{ textAlign: ['Symbol', 'Strategy', 'Exit reason'].includes(h) ? 'left' : 'right', padding: '8px 10px', fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase' }}>{h}</th>)}
                </tr></thead>
                <tbody>{filteredTrades.map(t => (
                  <tr key={t.simulated_trade_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '8px 10px', fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{t.symbol}</td>
                    <td style={{ padding: '8px 10px', fontSize: 11, color: 'rgba(255,255,255,0.45)' }}>{t.strategy_id.replace(/_/g, ' ')}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: 'rgba(255,255,255,0.7)' }}>${Number(t.entry_price).toFixed(2)}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: 'rgba(255,255,255,0.7)' }}>${Number(t.exit_price).toFixed(2)}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: (t.pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>{fmt$(t.pnl ?? 0)}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right', color: (t.r_multiple ?? 0) >= 0 ? '#86efac' : '#fca5a5' }}>{fmtR(t.r_multiple ?? 0)}</td>
                    <td style={{ padding: '8px 10px', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{t.exit_reason || '—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* MISSED */}
      {tab === 'missed' && missed && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {[
              { label: 'Would have won', value: missed.would_win, color: '#4ade80', bg: 'rgba(34,197,94,0.1)', border: 'rgba(34,197,94,0.25)' },
              { label: 'Would have lost', value: missed.would_lose, color: '#f87171', bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.25)' },
              { label: 'P&L left on table', value: `$${missed.pnl_left_on_table.toFixed(2)}`, color: '#fbbf24', bg: 'rgba(251,191,36,0.1)', border: 'rgba(251,191,36,0.25)' },
            ].map(k => (
              <div key={k.label} style={{ background: k.bg, border: `1px solid ${k.border}`, borderRadius: 12, padding: 20, textAlign: 'center' }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: k.color }}>{k.value}</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.45)', marginTop: 6 }}>{k.label}</div>
              </div>
            ))}
          </div>
          <div style={card}>
            <div style={secTitle}>All {missed.opportunities.length} missed proposals</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  {['Date', 'Symbol', 'Strategy', 'Status', 'Entry', 'Target', 'Stop', 'Sim P&L', 'Sim R', 'Outcome'].map(h => <th key={h} style={{ textAlign: ['Date', 'Symbol', 'Strategy', 'Status', 'Outcome'].includes(h) ? 'left' : 'right', padding: '8px 10px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>)}
                </tr></thead>
                <tbody>{missed.opportunities.map(o => (
                  <tr key={o.proposal_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: o.verdict === 'WOULD_WIN' ? 'rgba(34,197,94,0.03)' : 'transparent' }}>
                    <td style={{ padding: '7px 10px', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{o.proposed_date}</td>
                    <td style={{ padding: '7px 10px', fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{o.symbol}</td>
                    <td style={{ padding: '7px 10px', fontSize: 11, color: 'rgba(255,255,255,0.45)' }}>{o.strategy_id.replace(/_/g, ' ')}</td>
                    <td style={{ padding: '7px 10px' }}><span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: o.proposal_status.toLowerCase().includes('exp') ? 'rgba(251,191,36,0.15)' : 'rgba(239,68,68,0.15)', color: o.proposal_status.toLowerCase().includes('exp') ? '#fbbf24' : '#f87171' }}>{o.proposal_status}</span></td>
                    <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>${Number(o.proposed_entry || 0).toFixed(2)}</td>
                    <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>${Number(o.proposed_target || 0).toFixed(2)}</td>
                    <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>${Number(o.proposed_stop || 0).toFixed(2)}</td>
                    <td style={{ padding: '7px 10px', textAlign: 'right', fontWeight: 600, color: o.simulated_pnl == null ? 'rgba(255,255,255,0.25)' : o.simulated_pnl >= 0 ? '#4ade80' : '#f87171' }}>{o.simulated_pnl == null ? '—' : fmt$(o.simulated_pnl)}</td>
                    <td style={{ padding: '7px 10px', textAlign: 'right', color: o.simulated_r == null ? 'rgba(255,255,255,0.25)' : o.simulated_r >= 0 ? '#86efac' : '#fca5a5' }}>{o.simulated_r == null ? '—' : fmtR(o.simulated_r)}</td>
                    <td style={{ padding: '7px 10px' }}>{o.verdict === 'WOULD_WIN' ? <span style={{ color: '#4ade80', fontWeight: 600, fontSize: 11 }}>Win</span> : o.verdict === 'WOULD_LOSE' ? <span style={{ color: '#f87171', fontSize: 11 }}>Loss</span> : <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: 11 }}>—</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* RESULTS with equity curves */}
      {tab === 'results' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {selectedResult?.equity_curve && selectedResult.equity_curve.length > 1 && (
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div>
                  <div style={secTitle}>Equity curve — {selectedResult.strategy_id?.replace(/_/g, ' ')}</div>
                  <div style={{ display: 'flex', gap: 16, marginTop: -10 }}>
                    {[
                      { l: 'Win rate', v: `${selectedResult.win_rate?.toFixed(1)}%`, c: wrColor(selectedResult.win_rate ?? 0) },
                      { l: 'PF', v: selectedResult.profit_factor?.toFixed(2) ?? '—', c: '#e2e8f0' },
                      { l: 'P&L', v: fmt$(selectedResult.total_pnl ?? 0), c: (selectedResult.total_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' },
                      { l: 'Max DD', v: `${selectedResult.max_drawdown_pct?.toFixed(1) ?? '—'}%`, c: '#f87171' },
                      { l: 'Exp R', v: fmtR(selectedResult.expectancy_r ?? 0), c: (selectedResult.expectancy_r ?? 0) >= 0 ? '#86efac' : '#fca5a5' },
                    ].map(k => <div key={k.l} style={{ textAlign: 'center' }}><div style={{ fontSize: 16, fontWeight: 600, color: k.c }}>{k.v}</div><div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>{k.l}</div></div>)}
                  </div>
                </div>
                <button onClick={() => setSelectedResult(null)} style={{ fontSize: 11, color: 'rgba(160,160,255,0.7)', background: 'none', border: '1px solid rgba(100,100,255,0.3)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>Deselect</button>
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={selectedResult.equity_curve} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                  <defs><linearGradient id="curveGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={(selectedResult.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0.3} /><stop offset="95%" stopColor={(selectedResult.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.3)' }} tickFormatter={d => d?.slice(5) || d} interval="preserveStartEnd" axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={v => `$${Number(v).toFixed(0)}`} tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.3)' }} axisLine={false} tickLine={false} />
                  <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeDasharray="3 3" />
                  <Area type="monotone" dataKey="value" dot={false} stroke={(selectedResult.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} fill="url(#curveGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 12 }}>
            {results.map(r => {
              const winPct = r.simulated_trades > 0 ? Math.round(r.wins / r.simulated_trades * 100) : 0
              const sel = selectedResult?.result_id === r.result_id
              return (
                <div key={r.result_id} onClick={() => setSelectedResult(p => p?.result_id === r.result_id ? null : r)}
                  style={{ ...card, cursor: 'pointer', border: sel ? '1px solid rgba(99,102,241,0.6)' : '1px solid rgba(255,255,255,0.08)', background: sel ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.04)', padding: '14px 16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: wrColor(r.win_rate ?? 0), lineHeight: 1 }}>{(r.win_rate ?? 0).toFixed(1)}%</div>
                      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 3 }}>{r.strategy_id?.replace(/_/g, ' ')?.slice(0, 22)}</div>
                    </div>
                    <span style={{ fontSize: 9, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: 'rgba(34,197,94,0.12)', color: '#86efac' }}>{r.run_type?.replace(/_/g, ' ')}</span>
                  </div>
                  <div style={{ height: 4, borderRadius: 2, overflow: 'hidden', background: 'rgba(239,68,68,0.3)', marginBottom: 8 }}>
                    <div style={{ height: '100%', width: `${winPct}%`, borderRadius: 2, background: '#22c55e' }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
                    <span>{r.wins}W / {r.losses}L</span>
                    <span style={{ color: (r.total_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>{fmt$(r.total_pnl ?? 0)}</span>
                  </div>
                  {r.equity_curve && r.equity_curve.length > 2 && (
                    <div style={{ marginTop: 8, height: 36 }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={r.equity_curve}>
                          <ReferenceLine y={0} stroke="rgba(255,255,255,0.1)" />
                          <Line type="monotone" dataKey="value" dot={false} stroke={(r.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444'} strokeWidth={1.5} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* RUNS */}
      {tab === 'runs' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={secTitle}>All {runs.length} backtest runs</div>
            <div style={{ display: 'flex', gap: 8 }}>
              {['all', 'replay_trades', 'replay_proposals', 'champion'].map(f => (
                <button key={f} onClick={() => setRunFilter(f)} style={{
                  fontSize: 11, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
                  background: runFilter === f ? 'rgba(99,102,241,0.2)' : 'transparent',
                  border: runFilter === f ? '1px solid rgba(99,102,241,0.5)' : '1px solid rgba(255,255,255,0.1)',
                  color: runFilter === f ? '#a5b4fc' : 'rgba(255,255,255,0.4)',
                }}>{f === 'all' ? 'All' : f.replace(/_/g, ' ')}</button>
              ))}
            </div>
          </div>
          {runs.filter(r => runFilter === 'all' || r.run_type === runFilter).map(r => (
            <div key={r.run_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', marginBottom: 4, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600, background: r.run_type === 'replay_trades' ? 'rgba(34,197,94,0.15)' : 'rgba(139,92,246,0.15)', color: r.run_type === 'replay_trades' ? '#86efac' : '#c4b5fd' }}>{r.run_type.replace(/_/g, ' ')}</span>
                <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.75)', fontWeight: 500 }}>{r.strategy_id?.replace(/_/g, ' ')}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>{r.start_date} - {r.end_date}</div>
                <div style={{ fontSize: 11, color: '#4ade80', marginTop: 2 }}>{r.status}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
