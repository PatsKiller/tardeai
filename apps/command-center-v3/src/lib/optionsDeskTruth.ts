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

/** Existing desk rules. Display only — do not lower either number in this module. */
export const DESK_SPREAD_CAP_PCT = 12
export const CREDIT_SPREAD_RR_FLOOR = 0.25

type FloorInput = {
  strategy?: string
  risk_reward?: number | null
  legs_liquidity?: Array<{ spread_pct?: number | null }>
  enterprise?: { blocks?: Array<{ reason?: string } | string> }
  thesis_blocks?: Array<{ reason?: string }>
  recommendation_comparison?: { comparison?: { reward_to_risk?: number | null } }
}

function spreadReadings(p: FloorInput): number[] {
  const out: number[] = []
  for (const leg of p.legs_liquidity || []) {
    const n = Number(leg?.spread_pct)
    if (Number.isFinite(n)) out.push(n)
  }
  const blobs = [
    ...(p.enterprise?.blocks || []).map(b => (typeof b === 'string' ? b : b?.reason)),
    ...(p.thesis_blocks || []).map(b => b?.reason),
  ]
  for (const text of blobs) {
    const m = String(text || '').match(/spread\s+([\d.]+)%\s*>\s*([\d.]+)%/i)
    if (m) out.push(Number(m[1]))
  }
  return out.filter(n => Number.isFinite(n))
}

/** Name a breach of the existing caps. A cash-secured put is not relabeled as a credit spread. */
export function floorCallouts(p: FloorInput): string[] {
  const out: string[] = []
  const spreads = spreadReadings(p)
  const worst = spreads.length ? Math.max(...spreads) : null
  if (worst != null && worst > DESK_SPREAD_CAP_PCT) {
    out.push(`Widest quote is ${worst.toFixed(1)}% wide. The desk cap stays ${DESK_SPREAD_CAP_PCT}%.`)
  }
  const strategy = String(p.strategy || '')
  const creditSpread = strategy === 'credit_spread' || strategy.endsWith('_credit_spread')
  const raw = p.risk_reward ?? p.recommendation_comparison?.comparison?.reward_to_risk
  const rr = raw == null ? null : Number(raw)
  if (creditSpread && rr != null && Number.isFinite(rr) && rr < CREDIT_SPREAD_RR_FLOOR) {
    out.push(`Reward/risk ${rr.toFixed(2)} is under the ${CREDIT_SPREAD_RR_FLOOR} credit-spread floor. The floor is unchanged.`)
  }
  return out
}

/** First card per symbol keeps the shared scenario table. Later cards point at it. */
export function packageLeadIds(rows: Array<{ id?: string; symbol?: string; combined_exposure?: { symbol?: string } | null }> | undefined): Set<string> {
  const seen = new Set<string>()
  const leads = new Set<string>()
  for (const p of rows || []) {
    if (!p?.combined_exposure) continue
    const key = String(p.combined_exposure.symbol || p.symbol || '').toUpperCase()
    if (!key || seen.has(key)) continue
    seen.add(key)
    if (p.id) leads.add(String(p.id))
  }
  return leads
}

/** A blocked card keeps the route fact and drops the submit invitation. */
export function blockedRouteNote(note: string | undefined, blocked: boolean): string | undefined {
  if (!note) return note
  if (!blocked) return note
  const hedge = /manual hedge/i.test(note) ? ' Manual hedge — size to shares held.' : ''
  return `Broker route is open. This idea is not eligible until its blocks clear.${hedge}`
}

export function armedDeskLine(armed: boolean, liveEligible: number): string {
  if (!armed) return 'advisory only'
  if (liveEligible <= 0) return 'broker route open · no card on this page is eligible'
  return 'broker route open: you place each order (2FA)'
}

export function armedOverviewLine(armed: boolean, liveEligible: number): string {
  if (!armed) return ' Execution advisory until options_pilot_arm --approve.'
  if (liveEligible <= 0) return ' Broker route is open. No proposal on this desk is eligible.'
  return ' Broker route is open. Preflight and per-order 2FA are required before any submit.'
}

/** Hedge payoff ratio is not a credit R:R, and a blocked card does not paint the chip as a pass. */
export function rewardRiskPresentation(p: RewardRiskInput): { label: string; success: boolean } {
  const hedge = String(p?.strategy || '') === 'protective_put'
  const blocked = isCardBlocked(p as never)
  const n = p?.risk_reward == null ? null : Number(p.risk_reward)
  const success = !hedge && !blocked && n != null && Number.isFinite(n) && n >= 0.3
  return { label: hedge ? 'hedge ratio' : 'R:R', success }
}
