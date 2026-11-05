/**
 * The two states a scan row must never hide (cx-openai-3 F2 at c3ea49812).
 *
 * The compact row showed `High Conviction Opportunity`, `$22.25`, `-3.40%` for a decision whose own status was
 * `expired` and whose quote was `STALE`: every one of those numbers was true and the row still read as a live idea.
 * The grid card carries `WatchDecisionBadges` and `FreshnessChips`; the scan row and the reading view did not.
 *
 * These functions say the state in the operator's words, and only when it is NOT the normal case — a healthy row stays
 * a single short line.
 */

/** Quote states the projection treats as current (`watch_domains.QUALITY_POINTS`). */
const CURRENT_QUOTE = new Set(['CURRENT', 'PREMARKET_CURRENT', 'AFTER_HOURS_CURRENT'])

/** `expired` → "Signal expired", matching WatchDecisionBadges so the row and the card never disagree. */
const DECISION_STATUS: Record<string, string> = {
  active: 'Active',
  needs_data: 'Needs fresh analysis',
  expired: 'Signal expired',
  invalidated: 'Invalidated',
}

export function decisionStatusWords(status: string | null | undefined): string | null {
  const key = String(status ?? '').trim().toLowerCase()
  if (!key || key === 'active') return null
  return DECISION_STATUS[key] ?? key.replace(/_/g, ' ')
}

export function quoteStateWords(state: string | null | undefined): string | null {
  const key = String(state ?? '').trim().toUpperCase()
  if (!key || CURRENT_QUOTE.has(key)) return null
  if (key === 'DATA_UNAVAILABLE' || key === 'UNAVAILABLE') return 'Quote unavailable'
  if (key === 'STALE') return 'Quote stale'
  return `Quote ${key.replace(/_/g, ' ').toLowerCase()}`
}

/** The warning line for one card, empty when the card is current. */
export function rowStateWords(card: { decision?: { status?: string | null } | null; quote_freshness?: string | null; freshness_state?: string | null } | null | undefined): string[] {
  if (!card) return []
  return [
    decisionStatusWords(card.decision?.status),
    quoteStateWords(card.quote_freshness || card.freshness_state),
  ].filter((word): word is string => Boolean(word))
}
