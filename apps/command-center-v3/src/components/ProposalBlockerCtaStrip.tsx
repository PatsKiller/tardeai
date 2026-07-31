/**
 * Proposals desk — blocker-first CTA strip (quality plan W5).
 * One primary next step per wall: oversight · sizing · thesis · route-ready.
 */
import type { CSSProperties } from 'react'
import { desk } from '../lib/proposalDeskTheme'
import { fmtDeskTimestamp } from '../lib/fmtTimestamp'

export type ProposalCta = {
  id: string
  label: string
  count?: number
  action?: string
  proposal_ids?: number[]
  tone?: string
  href?: string
}

export type QueueSummary = {
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
  ctas?: ProposalCta[]
  primary_cta?: ProposalCta | null
  oversized_ids?: number[]
  oversight_ids?: number[]
  ready_ids?: number[]
  thesis_ids?: number[]
}

type Props = {
  summary?: QueueSummary | null
  busy?: boolean
  focusBlocker?: string | null
  onFocusBlocker?: (blocker: string | null) => void
  /** Generic agent batch (all agents) */
  onQueueAgents?: () => void
  /** One-click: steph only on oversight proposal IDs */
  onQueueSteph?: (ids: number[]) => void
  onResizeIds?: (ids: number[]) => void
  onRejectIds?: (ids: number[], reason: string) => void
  onFocusIds?: (ids: number[], label: string) => void
  onOpenAgents?: () => void
  /** Entry vs Protection lane chips */
  queueKind?: 'broker' | 'proposal' | 'protection' | 'all'
  entryCount?: number | null
  protectionCount?: number | null
  onQueueKind?: (kind: 'broker' | 'proposal' | 'protection' | 'all') => void
  /** Live toast from last steph/agent action */
  toast?: string | null
}

const toneColor = (t?: string) => {
  if (t === 'green') return desk.green
  if (t === 'amber') return desk.amber
  if (t === 'red') return desk.red
  if (t === 'blue') return desk.blue
  return desk.text
}

const chip = (active: boolean, color: string): CSSProperties => ({
  fontSize: 11,
  fontWeight: 800,
  padding: '7px 12px',
  borderRadius: 8,
  cursor: 'pointer',
  border: `1px solid ${active ? color : desk.border}`,
  background: active ? `${color}18` : desk.bgInset,
  color: active ? color : desk.text,
  whiteSpace: 'nowrap',
})

export default function ProposalBlockerCtaStrip({
  summary,
  busy,
  focusBlocker,
  onFocusBlocker,
  onQueueAgents,
  onQueueSteph,
  onResizeIds,
  onRejectIds,
  onFocusIds,
  onOpenAgents,
  queueKind = 'broker',
  entryCount,
  protectionCount,
  onQueueKind,
  toast,
}: Props) {
  if (!summary || !(summary.total || summary.blocked || summary.route_ready)) return null

  const ready = summary.route_ready ?? 0
  const blocked = summary.blocked ?? 0
  const pct = summary.route_ready_pct ?? 0
  const bc = summary.blocker_counts || {}
  const backlog = summary.agent_backlog || {}
  const stephN = backlog.steph ?? 0
  const oversightIds = summary.oversight_ids || []
  const ctas = summary.ctas?.length
    ? summary.ctas
    : _fallbackCtas(summary)

  const runCta = (c: ProposalCta) => {
    const ids = c.proposal_ids || []
    if (c.action === 'queue_steph') {
      onFocusBlocker?.('oversight')
      onQueueSteph?.(ids.length ? ids : oversightIds)
      if (ids.length || oversightIds.length) onFocusIds?.(ids.length ? ids : oversightIds, 'steph')
      return
    }
    if (c.action === 'queue_agents') {
      onFocusBlocker?.('oversight')
      onQueueAgents?.()
      if (ids.length) onFocusIds?.(ids, 'oversight')
      return
    }
    if (c.action === 'resize_to_cap') {
      onFocusBlocker?.('sizing')
      if (ids.length) onResizeIds?.(ids)
      else onFocusIds?.(summary.oversized_ids || [], 'sizing')
      return
    }
    if (c.action === 'reject_invalid_thesis') {
      onFocusBlocker?.('thesis')
      if (ids.length) onRejectIds?.(ids, 'invalid_thesis_bulk')
      return
    }
    if (c.action === 'filter_ready') {
      onFocusBlocker?.('ready')
      onFocusIds?.(ids.length ? ids : (summary.ready_ids || []), 'route-ready')
      return
    }
    if (c.action === 'focus_blocked') {
      onFocusBlocker?.('blocked')
      onFocusIds?.(ids, 'blocked')
      return
    }
    if (c.href && onOpenAgents) onOpenAgents()
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        marginBottom: 12,
        padding: '12px 14px',
        borderRadius: desk.radiusLg,
        border: `1px solid ${ready === 0 && blocked > 0 ? `${desk.amber}66` : desk.border}`,
        background: ready === 0 && blocked > 0 ? desk.amberDim : desk.bg,
      }}
      role="region"
      aria-label="Proposal blockers and next actions"
    >
      {/* Entry vs Protection — keep protection from crowding entry CTAs */}
      {onQueueKind && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, fontWeight: 800, color: desk.textMuted, textTransform: 'uppercase', letterSpacing: '.4px' }}>
            Queue lane
          </span>
          <button type="button" style={chip(queueKind === 'broker' || queueKind === 'proposal', desk.green)} onClick={() => onQueueKind('proposal')} title="Entry proposals only (excludes protection rows)">
            Entry{entryCount != null ? ` ${entryCount}` : ''}
          </button>
          <button type="button" style={chip(queueKind === 'protection', desk.amber)} onClick={() => onQueueKind('protection')} title="Protective-stop / stop-management proposals only">
            Protection{protectionCount != null ? ` ${protectionCount}` : ''}
          </button>
          <button type="button" style={chip(queueKind === 'all', desk.textMuted)} onClick={() => onQueueKind('all')} title="Entry + protection mixed">
            All
          </button>
          <span style={{ fontSize: 11, color: desk.textDim }}>
            {queueKind === 'protection'
              ? 'Protection rows do not compete with entry route CTAs'
              : 'Entry is the default for Clear oversight / Fix size'}
          </span>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 12, fontWeight: 800, color: desk.text }}>
          Proposals · next action
        </span>
        <span style={{ fontSize: 11, fontFamily: desk.mono, color: ready > 0 ? desk.green : desk.red, fontWeight: 800 }}>
          {pct}% route-ready · {ready} ready · {blocked} blocked
        </span>
        {(summary.oversized ?? 0) > 0 && (
          <button type="button" style={chip(focusBlocker === 'sizing', desk.amber)} onClick={() => onFocusBlocker?.(focusBlocker === 'sizing' ? null : 'sizing')}>
            {summary.oversized} oversized
          </button>
        )}
        {(bc.oversight ?? 0) > 0 && (
          <button type="button" style={chip(focusBlocker === 'oversight', desk.amber)} onClick={() => onFocusBlocker?.(focusBlocker === 'oversight' ? null : 'oversight')}>
            {bc.oversight} oversight
          </button>
        )}
        {(bc.sizing ?? 0) > 0 && (
          <button type="button" style={chip(focusBlocker === 'sizing', desk.blue)} onClick={() => onFocusBlocker?.(focusBlocker === 'sizing' ? null : 'sizing')}>
            {bc.sizing} sizing
          </button>
        )}
        {(summary.invalid_thesis ?? 0) > 0 && (
          <button type="button" style={chip(focusBlocker === 'thesis', desk.red)} onClick={() => onFocusBlocker?.(focusBlocker === 'thesis' ? null : 'thesis')}>
            {summary.invalid_thesis} bad thesis
          </button>
        )}
        <span style={{ flex: 1 }} />
        {summary.generated_at && (
          <span style={{ fontSize: 10, color: desk.textDim, fontFamily: desk.mono }}>
            as of {fmtDeskTimestamp(summary.generated_at)}
          </span>
        )}
      </div>

      {Object.keys(backlog).length > 0 && (
        <div style={{ fontSize: 11, color: desk.textMuted }}>
          Agent backlog:{' '}
          {Object.entries(backlog).map(([k, n]) => `${k} ${n}`).join(' · ')}
          {' · '}
          <button
            type="button"
            onClick={() => onOpenAgents?.()}
            style={{ background: 'none', border: 'none', color: desk.blue, fontWeight: 700, cursor: 'pointer', padding: 0, fontSize: 11 }}
          >
            Open Agents →
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {/* Primary one-click: steph on oversight IDs (also emitted as server CTA queue_steph) */}
        {(stephN > 0 || oversightIds.length > 0) && onQueueSteph && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              onFocusBlocker?.('oversight')
              onQueueSteph(oversightIds)
              if (oversightIds.length) onFocusIds?.(oversightIds, 'steph')
            }}
            style={{
              ...chip(true, desk.amber),
              opacity: busy ? 0.6 : 1,
              cursor: busy ? 'not-allowed' : 'pointer',
              minWidth: 140,
            }}
            title="Queue Steph only on oversight-blocked proposal IDs"
          >
            Queue steph ({stephN || oversightIds.length}) →
          </button>
        )}
        {ctas.filter(c => c.id !== 'queue_steph').map(c => {
          // queue_steph rendered above as primary; avoid duplicate button
          const color = toneColor(c.tone)
          return (
            <button
              key={c.id}
              type="button"
              disabled={busy}
              onClick={() => runCta(c)}
              style={{
                ...chip(true, color),
                opacity: busy ? 0.6 : 1,
                cursor: busy ? 'not-allowed' : 'pointer',
                minWidth: 120,
              }}
              title={`${c.label}${c.count != null ? ` (${c.count})` : ''}`}
            >
              {c.label}{c.count != null ? ` (${c.count})` : ''} →
            </button>
          )
        })}
        {focusBlocker && (
          <button type="button" style={chip(false, desk.textDim)} onClick={() => onFocusBlocker?.(null)}>
            Clear focus
          </button>
        )}
      </div>

      {toast && (
        <div
          role="status"
          aria-live="polite"
          style={{
            fontSize: 11,
            fontWeight: 700,
            padding: '8px 10px',
            borderRadius: 8,
            border: `1px solid ${toast.startsWith('✅') || toast.startsWith('Queued') ? desk.green : desk.amber}`,
            background: toast.startsWith('✅') || toast.startsWith('Queued') ? desk.greenDim : desk.amberDim,
            color: toast.startsWith('✅') || toast.startsWith('Queued') ? desk.green : desk.amber,
          }}
        >
          {toast}
        </div>
      )}

      <div style={{ fontSize: 11, color: desk.textDim, lineHeight: 1.45 }}>
        {ready === 0 && blocked > 0
          ? 'Nothing is route-ready. Queue steph on oversight IDs, or Fix size first — 2FA still required for live route.'
          : 'CTAs act on the blocked subset only. Live capital still needs per-order 2FA.'}
      </div>
    </div>
  )
}

function _fallbackCtas(summary: QueueSummary): ProposalCta[] {
  const out: ProposalCta[] = []
  if ((summary.agent_pending ?? 0) > 0 || (summary.blocker_counts?.oversight ?? 0) > 0) {
    out.push({
      id: 'clear_oversight',
      label: 'Clear oversight',
      count: summary.agent_pending || summary.blocker_counts?.oversight,
      action: 'queue_agents',
      proposal_ids: summary.oversight_ids,
      tone: 'amber',
    })
  }
  if ((summary.oversized ?? 0) > 0) {
    out.push({
      id: 'fix_size',
      label: 'Fix size → cap',
      count: summary.oversized,
      action: 'resize_to_cap',
      proposal_ids: summary.oversized_ids,
      tone: 'blue',
    })
  }
  if ((summary.invalid_thesis ?? 0) > 0) {
    out.push({
      id: 'reject_thesis',
      label: 'Reject bad thesis',
      count: summary.invalid_thesis,
      action: 'reject_invalid_thesis',
      proposal_ids: summary.thesis_ids,
      tone: 'red',
    })
  }
  if ((summary.route_ready ?? 0) > 0) {
    out.push({
      id: 'route_ready',
      label: 'Review route-ready',
      count: summary.route_ready,
      action: 'filter_ready',
      proposal_ids: summary.ready_ids,
      tone: 'green',
    })
  }
  return out
}
