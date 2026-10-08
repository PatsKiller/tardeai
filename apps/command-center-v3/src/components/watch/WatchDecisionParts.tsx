/** Watch decision standards — board, badges and filter modal (operator 2026-10-07).
 *  Same vocabulary as the Communications hub: category, priority, five scores, TTL / expiry, status, actionability.
 *  Data: card.decision and body.decision_board from /api/v3/data-broker/watch-intelligence
 *  (scripts/lib/data_broker/watch_decision.py, config/watch_decision_standards.yaml). */
import { BigNumberCard, type Family } from '../decision/DecisionParts'
import { useEffect, useState } from 'react'
import { RADIUS, TOKENS } from '../../lib/designTokens'
import {
  Badge, CATEGORY_COLOR, Chips, LEVELS, PRIORITY_COLOR, REENTRY_COLOR, ScoreBar, labelOf, tint, ttlLabel,
} from '../comms/CommsHubParts'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const BORDER = 'var(--border)'
const MONO = "'JetBrains Mono', ui-monospace, Consolas, monospace"

export type WatchDecision = {
  category?: string
  category_label?: string
  priority?: string
  priority_score?: number
  confidence?: number
  confidence_source?: string
  risk_score?: number
  reward_score?: number
  time_sensitivity?: number
  reentry_status?: string | null
  actionable?: boolean
  action_hint?: string | null
  status?: string
  held?: boolean
  ttl_hours?: number
  evidence_at?: string | null
  expires_at?: string | null
  ttl_remaining_s?: number | null
  rule_id?: string
}

export const STATUS_COLOR: Record<string, string> = {
  active: TOKENS.success, needs_data: TOKENS.warning, expired: TOKENS.neutral, invalidated: TOKENS.danger,
}
const STATUS_LABEL: Record<string, string> = {
  active: 'Active', needs_data: 'Needs fresh analysis', expired: 'Signal expired', invalidated: 'Invalidated',
}

/** The decision filter keys this page sends to the projection. */
export const DECISION_KEYS = ['category', 'priority', 'decision_status', 'reentry_status', 'min_confidence', 'min_risk',
  'max_risk', 'min_reward', 'min_time', 'actionable', 'expiring_within_h', 'include_expired']

export const DECISION_SORTS: [string, string][] = [
  ['priority_score', 'Sort: priority'], ['confidence', 'Sort: confidence'], ['risk_score', 'Sort: risk'],
  ['reward_score', 'Sort: reward'], ['time_sensitivity', 'Sort: time sensitivity'], ['expires_at', 'Sort: expiring first'],
]

function expiryText(d: WatchDecision) {
  if (d.status === 'active') return ttlLabel(d.ttl_remaining_s)
  if (d.status === 'expired') return d.held ? 'signal expired — review' : 'signal expired'
  if (d.status === 'needs_data') return 'no fresh plan / synthesis / review'
  return ''
}

/** One line of decision badges + score bars + TTL — sits inside the existing card's chip row (no layout change). */
export function WatchDecisionBadges({ d }: { d?: WatchDecision | null }) {
  if (!d) return null
  const when = d.expires_at ? new Date(d.expires_at).toLocaleString() : null
  return (
    <span data-watch-decision data-decision-category={d.category || ''} data-decision-priority={d.priority || ''}
      data-decision-status={d.status || ''} data-decision-actionable={String(!!d.actionable)}
      style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
      {d.priority && <Badge text={d.priority.toUpperCase()} color={PRIORITY_COLOR[d.priority] || MUTED} title={`priority score ${d.priority_score ?? '—'} · rule ${d.rule_id || '—'}`} />}
      {d.category && <Badge text={d.category_label || labelOf(d.category)} color={CATEGORY_COLOR[d.category] || MUTED} />}
      {d.reentry_status && <Badge text={`Re-entry: ${d.reentry_status}`} color={REENTRY_COLOR[d.reentry_status] || MUTED} />}
      {d.status && <Badge text={STATUS_LABEL[d.status] || labelOf(d.status)} color={STATUS_COLOR[d.status] || MUTED}
        title={d.evidence_at ? `evidence ${new Date(d.evidence_at).toLocaleString()}${when ? ` · expires ${when}` : ''}` : 'no evidence inside the freshness window'} />}
      {d.actionable && <Badge text={d.action_hint ? `▶ ${d.action_hint}` : '▶ Actionable'} color={TOKENS.success} />}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 1 }} title="confidence · risk · reward · time sensitivity">
        <ScoreBar v={d.confidence} color={TOKENS.info} title={`confidence (${d.confidence_source || '—'})`} />
        <ScoreBar v={d.risk_score} color={TOKENS.danger} title="risk" />
        <ScoreBar v={d.reward_score} color={TOKENS.success} title="reward" />
        <ScoreBar v={d.time_sensitivity} color={TOKENS.warning} title="time sensitivity" />
      </span>
      <span style={{ fontSize: 10, color: MUTED }}>{expiryText(d)}</span>
    </span>
  )
}

// ── Board ───────────────────────────────────────────────────────────────────

const PANEL_PRESET: Record<string, Record<string, string>> = {
  attention: { view: 'all', actionable: '1', sort: 'priority_score' },
  reward: { view: 'all', min_reward: '0.5', sort: 'reward_score' },
  reentry: { view: 'all', category: 're_entry', reentry_status: 'confirmed,potential', sort: 'priority_score' },
  risk: { view: 'all', min_risk: '0.6', sort: 'risk_score' },
  expiring: { view: 'all', expiring_within_h: '24', sort: 'expires_at' },
  recent: { view: 'all', actionable: '1', sort: 'time_sensitivity' },
}
const PANEL_ORDER = ['attention', 'reward', 'reentry', 'risk', 'expiring', 'recent']
const BOARD_LOOK: Record<string, { icon: string; label: string; family: Family }> = {
  attention: { icon: '🚨', label: 'Needs attention', family: 'critical' },
  reward: { icon: '🟢', label: 'Highest reward', family: 'opportunity' },
  reentry: { icon: '↩️', label: 'Re-entry', family: 'opportunity' },
  risk: { icon: '🔴', label: 'Highest risk', family: 'high' },
  expiring: { icon: '⏳', label: 'Expiring soon', family: 'medium' },
  recent: { icon: '⚡', label: 'Recently actionable', family: 'medium' },
}

export function WatchDecisionBoard({ board, onPreset, onOpen }: {
  board: any; onPreset: (preset: Record<string, string>) => void; onOpen: (symbol: string) => void
}) {
  if (!board?.panels) return null
  const st = board.facets?.status || {}
  return (
    <div data-watch-decision-board style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: MUTED, marginBottom: 6 }}>
        <b style={{ color: TEXT }}>{board.live ?? 0}</b> live ·{' '}
        <b style={{ color: TOKENS.success }}>{board.actionable ?? 0}</b> actionable ·{' '}
        <b style={{ color: TOKENS.warning }}>{st.needs_data ?? 0}</b> need fresh analysis ·{' '}
        <button type="button" onClick={() => onPreset({ view: 'expired' })} style={{ all: 'unset', cursor: 'pointer', color: TEXT2 }}
          title="Signals past their TTL and invalidated ideas — hidden from the active views">
          <b>{(st.expired ?? 0) + (st.invalidated ?? 0)}</b> expired / invalidated →
        </button>
      </div>
      {/* Numbers first (operator 2026-10-08): one big-number card per question; click → that view. */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        {PANEL_ORDER.filter((k) => board.panels[k]).map((k) => {
          const p = board.panels[k]
          const look = BOARD_LOOK[k]
          return (
            <BigNumberCard key={k} testId={`watch-board-${k}`} icon={look.icon} label={look.label} value={p.count ?? 0}
              family={look.family} onClick={() => onPreset(PANEL_PRESET[k])}
              sub={(p.items || []).slice(0, 3).map((e: any) => e.symbol).filter(Boolean).join(' · ') || undefined} />
          )
        })}
      </div>
    </div>
  )
}

// ── Filter modal ────────────────────────────────────────────────────────────

export function WatchDecisionFilterModal({ open, initial, board, onApply, onClose }: {
  open: boolean; initial: Record<string, string>; board: any; onApply: (f: Record<string, string>) => void; onClose: () => void
}) {
  const [f, setF] = useState<Record<string, string>>(initial)
  useEffect(() => { if (open) setF(initial) }, [open, initial])
  if (!open) return null
  const set = (k: string, v: string) => setF((p) => { const n = { ...p }; if (v) n[k] = v; else delete n[k]; return n })
  const facets = board?.facets || {}
  const cats = (board?.categories || []).map((c: any) => ({ id: c.id, label: c.label, count: facets.category?.[c.id] }))
  const prios = ['critical', 'high', 'medium', 'low'].map((p) => ({ id: p, label: labelOf(p), count: facets.priority?.[p] }))
  const stats = ['active', 'needs_data', 'expired', 'invalidated'].map((p) => ({ id: p, label: STATUS_LABEL[p], count: facets.status?.[p] }))
  const reent = ['confirmed', 'potential', 'opportunity', 'expired', 'invalidated'].map((p) => ({ id: p, label: labelOf(p), count: facets.reentry_status?.[p] }))
  const row = (label: string, el: any) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>{label}</div>
      {el}
    </div>
  )
  const sel = (k: string, opts: string[][]) => (
    <select value={f[k] || ''} onChange={(e) => set(k, e.target.value)} style={{ fontSize: 11, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT }}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
  const toggle = (k: string, label: string) => (
    <button type="button" onClick={() => set(k, f[k] ? '' : '1')}
      style={{ fontSize: 11, padding: '3px 10px', borderRadius: RADIUS.sm, cursor: 'pointer', border: `1px solid ${f[k] ? TOKENS.success : BORDER}`, background: f[k] ? tint(TOKENS.success) : 'transparent', color: TEXT }}>
      {label}
    </button>
  )
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div data-watch-decision-modal onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.lg, padding: 18, width: 620, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <b style={{ color: TEXT }}>Watch decision filters</b>
          <button type="button" onClick={() => setF({})} style={{ fontSize: 11, border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer', padding: '2px 8px' }}>Clear all</button>
        </div>
        {row('Category', <Chips options={cats} value={f.category} onChange={(v) => set('category', v)} colors={CATEGORY_COLOR} />)}
        {row('Priority', <Chips options={prios} value={f.priority} onChange={(v) => set('priority', v)} colors={PRIORITY_COLOR} />)}
        {row('Status', <Chips options={stats} value={f.decision_status} onChange={(v) => set('decision_status', v)} colors={STATUS_COLOR} />)}
        {row('Re-entry status', <Chips options={reent} value={f.reentry_status} onChange={(v) => set('reentry_status', v)} colors={REENTRY_COLOR} />)}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {row('Confidence', sel('min_confidence', LEVELS))}
          {row('Reward potential', sel('min_reward', LEVELS))}
          {row('Risk at least', sel('min_risk', LEVELS))}
          {row('Risk at most', sel('max_risk', [['', 'any'], ['0.3', '≤ 0.3'], ['0.5', '≤ 0.5'], ['0.7', '≤ 0.7']]))}
          {row('Time sensitivity', sel('min_time', LEVELS))}
          {row('Expiring within', sel('expiring_within_h', [['', 'any'], ['12', '12h'], ['24', '24h'], ['48', '48h'], ['96', '4d']]))}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          {toggle('actionable', 'Actionable only')}
          {toggle('include_expired', 'Include expired / invalidated')}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
          <button type="button" onClick={onClose} style={{ fontSize: 11, padding: '4px 12px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer' }}>Cancel</button>
          <button type="button" onClick={() => { onApply(f); onClose() }} style={{ fontSize: 11, padding: '4px 12px', border: `1px solid ${TOKENS.success}`, background: tint(TOKENS.success), color: TEXT, cursor: 'pointer', fontWeight: 700 }}>Apply filters</button>
        </div>
      </div>
    </div>
  )
}
