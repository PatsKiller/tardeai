import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const SC: Record<string, string> = {
  draft:'#848e9c', proposed:'#f0b90b', approved_for_shadow:'#4a90f4',
  shadow_running:'#4a90f4', evidence_ready:'#0ecb81', rejected:'#f6465d',
  promoted:'#0ecb81', rolled_back:'#f6465d', archived:'#848e9c',
  planned:'#848e9c', running:'#4a90f4', completed:'#0ecb81',
  failed:'#f6465d', cancelled:'#848e9c', approved:'#0ecb81',
  implemented:'#0ecb81', expired:'#848e9c', shadow_only:'#4a90f4',
  insight_only:'#f0b90b', shadow_allowed:'#4a90f4', promotion_allowed:'#0ecb81',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background:SC[s]||'#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }

export default function LearningGovernance() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')
  const { data: status } = useApi<any>(`/api/v2/learning/status?_r=${rk}`)
  const { data: hyps } = useApi<any>(`/api/v2/learning/hypotheses?_r=${rk}`)
  const { data: exps } = useApi<any>(`/api/v2/learning/experiments?_r=${rk}`)
  const { data: recs } = useApi<any>(`/api/v2/learning/recommendations?_r=${rk}`)
  const { data: props } = useApi<any>(`/api/v2/learning/config-proposals?_r=${rk}`)

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
      <PageHeader title="Learning Governance" subtitle="Self-improvement control plane — learning proposes, admin approves" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      {/* Sample Size Banner */}
      <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6,
        background: s.sample_size_tier === 'insight_only' ? 'rgba(240,185,11,.08)' : 'rgba(14,203,129,.08)',
        border: `1px solid ${s.sample_size_tier === 'insight_only' ? '#f0b90b' : '#0ecb81'}` }}>
        <span style={{ fontSize:12, fontWeight:700, color: s.sample_size_tier === 'insight_only' ? '#f0b90b' : '#0ecb81' }}>
          {dot(s.sample_size_tier || 'insight_only')}
          Sample Tier: {(s.sample_size_tier || 'insight_only').replace(/_/g,' ').toUpperCase()}
        </span>
        <span style={{ fontSize:11, color:'var(--text2)', marginLeft:12 }}>
          {s.closed_paper_trades ?? '?'} closed paper trades | Need 30 for shadow, 100 for promotion
        </span>
      </div>

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('hypotheses', `Hypotheses (${(hyps?.data||[]).length})`)}
        {tabBtn('experiments', `Experiments (${(exps?.data||[]).length})`)}
        {tabBtn('recommendations', `Recommendations (${(recs?.data||[]).length})`)}
        {tabBtn('proposals', `Config Proposals (${(props?.data||[]).length})`)}
      </div>

      {tab === 'overview' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px, 1fr))', gap:10 }}>
          {[
            ['Hypotheses', s.hypotheses_total],
            ['Experiments', s.experiments_total],
            ['Recommendations', s.recommendations_total],
            ['Config Proposals', s.config_proposals_total],
            ['Evidence Items', s.evidence_items_total],
            ['Source Scores', s.source_scores_total],
            ['Strategy Scores', s.strategy_scores_total],
            ['Agent Scores', s.agent_scores_total],
          ].map(([label, val]) => (
            <Card key={String(label)} compact title={String(label)}>
              <div style={{ fontSize:24, fontWeight:700, color:'var(--text0)' }}>{val ?? 0}</div>
            </Card>
          ))}
        </div>
      )}

      {tab === 'hypotheses' && (
        <Card title="Learning Hypotheses">
          {!(hyps?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No hypotheses yet. Run learning engines first.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Title','Domain','Type','Status','Sample','Confidence','Risk','Source','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(hyps.data as any[]).map((h: any) => (
                <tr key={h.hypothesis_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{h.hypothesis_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{h.title}</td>
                  <td style={td}>{h.domain}</td><td style={td}>{h.hypothesis_type}</td>
                  <td style={td}>{dot(h.status)}{h.status}</td>
                  <td style={td}>{h.sample_size}</td>
                  <td style={td}>{h.confidence ? `${(Number(h.confidence)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{h.risk_level}</td><td style={td}>{h.generated_by}</td>
                  <td style={{ ...td, fontSize:9 }}>{h.created_at ? new Date(h.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'experiments' && (
        <Card title="Shadow Experiments">
          {!(exps?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No experiments yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Name','Domain','Type','Status','Sample','MinSample','Conclusion','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(exps.data as any[]).map((e: any) => (
                <tr key={e.experiment_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{e.experiment_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{e.name}</td>
                  <td style={td}>{e.domain}</td><td style={td}>{e.experiment_type}</td>
                  <td style={td}>{dot(e.status)}{e.status}</td>
                  <td style={td}>{e.actual_sample_size}/{e.min_sample_size}</td>
                  <td style={td}>{e.min_sample_size}</td>
                  <td style={{ ...td, fontSize:10 }}>{e.conclusion || '—'}</td>
                  <td style={{ ...td, fontSize:9 }}>{e.created_at ? new Date(e.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'recommendations' && (
        <Card title="Learning Recommendations">
          {!(recs?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No recommendations yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Title','Domain','Type','Status','Sample','Confidence','Risk','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(recs.data as any[]).map((r: any) => (
                <tr key={r.recommendation_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{r.recommendation_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.title}</td>
                  <td style={td}>{r.domain}</td><td style={td}>{r.recommendation_type}</td>
                  <td style={td}>{dot(r.status)}{r.status}</td>
                  <td style={td}>{r.sample_size}</td>
                  <td style={td}>{r.confidence ? `${(Number(r.confidence)*100).toFixed(0)}%` : '—'}</td>
                  <td style={td}>{r.risk_level}</td>
                  <td style={{ ...td, fontSize:9 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'proposals' && (
        <Card title="Config Change Proposals">
          {!(props?.data?.length) ? <div style={{ color:'#848e9c', padding:16 }}>No config proposals yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Domain','Target','Change','Status','Risk','Approved By','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(props.data as any[]).map((p: any) => (
                <tr key={p.proposal_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{p.proposal_id?.slice(-12)}</td>
                  <td style={td}>{p.domain}</td><td style={td}>{p.target_key}</td>
                  <td style={td}>{p.change_type}</td>
                  <td style={td}>{dot(p.status)}{p.status}</td>
                  <td style={td}>{p.risk_assessment || '—'}</td>
                  <td style={td}>{p.approved_by || '—'}</td>
                  <td style={{ ...td, fontSize:9 }}>{p.created_at ? new Date(p.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}
