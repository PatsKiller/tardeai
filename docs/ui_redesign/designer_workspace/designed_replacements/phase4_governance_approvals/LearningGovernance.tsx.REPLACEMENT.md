# LearningGovernance.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

- **Target**: `apps/command-center-v2/src/pages/LearningGovernance.tsx`

## Changes

- Inline `btn` style replaced with `ActionButton` (children pattern)
- Inline `dot()` function replaced with `StatusBadge` for hypothesis/experiment/recommendation/proposal statuses
- Overview tile cards use `StateCard` instead of `Card` with manual layout
- Sample Size Banner preserved exactly (critical governance notice)
- Tab button style updated to use `ActionButton` with variant switching
- Refresh button uses `ActionButton`

## What did NOT change

- All API endpoints preserved:
  - `/api/v2/learning/status` (with refresh key)
  - `/api/v2/learning/hypotheses` (with refresh key)
  - `/api/v2/learning/experiments` (with refresh key)
  - `/api/v2/learning/recommendations` (with refresh key)
  - `/api/v2/learning/config-proposals` (with refresh key)
- All 5 tabs preserved (overview, hypotheses, experiments, recommendations, proposals)
- All table columns preserved
- All data transforms preserved
- Refresh mechanism (setRk) preserved
- No new actions or approvals added

## Full Replacement

```tsx
import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { StateCard } from '../components/StateCard'
import { ActionButton } from '../components/ActionButton'

const SC: Record<string, string> = {
  draft:'unknown', proposed:'warning', approved_for_shadow:'running',
  shadow_running:'running', evidence_ready:'complete', rejected:'blocked',
  promoted:'complete', rolled_back:'blocked', archived:'unknown',
  planned:'unknown', running:'running', completed:'complete',
  failed:'blocked', cancelled:'unknown', approved:'complete',
  implemented:'complete', expired:'unknown', shadow_only:'running',
  insight_only:'warning', shadow_allowed:'running', promotion_allowed:'complete',
}

const th: React.CSSProperties = { padding:'6px 8px', textAlign:'left', color:'#848e9c', fontSize:10 }
const td: React.CSSProperties = { padding:'6px 8px', fontSize:11 }

export default function LearningGovernance() {
  const [rk, setRk] = useState(0)
  const [tab, setTab] = useState('overview')
  const { data: status } = useApi<any>(`/api/v2/learning/status?_r=${rk}`)
  const { data: hyps } = useApi<any>(`/api/v2/learning/hypotheses?_r=${rk}`)
  const { data: exps } = useApi<any>(`/api/v2/learning/experiments?_r=${rk}`)
  const { data: recs } = useApi<any>(`/api/v2/learning/recommendations?_r=${rk}`)
  const { data: props } = useApi<any>(`/api/v2/learning/config-proposals?_r=${rk}`)

  // useApi unwraps { ok, data } -- status IS the data object directly
  const s = status || {}
  const hypotheses: any[] = hyps || []
  const experiments: any[] = exps || []
  const recommendations: any[] = recs || []
  const configProposals: any[] = props || []

  const tabBtn = (t: string, label: string) => (
    <ActionButton
      variant={tab === t ? 'primary' : 'secondary'}
      size="sm"
      onClick={() => setTab(t)}
    >
      {label}
    </ActionButton>
  )

  return (
    <div style={{ padding:'16px 24px', maxWidth:1200 }}>
      <PageHeader title="Learning Governance" subtitle="Self-improvement control plane -- learning proposes, admin approves" actions={
        <ActionButton variant="secondary" size="sm" onClick={() => setRk(k=>k+1)}>Refresh</ActionButton>
      }/>

      {/* Sample Size Banner */}
      <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6,
        background: s.sample_size_tier === 'insight_only' ? 'rgba(240,185,11,.08)' : 'rgba(14,203,129,.08)',
        border: `1px solid ${s.sample_size_tier === 'insight_only' ? '#f0b90b' : '#0ecb81'}` }}>
        <span style={{ fontSize:12, fontWeight:700, color: s.sample_size_tier === 'insight_only' ? '#f0b90b' : '#0ecb81', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <StatusBadge status={SC[s.sample_size_tier] || 'warning'} label={(s.sample_size_tier || 'insight_only').replace(/_/g,' ').toUpperCase()} />
          Sample Tier
        </span>
        <span style={{ fontSize:11, color:'var(--text2)', marginLeft:12 }}>
          {s.closed_paper_trades ?? '?'} closed paper trades | Need 30 for shadow, 100 for promotion
        </span>
      </div>

      <div style={{ display:'flex', gap:6, marginBottom:16, flexWrap:'wrap' }}>
        {tabBtn('overview', 'Overview')}
        {tabBtn('hypotheses', `Hypotheses (${hypotheses.length})`)}
        {tabBtn('experiments', `Experiments (${experiments.length})`)}
        {tabBtn('recommendations', `Recommendations (${recommendations.length})`)}
        {tabBtn('proposals', `Config Proposals (${configProposals.length})`)}
      </div>

      {tab === 'overview' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px, 1fr))', gap:10 }}>
          <StateCard title="Hypotheses" value={s.hypotheses_total ?? 0} compact />
          <StateCard title="Experiments" value={s.experiments_total ?? 0} compact />
          <StateCard title="Recommendations" value={s.recommendations_total ?? 0} compact />
          <StateCard title="Config Proposals" value={s.config_proposals_total ?? 0} compact />
          <StateCard title="Evidence Items" value={s.evidence_items_total ?? 0} compact />
          <StateCard title="Source Scores" value={s.source_scores_total ?? 0} compact />
          <StateCard title="Strategy Scores" value={s.strategy_scores_total ?? 0} compact />
          <StateCard title="Agent Scores" value={s.agent_scores_total ?? 0} compact />
        </div>
      )}

      {tab === 'hypotheses' && (
        <Card title="Learning Hypotheses">
          {!hypotheses.length ? <div style={{ color:'#848e9c', padding:16 }}>No hypotheses yet. Run learning engines first.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Title','Domain','Type','Status','Sample','Confidence','Risk','Source','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(hypotheses as any[]).map((h: any) => (
                <tr key={h.hypothesis_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{h.hypothesis_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{h.title}</td>
                  <td style={td}>{h.domain}</td><td style={td}>{h.hypothesis_type}</td>
                  <td style={td}><StatusBadge status={SC[h.status] || 'unknown'} label={h.status} /></td>
                  <td style={td}>{h.sample_size}</td>
                  <td style={td}>{h.confidence ? `${(Number(h.confidence)*100).toFixed(0)}%` : '--'}</td>
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
          {!experiments.length ? <div style={{ color:'#848e9c', padding:16 }}>No experiments yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Name','Domain','Type','Status','Sample','MinSample','Conclusion','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(experiments as any[]).map((e: any) => (
                <tr key={e.experiment_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{e.experiment_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{e.name}</td>
                  <td style={td}>{e.domain}</td><td style={td}>{e.experiment_type}</td>
                  <td style={td}><StatusBadge status={SC[e.status] || 'unknown'} label={e.status} /></td>
                  <td style={td}>{e.actual_sample_size}/{e.min_sample_size}</td>
                  <td style={td}>{e.min_sample_size}</td>
                  <td style={{ ...td, fontSize:10 }}>{e.conclusion || '--'}</td>
                  <td style={{ ...td, fontSize:9 }}>{e.created_at ? new Date(e.created_at).toLocaleDateString() : ''}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}

      {tab === 'recommendations' && (
        <Card title="Learning Recommendations">
          {!recommendations.length ? <div style={{ color:'#848e9c', padding:16 }}>No recommendations yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Title','Domain','Type','Status','Sample','Confidence','Risk','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(recommendations as any[]).map((r: any) => (
                <tr key={r.recommendation_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{r.recommendation_id?.slice(-12)}</td>
                  <td style={{ ...td, maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r.title}</td>
                  <td style={td}>{r.domain}</td><td style={td}>{r.recommendation_type}</td>
                  <td style={td}><StatusBadge status={SC[r.status] || 'unknown'} label={r.status} /></td>
                  <td style={td}>{r.sample_size}</td>
                  <td style={td}>{r.confidence ? `${(Number(r.confidence)*100).toFixed(0)}%` : '--'}</td>
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
          {!configProposals.length ? <div style={{ color:'#848e9c', padding:16 }}>No config proposals yet.</div> : (
            <table style={{ width:'100%', fontSize:11, borderCollapse:'collapse' }}>
              <thead><tr style={{ borderBottom:'1px solid var(--border)' }}>
                {['ID','Domain','Target','Change','Status','Risk','Approved By','Created'].map(h =>
                  <th key={h} style={th}>{h}</th>)}
              </tr></thead>
              <tbody>{(configProposals as any[]).map((p: any) => (
                <tr key={p.proposal_id} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ ...td, fontSize:9 }}>{p.proposal_id?.slice(-12)}</td>
                  <td style={td}>{p.domain}</td><td style={td}>{p.target_key}</td>
                  <td style={td}>{p.change_type}</td>
                  <td style={td}><StatusBadge status={SC[p.status] || 'unknown'} label={p.status} /></td>
                  <td style={td}>{p.risk_assessment || '--'}</td>
                  <td style={td}>{p.approved_by || '--'}</td>
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
```
