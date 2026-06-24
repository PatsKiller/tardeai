/** Buy-side CIO recommendations that warrant a watchlist prospectus link. */
const BUY_SIDE = [
  'STRONG BUY', 'STRONG_BUY', 'BUY', 'ADD', 'ACCUMULATE', 'ADD ON PULLBACK', 'ADD_ON_PULLBACK',
  'WAIT FOR PULLBACK', 'WAIT_PULLBACK',
]

function recBuySide(rec: string): boolean {
  const u = rec.toUpperCase().replace(/_/g, ' ').trim()
  if (!u) return false
  if (BUY_SIDE.some(b => u.includes(b.replace(/_/g, ' ')))) return true
  return u.includes('PULLBACK') && (u.includes('WAIT') || u.includes('ADD') || u.includes('BUY'))
}

const MANUAL_WATCHLIST_SOURCES = new Set(['operator', 'personal_watchlist'])

function isManualWatchlist(it: { source?: string; origin_system?: string }): boolean {
  const src = String(it.source || '').toLowerCase()
  const origin = String(it.origin_system || '').toLowerCase()
  return MANUAL_WATCHLIST_SOURCES.has(src) || origin === 'operator'
}

/** Whether a watchlist row should show analyst report links. */
export function watchlistReportEligible(it: {
  latest_recommendation?: string
  holdings_llm_action?: string
  synthesis_recommendation?: string
  source?: string
  origin_system?: string
  grok_recommendation?: string
  chatgpt_recommendation?: string
}): boolean {
  if (isManualWatchlist(it)) return true
  const recs = [
    it.latest_recommendation,
    it.holdings_llm_action,
    it.synthesis_recommendation,
    it.grok_recommendation,
    it.chatgpt_recommendation,
  ].map(r => String(r || ''))
  return recs.some(recBuySide)
}

/** All non-cash portfolio holdings show report links (generate or prospectus). */
export function holdingReportEligible(_h: { is_cash?: boolean; symbol?: string }): boolean {
  return !_h.is_cash && !!_h.symbol
}