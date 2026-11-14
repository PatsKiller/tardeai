/** Relative age, computed by the caller from an absolute instant at render time.
 *
 *  A payload's `age_s` is a snapshot of the producer's clock at the moment it answered. Rendered from a tab that has
 *  been open for an hour, it freezes: "4 m" stays "4 m" while the source is 64 m old. The rule (combined Home,
 *  operator controlling decision 2026-11-13 §2) is that a relative age is COMPUTED at render from the slice's own
 *  absolute source time and the client clock; it is never stored or echoed. This is the one formatter for that.
 *
 *  Wording matches the Home v010 model since 2026-11-11: "<1 m", "12 m", "1 h 5 m", "2 d". Pure functions. */

/** "12 m", "1 h 5 m", "2 d" for a number of seconds; '' when the age is unknown. */
export function ageText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const m = Math.floor(Math.max(0, seconds) / 60)
  if (m < 1) return '<1 m'
  if (m < 60) return `${m} m`
  const h = Math.floor(m / 60)
  return h < 48 ? `${h} h ${m % 60} m` : `${Math.floor(h / 24)} d`
}

/** Seconds from an absolute ISO instant to `nowMs`; null when the instant is absent or unparseable.
 *  Clamped at zero: a stamp slightly ahead of the client clock reads "<1 m", never a negative age. */
export function ageSecondsFrom(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.round((nowMs - t) / 1000))
}
