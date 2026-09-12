/** How an oscillator row presents its reading and its age.
 *
 * Two defects this exists to prevent, both found on the live board 2026-09-12.
 *
 * 1. `rs_score` was rendered with a `%` suffix alongside `breadth_pct`. Breadth
 *    genuinely is a percentage of constituents above their 20-day average.
 *    `rs_score` is a RANK-NORMALISED 0-100 score, and the ladder is sorted
 *    descending, so `sectors[0].rs_score` is the maximum by construction: the
 *    board displayed "Sector RS Ladder 100%" on every render regardless of
 *    market state. A constant presented as a percentage is wrong twice.
 *
 * 2. A null `as_of` rendered as the literal word "never", which asserts that
 *    the producer has never run. For `sector_comovement` that assertion is
 *    simply false — the oscillator has no reader wired to its registered store,
 *    which is a different thing. DefenseRedesign.tsx states the contract in its
 *    own header: "Nulls render through <Unk>, never as an em-dash, zero, or
 *    blank." A confident English word is further from that contract than an
 *    em-dash, not closer.
 */

/** Reading names that are genuinely a percentage of something. */
const PERCENT_READINGS = new Set(['breadth_pct'])

/** Suffix for a numeric oscillator reading. Empty string when it has no unit. */
export function readingSuffix(readingName?: string | null): string {
  return readingName && PERCENT_READINGS.has(readingName) ? '%' : ''
}

export function formatReading(reading: number, readingName?: string | null): string {
  return `${reading}${readingSuffix(readingName)}`
}

/** Compact age, or null when there is no timestamp to describe.
 *
 * Returning null rather than a word is deliberate: the caller renders <Unk>,
 * which carries a hover reason, instead of asserting something the data does
 * not support.
 */
export function ageLabel(iso?: string | null, now: number = Date.now()): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return null
  const m = Math.round((now - t) / 60000)
  if (m < 60) return `${m}m`
  if (m < 48 * 60) return `${Math.round(m / 60)}h`
  return `${Math.round(m / 1440)}d`
}
