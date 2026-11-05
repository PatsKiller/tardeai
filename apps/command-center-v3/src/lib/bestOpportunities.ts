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
