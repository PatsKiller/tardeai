import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const SC: Record<string, string> = {
  healthy:'#0ecb81', warning:'#f0b90b', degraded:'#f6465d',
  failed:'#f6465d', unknown:'#848e9c',
  urgent:'#f6465d', important:'#f0b90b', normal:'#4a90f4', info:'#848e9c',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background:SC[s]||'#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }

export default function SelfImprovement() {
  const navigate = useNavigate()
  const [rk, setRk] = useState(0)
  const { data: status } = useApi<any>(`/api/v2/self-improvement/status?_r=${rk}`)
  const { data: queue } = useApi<any>(`/api/v2/self-improvement/review-queue?_r=${rk}`)
  const { data: health } = useApi<any>(`/api/v2/self-improvement/component-health?_r=${rk}`)

  const s = status?.data || {}
  const safety = s.safety || {}
  const paper = s.paper_trading || {}
  const learning = s.learning || {}
  const agents = s.agent_calibration || {}
  const bt = s.backtesting || {}
  const pipe = s.pipeline || {}
  const warnings = s.warnings || []
  const actions = s.recommended_actions || []
  const queueItems = queue?.data || []
  const components = health?.data || []

  const link = (route: string, label: string) => (
    <button onClick={() => navigate(route)} style={{ ...btn, fontSize:9, padding:'2px 8px' }}>{label} →</button>
  )

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Self-Improvement Command Center" subtitle="Unified operator view — read-only aggregation across all intelligence layers" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      {/* Safety Banner */}
      <div style={{ padding:'10px 16px', marginBottom:14, borderRadius:6,
        background: safety.allowed ? 'rgba(246,70,93,.15)' : 'rgba(14,203,129,.08)',
        border: `1px solid ${safety.allowed ? '#f6465d' : '#0ecb81'}`,
        display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <div>
          <span style={{ fontSize:14, fontWeight:700, color: safety.allowed ? '#f6465d' : '#0ecb81' }}>
            {safety.allowed ? 'LIVE TRADING ALLOWED — DANGER' : 'PAPER MODE ACTIVE — BLOCKED'}
          </span>
          <span style={{ fontSize:11, color:'var(--text2)', marginLeft:12 }}>
            Holdings: ${(safety.holdings_value||0).toLocaleString()} | Guard: {safety.holdings_guard ? 'PASS' : 'FAIL'}
          </span>
        </div>
        <span style={{ fontSize:10, color:'var(--text3)' }}>{(safety.blocked_reasons||[]).length} block reasons</span>
      </div>

      {/* Overview Cards */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(160px,1fr))', gap:8, marginBottom:14 }}>
        {[['Paper Closed', paper.closed, paper.low_sample ? 'LOW SAMPLE' : ''],
          ['Paper Open', paper.open, ''],
          ['Pending Proposals', paper.pending_proposals, ''],
          ['Learning Recs', learning.recommendations_pending, learning.recommendations_pending > 0 ? 'REVIEW' : ''],
          ['Config Proposals', learning.config_proposals_pending, learning.config_proposals_pending > 0 ? 'APPROVAL' : ''],
          ['Agent Recs', agents.recommendations, ''],
          ['Backtest Runs', bt.runs, ''],
          ['Pipeline Fails', pipe.failures, pipe.failures > 0 ? 'CHECK' : ''],
          ['Warnings', warnings.length, ''],
        ].map(([label, val, badge]) => (
          <div key={String(label)} style={{ padding:'8px 12px', border:'1px solid var(--border)', borderRadius:6,
            background: badge ? 'rgba(240,185,11,.05)' : 'transparent' }}>
            <div style={{ fontSize:10, color:'#848e9c' }}>{String(label)}</div>
            <div style={{ fontSize:20, fontWeight:700 }}>{val ?? 0}</div>
            {badge && <div style={{ fontSize:9, color:'#f0b90b', fontWeight:600 }}>{String(badge)}</div>}
          </div>
        ))}
      </div>

      {/* Operator Review Queue */}
      {queueItems.length > 0 && (
        <Card title={`Operator Review Queue (${queueItems.length})`} style={{ marginBottom:14 }}>
          {queueItems.map((q: any) => (
            <div key={q.review_item_id} style={{ padding:'6px 0', borderBottom:'1px solid var(--border)',
              display:'flex', justifyContent:'space-between', alignItems:'center' }}>
              <div>
                {dot(q.severity)}
                <span style={{ fontSize:11 }}>{q.title}</span>
                {q.requires_action && <span style={{ fontSize:9, color:'#f0b90b', marginLeft:6 }}>ACTION</span>}
              </div>
              {q.linked_dashboard_route && link(q.linked_dashboard_route, q.source_domain)}
            </div>
          ))}
        </Card>
      )}

      {/* Component Health */}
      <Card title="Component Health" style={{ marginBottom:14 }}>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px,1fr))', gap:6 }}>
          {components.map((c: any) => (
            <div key={c.component_key} style={{ padding:'6px 10px', border:'1px solid var(--border)', borderRadius:4,
              fontSize:11, display:'flex', justifyContent:'space-between' }}>
              <span>{dot(c.status)}{c.component_name}</span>
              <span style={{ color:'var(--text3)', fontSize:10 }}>{c.status}</span>
            </div>
          ))}
          {components.length === 0 && <div style={{ color:'#848e9c', fontSize:11, padding:8 }}>Run snapshot first to populate health</div>}
        </div>
      </Card>

      {/* Quick Links */}
      <Card title="Subsystem Dashboards" style={{ marginBottom:14 }}>
        <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
          {['/v2/learning-governance', '/v2/agent-calibration', '/v2/weekly-learning',
            '/v2/backtesting', '/v2/paper-trade-intelligence', '/v2/pipeline-controller'].map(r => (
            <button key={r} onClick={() => navigate(r)} style={btn}>{r.replace('/v2/', '')}</button>
          ))}
        </div>
      </Card>

      {/* Warnings */}
      {warnings.length > 0 && (
        <Card title={`Warnings (${warnings.length})`}>
          {warnings.map((w: any, i: number) => (
            <div key={i} style={{ fontSize:11, padding:'4px 0', borderBottom:'1px solid var(--border)' }}>
              {dot(w.type === 'low_sample' ? 'info' : 'warning')}{w.msg}
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
