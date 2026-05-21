import { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }
const runBtn: React.CSSProperties = { fontSize:10, padding:'6px 12px', border:'1px solid var(--green)', borderRadius:4, background:'var(--green-dim)', color:'var(--green)', cursor:'pointer', fontWeight:600 }

const STRATEGIES = [
  'momentum_scalp', 'swing_breakout', 'swing_trade', 'gap_and_go',
  'recovery_watch', 'earnings_catalyst', 'speculative_growth',
  'sector_rotation', 'dividend_growth_compounder', 'defense_thesis',
]
const n = (v: unknown, d=2) => typeof v === 'number' ? v.toFixed(d) : '—'
const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10 }
const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

export default function Backtesting() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')
  const { data: status } = useApi<any>(`/api/v2/backtesting/status?_r=${rk}`)
  const { data: datasets } = useApi<any>(`/api/v2/backtesting/datasets?_r=${rk}`)
  const { data: runs } = useApi<any>(`/api/v2/backtesting/runs?_r=${rk}`)
  const { data: results } = useApi<any>(`/api/v2/backtesting/results?_r=${rk}`)
  const { data: trades } = useApi<any>(`/api/v2/backtesting/trades?_r=${rk}`)
  const { data: challengers } = useApi<any>(`/api/v2/champion-challenger?_r=${rk}`)

  const s = status?.data || {}
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)', color: tab === t ? '#fff' : 'var(--text1)'
    }}>{label}</button>
  )

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Backtesting" subtitle="Strategy backtests, champion/challenger comparisons — simulated, not live proof" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6, background:'rgba(240,185,11,.08)', border:'1px solid #f0b90b' }}>
        <span style={{ fontSize:12, fontWeight:700, color:'#f0b90b' }}>SIMULATED EVIDENCE ONLY — Not live trading proof. Backtests use simplified models.</span>
      </div>

      {/* Run Buttons */}
      <RunPanel onDone={() => setRk(k => k + 1)} />

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('runs', `Runs (${(runs?.data||[]).length})`)}
        {tabBtn('results', `Results (${(results?.data||[]).length})`)}
        {tabBtn('trades', `Trades (${(trades?.data||[]).length})`)}
        {tabBtn('challengers', `Challengers (${(challengers?.data||[]).length})`)}
      </div>

      {tab === 'overview' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(180px,1fr))', gap:10 }}>
          {[['Datasets', s.datasets_total], ['Runs', s.runs_total], ['Sim Trades', s.trades_total],
            ['Challengers', s.challengers_total], ['Comparisons', s.comparisons_total]
          ].map(([l,v]) => (
            <Card key={String(l)} compact title={String(l)}>
              <div style={{ fontSize:24, fontWeight:700 }}>{v ?? 0}</div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'results' && (
        <Card title="Backtest Results">
          {!(results?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No results yet. Run backtester first.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Strategy','Trades','Wins','Losses','WR','PF','E[R]','Sample'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(results.data as any[]).map((r: any) => (
                <tr key={r.result_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{r.strategy_id}</td>
                  <td style={td}>{r.simulated_trades}</td>
                  <td style={{ ...td, color:'#0ecb81' }}>{r.wins}</td>
                  <td style={{ ...td, color:'#f6465d' }}>{r.losses}</td>
                  <td style={td}>{r.win_rate ? `${(Number(r.win_rate)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{n(r.profit_factor)}</td>
                  <td style={td}>{n(r.expectancy_r)}</td>
                  <td style={td}>{r.sample_size_status}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'runs' && (
        <Card title="Backtest Runs">
          {!(runs?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No runs yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Run ID','Strategy','Type','Status','Period','Duration','Created'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(runs.data as any[]).map((r: any) => (
                <tr key={r.run_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{r.run_id?.slice(-15)}</td>
                  <td style={td}>{r.strategy_id}</td><td style={td}>{r.run_type}</td>
                  <td style={td}>{r.status}</td>
                  <td style={td}>{r.start_date}—{r.end_date}</td>
                  <td style={td}>{r.duration_seconds ? `${Number(r.duration_seconds).toFixed(1)}s` : '—'}</td>
                  <td style={{ ...td, fontSize:9 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'trades' && (
        <Card title="Simulated Trades (latest 50)">
          {!(trades?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No simulated trades yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Symbol','Strategy','Entry','Exit','PnL','R','Exit Reason'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(trades.data as any[]).slice(0,30).map((t: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{t.symbol}</td>
                  <td style={td}>{t.strategy_id}</td>
                  <td style={td}>{n(t.entry_price)}</td><td style={td}>{n(t.exit_price)}</td>
                  <td style={{ ...td, color: Number(t.pnl)>0?'#0ecb81':'#f6465d' }}>${n(t.pnl)}</td>
                  <td style={td}>{n(t.r_multiple,1)}</td>
                  <td style={td}>{t.exit_reason}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'challengers' && (
        <Card title="Challenger Definitions">
          {!(challengers?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No challengers defined yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Name','Domain','Strategy','Type','Status','Created'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(challengers.data as any[]).map((c: any) => (
                <tr key={c.challenger_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{c.challenger_id?.slice(-12)}</td>
                  <td style={td}>{c.name}</td><td style={td}>{c.domain}</td>
                  <td style={td}>{c.strategy_id}</td><td style={td}>{c.challenger_type}</td>
                  <td style={td}>{c.status}</td>
                  <td style={{ ...td, fontSize:9 }}>{c.created_at ? new Date(c.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}

function RunPanel({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState('')
  const [msg, setMsg] = useState('')

  const run = useCallback(async (endpoint: string, label: string) => {
    setRunning(label)
    setMsg('')
    try {
      const r = await fetch(endpoint, { method: 'POST' })
      const d = await r.json()
      if (d.ok) {
        setMsg(`${label} started — refreshing in 30s...`)
        setTimeout(() => { onDone(); setRunning(''); setMsg('') }, 30000)
      } else {
        setMsg(`Failed: ${d.error || 'unknown'}`)
        setRunning('')
      }
    } catch (e) {
      setMsg(`Error: ${e}`)
      setRunning('')
    }
  }, [onDone])

  return (
    <div style={{ padding: '10px 14px', marginBottom: 12, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginBottom: 8 }}>Enterprise Price-Replay Backtester (Real OHLC)</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/run-replay-trades', 'Replay Trades')}
          style={{ ...runBtn, opacity: running ? 0.5 : 1 }}>
          {running === 'Replay Trades' ? 'Running...' : '▶ Replay Actual Trades'}
        </button>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/run-replay-proposals', 'Replay Proposals')}
          style={{ ...runBtn, opacity: running ? 0.5 : 1 }}>
          {running === 'Replay Proposals' ? 'Running...' : '▶ Replay Untaken Proposals'}
        </button>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 6 }}>Per-strategy replay:</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {STRATEGIES.map(s => (
          <button key={s} disabled={!!running}
            onClick={() => run(`/api/v2/backtesting/run-strategy/${s}`, s)}
            style={{ fontSize: 9, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 3,
              background: running === s ? 'var(--accent)' : 'var(--bg2)',
              color: running === s ? '#fff' : 'var(--text2)', cursor: running ? 'wait' : 'pointer' }}>
            {running === s ? '...' : s.replace(/_/g, ' ')}
          </button>
        ))}
      </div>
      {msg && <div style={{ fontSize: 10, color: 'var(--green)', marginTop: 6 }}>{msg}</div>}
    </div>
  )
}
