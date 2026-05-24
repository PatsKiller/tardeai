import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const SC: Record<string, string> = {
  correct:'#0ecb81', incorrect:'#f6465d', neutral:'#848e9c',
  unresolved:'#848e9c', partially_correct:'#f0b90b',
  insight_only:'#f0b90b', shadow_only:'#4a90f4', proposal_allowed:'#0ecb81',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background:SC[s]||'#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }
const n = (v: unknown, d=2) => typeof v === 'number' ? v.toFixed(d) : '—'

export default function AgentCalibration() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')
  const { data: status } = useApi<any>(`/api/v2/agent-calibration/status?_r=${rk}`)
  const { data: agents } = useApi<any>(`/api/v2/agent-calibration/agents?_r=${rk}`)
  const { data: windows } = useApi<any>(`/api/v2/agent-calibration/windows?_r=${rk}`)
  const { data: events } = useApi<any>(`/api/v2/agent-calibration/events?_r=${rk}`)
  const { data: disagreements } = useApi<any>(`/api/v2/agent-calibration/disagreements?_r=${rk}`)
  const { data: proposals } = useApi<any>(`/api/v2/agent-calibration/weight-proposals?_r=${rk}`)

  const s = status?.data || {}
  const tabBtn = (t: string, label: string) => (
    <button onClick={() => setTab(t)} style={{
      ...btn, background: tab === t ? 'var(--accent)' : 'var(--bg1)',
      color: tab === t ? '#fff' : 'var(--text1)'
    }}>{label}</button>
  )
  const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10 }
  const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Agent Calibration" subtitle="Recommendation accuracy, calibration error, disagreement outcomes" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('windows', `Scorecards (${(windows?.data||[]).length})`)}
        {tabBtn('events', `Events (${(events?.data||[]).length})`)}
        {tabBtn('disagreements', `Disagreements (${(disagreements?.data||[]).length})`)}
        {tabBtn('proposals', `Weight Proposals (${(proposals?.data||[]).length})`)}
      </div>

      {tab === 'overview' && (<>
        {(s.recommendations_total ?? 0) === 0 && (s.calibration_events_total ?? 0) === 0 && (
          <div style={{ padding:'10px 14px', marginBottom:12, borderRadius:6,
            background:'rgba(240,185,11,.08)', border:'1px solid rgba(240,185,11,.3)' }}>
            <span style={{ fontSize:12, fontWeight:700, color:'#f0b90b' }}>
              INSUFFICIENT DATA — Calibration requires scored trade outcomes. No graded outcomes yet.
            </span>
            <div style={{ fontSize:10, color:'#848e9c', marginTop:4 }}>
              Agent accuracy cannot be computed until paper trades close and outcomes are scored.
              The system needs 10+ scored outcomes to begin calibration.
            </div>
          </div>
        )}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(180px,1fr))', gap:10 }}>
          {[['Recommendations', s.recommendations_total], ['Outcome Links', s.outcome_links_total],
            ['Calibration Events', s.calibration_events_total], ['Windows', s.calibration_windows_total],
            ['Disagreements', s.disagreements_total], ['Weight Proposals', s.weight_proposals_total],
          ].map(([l,v]) => (
            <Card key={String(l)} compact title={String(l)}>
              <div style={{ fontSize:24, fontWeight:700 }}>{v ?? 0}</div>
            </Card>
          ))}
          {(agents?.data||[]).map((a: any) => (
            <Card key={a.agent_name} compact title={a.agent_name}>
              <div style={{ fontSize:11, color:'var(--text2)' }}>{a.total} recs, {a.symbols} symbols</div>
            </Card>
          ))}
        </div>
      </>)}

      {tab === 'windows' && (
        <Card title="Agent Calibration Windows">
          {!(windows?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No calibration windows yet. Run calibration engine first.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Agent','Domain','Recs','Resolved','Correct','Incorrect','Accuracy','Conf','Cal Err','OC','UC','Sample'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(windows.data as any[]).map((w: any) => (
                <tr key={w.window_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{w.agent_name}</td>
                  <td style={td}>{w.domain}</td>
                  <td style={td}>{w.recommendations}</td><td style={td}>{w.resolved}</td>
                  <td style={{ ...td, color:'#0ecb81' }}>{w.correct}</td>
                  <td style={{ ...td, color:'#f6465d' }}>{w.incorrect}</td>
                  <td style={td}>{w.accuracy ? `${(Number(w.accuracy)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{n(w.avg_confidence)}</td>
                  <td style={td}>{n(w.calibration_error)}</td>
                  <td style={td}>{n(w.overconfidence_score)}</td>
                  <td style={td}>{n(w.underconfidence_score)}</td>
                  <td style={td}>{dot(w.sample_size_status||'insight_only')}{w.sample_size_status}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'events' && (
        <Card title="Recent Calibration Events">
          {!(events?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No events yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Agent','Symbol','Action','Conf','Outcome','Score','Cal Err','Explanation'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(events.data as any[]).slice(0,30).map((e: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={td}>{e.agent_name}</td><td style={td}>{e.symbol}</td>
                  <td style={td}>{e.predicted_action}</td>
                  <td style={td}>{n(e.predicted_confidence)}</td>
                  <td style={td}>{dot(e.actual_outcome)}{e.actual_outcome}</td>
                  <td style={td}>{n(e.outcome_score,1)}</td>
                  <td style={td}>{n(e.calibration_error)}</td>
                  <td style={{ ...td, fontSize:10, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{e.explanation}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'disagreements' && (
        <Card title="Agent Disagreements">
          {!(disagreements?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No disagreements yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['Symbol','Type','Agents','Winner','Loser','Outcome','Resolved'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(disagreements.data as any[]).slice(0,20).map((d: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontWeight:600 }}>{d.symbol}</td>
                  <td style={td}>{d.disagreement_type}</td>
                  <td style={{ ...td, fontSize:10 }}>{JSON.stringify(d.agents_involved).slice(0,40)}</td>
                  <td style={{ ...td, color:'#0ecb81' }}>{d.winning_view||'—'}</td>
                  <td style={{ ...td, color:'#f6465d' }}>{d.losing_view||'—'}</td>
                  <td style={{ ...td, fontSize:10 }}>{(d.outcome_summary||'').slice(0,50)}</td>
                  <td style={td}>{d.resolved ? 'Yes' : 'No'}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'proposals' && (
        <Card title="Agent Weight Shadow Proposals">
          {!(proposals?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No weight proposals yet. Need more calibration data.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Agent','Domain','Current','Proposed','Delta','Sample','Status'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(proposals.data as any[]).map((p: any) => (
                <tr key={p.shadow_proposal_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{p.shadow_proposal_id?.slice(-12)}</td>
                  <td style={td}>{p.agent_name}</td><td style={td}>{p.domain}</td>
                  <td style={td}>{n(p.current_weight)}</td><td style={td}>{n(p.proposed_weight)}</td>
                  <td style={td}>{n(p.weight_delta)}</td><td style={td}>{p.sample_size}</td>
                  <td style={td}>{p.status}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
