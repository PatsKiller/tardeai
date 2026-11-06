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
 * computes no verdict of its own.
 *
 * F1 (cc-deepseek-3 at 49d15e5cb): until that producer ships, NO served row carries the receipt — and the unfiltered
 * version blanked Home's primary opportunities card on every payload the server can serve. So the rule is one-way in
 * the other direction too: a payload the producer has NOT answered shows the rows it did send (the list the operator
 * has today), and only once ANY row carries `top_eligibility` (or the producer sends its `top_list`) does Home restrict
 * itself to `eligible === true`. It never widens a list the producer has qualified, and it never blanks a list the
 * producer has not qualified.
 *
 * Nil-safe and total: anything that is not a list of objects yields [].
 */
export function topEligibleRows(body: any): any[] {
  const items = body && Array.isArray(body.items) ? body.items : []
  const rows = items.filter((row: any) => row && typeof row === 'object')
  const producerAnswered = !!body && (body.top_list != null || rows.some((row: any) => row.top_eligibility != null))
  return producerAnswered ? rows.filter((row: any) => row.top_eligibility?.eligible === true) : rows
}

/**
 * The row's middle-column label. The stored CIO stance when the producer sent one; otherwise the row's own `type`
 * (a fact the payload carries), never a constant "CIO review pending" the page has no review record to support.
 */
export function opportunityRowLabel(row: any): string {
  const stance = row && typeof row === 'object' ? row.cio_review?.stance : null
  if (typeof stance === 'string' && stance.trim()) return stance.trim()
  const type = row && typeof row === 'object' ? row.type : null
  if (typeof type === 'string' && type.trim()) return type.trim().replace(/_/g, ' ')
  return '—'
}

/** The producer's own risk/qualification sentence for the top list, or null when it sent none. */
export function topListNotice(body: any): string | null {
  const notice = body && body.top_list && typeof body.top_list === 'object' ? body.top_list.notice : null
  return typeof notice === 'string' && notice.trim() ? notice.trim() : null
}
