import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface ApiResp { ok: boolean; data: Record<string, unknown>[] }
interface GateResp { ok: boolean; data: { gates: Record<string, unknown>; blocked_reasons: string[] } }

const SC: Record<string, string> = {
  proposed: '#f0b90b', approved: '#4a90f4', rejected: '#f6465d',
  executed: '#0ecb81', expired: '#848e9c', failed: '#f6465d',
  EXCELLENT: '#0ecb81', GOOD: '#4a90f4', FAIR: '#f0b90b', POOR: '#f6465d',
  win: '#0ecb81', loss: '#f6465d', breakeven: '#848e9c',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background: SC[s] || '#848e9c', marginRight:6 }}/>
const n = (v: unknown, d = 2) => typeof v === 'number' ? v.toFixed(d) : '—'
const $ = (v: unknown) => typeof v === 'number' ? `$${v.toFixed(2)}` : '—'

export default function PaperTradeIntelligence() {
  const { data: intel } = useApi<ApiResp>('/api/v2/open-trade-intelligence')
  const { data: mods } = useApi<ApiResp>('/api/v2/paper-order-modifications?status=all')
  const { data: tca } = useApi<ApiResp>('/api/v2/paper-tca')
  const { data: recon } = useApi<ApiResp>('/api/v2/paper-broker-reconciliation')
  const { data: outcomes } = useApi<ApiResp>('/api/v2/paper-outcome-analytics')
  const { data: gate } = useApi<GateResp>('/api/v2/paper-validation-status')
  const { data: rechecks } = useApi<ApiResp>('/api/v2/paper-execution-rechecks')
  const { data: session } = useApi<{ ok: boolean; data: Record<string, unknown> }>('/api/v2/market-session')
  const [tab, setTab] = useState<string>('intel')

  const g = gate?.data?.gates || {}
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      padding:'6px 14px', border:'1px solid var(--border)', borderRadius:4, cursor:'pointer',
      background: tab === t ? 'var(--accent)' : 'var(--bg1)', color: tab === t ? '#fff' : 'var(--text1)',
      fontSize:12
    }}>{label}</button>
  )

  const th = { padding:'6px 8px' as const, textAlign:'left' as const, color:'#848e9c' }
  const td = { padding:'6px 8px' as const }

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Paper Trade Intelligence" />

      <div style={{ background:'#1a2332', border:'1px solid #f0b90b', borderRadius:8, padding:12, marginBottom:16 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <span style={{ color:'#f0b90b', fontWeight:700, fontSize:14 }}>PAPER MODE ACTIVE — Live Trading BLOCKED</span>
          <span style={{ color:'#848e9c', fontSize:11 }}>
            {g.validation_days_elapsed !== undefined ? `${g.validation_days_elapsed}/${g.validation_days_required} days | ${g.closed_trades}/${g.closed_trades_required} trades` : 'Loading...'}
          </span>
        </div>
      </div>

      <div style={{ display:'flex', gap:6, marginBottom:16 }}>
        {tabBtn('intel', 'Open Trades')}
        {tabBtn('mods', `Modifications (${(mods?.data || []).length})`)}
        {tabBtn('tca', 'TCA / Fill Quality')}
        {tabBtn('recon', 'Broker Recon')}
        {tabBtn('outcomes', 'Outcome Analytics')}
        {tabBtn('rechecks', `Execution Rechecks (${(rechecks?.data || []).length})`)}
      </div>

      {tab === 'intel' && (
        <Card title="Open Trade Intelligence">
          {!(intel?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No open trades</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Symbol','Price','Entry','Stop','Target','P&L %','R','Stop Dist','RSI','News','Summary'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{intel.data.map((t: Record<string, unknown>) => (
                <tr key={String(t.paper_trade_id)} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{String(t.symbol)}</td>
                  <td style={td}>{$(t.current_price)}</td><td style={td}>{$(t.entry_price)}</td>
                  <td style={td}>{$(t.stop_price)}</td><td style={td}>{$(t.limit_price)}</td>
                  <td style={{ ...td, color: Number(t.unrealized_pnl_pct) > 0 ? '#0ecb81' : '#f6465d' }}>{n(t.unrealized_pnl_pct,1)}%</td>
                  <td style={td}>{n(t.r_multiple,1)}</td>
                  <td style={td}>{n(t.distance_to_stop_pct,1)}%</td>
                  <td style={td}>{n(t.rsi,0)}</td>
                  <td style={td}>{n(t.news_risk_score,1)}</td>
                  <td style={{ ...td, fontSize:10, color:'#848e9c' }}>{String(t.intelligence_summary || '')}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'mods' && (
        <Card title="Order Modification Proposals">
          {!(mods?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No proposals</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Symbol','Action','Stop','Limit','Conf','Status','Reason'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{mods.data.map((m: Record<string, unknown>) => (
                <tr key={String(m.proposal_id)} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontFamily:'monospace', fontSize:9 }}>{String(m.proposal_id).slice(0,20)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{String(m.symbol)}</td>
                  <td style={td}>{String(m.action)}</td>
                  <td style={td}>{m.current_stop ? `${m.current_stop}→${m.proposed_stop}` : '—'}</td>
                  <td style={td}>{m.current_limit ? `${m.current_limit}→${m.proposed_limit}` : '—'}</td>
                  <td style={td}>{n(m.confidence)}</td>
                  <td style={td}>{dot(String(m.status))}{String(m.status)}</td>
                  <td style={{ ...td, fontSize:10, color:'#848e9c' }}>{String(m.reason || '').slice(0,60)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'tca' && (
        <Card title="Execution Quality (TCA)">
          {!(tca?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No TCA events</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Trade','Symbol','Type','Expected','Actual','Slip(bps)','Grade','Time'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{tca.data.map((e: Record<string, unknown>, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={td}>#{String(e.paper_trade_id)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{String(e.symbol)}</td>
                  <td style={td}>{String(e.event_type)}</td>
                  <td style={td}>{$(e.expected_price)}</td><td style={td}>{$(e.actual_price)}</td>
                  <td style={{ ...td, color: Math.abs(Number(e.slippage_bps)||0) < 15 ? '#0ecb81' : '#f6465d' }}>{n(e.slippage_bps,1)}</td>
                  <td style={td}>{dot(String(e.quality_grade||''))}{String(e.quality_grade||'')}</td>
                  <td style={{ ...td, fontSize:10, color:'#848e9c' }}>{String(e.created_at||'').slice(0,16)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'recon' && (
        <Card title="Broker Reconciliation">
          {!(recon?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No reconciliation runs</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Run','Status','Mode','DB','Broker Pos','Orders','Matched','Unmatched','Time'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{recon.data.map((r: Record<string, unknown>) => (
                <tr key={String(r.run_id)} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontFamily:'monospace', fontSize:9 }}>{String(r.run_id).slice(0,20)}</td>
                  <td style={td}>{String(r.status)}</td><td style={td}>{String(r.alpaca_mode)}</td>
                  <td style={td}>{String(r.db_open_trades)}</td>
                  <td style={td}>{String(r.broker_open_positions)}</td>
                  <td style={td}>{String(r.broker_open_orders)}</td>
                  <td style={{ ...td, color:'#0ecb81' }}>{String(r.matched_positions)}</td>
                  <td style={{ ...td, color: Number(r.unmatched_db_trades)>0?'#f6465d':'#848e9c' }}>{String(r.unmatched_db_trades)}</td>
                  <td style={{ ...td, fontSize:10, color:'#848e9c' }}>{String(r.finished_at||'').slice(0,16)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'rechecks' && (
        <Card title={`Execution Rechecks — Market: ${session?.data?.session || '?'}`}>
          {session?.data && (
            <div style={{ fontSize:10, color:'#848e9c', marginBottom:8 }}>
              {String(session.data.eastern_time)} | Open: {String(session.data.market_open)} | Delay: {String(session.data.should_delay)} ({String(session.data.delay_reason)})
            </div>
          )}
          {!(rechecks?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No execution rechecks yet</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Proposal','Symbol','Trigger','Status','Score','Drift','Session','Material','Reapproval','Reason','Time'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(rechecks.data as Record<string,unknown>[]).map((r) => {
                const st = String(r.status||'')
                const sc = Number(r.execution_readiness_score||0)
                return (
                <tr key={String(r.recheck_id)} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={td}>#{String(r.paper_trade_proposal_id)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{String(r.symbol)}</td>
                  <td style={{ ...td, fontSize:10 }}>{String(r.trigger_type||'')}</td>
                  <td style={{ ...td, color: st==='valid_original'?'#0ecb81': st==='delayed'?'#f0b90b': st==='blocked_safety'?'#f6465d':'#848e9c' }}>
                    {st}
                  </td>
                  <td style={{ ...td, color: sc>=70?'#0ecb81': sc>=50?'#f0b90b':'#f6465d' }}>{sc}</td>
                  <td style={td}>{r.price_drift_pct ? `${Number(r.price_drift_pct).toFixed(1)}%` : '—'}</td>
                  <td style={td}>{String(r.market_session||'')}</td>
                  <td style={td}>{r.material_change_detected ? 'YES' : '—'}</td>
                  <td style={{ ...td, color: r.requires_reapproval?'#f6465d':'#848e9c' }}>{r.requires_reapproval ? 'YES' : 'No'}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:10 }}>{String(r.reason||'')}</td>
                  <td style={{ ...td, fontSize:10 }}>{r.created_at ? new Date(String(r.created_at)).toLocaleString() : ''}</td>
                </tr>
              )})}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'outcomes' && (
        <Card title="Paper Trade Outcomes">
          {!(outcomes?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No outcome analytics</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Trade','Symbol','Strategy','Entry','Exit','P&L','P&L %','R','Exit','TCA','Verdict'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{outcomes.data.map((o: Record<string, unknown>) => (
                <tr key={String(o.paper_trade_id)} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={td}>#{String(o.paper_trade_id)}</td>
                  <td style={{ ...td, fontWeight:600 }}>{String(o.symbol)}</td>
                  <td style={td}>{String(o.strategy_id||'—')}</td>
                  <td style={td}>{$(o.entry_price)}</td><td style={td}>{$(o.exit_price)}</td>
                  <td style={{ ...td, color: Number(o.pnl)>0?'#0ecb81':'#f6465d' }}>{$(o.pnl)}</td>
                  <td style={{ ...td, color: Number(o.pnl_pct)>0?'#0ecb81':'#f6465d' }}>{n(o.pnl_pct,1)}%</td>
                  <td style={td}>{n(o.r_multiple,1)}</td>
                  <td style={{ ...td, fontSize:10 }}>{String(o.exit_reason||'—')}</td>
                  <td style={td}>{String(o.tca_grade||'—')}</td>
                  <td style={td}>{dot(String(o.outcome_verdict||''))}{String(o.outcome_verdict||'')}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
