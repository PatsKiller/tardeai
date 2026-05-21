import { useState, useCallback, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }
const runBtn: React.CSSProperties = { fontSize:10, padding:'6px 12px', border:'1px solid var(--green)', borderRadius:4, background:'var(--green-dim)', color:'var(--green)', cursor:'pointer', fontWeight:600 }

const STRATEGIES = [
  'momentum_scalp', 'swing_breakout', 'swing_trade', 'gap_and_go',
  'recovery_watch', 'earnings_catalyst', 'earnings_post_momentum',
  'earnings_pre_buildup', 'speculative_growth', 'sector_rotation',
  'fib_retracement_bounce', 'dividend_growth_compounder', 'defense_thesis',
  'core_growth_compounder', 'core_index', 'covered_call_income',
  'high_yield_income_bdc', 'income_add', 'reit_income',
  'international_dividend', 'bond_income', 'tax_loss_harvest', 'cash_or_stable',
]
const SCALP_STRATEGIES = new Set(['momentum_scalp', 'gap_and_go'])
const n = (v: unknown, d=2) => typeof v === 'number' ? v.toFixed(d) : '—'
const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10, textTransform:'uppercase' }
const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

export default function Backtesting() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')

  // useApi unwraps {ok, data} — so status IS the data object, runs IS the array
  const { data: statusRaw } = useApi<any>(`/api/v2/backtesting/status?_r=${rk}`)
  const { data: runsArr } = useApi<any>(`/api/v2/backtesting/runs?_r=${rk}`)
  const { data: resultsArr } = useApi<any>(`/api/v2/backtesting/results?_r=${rk}`)
  const { data: tradesArr } = useApi<any>(`/api/v2/backtesting/trades?_r=${rk}`)
  const { data: missedRaw } = useApi<any>(`/api/v2/backtesting/missed-opportunities?_r=${rk}`)
  const { data: challengersArr } = useApi<any>(`/api/v2/champion-challenger?_r=${rk}`)

  // Normalize — useApi already unwraps, but status/missed are objects not arrays
  const s = statusRaw || {}
  const runs = Array.isArray(runsArr) ? runsArr : runsArr?.data || []
  const results = Array.isArray(resultsArr) ? resultsArr : resultsArr?.data || []
  const trades = Array.isArray(tradesArr) ? tradesArr : tradesArr?.data || []
  const missed = missedRaw || {}
  const challengers = Array.isArray(challengersArr) ? challengersArr : challengersArr?.data || []

  // Derive per-strategy stats from trades
  const strategyStats = useMemo(() => {
    const byS: Record<string, {n:number, wins:number, pnl:number, rs:number[]}> = {}
    trades.forEach((t: any) => {
      const sid = t.strategy_id || 'unknown'
      if (!byS[sid]) byS[sid] = {n:0, wins:0, pnl:0, rs:[]}
      byS[sid].n++
      if ((t.pnl || 0) > 0) byS[sid].wins++
      byS[sid].pnl += Number(t.pnl || 0)
      if (t.r_multiple != null) byS[sid].rs.push(Number(t.r_multiple))
    })
    return Object.entries(byS)
      .map(([strategy, v]) => ({
        strategy, trades: v.n,
        win_rate: v.n > 0 ? Math.round(100 * v.wins / v.n) : 0,
        total_pnl: Math.round(v.pnl * 100) / 100,
        avg_r: v.rs.length > 0 ? Math.round(v.rs.reduce((a, b) => a+b, 0) / v.rs.length * 100) / 100 : 0,
      }))
      .sort((a, b) => b.win_rate - a.win_rate)
  }, [trades])

  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)', color: tab === t ? '#fff' : 'var(--text1)'
    }}>{label}</button>
  )

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Backtesting" subtitle="Enterprise price-replay backtester with LLM analysis" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6, background:'rgba(240,185,11,.08)', border:'1px solid #f0b90b', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <span style={{ fontSize:12, fontWeight:700, color:'#f0b90b' }}>SIMULATED EVIDENCE ONLY — Not live trading proof.</span>
        <span style={{ fontSize:9, color:'#f0b90b', cursor:'help', borderBottom:'1px dashed #f0b90b' }}
          title="Backtests replay your signals against historical prices but do NOT account for: slippage (real fills may differ), bid/ask spread costs, or market impact. Use backtests to compare strategies directionally — not as precise P&L forecasts.">
          [what does this mean?]
        </span>
      </div>

      <RunPanel onDone={() => setRk(k => k + 1)} />
      <AnalyzerPanel onDone={() => setRk(k => k + 1)} />

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('runs', `Runs (${s.runs_total ?? runs.length})`)}
        {tabBtn('results', `Results (${results.length})`)}
        {tabBtn('trades', `Trades (${s.trades_total ?? trades.length})`)}
        {tabBtn('missed', `Missed (${missed.total_missed ?? 0})`)}
        {tabBtn('challengers', `Challengers (${s.challengers_total ?? 0})`)}
      </div>

      {/* ── OVERVIEW ── */}
      {tab === 'overview' && (
        <>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(140px,1fr))', gap:10, marginBottom:14 }}>
          {([['Datasets', s.datasets_total], ['Runs', s.runs_total], ['Sim Trades', s.trades_total],
            ['Results', results.length], ['Challengers', s.challengers_total],
          ] as [string,any][]).map(([l,v]) => (
            <Card key={l} compact title={l}>
              <div style={{ fontSize:24, fontWeight:700 }}>{v ?? 0}</div>
            </Card>
          ))}
        </div>

        {/* Low win rate warning */}
        {strategyStats.filter(ss => ss.win_rate < 35 && ss.trades >= 3).length > 0 && (
          <div style={{ padding:'8px 12px', marginBottom:12, borderRadius:6, background:'var(--red-dim)', border:'1px solid var(--red)', fontSize:11, color:'var(--red)' }}>
            ⚠ Low win rate: {strategyStats.filter(ss => ss.win_rate < 35 && ss.trades >= 3).map(ss => `${ss.strategy} ${ss.win_rate}%`).join(' · ')} — review before approving more proposals.
          </div>
        )}

        {/* Strategy performance from trades */}
        {strategyStats.length > 0 && (
          <Card title="Strategy Performance (from sim trades)">
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Strategy','Trades','Win %','Avg R','Total P&L'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{strategyStats.map(ss => (
                <tr key={ss.strategy} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{ss.strategy}</td>
                  <td style={td}>{ss.trades}</td>
                  <td style={{ ...td, color: ss.win_rate>=50?'#0ecb81':ss.win_rate>=35?'#f0b90b':'#f6465d', fontWeight:600 }}>{ss.win_rate}%</td>
                  <td style={{ ...td, color: ss.avg_r>=0?'#0ecb81':'#f6465d' }}>{ss.avg_r>=0?'+':''}{ss.avg_r.toFixed(2)}</td>
                  <td style={{ ...td, color: ss.total_pnl>=0?'#0ecb81':'#f6465d' }}>{ss.total_pnl>=0?'+':''}${Math.abs(ss.total_pnl).toFixed(2)}</td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        )}

        {/* Aggregated results summary */}
        {results.length > 0 && (
          <Card title={`Aggregated Run Results (${results.length})`} style={{ marginTop:12 }}>
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Strategy','Type','Trades','Win%','PF','Avg R','P&L','Max DD'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{results.map((r: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{(r.strategy_id||'').split(',')[0]}</td>
                  <td style={td}><span style={{ fontSize:8, padding:'1px 4px', borderRadius:3, background:'var(--accent-dim)', color:'var(--accent)' }}>{r.run_type||'?'}</span></td>
                  <td style={td}>{r.simulated_trades ?? r.total_trades}</td>
                  <td style={{ ...td, color: Number(r.win_rate)>=50?'#0ecb81':Number(r.win_rate)>=35?'#f0b90b':'#f6465d', fontWeight:600 }}>{n(r.win_rate,1)}%</td>
                  <td style={td}>{n(r.profit_factor)}</td>
                  <td style={td}>{n(r.avg_r_multiple || r.expectancy_r)}</td>
                  <td style={{ ...td, color: Number(r.total_pnl)>0?'#0ecb81':'#f6465d' }}>${n(r.total_pnl)}</td>
                  <td style={{ ...td, color:'#f6465d' }}>{r.max_drawdown_pct ? n(r.max_drawdown_pct,1)+'%' : '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        )}
        </>
      )}

      {/* ── RUNS ── */}
      {tab === 'runs' && (
        <Card title={`Backtest Runs (${runs.length} loaded)`}>
          {runs.length === 0 ? <div style={{ color:'#848e9c', padding:16 }}>No runs yet. Use the buttons above to start a backtest.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Run ID','Strategy','Type','Status','Period','Created'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{runs.map((r: any) => (
                <tr key={r.run_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{r.run_id?.slice(-15)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{r.strategy_id}</td>
                  <td style={td}><span style={{ fontSize:8, padding:'1px 4px', borderRadius:3, background: r.run_type?.includes('replay')?'var(--accent-dim)':'var(--amber-dim)', color: r.run_type?.includes('replay')?'var(--accent)':'var(--amber)' }}>{r.run_type}</span></td>
                  <td style={td}><span style={{ color: r.status==='completed'?'#0ecb81':'#f0b90b' }}>{r.status}</span></td>
                  <td style={td}>{r.start_date} → {r.end_date}</td>
                  <td style={{ ...td, fontSize:9 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {/* ── RESULTS ── */}
      {tab === 'results' && (
        <Card title={`Backtest Results (${results.length})`}>
          {results.length === 0 ? <div style={{ color:'#848e9c', padding:16 }}>No results aggregated yet. Run the backtester then the aggregator.</div> : (
            <>
            {/* Result cards */}
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(260px,1fr))', gap:10, marginBottom:14 }}>
              {results.slice(0, 12).map((r: any, i: number) => (
                <div key={i} style={{ padding:12, background:'var(--bg3)', borderRadius:8, border:'1px solid var(--border)' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                    <span style={{ fontSize:11, fontWeight:600 }}>{(r.strategy_id||'').split(',')[0]}</span>
                    <span style={{ fontSize:8, padding:'1px 4px', borderRadius:3, background:'var(--accent-dim)', color:'var(--accent)' }}>{r.run_type||'?'}</span>
                  </div>
                  <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:6, fontSize:10, textAlign:'center' }}>
                    <div><div style={{ fontSize:18, fontWeight:700, color: Number(r.win_rate)>=50?'#0ecb81':Number(r.win_rate)>=35?'#f0b90b':'#f6465d' }}>{n(r.win_rate,1)}%</div><div style={{ color:'var(--text3)', fontSize:8 }}>Win Rate</div></div>
                    <div><div style={{ fontSize:14, fontWeight:600 }}>{r.simulated_trades ?? r.total_trades}</div><div style={{ color:'var(--text3)', fontSize:8 }}>Trades</div></div>
                    <div><div style={{ fontSize:14, fontWeight:600, color: Number(r.total_pnl)>=0?'#0ecb81':'#f6465d' }}>${n(r.total_pnl)}</div><div style={{ color:'var(--text3)', fontSize:8 }}>P&L</div></div>
                  </div>
                  {r.wins != null && r.losses != null && (r.wins+r.losses) > 0 && (
                    <div style={{ marginTop:8 }}>
                      <div style={{ display:'flex', height:4, borderRadius:2, overflow:'hidden' }}>
                        <div style={{ width:`${r.wins/(r.wins+r.losses)*100}%`, background:'#0ecb81' }}/>
                        <div style={{ flex:1, background:'#f6465d' }}/>
                      </div>
                      <div style={{ display:'flex', justifyContent:'space-between', fontSize:8, color:'var(--text3)', marginTop:2 }}><span>{r.wins}W</span><span>{r.losses}L</span></div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            </>
          )}
        </Card>
      )}

      {/* ── TRADES ── */}
      {tab === 'trades' && (
        <Card title={`Simulated Trades (${trades.length} loaded, ${s.trades_total ?? '?'} total)`}>
          {trades.length === 0 ? <div style={{ color:'#848e9c', padding:16 }}>No simulated trades yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Symbol','Strategy','Entry','Exit','P&L','R','Exit Reason'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{trades.slice(0,50).map((t: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{t.symbol}</td>
                  <td style={{ ...td, fontSize:9 }}>{t.strategy_id}</td>
                  <td style={td}>${n(t.entry_price)}</td>
                  <td style={td}>${n(t.exit_price)}</td>
                  <td style={{ ...td, color: Number(t.pnl)>0?'#0ecb81':'#f6465d', fontWeight:600 }}>{Number(t.pnl)>0?'+':''}${n(t.pnl)}</td>
                  <td style={{ ...td, color: Number(t.r_multiple)>=0?'#0ecb81':'#f6465d' }}>{n(t.r_multiple,1)}</td>
                  <td style={{ ...td, fontSize:9 }}>{t.exit_reason}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {/* ── MISSED ── */}
      {tab === 'missed' && (
        <Card title="Missed Opportunities — What We Left on the Table">
          <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10, marginBottom:12 }}>
            <div style={{ padding:10, background:'var(--green-dim)', borderRadius:6, textAlign:'center' }}>
              <div style={{ fontSize:24, fontWeight:700, color:'var(--green)' }}>{missed.would_win ?? 0}</div>
              <div style={{ fontSize:9, color:'var(--text3)' }}>Would Have Won</div>
            </div>
            <div style={{ padding:10, background:'var(--red-dim)', borderRadius:6, textAlign:'center' }}>
              <div style={{ fontSize:24, fontWeight:700, color:'var(--red)' }}>{missed.would_lose ?? 0}</div>
              <div style={{ fontSize:9, color:'var(--text3)' }}>Would Have Lost</div>
            </div>
            <div style={{ padding:10, background:'var(--amber-dim)', borderRadius:6, textAlign:'center' }}>
              <div style={{ fontSize:24, fontWeight:700, color:'var(--amber)' }}>${n(missed.pnl_left_on_table)}</div>
              <div style={{ fontSize:9, color:'var(--text3)' }}>P&L Left on Table</div>
            </div>
          </div>
          <div style={{ fontSize:9, color:'var(--text3)', padding:'6px 10px', background:'var(--bg3)', borderRadius:4, marginBottom:10 }}>
            These are proposals that expired or were rejected. The simulated outcome shows what would have happened based on actual price data.
          </div>
          {(missed.opportunities?.length ?? 0) > 0 ? (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Date','Symbol','Strategy','Status','Sim P&L','Sim R','Verdict'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(missed.opportunities as any[]).map((o: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{String(o.proposed_date||'').slice(0,10)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{o.symbol}</td>
                  <td style={{ ...td, fontSize:9 }}>{o.strategy_id}</td>
                  <td style={td}><span style={{ fontSize:8, padding:'1px 4px', borderRadius:3, background:'var(--bg3)', color:'var(--text3)' }}>{o.proposal_status}</span></td>
                  <td style={{ ...td, color: Number(o.simulated_pnl)>0?'#0ecb81':Number(o.simulated_pnl)<0?'#f6465d':'var(--text3)' }}>{o.simulated_pnl != null ? (Number(o.simulated_pnl)>0?'+':'')+'$'+n(o.simulated_pnl) : '—'}</td>
                  <td style={{ ...td, color: Number(o.simulated_r)>=0?'#0ecb81':'#f6465d' }}>{o.simulated_r != null ? n(o.simulated_r,1) : '—'}</td>
                  <td style={td}>{Number(o.simulated_pnl)>0 ? '🟢 Win' : Number(o.simulated_pnl)<0 ? '🔴 Loss' : '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div style={{ color:'var(--text3)', padding:16 }}>No matched missed opportunities. Run "Replay Untaken Proposals" first.</div>}
        </Card>
      )}

      {/* ── CHALLENGERS ── */}
      {tab === 'challengers' && (
        <Card title="Champion/Challenger Experiments">
          {challengers.length === 0 ? <div style={{ color:'#848e9c', padding:16 }}>No challengers defined yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Name','Strategy','Type','Status'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{challengers.map((c: any) => (
                <tr key={c.challenger_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{c.challenger_id?.slice(-12)}</td>
                  <td style={td}>{c.name}</td>
                  <td style={td}>{c.strategy_id}</td>
                  <td style={td}>{c.challenger_type}</td>
                  <td style={td}>{c.status}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}

function AnalyzerPanel({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState('')
  const [msg, setMsg] = useState('')
  const run = useCallback(async (endpoint: string, label: string) => {
    setRunning(label); setMsg('')
    try {
      const r = await fetch(endpoint, { method: 'POST' })
      const d = await r.json()
      if (d.ok) { setMsg(`${d.message} — refreshing in 45s...`); setTimeout(() => { onDone(); setRunning(''); setMsg('') }, 45000) }
      else { setMsg(`Failed: ${d.error || 'unknown'}`); setRunning('') }
    } catch (e) { setMsg(`Error: ${e}`); setRunning('') }
  }, [onDone])
  return (
    <div style={{ padding:'10px 14px', marginBottom:12, background:'var(--bg1)', border:'1px solid var(--accent)', borderRadius:8 }}>
      <div style={{ fontSize:11, fontWeight:700, color:'var(--accent)', marginBottom:8 }}>LLM Trade Analysis + Incubator Strategy Testing</div>
      <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:8 }}>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/analyze-trades', 'LLM Analysis')}
          style={{ ...runBtn, border:'1px solid var(--accent)', background:'var(--accent-dim)', color:'var(--accent)', opacity:running?0.5:1 }}>
          {running === 'LLM Analysis' ? 'Analyzing...' : '🧠 LLM Grade Trades'}
        </button>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/all-incubator', 'All Incubator')}
          style={{ ...runBtn, border:'1px solid var(--purple)', background:'rgba(168,139,250,.08)', color:'var(--purple)', opacity:running?0.5:1 }}>
          {running === 'All Incubator' ? 'Running...' : '🔬 Backtest All on Incubator'}
        </button>
      </div>
      <div style={{ fontSize:9, color:'var(--text3)', marginBottom:4 }}>Per-strategy incubator backtest:</div>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {STRATEGIES.filter(s => !SCALP_STRATEGIES.has(s)).map(s => (
          <button key={s} disabled={!!running} onClick={() => run(`/api/v2/backtesting/backtest-incubator/${s}`, s)}
            style={{ fontSize:8, padding:'2px 6px', border:'1px solid var(--purple)', borderRadius:3, background:running===s?'var(--purple)':'rgba(168,139,250,.05)', color:running===s?'#fff':'var(--purple)', cursor:running?'wait':'pointer' }}>
            {running === s ? '...' : s.replace(/_/g, ' ')}
          </button>
        ))}
      </div>
      {msg && <div style={{ fontSize:10, color:'var(--green)', marginTop:6 }}>{msg}</div>}
    </div>
  )
}

function RunPanel({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState('')
  const [msg, setMsg] = useState('')
  const run = useCallback(async (endpoint: string, label: string) => {
    setRunning(label); setMsg('')
    try {
      const r = await fetch(endpoint, { method: 'POST' })
      const d = await r.json()
      if (d.ok) { setMsg(`${label} started — refreshing in 30s...`); setTimeout(() => { onDone(); setRunning(''); setMsg('') }, 30000) }
      else { setMsg(`Failed: ${d.error || 'unknown'}`); setRunning('') }
    } catch (e) { setMsg(`Error: ${e}`); setRunning('') }
  }, [onDone])
  return (
    <div style={{ padding:'10px 14px', marginBottom:12, background:'var(--bg1)', border:'1px solid var(--border)', borderRadius:8 }}>
      <div style={{ fontSize:11, fontWeight:700, color:'var(--text1)', marginBottom:8 }}>Enterprise Price-Replay Backtester (Real OHLC)</div>
      <div style={{ display:'flex', gap:8, flexWrap:'wrap', marginBottom:8 }}>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/run-replay-trades', 'Replay Trades')} style={{ ...runBtn, opacity:running?0.5:1 }}>
          {running === 'Replay Trades' ? 'Running...' : '▶ Replay Actual Trades'}
        </button>
        <button disabled={!!running} onClick={() => run('/api/v2/backtesting/run-replay-proposals', 'Replay Proposals')} style={{ ...runBtn, opacity:running?0.5:1 }}>
          {running === 'Replay Proposals' ? 'Running...' : '▶ Replay Untaken Proposals'}
        </button>
      </div>
      <div style={{ fontSize:9, color:'var(--text3)', marginBottom:4 }}>Per-strategy replay:</div>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {STRATEGIES.map(s => (
          <button key={s} disabled={!!running} onClick={() => run(`/api/v2/backtesting/run-strategy/${s}`, s)}
            style={{ fontSize:8, padding:'2px 6px', border:'1px solid var(--border)', borderRadius:3, background:running===s?'var(--accent)':'var(--bg2)', color:running===s?'#fff':'var(--text2)', cursor:running?'wait':'pointer' }}>
            {running === s ? '...' : s.replace(/_/g, ' ')}
          </button>
        ))}
      </div>
      {msg && <div style={{ fontSize:10, color:'var(--green)', marginTop:6 }}>{msg}</div>}
    </div>
  )
}
