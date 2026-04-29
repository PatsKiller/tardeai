import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { DoughnutChart, BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'

interface CIODashboardData {
  decision_summary: { action: string; priority: string; cnt: number }[]
  human_review_pending: number
  pending_rotations: number
  draft_plans: number
  latest_plan: { plan_id: string; plan_summary: string; total_trade_value: number; human_review_required: boolean } | null
  marl_simulations: number
}

interface CIODecision {
  decision_id: string; symbol: string; strategy_type: string; action: string
  action_class: string; priority: string; confidence_raw: number
  decision_safety: string; human_review_required: boolean; rationale: string
  expected_income_impact: number; expected_allocation_impact: number; status: string
  created_at: string; reasoning?: string
}

interface AgentRow { agent: string; total: number; buy_count: number; sell_count: number; hold_count: number; avg_confidence: number }
interface AgentsResp { agents: AgentRow[] }

export default function CIODashboard() {
  const [refreshKey, setRefreshKey] = useState(0)
  const { data: dashboard } = useApi<CIODashboardData>(`/api/v2/cio-dashboard?_r=${refreshKey}`)
  const { data: decisionsResp } = useApi<{ decisions: CIODecision[] }>(`/api/v2/cio-decisions?_r=${refreshKey}`)
  const { data: agentsSummary } = useApi<AgentsResp>(`/api/v2/agents/summary?_r=${refreshKey}`)
  const { data: rotations } = useApi<{ rotations: any[] }>(`/api/v2/strategy-rotations?_r=${refreshKey}`)
  const { data: rebalance } = useApi<{ plan: any; actions: any[] }>(`/api/v2/rebalance-plans/latest?_r=${refreshKey}`)
  const { data: marl } = useApi<any>(`/api/v2/marl/shadow-diagnostics?_r=${refreshKey}`)
  const { data: agentPerf } = useApi<{ history: any[] }>(`/api/v2/agent-performance?_r=${refreshKey}`)
  const { data: signalQA } = useApi<any>(`/api/v2/portfolio-signal-qa?_r=${refreshKey}`)

  const decisions = decisionsResp?.decisions || []
  const critical = decisions.filter(d => d.priority === 'critical' || d.priority === 'high')
  const humanReview = decisions.filter(d => d.human_review_required)

  // Action distribution for doughnut
  const actionCounts: Record<string, number> = {}
  decisions.forEach(d => { actionCounts[d.action] = (actionCounts[d.action] || 0) + 1 })
  const actionLabels = Object.keys(actionCounts)
  const actionData = Object.values(actionCounts)

  // Priority distribution for bar chart
  const priorityCounts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 }
  decisions.forEach(d => { if (priorityCounts[d.priority] !== undefined) priorityCounts[d.priority]++; else priorityCounts[d.priority] = (priorityCounts[d.priority] || 0) + 1 })
  const priorityLabels = Object.keys(priorityCounts)
  const priorityData = Object.values(priorityCounts)
  const priorityColors = priorityLabels.map(p => p === 'critical' ? '#f6465d' : p === 'high' ? '#f0b90b' : p === 'medium' ? '#4a90f4' : '#6b7280')

  // Recent 10 decisions
  const recentDecisions = [...decisions].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')).slice(0, 10)

  return (
    <>
      <PageHeader title="CIO Intelligence Dashboard" subtitle={`${decisions.length} decisions · ${humanReview.length} need review · ${dashboard?.pending_rotations || 0} rotations · ${dashboard?.draft_plans || 0} plans`} actions={
        <button onClick={() => setRefreshKey(k => k + 1)} style={btnStyle}>⟳ Refresh</button>
      } />

      {/* Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Total Decisions" value={String(decisions.length)} />
        <MetricTile label="Critical/High" value={String(critical.length)} deltaColor={critical.length > 0 ? 'var(--red)' : undefined} />
        <MetricTile label="Human Review" value={String(dashboard?.human_review_pending ?? humanReview.length)} deltaColor={humanReview.length > 0 ? 'var(--amber)' : undefined} />
        <MetricTile label="Rotations" value={String(dashboard?.pending_rotations || 0)} />
        <MetricTile label="Draft Plans" value={String(dashboard?.draft_plans || 0)} />
        <MetricTile label="MARL Sims" value={String(dashboard?.marl_simulations || 0)} />
      </div>

      {/* Charts Row: Action Distribution + Priority Distribution */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <Card>
          <SectionHeader title="Decision Action Distribution" />
          <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 160, height: 160 }}>
              {actionLabels.length > 0 && <DoughnutChart labels={actionLabels} data={actionData} height={160} />}
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {actionLabels.map((label, i) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: ['#4a90f4', '#0ecb81', '#f6465d', '#f0b90b', '#a78bfa', '#38bdf8', '#fb923c', '#6ee7b7', '#f472b6', '#94a3b8'][i % 10] }} />
                  <span style={{ color: 'var(--text2)', flex: 1 }}>{label}</span>
                  <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{actionData[i]}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
        <Card>
          <SectionHeader title="Decisions by Priority" />
          <div style={{ padding: '12px 16px' }}>
            <BarChartJS labels={priorityLabels} data={priorityData} colors={priorityColors} height={140} />
          </div>
        </Card>
      </div>

      {/* Agent Activity Summary */}
      {(agentsSummary?.agents?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Agent Activity" count={agentsSummary!.agents.reduce((s, a) => s + a.total, 0)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginBottom: 14 }}>
            {agentsSummary!.agents.map(a => {
              const total = a.total || 1
              const buyPct = (a.buy_count / total) * 100
              const sellPct = (a.sell_count / total) * 100
              const holdPct = (a.hold_count / total) * 100
              return (
                <Card key={a.agent}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)', marginBottom: 8 }}>
                    {a.agent.replace('_agent', '').replace(/^\w/, c => c.toUpperCase())}
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{a.total}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>decisions · avg conf: {(a.avg_confidence * 100).toFixed(0)}%</div>
                  <div style={{ display: 'flex', height: 6, borderRadius: 99, overflow: 'hidden', marginBottom: 4 }}>
                    {buyPct > 0 && <div style={{ width: `${buyPct}%`, background: 'var(--green)' }} />}
                    {holdPct > 0 && <div style={{ width: `${holdPct}%`, background: 'var(--amber)' }} />}
                    {sellPct > 0 && <div style={{ width: `${sellPct}%`, background: 'var(--red)' }} />}
                    {(100 - buyPct - holdPct - sellPct) > 0 && <div style={{ width: `${100 - buyPct - holdPct - sellPct}%`, background: 'var(--bg3)' }} />}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)' }}>
                    <span style={{ color: 'var(--green)' }}>{a.buy_count} buy</span>
                    <span style={{ color: 'var(--amber)' }}>{a.hold_count} hold</span>
                    <span style={{ color: 'var(--red)' }}>{a.sell_count} sell</span>
                  </div>
                </Card>
              )
            })}
          </div>
        </>
      )}

      {/* Recent Decisions Table */}
      <Card>
        <SectionHeader title="Recent Decisions" count={recentDecisions.length} />
        <div style={{ maxHeight: 340, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'var(--sans)' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <th style={thStyle}>Symbol</th>
                <th style={thStyle}>Action</th>
                <th style={thStyle}>Priority</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Reasoning</th>
                <th style={thStyle}>Time</th>
              </tr>
            </thead>
            <tbody>
              {recentDecisions.map(d => (
                <tr key={d.decision_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ ...tdStyle, fontWeight: 700, color: 'var(--accent)' }}>{d.symbol || '—'}</td>
                  <td style={tdStyle}><ActionBadge action={d.action} /></td>
                  <td style={tdStyle}><PriorityBadge priority={d.priority} /></td>
                  <td style={{ ...tdStyle, color: 'var(--text2)' }}>{d.status}</td>
                  <td style={{ ...tdStyle, color: 'var(--text2)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.reasoning || d.rationale || '—'}</td>
                  <td style={{ ...tdStyle, color: 'var(--text3)', fontSize: 9 }}>{d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 1. IMMEDIATE DECISIONS */}
      <Card>
        <SectionHeader title="Immediate CIO Decisions" count={critical.length || undefined} />
        {critical.length === 0 && <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>No critical/high-priority decisions pending.</div>}
        <div style={{ maxHeight: 300, overflowY: 'auto' }}>
          {critical.map(d => (
            <div key={d.decision_id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <PriorityBadge priority={d.priority} />
              <span style={{ fontWeight: 700, color: 'var(--accent)', fontSize: 12, minWidth: 50 }}>{d.symbol || '—'}</span>
              <ActionBadge action={d.action} />
              <span style={{ fontSize: 10, color: 'var(--text2)', flex: 1 }}>{d.rationale?.slice(0, 80)}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{d.strategy_type}</span>
              {d.human_review_required && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 99, background: 'rgba(246,70,93,0.1)', color: 'var(--red)', fontWeight: 700 }}>REVIEW</span>}
            </div>
          ))}
        </div>
      </Card>

      {/* 2. HUMAN APPROVAL QUEUE */}
      {humanReview.length > 0 && (
        <Card>
          <SectionHeader title="Human Approval Queue" count={humanReview.length} />
          <div style={{ maxHeight: 250, overflowY: 'auto' }}>
            {humanReview.map(d => (
              <div key={d.decision_id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 12px', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                <span style={{ fontWeight: 700, color: 'var(--accent)', minWidth: 50 }}>{d.symbol || '—'}</span>
                <ActionBadge action={d.action} />
                <span style={{ color: 'var(--text2)', flex: 1 }}>{d.rationale?.slice(0, 60)}</span>
                <SafetyBadge safety={d.decision_safety} />
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>conf={d.confidence_raw?.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 3. STRATEGY ROTATION */}
      <Card>
        <SectionHeader title="Strategy Rotation" count={rotations?.rotations?.length || 0} />
        {(!rotations?.rotations?.length) && <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>No rotation recommendations. Allocation drift within targets.</div>}
        {(rotations?.rotations || []).map((r: any, i: number) => (
          <div key={i} style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
            <span style={{ color: 'var(--red)' }}>{r.source_group_id}</span> → <span style={{ color: 'var(--green)' }}>{r.target_group_id}</span>
            {' '}<span style={{ color: 'var(--text2)' }}>{r.rotation_amount_pct?.toFixed(1)}%</span>
            {' '}<span style={{ color: 'var(--text3)' }}>{r.rationale?.slice(0, 60)}</span>
          </div>
        ))}
      </Card>

      {/* 4. REBALANCE PLANNER */}
      <Card>
        <SectionHeader title="Rebalance Planner" />
        {rebalance?.plan ? (
          <>
            <div style={{ padding: '8px 12px', fontSize: 10, color: 'var(--text2)' }}>
              <b>Plan:</b> {rebalance.plan.plan_id} | {rebalance.plan.plan_summary?.slice(0, 100)} | Trade value: ${rebalance.plan.total_trade_value?.toLocaleString()}
              {rebalance.plan.human_review_required && <span style={{ color: 'var(--amber)', marginLeft: 8 }}>Human review required</span>}
            </div>
            <div style={{ maxHeight: 200, overflowY: 'auto' }}>
              {(rebalance.actions || []).slice(0, 10).map((a: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 12px', borderBottom: '1px solid var(--border-subtle)', fontSize: 9 }}>
                  <span style={{ fontWeight: 700, color: 'var(--accent)', minWidth: 50 }}>{a.symbol || 'GROUP'}</span>
                  <ActionBadge action={a.action} />
                  <span style={{ color: 'var(--text2)', flex: 1 }}>{a.reason?.slice(0, 60)}</span>
                  {a.human_review_required && <span style={{ color: 'var(--red)', fontSize: 8 }}>REVIEW</span>}
                </div>
              ))}
            </div>
          </>
        ) : (
          <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>No rebalance plans generated yet.</div>
        )}
      </Card>

      {/* 5. SIGNAL INTELLIGENCE + PORTFOLIO QA */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 2 }}>
        <Card>
          <SectionHeader title="Signal QA" />
          <div style={{ padding: 12, fontSize: 10, color: 'var(--text2)' }}>
            Clusters: {signalQA?.clusters?.length || 0} | Events: {signalQA?.latest_events?.length || 0}
          </div>
        </Card>
        <Card>
          <SectionHeader title="MARL Shadow" />
          <div style={{ padding: 12, fontSize: 10, color: 'var(--text2)' }}>
            Mode: <b style={{ color: 'var(--amber)' }}>shadow only</b>
            {marl?.latest_simulation && <> | Last sim: {JSON.stringify(marl.latest_simulation.metrics || {}).slice(0, 60)}</>}
            <br />Live policies: {marl?.live_policies || 0} | Datasets: {marl?.datasets?.length || 0}
          </div>
        </Card>
      </div>

      {/* 6. AGENT PERFORMANCE */}
      <Card>
        <SectionHeader title="Agent Performance" count={agentPerf?.history?.length || 0} />
        {(agentPerf?.history || []).length === 0 && <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>No agent performance data yet. Needs more decision outcomes.</div>}
        {(agentPerf?.history || []).map((a: any, i: number) => (
          <div key={i} style={{ display: 'flex', gap: 12, padding: '4px 12px', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
            <span style={{ fontWeight: 700, color: 'var(--accent)', minWidth: 80 }}>{a.agent}</span>
            <span>Accuracy: {a.accuracy_pct}%</span>
            <span>Recs: {a.total_recommendations}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

function PriorityBadge({ priority }: { priority: string }) {
  const c = priority === 'critical' ? 'var(--red)' : priority === 'high' ? 'var(--amber)' : priority === 'medium' ? 'var(--accent)' : 'var(--text3)'
  return <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 99, background: `color-mix(in srgb, ${c} 12%, transparent)`, color: c, textTransform: 'uppercase' }}>{priority}</span>
}

function ActionBadge({ action }: { action: string }) {
  const colors: Record<string, string> = {
    HOLD: 'var(--text2)', ADD_REVIEW: 'var(--green)', TRIM_REVIEW: 'var(--red)',
    ROTATION_REVIEW: 'var(--accent)', REBALANCE_REVIEW: 'var(--accent)',
    HUMAN_REVIEW: 'var(--amber)', BLOCKED: 'var(--red)', ROTATION: 'var(--purple)',
    BUY: 'var(--green)', SELL: 'var(--red)', TRIM: 'var(--red)',
  }
  const c = colors[action] || 'var(--text2)'
  return <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 99, background: `color-mix(in srgb, ${c} 10%, transparent)`, color: c }}>{action}</span>
}

function SafetyBadge({ safety }: { safety: string }) {
  const c = safety === 'safe' ? 'var(--green)' : safety === 'review' ? 'var(--amber)' : 'var(--red)'
  return <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 99, background: `color-mix(in srgb, ${c} 10%, transparent)`, color: c, textTransform: 'uppercase' }}>{safety}</span>
}

const btnStyle: React.CSSProperties = { padding: '4px 12px', fontSize: 10, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontWeight: 600, fontSize: 9, textTransform: 'uppercase', letterSpacing: '.04em' }
const tdStyle: React.CSSProperties = { padding: '6px 8px', color: 'var(--text1)' }
