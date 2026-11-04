/** Home and Watch share the server's top5 preset; thresholds and ordering stay in the producer.
 * Never add a default page size after selecting Home's preset: that overrides its own cap. */
import { positionQuery } from './watchListsModel.ts'

export const BEST_OPPORTUNITIES_PRESET = 'top5'
export const BEST_OPPORTUNITIES_PATH = `/watch?tab=opportunities&preset=${BEST_OPPORTUNITIES_PRESET}`
export const BEST_OPPORTUNITIES_API = `/api/v3/opportunities?preset=${BEST_OPPORTUNITIES_PRESET}`
export const OPPORTUNITY_QUERY_KEYS = [
  'preset', 'sort', 'sector', 'q', 'limit', 'page', 'type', 'min_conviction', 'min_rr', 'min_upside',
  'technical_condition', 'cap_band',
] as const

export function opportunitiesQuery(sp: URLSearchParams): Record<string, string> {
  const base = Object.fromEntries(OPPORTUNITY_QUERY_KEYS.map(key => [key, sp.get(key) || '']).filter(([, value]) => value))
  return { ...(base.preset === BEST_OPPORTUNITIES_PRESET ? {} : { limit: '100' }), ...base, ...positionQuery(sp) }
}

/** A customized sort/filter is a research view, rather than a claim to match Home's selection. */
export function isHomeBestOpportunities(sp: URLSearchParams): boolean {
  const q = opportunitiesQuery(sp)
  return q.preset === BEST_OPPORTUNITIES_PRESET && Object.entries(q).every(([key, value]) =>
    key === 'preset' || (key === 'sort' && value === 'conviction') || (key === 'limit' && value === '5')
    || (key === 'page' && value === '1'))
}

/**
 * FQ-114 (cx-openai-5's consumer contract): the producer, not the page, decides which names are top candidates.
 * `top_eligibility.eligible === true` means the row named its indicators, cleared the coverage floor and carries an
 * active dated CIO thesis, and that RED/ORANGE stances were already suppressed upstream. Home renders the receipt and
 * computes no verdict of its own, so a row without the receipt is not a top candidate — a legacy response therefore
 * shows none rather than a best guess.
 *
 * Nil-safe and total: anything that is not a list of objects yields [].
 */
export function topEligibleRows(body: any): any[] {
  const items = body && Array.isArray(body.items) ? body.items : []
  return items.filter((row: any) => row && typeof row === 'object' && row.top_eligibility?.eligible === true)
}

/** The producer's own risk/qualification sentence for the top list, or null when it sent none. */
export function topListNotice(body: any): string | null {
  const notice = body && body.top_list && typeof body.top_list === 'object' ? body.top_list.notice : null
  return typeof notice === 'string' && notice.trim() ? notice.trim() : null
}
