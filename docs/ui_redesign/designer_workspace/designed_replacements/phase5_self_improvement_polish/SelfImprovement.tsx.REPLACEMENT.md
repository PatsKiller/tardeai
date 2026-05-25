# SelfImprovement.tsx -- Phase 5 Polish Replacement

**Original hash:** `fc411dfaa7f87fbbaf82f89cb6476cbe79d19d4aa9213c68e4eb90adc44e4831`
**Original location:** `apps/command-center-v2/src/pages/SelfImprovement.tsx`
**Original lines:** 173

---

## Full replacement file

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'

/* ── status-to-StatusBadge mapping for component health ── */
const healthStatusMap: Record<string, string> = {
  healthy: 'fresh',
  warning: 'warning',
  degraded: 'stale',
  failed: 'blocked',
  unknown: 'unknown',
}

/* ── severity mapping for review-queue items ── */
const queueSeverityMap: Record<string, string> = {
  urgent: 'critical',
  important: 'high',
  normal: 'medium',
  info: 'info',
}

/* ── overview card config: [label, accessor, badgeCondition, route, statusHint] ── */
type OverviewDef = {
  label: string
  value: any
  badge: string
  route: string
  status: string
}

export default function SelfImprovement() {
  const navigate = useNavigate()
  const [rk, setRk] = useState(0)
  const { data: status } = useApi<any>(`/api/v2/self-improvement/status?_r=${rk}`)
  const { data: queue } = useApi<any>(`/api/v2/self-improvement/review-queue?_r=${rk}`)
  const { data: health } = useApi<any>(`/api/v2/self-improvement/component-health?_r=${rk}`)

  const s = status || {}
  const safety = s.safety || {}
  const paper = s.paper_trading || {}
  const learning = s.learning || {}
  const agents = s.agent_calibration || {}
  const bt = s.backtesting || {}
  const pipe = s.pipeline || {}
  const warnings = s.warnings || []
  const actions = s.recommended_actions || []
  const queueItems = (Array.isArray(queue) ? queue : queue?.items || queue?.data || []) as any[]
  const components = (Array.isArray(health) ? health : health?.components || health?.data || []) as any[]

  /* ── overview cards ── */
  const overviewCards: OverviewDef[] = [
    { label: 'Paper Closed', value: paper.closed, badge: paper.low_sample ? 'LOW SAMPLE' : '', route: '/paper-journal', status: paper.low_sample ? 'warning' : 'fresh' },
    { label: 'Paper Open', value: paper.open, badge: '', route: '/paper-status', status: 'fresh' },
    { label: 'Pending Proposals', value: paper.pending_proposals, badge: '', route: '/paper-proposals', status: (paper.pending_proposals || 0) > 0 ? 'waiting' : 'fresh' },
    { label: 'Learning Recs', value: learning.recommendations_pending, badge: (learning.recommendations_pending || 0) > 0 ? 'REVIEW' : '', route: '/governance?tab=learning', status: (learning.recommendations_pending || 0) > 0 ? 'warning' : 'fresh' },
    { label: 'Config Proposals', value: learning.config_proposals_pending, badge: (learning.config_proposals_pending || 0) > 0 ? 'APPROVAL' : '', route: '/governance?tab=learning', status: (learning.config_proposals_pending || 0) > 0 ? 'warning' : 'fresh' },
    { label: 'Agent Recs', value: agents.recommendations, badge: '', route: '/agent-calibration', status: 'fresh' },
    { label: 'Backtest Runs', value: bt.runs, badge: '', route: '/backtesting', status: 'fresh' },
    { label: 'Pipeline Fails', value: pipe.failures, badge: (pipe.failures || 0) > 0 ? 'CHECK' : '', route: '/pipeline', status: (pipe.failures || 0) > 0 ? 'blocked' : 'fresh' },
    { label: 'Warnings', value: warnings.length, badge: '', route: '', status: warnings.length > 0 ? 'warning' : 'fresh' },
  ]

  /* ── component health route map ── */
  const healthRoutes: Record<string, string> = {
    'agent_calibration': '/agent-calibration',
    'agent-calibration': '/agent-calibration',
    'backtesting': '/backtesting',
    'execution_revalidation': '/paper-status',
    'execution-revalidation': '/paper-status',
    'ingestion_sources': '/intelligence',
    'ingestion-sources': '/intelligence',
    'learning_governance': '/governance?tab=learning',
    'learning-governance': '/governance?tab=learning',
    'paper_trading': '/paper-journal',
    'paper-trading': '/paper-journal',
    'pipeline_controller': '/pipeline',
    'pipeline-controller': '/pipeline',
    'safety_gate': '/risk',
    'safety-gate': '/risk',
    'weekly_digest': '/weekly-learning',
    'weekly-digest': '/weekly-learning',
  }

  /* ── warning route inference ── */
  const warningRoute = (msg: string): string => {
    if (msg.includes('closed trades')) return '/paper-journal'
    if (msg.includes('recommendation')) return '/governance?tab=learning'
    if (msg.includes('material change') || msg.includes('reapproval')) return '/paper-proposals'
    if (msg.includes('pipeline')) return '/pipeline'
    if (msg.includes('stop')) return '/risk'
    return ''
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200 }}>
      <PageHeader
        title="Self-Improvement Center"
        subtitle="Learning loops, calibration health, improvement backlog, and evidence that the system is getting better"
        actions={
          <ActionButton variant="secondary" size="sm" onClick={() => setRk(k => k + 1)}>
            Refresh
          </ActionButton>
        }
      />

      {/* ── Safety Banner ── */}
      <div style={{
        padding: '10px 16px', marginBottom: 14, borderRadius: 6,
        background: safety.allowed ? 'rgba(246,70,93,.15)' : 'rgba(14,203,129,.08)',
        border: `1px solid ${safety.allowed ? '#f6465d' : '#0ecb81'}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <span style={{ fontSize: 14, fontWeight: 700, color: safety.allowed ? '#f6465d' : '#0ecb81' }}>
            {safety.allowed ? 'LIVE TRADING ALLOWED -- DANGER' : 'PAPER MODE ACTIVE -- BLOCKED'}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text2)', marginLeft: 12 }}>
            Holdings: ${(safety.holdings_value || 0).toLocaleString()} | Guard:{' '}
            <StatusBadge status={safety.holdings_guard ? 'complete' : 'blocked'} label={safety.holdings_guard ? 'PASS' : 'FAIL'} />
          </span>
        </div>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>
          {(safety.blocked_reasons || []).length} block reasons
        </span>
      </div>

      {/* ── Overview Cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: 8, marginBottom: 14 }}>
        {overviewCards.map((card) => (
          <StateCard
            key={card.label}
            title={card.label}
            value={card.value ?? 0}
            description={card.badge || undefined}
            status={card.status}
            actionLabel={card.route ? 'View' : undefined}
            onClick={card.route ? () => navigate(card.route) : undefined}
            compact
          />
        ))}
      </div>

      {/* ── Cross-link Navigation ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <ActionButton variant="ghost" size="sm" onClick={() => navigate('/agent-calibration')}>
          Agent Calibration
        </ActionButton>
        <ActionButton variant="ghost" size="sm" onClick={() => navigate('/weekly-learning')}>
          Weekly Learning
        </ActionButton>
        <ActionButton variant="ghost" size="sm" onClick={() => navigate('/ops')}>
          Automation Trust
        </ActionButton>
      </div>

      {/* ── Operator Review Queue ── */}
      {queueItems.length > 0 ? (
        <Card title={`Operator Review Queue (${queueItems.length})`} style={{ marginBottom: 14 }}>
          {queueItems.map((q: any) => (
            <div key={q.review_item_id} style={{
              padding: '6px 0', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <SeverityBadge severity={queueSeverityMap[q.severity] || q.severity || 'info'} />
                <span style={{ fontSize: 11 }}>{q.title}</span>
                {q.requires_action && (
                  <StatusBadge status="warning" label="ACTION" size="sm" />
                )}
              </div>
              {q.linked_dashboard_route && (
                <ActionButton variant="ghost" size="sm" onClick={() => navigate(q.linked_dashboard_route)}>
                  {q.source_domain}
                </ActionButton>
              )}
            </div>
          ))}
        </Card>
      ) : (
        <Card title="Operator Review Queue" style={{ marginBottom: 14 }}>
          <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12, textAlign: 'center' }}>
            No items require operator review. The queue is clear.
          </div>
        </Card>
      )}

      {/* ── Component Health ── */}
      <Card title="Component Health" style={{ marginBottom: 14 }}>
        {components.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px,1fr))', gap: 6 }}>
            {components.map((c: any) => {
              const route = healthRoutes[c.component_key] || ''
              const mappedStatus = healthStatusMap[c.status] || c.status || 'unknown'
              return (
                <div key={c.component_key}
                  onClick={route ? () => navigate(route) : undefined}
                  style={{
                    padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 4,
                    fontSize: 11, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    cursor: route ? 'pointer' : 'default', transition: 'background 120ms',
                  }}
                  onMouseEnter={route ? (e) => { e.currentTarget.style.background = 'var(--bg3)' } : undefined}
                  onMouseLeave={route ? (e) => { e.currentTarget.style.background = '' } : undefined}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {c.component_name}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <StatusBadge status={mappedStatus} label={c.status} />
                    {route && <span style={{ fontSize: 9, color: 'var(--accent)' }}>&rarr;</span>}
                  </span>
                </div>
              )
            })}
          </div>
        ) : (
          <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12, textAlign: 'center' }}>
            Run the health snapshot first to populate component status.
          </div>
        )}
      </Card>

      {/* ── Subsystem Dashboards ── */}
      <Card title="Subsystem Dashboards" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {[
            ['/governance?tab=learning', 'Learning Governance'],
            ['/agent-calibration', 'Agent Calibration'],
            ['/weekly-learning', 'Weekly Learning'],
            ['/backtesting', 'Backtesting'],
            ['/paper-journal', 'Paper Trade Intelligence'],
            ['/pipeline', 'Pipeline Controller'],
            ['/paper-proposals', 'Trade Proposals'],
            ['/risk', 'Risk Management'],
          ].map(([route, label]) => (
            <ActionButton key={route} variant="secondary" size="sm" onClick={() => navigate(route)} style={{ fontWeight: 600 }}>
              {label} &rarr;
            </ActionButton>
          ))}
        </div>
      </Card>

      {/* ── Warnings ── */}
      {warnings.length > 0 ? (
        <Card title={`Warnings (${warnings.length})`}>
          {warnings.map((w: any, i: number) => {
            const msg = w.msg || ''
            const route = warningRoute(msg)
            return (
              <div key={i}
                onClick={route ? () => navigate(route) : undefined}
                style={{
                  fontSize: 11, padding: '6px 0', borderBottom: '1px solid var(--border)',
                  cursor: route ? 'pointer' : 'default', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}
                onMouseEnter={route ? (e) => { e.currentTarget.style.background = 'var(--bg3)' } : undefined}
                onMouseLeave={route ? (e) => { e.currentTarget.style.background = '' } : undefined}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <StatusBadge status={w.type === 'low_sample' ? 'unknown' : 'warning'} label={w.type === 'low_sample' ? 'info' : 'warn'} />
                  {msg}
                </span>
                {route && (
                  <span style={{ fontSize: 9, color: 'var(--accent)' }}>View &rarr;</span>
                )}
              </div>
            )
          })}
        </Card>
      ) : warnings.length === 0 && status && (
        <Card title="Warnings">
          <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12, textAlign: 'center' }}>
            No active warnings. All subsystems operating normally.
          </div>
        </Card>
      )}
    </div>
  )
}
```
