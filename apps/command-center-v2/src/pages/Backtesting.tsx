import { useState, useCallback, useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip as CJTooltip } from 'chart.js'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'

ChartJS.register(CategoryScale, LinearScale, BarElement, CJTooltip)

const STRATEGIES = [
  'momentum_scalp','swing_breakout','swing_trade','gap_and_go','recovery_watch',
  'earnings_catalyst','earnings_post_momentum','earnings_pre_buildup','speculative_growth',
  'sector_rotation','fib_retracement_bounce','dividend_growth_compounder','defense_thesis',
  'core_growth_compounder','core_index','covered_call_income','high_yield_income_bdc',
  'income_add','reit_income','international_dividend','bond_income','tax_loss_harvest','cash_or_stable',
]
const SCALPS = new Set(['momentum_scalp', 'gap_and_go'])
const n = (v: unknown, d=2) => typeof v === 'number' ? v.toFixed(d) : '—'
const wrColor = (wr: number) => wr >= 55 ? '#0ecb81' : wr >= 35 ? '#f0b90b' : '#f6465d'

const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'var(--text3)', fontSize:9, textTransform:'uppercase', letterSpacing:'.4px', fontWeight:600 }
const td: React.CSSProperties = { padding:'5px 8px', fontSize:11 }
const tabStyle = (active: boolean): React.CSSProperties => ({
  padding:'8px 14px', fontSize:11, fontWeight: active?600:400, cursor:'pointer', border:'none',
  borderBottom: active?'2px solid var(--accent)':'2px solid transparent',
  background:'transparent', color: active?'var(--accent)':'var(--text3)', whiteSpace:'nowrap',
})

export default function Backtesting() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')

  const { data: statusRaw } = useApi<any>(`/api/v2/backtesting/status?_r=${rk}`)
  const { data: runsArr } = useApi<any>(`/api/v2/backtesting/runs?_r=${rk}`)
  const { data: resultsArr } = useApi<any>(`/api/v2/backtesting/results?_r=${rk}`)
  const { data: tradesArr } = useApi<any>(`/api/v2/backtesting/trades?_r=${rk}`)
  const { data: missedRaw } = useApi<any>(`/api/v2/backtesting/missed-opportunities?_r=${rk}`)

  const s = statusRaw || {}
  const runs: any[] = Array.isArray(runsArr) ? runsArr : []
  const results: any[] = Array.isArray(resultsArr) ? resultsArr : []
  const trades: any[] = Array.isArray(tradesArr) ? tradesArr : []
  const missed = missedRaw || {}
  const opps: any[] = missed.opportunities || []

  // Strategy stats from trades
  const stratStats = useMemo(() => {
    const m: Record<string, {n:number;w:number;pnl:number;rs:number[]}> = {}
    trades.forEach((t: any) => {
      const sid = t.strategy_id || 'unknown'
      if (!m[sid]) m[sid] = {n:0,w:0,pnl:0,rs:[]}
      m[sid].n++; if ((t.pnl||0)>0) m[sid].w++
      m[sid].pnl += Number(t.pnl||0)
      if (t.r_multiple!=null) m[sid].rs.push(Number(t.r_multiple))
    })
    return Object.entries(m).map(([strategy,v]) => ({
      strategy, trades:v.n,
      wr: v.n>0 ? Math.round(100*v.w/v.n) : 0,
      pnl: Math.round(v.pnl*100)/100,
      avgR: v.rs.length>0 ? Math.round(v.rs.reduce((a,b)=>a+b,0)/v.rs.length*100)/100 : 0,
    })).sort((a,b) => b.wr - a.wr)
  }, [trades])

  // R-multiple buckets
  const rBuckets = useMemo(() => {
    const b = [{l:'<-2R',mn:-99,mx:-2},{l:'-2 to -1',mn:-2,mx:-1},{l:'-1 to 0',mn:-1,mx:0},
               {l:'0 to 1',mn:0,mx:1},{l:'1 to 2',mn:1,mx:2},{l:'>2R',mn:2,mx:99}]
    return b.map(x => ({...x, count: trades.filter((t:any) => t.r_multiple!=null && t.r_multiple>x.mn && t.r_multiple<=x.mx).length}))
  }, [trades])

  const flagged = stratStats.filter(ss => ss.wr<35 && ss.trades>=3)

  return (
    <div style={{ maxWidth:1200 }}>
      <PageHeader title="Backtesting" subtitle="Enterprise price-replay backtester with LLM analysis" actions={
        <button onClick={() => setRk(k=>k+1)} style={{ fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }}>Refresh</button>
      }/>

      {/* Disclaimer */}
      <div style={{ padding:'6px 12px', marginBottom:10, borderRadius:6, background:'rgba(240,185,11,.06)', border:'1px solid rgba(240,185,11,.3)', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <span style={{ fontSize:11, color:'#f0b90b' }}>SIMULATED EVIDENCE ONLY — not live trading proof.</span>
        <span style={{ fontSize:9, color:'#f0b90b', cursor:'help', borderBottom:'1px dashed' }}
          title="Backtests replay signals against historical prices. They don't account for slippage, spread, or market impact. Use for directional strategy comparison only.">[?]</span>
      </div>

      {/* Action panels */}
      <RunPanel onDone={() => setRk(k=>k+1)} />
      <AnalyzerPanel onDone={() => setRk(k=>k+1)} />

      {/* KPI tiles */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(6, 1fr)', gap:8, marginBottom:12 }}>
        <MetricTile label="Datasets" value={String(s.datasets_total ?? 0)} />
        <MetricTile label="Runs" value={String(s.runs_total ?? 0)} />
        <MetricTile label="Sim Trades" value={String(s.trades_total ?? 0)} />
        <MetricTile label="Results" value={String(results.length)} />
        <MetricTile label="Flagged" value={String(flagged.length)} deltaColor={flagged.length>0?'var(--red)':undefined} />
        <MetricTile label="Missed" value={String(missed.total_missed ?? 0)} />
      </div>

      {/* Alert */}
      {flagged.length > 0 && (
        <div style={{ padding:'8px 12px', marginBottom:12, borderRadius:6, background:'var(--red-dim)', border:'1px solid var(--red)', fontSize:11, color:'var(--red)' }}>
          ⚠ Low win rate: {flagged.map(ss => `${ss.strategy.replace(/_/g,' ')} ${ss.wr}%`).join(' · ')} — review before approving more proposals.
        </div>
      )}

      {/* Tabs */}
      <div style={{ display:'flex', gap:0, borderBottom:'1px solid var(--border)', marginBottom:14, overflowX:'auto' }}>
        {[['overview','Overview'],['strategy',`Strategy (${stratStats.length})`],['trades',`Sim Trades (${trades.length})`],
          ['missed',`Missed (${missed.total_missed??0})`],['results',`Results (${results.length})`],['runs',`Runs (${s.runs_total??runs.length})`],
        ].map(([id,label]) => (
          <button key={id} onClick={() => setTab(id)} style={tabStyle(tab===id)}>{label}</button>
        ))}
      </div>

      {/* ── OVERVIEW ── */}
      {tab === 'overview' && (
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          {/* Win rate chart */}
          <Card title="Win Rate by Strategy">
            {stratStats.length > 0 && (
              <div style={{ height: Math.max(200, stratStats.length * 28) }}>
                <Bar data={{
                  labels: stratStats.map(ss => ss.strategy.replace(/_/g,' ')),
                  datasets: [{ data: stratStats.map(ss => ss.wr), backgroundColor: stratStats.map(ss => wrColor(ss.wr)), borderRadius:3, maxBarThickness:18 }]
                }} options={{
                  indexAxis:'y' as const, responsive:true, maintainAspectRatio:false,
                  plugins:{ legend:{display:false}, tooltip:{ callbacks:{ label: ctx => `${ctx.raw}% win rate` }} },
                  scales:{ x:{min:0,max:100,ticks:{callback:v=>`${v}%`,color:'var(--text3)',font:{size:9}},grid:{color:'rgba(255,255,255,.05)'},border:{display:false}},
                           y:{ticks:{color:'var(--text2)',font:{size:10}},grid:{display:false},border:{display:false}} }
                }} />
              </div>
            )}
          </Card>

          <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
            {/* R-multiple distribution */}
            <Card title="R-Multiple Distribution">
              <div style={{ height:160 }}>
                <Bar data={{
                  labels: rBuckets.map(b => b.l),
                  datasets: [{ data: rBuckets.map(b => b.count), backgroundColor: rBuckets.map(b => b.mn>=0?'#0ecb81':'#f6465d'), borderRadius:3 }]
                }} options={{
                  responsive:true, maintainAspectRatio:false,
                  plugins:{ legend:{display:false} },
                  scales:{ x:{ticks:{color:'var(--text3)',font:{size:9}},grid:{display:false},border:{display:false}},
                           y:{ticks:{color:'var(--text3)',font:{size:9}},grid:{color:'rgba(255,255,255,.05)'},border:{display:false}} }
                }} />
              </div>
            </Card>

            {/* Missed summary */}
            <Card title="Missed Proposals Impact">
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:8 }}>
                <div style={{ padding:10, background:'var(--green-dim)', borderRadius:6, textAlign:'center' }}>
                  <div style={{ fontSize:22, fontWeight:700, color:'var(--green)' }}>{missed.would_win ?? 0}</div>
                  <div style={{ fontSize:8, color:'var(--text3)' }}>Would Win</div>
                </div>
                <div style={{ padding:10, background:'var(--red-dim)', borderRadius:6, textAlign:'center' }}>
                  <div style={{ fontSize:22, fontWeight:700, color:'var(--red)' }}>{missed.would_lose ?? 0}</div>
                  <div style={{ fontSize:8, color:'var(--text3)' }}>Would Lose</div>
                </div>
                <div style={{ padding:10, background:'var(--amber-dim)', borderRadius:6, textAlign:'center' }}>
                  <div style={{ fontSize:22, fontWeight:700, color:'var(--amber)' }}>${n(missed.pnl_left_on_table)}</div>
                  <div style={{ fontSize:8, color:'var(--text3)' }}>Left on Table</div>
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ── STRATEGY ── */}
      {tab === 'strategy' && stratStats.length > 0 && (
        <Card title="Strategy Performance">
          <table style={{ width:'100%', borderCollapse:'collapse' }}>
            <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
              {['Strategy','Trades','Win Rate','','Avg R','Total P&L'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr></thead>
            <tbody>{stratStats.map(ss => (
              <tr key={ss.strategy} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ ...td, fontWeight:600 }}>{ss.strategy.replace(/_/g,' ')}</td>
                <td style={{ ...td, color:'var(--text3)' }}>{ss.trades}</td>
                <td style={{ ...td, width:120 }}>
                  <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                    <div style={{ flex:1, height:6, background:'var(--bg3)', borderRadius:3, overflow:'hidden' }}>
                      <div style={{ width:`${ss.wr}%`, height:'100%', borderRadius:3, background:wrColor(ss.wr) }}/>
                    </div>
                  </div>
                </td>
                <td style={{ ...td, fontWeight:600, color:wrColor(ss.wr), width:40 }}>{ss.wr}%</td>
                <td style={{ ...td, color:ss.avgR>=0?'#0ecb81':'#f6465d' }}>{ss.avgR>=0?'+':''}{ss.avgR.toFixed(2)}</td>
                <td style={{ ...td, color:ss.pnl>=0?'#0ecb81':'#f6465d', fontWeight:600 }}>{ss.pnl>=0?'+':''}${Math.abs(ss.pnl).toFixed(2)}</td>
              </tr>
            ))}</tbody>
          </table>
          <div style={{ fontSize:9, color:'var(--text3)', marginTop:8 }}>Small samples — treat as directional signal. &lt;5 trades may be statistically unreliable.</div>
        </Card>
      )}

      {/* ── TRADES ── */}
      {tab === 'trades' && (
        <>
        <Card title="R-Multiple Distribution" style={{ marginBottom:12 }}>
          <div style={{ height:160 }}>
            <Bar data={{ labels: rBuckets.map(b=>b.l), datasets:[{data:rBuckets.map(b=>b.count), backgroundColor:rBuckets.map(b=>b.mn>=0?'#0ecb81':'#f6465d'), borderRadius:3}] }}
              options={{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
                scales:{x:{ticks:{color:'var(--text3)',font:{size:9}},grid:{display:false},border:{display:false}},y:{ticks:{color:'var(--text3)',font:{size:9}},grid:{color:'rgba(255,255,255,.05)'},border:{display:false}}} }} />
          </div>
        </Card>
        <Card title={`Simulated Trades (${trades.length})`}>
          <table style={{ width:'100%', borderCollapse:'collapse' }}>
            <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
              {['Symbol','Strategy','Entry','Exit','P&L','R','Exit'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr></thead>
            <tbody>{trades.slice(0,50).map((t:any,i:number) => (
              <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                <td style={{ ...td, fontWeight:600 }}>{t.symbol}</td>
                <td style={{ ...td, fontSize:9, color:'var(--text3)' }}>{(t.strategy_id||'').replace(/_/g,' ')}</td>
                <td style={td}>${n(t.entry_price)}</td>
                <td style={td}>${n(t.exit_price)}</td>
                <td style={{ ...td, color:Number(t.pnl)>0?'#0ecb81':'#f6465d', fontWeight:600 }}>{Number(t.pnl)>0?'+':''}${n(t.pnl)}</td>
                <td style={{ ...td, color:Number(t.r_multiple)>=0?'#0ecb81':'#f6465d' }}>{n(t.r_multiple,1)}</td>
                <td style={{ ...td, fontSize:9, color:'var(--text3)' }}>{t.exit_reason||'—'}</td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
        </>
      )}

      {/* ── MISSED ── */}
      {tab === 'missed' && (
        <>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:12 }}>
          <div style={{ padding:14, background:'var(--green-dim)', borderRadius:8, textAlign:'center' }}>
            <div style={{ fontSize:28, fontWeight:700, color:'var(--green)' }}>{missed.would_win??0}</div>
            <div style={{ fontSize:10, color:'var(--text3)' }}>Would Have Won</div>
          </div>
          <div style={{ padding:14, background:'var(--red-dim)', borderRadius:8, textAlign:'center' }}>
            <div style={{ fontSize:28, fontWeight:700, color:'var(--red)' }}>{missed.would_lose??0}</div>
            <div style={{ fontSize:10, color:'var(--text3)' }}>Would Have Lost</div>
          </div>
          <div style={{ padding:14, background:'var(--amber-dim)', borderRadius:8, textAlign:'center' }}>
            <div style={{ fontSize:28, fontWeight:700, color:'var(--amber)' }}>${n(missed.pnl_left_on_table)}</div>
            <div style={{ fontSize:10, color:'var(--text3)' }}>P&L Left on Table</div>
          </div>
        </div>
        <div style={{ fontSize:9, color:'var(--text3)', padding:'6px 10px', background:'var(--bg3)', borderRadius:4, marginBottom:10 }}>
          Proposals that expired or were rejected. Simulated outcome based on actual price data after expiry. Not predictive.
        </div>
        <Card title={`Missed Opportunities (${opps.length})`}>
          {opps.length === 0 ? <div style={{ color:'var(--text3)', padding:16 }}>Run "Replay Untaken Proposals" first.</div> : (
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Date','Symbol','Strategy','Status','Sim P&L','Sim R','Verdict'].map(h => <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{opps.map((o:any,i:number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
                  <td style={{ ...td, fontSize:9 }}>{String(o.proposed_date||'').slice(0,10)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{o.symbol}</td>
                  <td style={{ ...td, fontSize:9 }}>{(o.strategy_id||'').replace(/_/g,' ')}</td>
                  <td style={td}><span style={{ fontSize:8, padding:'1px 4px', borderRadius:3, background:'var(--bg3)', color:'var(--text3)' }}>{o.proposal_status}</span></td>
                  <td style={{ ...td, color:Number(o.simulated_pnl)>0?'#0ecb81':Number(o.simulated_pnl)<0?'#f6465d':'var(--text3)', fontWeight:600 }}>
                    {o.simulated_pnl!=null ? (Number(o.simulated_pnl)>0?'+':'')+'$'+n(o.simulated_pnl) : '—'}
                  </td>
                  <td style={{ ...td, color:Number(o.simulated_r)>=0?'#0ecb81':'#f6465d' }}>{o.simulated_r!=null ? n(o.simulated_r,1) : '—'}</td>
                  <td style={td}>{Number(o.simulated_pnl)>0?'🟢':Number(o.simulated_pnl)<0?'🔴':'—'}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
        </>
      )}

      {/* ── RESULTS ── */}
      {tab === 'results' && (
        <>
        {results.length === 0 ? <div style={{ color:'var(--text3)', padding:20 }}>No results. Run backtest_results_aggregator.py.</div> : (
          <>
          <Card title={`Win Rate Across ${results.length} Runs`} style={{ marginBottom:12 }}>
            <div style={{ height:200 }}>
              <Bar data={{
                labels: results.filter((r:any)=>r.win_rate!=null).slice(0,20).map((r:any) => (r.strategy_id||'?').split(',')[0].replace(/_/g,' ').slice(0,14)),
                datasets:[{data:results.filter((r:any)=>r.win_rate!=null).slice(0,20).map((r:any)=>r.win_rate),
                  backgroundColor:results.filter((r:any)=>r.win_rate!=null).slice(0,20).map((r:any)=>wrColor(r.win_rate||0)),borderRadius:3}]
              }} options={{
                responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
                scales:{x:{ticks:{color:'var(--text3)',font:{size:8},maxRotation:45},grid:{display:false},border:{display:false}},
                        y:{min:0,max:100,ticks:{callback:v=>`${v}%`,color:'var(--text3)',font:{size:9}},grid:{color:'rgba(255,255,255,.05)'},border:{display:false}}}
              }} />
            </div>
          </Card>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(220px,1fr))', gap:10 }}>
            {results.map((r:any,i:number) => {
              const winPct = (r.total_trades||r.simulated_trades)>0 ? Math.round((r.wins||0)/((r.total_trades||r.simulated_trades)||1)*100) : 0
              return (
                <div key={i} style={{ padding:12, background:'var(--bg3)', borderRadius:8, border:'1px solid var(--border)' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                    <span style={{ fontSize:11, fontWeight:600 }}>{(r.strategy_id||'?').split(',')[0].replace(/_/g,' ')}</span>
                    <span style={{ fontSize:7, padding:'1px 4px', borderRadius:3, background:'var(--accent-dim)', color:'var(--accent)' }}>{r.run_type||'?'}</span>
                  </div>
                  <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:4, textAlign:'center', fontSize:10 }}>
                    <div><div style={{ fontSize:16, fontWeight:700, color:wrColor(r.win_rate||0) }}>{n(r.win_rate,1)}%</div><div style={{ fontSize:7, color:'var(--text3)' }}>WR</div></div>
                    <div><div style={{ fontSize:12, fontWeight:600 }}>{r.total_trades||r.simulated_trades||0}</div><div style={{ fontSize:7, color:'var(--text3)' }}>Trades</div></div>
                    <div><div style={{ fontSize:12, fontWeight:600, color:Number(r.total_pnl)>=0?'#0ecb81':'#f6465d' }}>${n(r.total_pnl)}</div><div style={{ fontSize:7, color:'var(--text3)' }}>P&L</div></div>
                  </div>
                  <div style={{ marginTop:6 }}>
                    <div style={{ display:'flex', height:4, borderRadius:2, overflow:'hidden' }}>
                      <div style={{ width:`${winPct}%`, background:'#0ecb81' }}/>
                      <div style={{ flex:1, background:'#f6465d' }}/>
                    </div>
                    <div style={{ display:'flex', justifyContent:'space-between', fontSize:7, color:'var(--text3)', marginTop:2 }}><span>{r.wins||0}W</span><span>{r.losses||0}L</span></div>
                  </div>
                </div>
              )
            })}
          </div>
          </>
        )}
        </>
      )}

      {/* ── RUNS ── */}
      {tab === 'runs' && (
        <Card title={`Backtest Runs (${runs.length} loaded, ${s.runs_total??'?'} total)`}>
          {runs.length === 0 ? <div style={{ color:'var(--text3)', padding:16 }}>No runs yet.</div> : (
            <div style={{ display:'flex', flexDirection:'column', gap:2 }}>
              {runs.map((r:any) => (
                <div key={r.run_id} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'8px 10px', borderRadius:6, border:'1px solid transparent' }}
                  onMouseEnter={e=>{e.currentTarget.style.background='var(--bg3)';e.currentTarget.style.borderColor='var(--border)'}}
                  onMouseLeave={e=>{e.currentTarget.style.background='';e.currentTarget.style.borderColor='transparent'}}>
                  <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                    <span style={{ fontSize:8, padding:'1px 6px', borderRadius:3, fontWeight:600,
                      background: (r.run_type||'').includes('replay_trade')?'var(--green-dim)':
                        (r.run_type||'').includes('proposal')?'rgba(168,139,250,.1)':'var(--amber-dim)',
                      color: (r.run_type||'').includes('replay_trade')?'var(--green)':
                        (r.run_type||'').includes('proposal')?'var(--purple)':'var(--amber)',
                    }}>{(r.run_type||'?').replace(/_/g,' ')}</span>
                    <span style={{ fontSize:11, fontWeight:500 }}>{(r.strategy_id||'').split(',').length>3?`${(r.strategy_id||'').split(',').length} strategies`:(r.strategy_id||'').replace(/_/g,' ')}</span>
                  </div>
                  <div style={{ textAlign:'right' }}>
                    <div style={{ fontSize:9, color:'var(--text3)' }}>{r.start_date} → {r.end_date}</div>
                    <div style={{ fontSize:9, color:'#0ecb81' }}>{r.status}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function AnalyzerPanel({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState(''); const [msg, setMsg] = useState('')
  const run = useCallback(async (ep: string, label: string) => {
    setRunning(label); setMsg('')
    try { const r = await fetch(ep,{method:'POST'}); const d = await r.json()
      if(d.ok){setMsg(`${d.message} — refreshing in 45s...`);setTimeout(()=>{onDone();setRunning('');setMsg('')},45000)}
      else{setMsg(`Failed: ${d.error||'?'}`);setRunning('')}
    } catch(e){setMsg(`Error: ${e}`);setRunning('')}
  },[onDone])
  return (
    <div style={{ padding:'8px 12px', marginBottom:10, background:'var(--bg1)', border:'1px solid var(--accent)', borderRadius:6 }}>
      <div style={{ fontSize:10, fontWeight:700, color:'var(--accent)', marginBottom:6 }}>LLM Analysis + Incubator Testing</div>
      <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:6 }}>
        <button disabled={!!running} onClick={()=>run('/api/v2/backtesting/analyze-trades','LLM')}
          style={{ fontSize:9, padding:'3px 8px', border:'1px solid var(--accent)', borderRadius:3, background:'var(--accent-dim)', color:'var(--accent)', cursor:'pointer', fontWeight:600, opacity:running?.5:1 }}>
          {running==='LLM'?'...':'🧠 LLM Grade Trades'}
        </button>
        <button disabled={!!running} onClick={()=>run('/api/v2/backtesting/all-incubator','All')}
          style={{ fontSize:9, padding:'3px 8px', border:'1px solid var(--purple)', borderRadius:3, background:'rgba(168,139,250,.08)', color:'var(--purple)', cursor:'pointer', fontWeight:600, opacity:running?.5:1 }}>
          {running==='All'?'...':'🔬 All Strategies on Incubator'}
        </button>
      </div>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {STRATEGIES.filter(s=>!SCALPS.has(s)).map(s=>(
          <button key={s} disabled={!!running} onClick={()=>run(`/api/v2/backtesting/backtest-incubator/${s}`,s)}
            style={{ fontSize:7, padding:'1px 5px', border:'1px solid var(--purple)', borderRadius:2, background:running===s?'var(--purple)':'rgba(168,139,250,.05)', color:running===s?'#fff':'var(--purple)', cursor:running?'wait':'pointer' }}>
            {running===s?'..':s.replace(/_/g,' ')}
          </button>
        ))}
      </div>
      {msg&&<div style={{fontSize:9,color:'var(--green)',marginTop:4}}>{msg}</div>}
    </div>
  )
}

function RunPanel({ onDone }: { onDone: () => void }) {
  const [running, setRunning] = useState(''); const [msg, setMsg] = useState('')
  const run = useCallback(async (ep: string, label: string) => {
    setRunning(label); setMsg('')
    try { const r = await fetch(ep,{method:'POST'}); const d = await r.json()
      if(d.ok){setMsg(`${label} started...`);setTimeout(()=>{onDone();setRunning('');setMsg('')},30000)}
      else{setMsg(`Failed: ${d.error||'?'}`);setRunning('')}
    } catch(e){setMsg(`Error: ${e}`);setRunning('')}
  },[onDone])
  return (
    <div style={{ padding:'8px 12px', marginBottom:10, background:'var(--bg1)', border:'1px solid var(--border)', borderRadius:6 }}>
      <div style={{ fontSize:10, fontWeight:700, color:'var(--text1)', marginBottom:6 }}>Enterprise Price-Replay (Real OHLC)</div>
      <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:6 }}>
        <button disabled={!!running} onClick={()=>run('/api/v2/backtesting/run-replay-trades','RT')}
          style={{ fontSize:9, padding:'3px 8px', border:'1px solid var(--green)', borderRadius:3, background:'var(--green-dim)', color:'var(--green)', cursor:'pointer', fontWeight:600, opacity:running?.5:1 }}>
          {running==='RT'?'...':'▶ Replay Trades'}
        </button>
        <button disabled={!!running} onClick={()=>run('/api/v2/backtesting/run-replay-proposals','RP')}
          style={{ fontSize:9, padding:'3px 8px', border:'1px solid var(--green)', borderRadius:3, background:'var(--green-dim)', color:'var(--green)', cursor:'pointer', fontWeight:600, opacity:running?.5:1 }}>
          {running==='RP'?'...':'▶ Replay Proposals'}
        </button>
      </div>
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {STRATEGIES.map(s=>(
          <button key={s} disabled={!!running} onClick={()=>run(`/api/v2/backtesting/run-strategy/${s}`,s)}
            style={{ fontSize:7, padding:'1px 5px', border:'1px solid var(--border)', borderRadius:2, background:running===s?'var(--accent)':'var(--bg2)', color:running===s?'#fff':'var(--text3)', cursor:running?'wait':'pointer' }}>
            {running===s?'..':s.replace(/_/g,' ')}
          </button>
        ))}
      </div>
      {msg&&<div style={{fontSize:9,color:'var(--green)',marginTop:4}}>{msg}</div>}
    </div>
  )
}
