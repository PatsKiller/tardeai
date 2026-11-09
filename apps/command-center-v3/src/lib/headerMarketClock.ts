// LQ-20261107-1610 (CC v3 audit A4): the header REGIME and VIX tiles always say how old they are.
//
// Before this, the REGIME tile showed its age only once it was stale, and the VIX tile showed only a clock time with no
// age, judged against a client-side 36 h line the server never used. An operator reading the strip could not tell a
// regime measured five minutes ago from one measured twenty hours ago. Both tiles now carry an age on their face; a
// stale one keeps its last measured value and turns grey (the "not current" colour the VIX tile already used), not amber,
// so it can never be mistaken for an amber "caution" reading of the market itself.
import { VIX_FRESH_HOURS } from './vixFreshness.ts'

/** 0.4 → "24 min old", 5.66 → "5.7 h old", 50 → "2.1 d old"; unknown or negative → null (never "0 min"). */
export function hoursOld(hours: number | null | undefined): string | null {
  if (hours == null || !Number.isFinite(hours) || hours < 0) return null
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min old`
  if (hours < 48) return `${hours.toFixed(1)} h old`
  return `${(hours / 24).toFixed(1)} d old`
}

/**
 * The line past which the headline VIX is stale. The server publishes it with the value (`vix_stale_after_hours`,
 * from config/market_regime_vix_complex.yaml), so the tile and the CIO risk card judge one number by one line. An
 * absent or nonsensical value falls back to the client default rather than to "always fresh".
 */
export function vixStaleAfterHours(serverLine: unknown): number {
  const n = typeof serverLine === 'number' ? serverLine : Number(serverLine)
  return Number.isFinite(n) && n > 0 ? n : VIX_FRESH_HOURS
}

export type RegimeClock = { stale: boolean; ageHours: number | null; asOf: string | null }

/**
 * The REGIME tile's age line, shown in every state. Fresh: "5.7 h old" (plus the optional detail). Stale: the age and
 * the word stale. No clock: an explicit admission, never a blank that reads as current.
 */
export function regimeAgeNote(clock: RegimeClock, detail?: string | null): string {
  const age = hoursOld(clock.ageHours)
  if (!age) return clock.asOf ? 'regime age unknown' : 'regime clock not reported'
  const head = clock.stale ? `stale · ${age}` : age
  return detail ? `${head} · ${detail}` : head
}

/** The colour a not-current reading takes on either tile: the shared "not current" grey, never a market colour. */
export const NOT_CURRENT_COLOR = 'var(--text3)'
