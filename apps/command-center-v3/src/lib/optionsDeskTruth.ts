import { isCardBlocked } from './optionsCardSemantics.ts'

type RewardRiskInput = {
  strategy?: string
  risk_reward?: number | null
  card_blocked?: boolean
  status?: string
  queue_status?: string
  enterprise_blocked?: boolean
  enterprise?: { blocks?: unknown[] }
  aegis_verdict?: string
  aegis_status?: string
  ensemble_verdict?: string
  ensemble_status?: string
}

export type FunnelStatusRow = {
  symbol?: string
  account?: string
  cc?: { status?: string }
}

export type FunnelNameList = {
  count: number
  names: string[]
  /** False when the payload has a status tally and no row list to name. */
  namesKnown: boolean
}

export type CoveredCallFunnelCounts = {
  /** CC_ELIGIBLE only. INTENT_BYPASS is not this number. */
  cleared: FunnelNameList
  /** Intent sleeve cleared the IV floor. Not a cleared-gates trade. */
  intentIvOnly: FunnelNameList
}

function listFor(
  rows: FunnelStatusRow[] | undefined,
  byStatus: Record<string, number> | undefined,
  status: string,
): FunnelNameList {
  const fromRows = Array.isArray(rows) && rows.some(r => r?.cc?.status)
  if (fromRows) {
    const matched = rows.filter(r => r?.cc?.status === status)
    const names = matched.map(r => {
      const sym = String(r.symbol || '').toUpperCase()
      const acct = String(r.account || '').replace(/_/g, ' ').trim()
      if (!sym) return ''
      return acct ? `${sym} · ${acct}` : sym
    }).filter(Boolean)
    return { count: matched.length, names, namesKnown: true }
  }
  return { count: Number(byStatus?.[status] ?? 0), names: [], namesKnown: false }
}

/** Green "eligible" must not add INTENT_BYPASS. Callers still receive both counts. */
export function coveredCallFunnelCounts(
  rows: FunnelStatusRow[] | undefined,
  byStatus?: Record<string, number> | null,
): CoveredCallFunnelCounts {
  const map = byStatus || undefined
  return {
    cleared: listFor(rows, map, 'CC_ELIGIBLE'),
    intentIvOnly: listFor(rows, map, 'INTENT_BYPASS'),
  }
}

export function funnelNameText(list: FunnelNameList): string {
  if (list.namesKnown) return list.names.length ? list.names.join(', ') : 'none'
  if (list.count > 0) return 'row list missing'
  return 'none'
}

type PersonRow = {
  options_decision_packet?: { state?: string }
  flags?: Array<{ key?: string }>
} & Record<string, unknown>

/** Matches the status chips. Thesis-incomplete is its own count, not "refused or incomplete". */
export function optionsDeskPersonLine(rows: PersonRow[] | undefined, openStrategies: number): string {
  const list = Array.isArray(rows) ? rows : []
  const blocked = list.filter(r => r.options_decision_packet?.state === 'BLOCKED' || isCardBlocked(r as never)).length
  const ready = list.filter(r => r.options_decision_packet?.state === 'ELIGIBLE_FOR_OPERATOR_REVIEW').length
  const thesisIncomplete = list.filter(r => (r.flags || []).some(f => f?.key === 'THESIS_INCOMPLETE')).length
  const thesisPart = thesisIncomplete ? ` ${thesisIncomplete} missing a thesis.` : ''
  return `Needs a person: ${ready} ready for operator review. ${blocked} blocked.${thesisPart} ${openStrategies} open strategies. A model score is not a CIO decision. Outcomes are not validated from this screen.`
}

/** Hedge payoff ratio is not a credit R:R, and a blocked card does not paint the chip as a pass. */
export function rewardRiskPresentation(p: RewardRiskInput): { label: string; success: boolean } {
  const hedge = String(p?.strategy || '') === 'protective_put'
  const blocked = isCardBlocked(p as never)
  const n = p?.risk_reward == null ? null : Number(p.risk_reward)
  const success = !hedge && !blocked && n != null && Number.isFinite(n) && n >= 0.3
  return { label: hedge ? 'hedge ratio' : 'R:R', success }
}
