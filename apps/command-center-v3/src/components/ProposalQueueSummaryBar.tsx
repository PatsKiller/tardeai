import { desk } from '../lib/proposalDeskTheme'
import { fmtDeskTimestamp } from '../lib/fmtTimestamp'

const MUTED = desk.textDim
const TEXT0 = desk.text
const AMBER = desk.amber
const RED = desk.red

type Summary = {
  total?: number
  route_ready?: number
  blocked?: number
  agent_pending?: number
  oversized?: number
  invalid_thesis?: number
  agent_backlog?: Record<string, number>
  blocker_counts?: Record<string, number>
  route_ready_pct?: number
  generated_at?: string
}

export default function ProposalQueueSummaryBar({
  summary,
  onQueueAgents,
  onReconcile,
  onMatureLlm,
  agentBusy,
  reconcileBusy,
  llmBusy,
}: {
  summary?: Summary | null
  onQueueAgents?: () => void
  onReconcile?: () => void
  onMatureLlm?: () => void
  agentBusy?: boolean
  reconcileBusy?: boolean
  llmBusy?: boolean
}) {
  if (!summary?.total) return null
  const ready = summary.route_ready ?? 0
  const blocked = summary.blocked ?? 0
  const agentPending = summary.agent_pending ?? 0
  const stephN = summary.agent_backlog?.steph ?? 0
  const pct = summary.route_ready_pct ?? (summary.total ? Math.round((ready / summary.total) * 100) : 0)
  const metric = (label: string, value: number | string, accent?: string) => (
    <span key={label} style={{
      display: 'inline-flex', gap: 6, alignItems: 'baseline', padding: '4px 10px', borderRadius: desk.radius,
      background: desk.bgInset, border: `1px solid ${desk.borderSubtle}`,
    }}>
      <span style={{ fontSize: 9, fontWeight: 700, color: MUTED, textTransform: 'uppercase', letterSpacing: '.35px' }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 800, fontFamily: desk.mono, color: accent || TEXT0 }}>{value}</span>
    </span>
  )
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12,
      padding: '10px 12px', borderRadius: desk.radiusLg, border: `1px solid ${desk.border}`, background: desk.bg }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: TEXT0 }}>Queue health</span>
      {metric('Route-ready', `${pct}%`, pct > 0 ? TEXT0 : MUTED)}
      {metric('Ready', ready)}
      {metric('Blocked', blocked, blocked > 0 ? RED : MUTED)}
      {agentPending > 0 && metric('Agent pending', agentPending)}
      {(summary.oversized ?? 0) > 0 && metric('Oversized', summary.oversized!, AMBER)}
      {(summary.invalid_thesis ?? 0) > 0 && metric('Invalid thesis', summary.invalid_thesis!, RED)}
      <span style={{ flex: 1 }} />
      {stephN > 0 && onQueueAgents && (
        <button onClick={onQueueAgents} disabled={agentBusy}
          style={{ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: agentBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${desk.border}`, background: desk.bgInset, color: desk.text }}>
          {agentBusy ? '…' : `Queue steph (${stephN})`}
        </button>
      )}
      {onReconcile && (
        <button onClick={onReconcile} disabled={reconcileBusy}
          style={{ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: reconcileBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${desk.border}`, background: desk.bgInset, color: desk.text }}>
          {reconcileBusy ? '…' : 'Reconcile sleeves'}
        </button>
      )}
      {onMatureLlm && (
        <button onClick={onMatureLlm} disabled={llmBusy}
          style={{ fontSize: 10, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: llmBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${desk.border}`, background: desk.bgInset, color: desk.text }}>
          {llmBusy ? '…' : 'LLM stage 2b'}
        </button>
      )}
      <span style={{ fontSize: 9, color: MUTED, width: '100%', lineHeight: 1.45 }}>
        {summary.total} active · {ready === 0 && blocked > 0
          ? '0% route-ready — resolve diligence blockers (agents, trade plan, sizing) or bulk reject stale rows'
          : `${pct}% pass live-route gates (Litmus + diligence + sizing)`}
        {summary.generated_at && (
          <span style={{ fontFamily: desk.mono, marginLeft: 8 }}>
            · computed {fmtDeskTimestamp(summary.generated_at)}
          </span>
        )}
      </span>
    </div>
  )
}