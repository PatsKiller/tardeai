/**
 * WP-T3 — pure triage model for the Trading command strip.
 * Fail-closed: missing sources → omit chip (never invent "all clear" from silence).
 */

import type { TradingTab } from './tradingDeepLink'

export type TriageTone = 'critical' | 'action' | 'warn' | 'info' | 'ok'

export type TriageChip = {
  id: string
  label: string
  detail: string
  count: number
  tone: TriageTone
  tab: TradingTab
  /** Deep-link query extras (symbol, proposal, intent) */
  params?: Record<string, string>
  /** Sample symbols for the operator (≤4) */
  samples?: string[]
}

export type TriageInput = {
  /** open-trades/intelligence summary + positions */
  intelSummary?: {
    risk_counts?: Record<string, number>
    total_positions?: number
  } | null
  intelPositions?: Array<{
    symbol?: string
    operator_priority?: string
    operator_decision?: string
    protection_state?: string
    risk_flags?: string[]
  }> | null
  /** broker-proposals/summary */
  queueSummary?: {
    total?: number
    route_ready?: number
    blocked?: number
    agent_pending?: number
    route_ready_pct?: number
  } | null
  /** broker-reconciliation latest */
  recon?: {
    unmatched_broker_orders?: number
    unmatched_local_trades?: number
    runs?: Array<{
      unmatched_broker_orders?: number
      unmatched_local_trades?: number
    }>
  } | null
  /** pilot status */
  pilot?: {
    standing_approvals_active?: number
    pilot_session_active?: boolean
  } | null
  /** optional paper pending for awareness (not Path B) */
  paperPending?: number | null
}

function uniqSyms(rows: Array<{ symbol?: string }>, limit = 4): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const r of rows) {
    const s = String(r.symbol || '').toUpperCase()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
    if (out.length >= limit) break
  }
  return out
}

/** Build ordered triage chips — highest urgency first. */
export function buildTradingTriage(input: TriageInput): TriageChip[] {
  const chips: TriageChip[] = []
  const positions = input.intelPositions ?? []
  const risk = input.intelSummary?.risk_counts ?? {}

  // 1) High-priority unprotected / needs protection review
  const needsProt = positions.filter(p => {
    const rf = p.risk_flags ?? []
    const pri = String(p.operator_priority || '').toLowerCase()
    const highPri = pri === 'critical' || pri === 'high'
    const unprot = String(p.protection_state || '').toLowerCase() === 'unprotected'
      || rf.includes('no_protection')
      || rf.includes('large_gain_unprotected')
    const needsReview = String(p.operator_decision || '').toLowerCase().includes('needs protection')
    return unprot && (highPri || needsReview || rf.includes('large_gain_unprotected'))
  })
  if (needsProt.length > 0) {
    chips.push({
      id: 'unprotected_priority',
      label: 'Unprotected (priority)',
      detail: 'Open trades needing protection review — Stage 2c on Open Trades',
      count: needsProt.length,
      tone: 'critical',
      tab: 'Open Trades',
      samples: uniqSyms(needsProt),
    })
  }

  // 2) Near stop
  const nearStop = Number(risk.near_stop ?? 0)
  if (nearStop > 0) {
    const nearRows = positions.filter(p => (p.risk_flags ?? []).includes('near_stop'))
    chips.push({
      id: 'near_stop',
      label: 'Near stop',
      detail: 'Positions near protective stop — review Open Trades',
      count: nearStop,
      tone: 'critical',
      tab: 'Open Trades',
      samples: uniqSyms(nearRows.length ? nearRows : positions),
    })
  }

  // 3) Large gain unprotected (broader than priority)
  const bigUnprot = Number(risk.large_gain_unprotected ?? 0)
  if (bigUnprot > 0 && needsProt.length < bigUnprot) {
    chips.push({
      id: 'large_gain_unprot',
      label: 'Big gain unprotected',
      detail: 'Large unrealized gains without stop protection',
      count: bigUnprot,
      tone: 'warn',
      tab: 'Open Trades',
    })
  }

  // 4) Route-ready Path B proposals
  const ready = Number(input.queueSummary?.route_ready ?? 0)
  if (ready > 0) {
    chips.push({
      id: 'route_ready',
      label: 'Route-ready',
      detail: 'Path B proposals pass live-route gates — review on Proposals (2FA still required)',
      count: ready,
      tone: 'action',
      tab: 'Proposals',
    })
  }

  // 5) Blocked / agent pending queue
  const blocked = Number(input.queueSummary?.blocked ?? 0)
  const agentPending = Number(input.queueSummary?.agent_pending ?? 0)
  if (blocked > 0) {
    chips.push({
      id: 'queue_blocked',
      label: 'Queue blocked',
      detail: agentPending > 0
        ? `${agentPending} agent-pending · resolve diligence on Proposals`
        : 'Broker queue items blocked on diligence/sizing',
      count: blocked,
      tone: 'warn',
      tab: 'Proposals',
    })
  }

  // 6) Standing 2FA / pilot approvals
  const standing = Number(input.pilot?.standing_approvals_active ?? 0)
  if (standing > 0) {
    chips.push({
      id: 'standing_2fa',
      label: 'Standing 2FA approvals',
      detail: 'Active standing approvals on Broker Orders pilot — not unattended auto-live',
      count: standing,
      tone: 'info',
      tab: 'Broker Orders',
    })
  }

  // 7) Recon breaks
  const runs = input.recon?.runs
  const latest = Array.isArray(runs) && runs.length ? runs[0] : input.recon
  const umBroker = Number(latest?.unmatched_broker_orders ?? input.recon?.unmatched_broker_orders ?? 0)
  const umLocal = Number(latest?.unmatched_local_trades ?? input.recon?.unmatched_local_trades ?? 0)
  const reconBreaks = umBroker + umLocal
  if (reconBreaks > 0) {
    chips.push({
      id: 'recon_break',
      label: 'Recon breaks',
      detail: `Unmatched broker ${umBroker} · local ${umLocal}`,
      count: reconBreaks,
      tone: 'warn',
      tab: 'Broker Recon',
    })
  }

  // 8) Paper pending (awareness only — never labeled as broker queue)
  const paper = input.paperPending
  if (paper != null && paper > 0 && ready === 0 && blocked === 0) {
    chips.push({
      id: 'paper_pending',
      label: 'Paper pending',
      detail: 'Validation/Alpaca pipeline only — not Path B live queue',
      count: paper,
      tone: 'info',
      tab: 'Proposals', // paper still managed near proposals tooling; Entry Desk is Path A
    })
  }

  // If we have intel and everything looks quiet, show calm OK (only when data present)
  if (chips.length === 0 && (input.intelSummary || input.queueSummary)) {
    chips.push({
      id: 'all_clear',
      label: 'No urgent triage',
      detail: 'No high-priority unprotected, route-ready, recon, or standing 2FA items from available sources',
      count: 0,
      tone: 'ok',
      tab: 'Trade AI',
    })
  }

  return chips
}
