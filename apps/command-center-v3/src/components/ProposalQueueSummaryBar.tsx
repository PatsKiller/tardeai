const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const BLUE = '#60a5fa'

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
  const chip = (label: string, n: number, color: string) => (
    <span key={label} style={{ fontSize: 10, fontWeight: 800, padding: '4px 9px', borderRadius: 6,
      border: `1px solid ${color}44`, background: `${color}14`, color }}>
      {label}: <b>{n}</b>
    </span>
  )
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12,
      padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg1)' }}>
      <span style={{ fontSize: 11, fontWeight: 800, color: TEXT0 }}>Queue health</span>
      {chip('Route-ready', ready, GREEN)}
      {chip('Blocked', blocked, blocked > 0 && ready === 0 ? RED : AMBER)}
      {agentPending > 0 && chip('Agent pending', agentPending, BLUE)}
      {(summary.oversized ?? 0) > 0 && chip('Oversized', summary.oversized!, AMBER)}
      {(summary.invalid_thesis ?? 0) > 0 && chip('Invalid thesis', summary.invalid_thesis!, RED)}
      <span style={{ flex: 1 }} />
      {stephN > 0 && onQueueAgents && (
        <button onClick={onQueueAgents} disabled={agentBusy}
          style={{ fontSize: 10, fontWeight: 800, padding: '5px 10px', borderRadius: 6, cursor: agentBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>
          {agentBusy ? '…' : `Queue steph (${stephN})`}
        </button>
      )}
      {onReconcile && (
        <button onClick={onReconcile} disabled={reconcileBusy}
          style={{ fontSize: 10, fontWeight: 800, padding: '5px 10px', borderRadius: 6, cursor: reconcileBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${AMBER}`, background: `${AMBER}18`, color: AMBER }}>
          {reconcileBusy ? '…' : 'Reconcile sleeves'}
        </button>
      )}
      {onMatureLlm && (
        <button onClick={onMatureLlm} disabled={llmBusy}
          style={{ fontSize: 10, fontWeight: 800, padding: '5px 10px', borderRadius: 6, cursor: llmBusy ? 'not-allowed' : 'pointer',
            border: `1px solid ${GREEN}`, background: `${GREEN}18`, color: GREEN }}>
          {llmBusy ? '…' : 'LLM stage 2b'}
        </button>
      )}
      <span style={{ fontSize: 9, color: MUTED, width: '100%' }}>
        {summary.total} active · {ready === 0 && blocked > 0 ? '0% route-ready — resolve blockers or bulk reject stale rows' : `${summary.route_ready_pct ?? 0}% route-ready`}
      </span>
    </div>
  )
}