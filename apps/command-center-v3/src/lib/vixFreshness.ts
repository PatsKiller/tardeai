// Is the VIX value on the screen CURRENT, and what is it worth if it is not (FQ-086 / HQ-02).
//
// The global VIX tile coloured itself by the VALUE alone (green <18, amber 18-25, red >=25). The observation time existed
// in provenance but was never compared to now, so a VIX carried over from a stale or failed transport - or one with no
// observation time at all - rendered exactly like a fresh one, in a confident colour. The Home panel made it worse by
// printing VIX beside the REGIME clock: regime freshness is not VIX freshness.
//
// This module answers the only question the tile needs: can this number be read as current? A value with no time is
// UNDATED, never FRESH. A dated value older than the threshold is STALE and carries its age. Nothing here invents a VIX.
export type VixState = 'FRESH' | 'STALE' | 'UNDATED' | 'UNAVAILABLE'

export type VixReading = {
  state: VixState
  /** the number, formatted for display; null when there is no value at all */
  value: string | null
  /** the observation age in words, or an explicit admission that it cannot be known */
  age: string | null
  /** one operator sentence; never claims freshness the record does not support */
  label: string
  /** true only for FRESH: the only state in which a value-specific colour is honest */
  current: boolean
}

/** A daily volatility index carried over a weekend is still usable; a week-old one is not. */
export const VIX_FRESH_HOURS = 36

const HOUR = 3_600_000

function ageWords(ms: number): string {
  const hours = ms / HOUR
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min old`
  if (hours < 48) return `${Math.round(hours)} h old`
  return `${Math.round(hours / 24)} d old`
}

export function vixFreshness(
  vix: number | string | null | undefined,
  source: string | null | undefined,
  observedIso: string | null | undefined,
  nowMs: number = Date.now(),
  freshHours: number = VIX_FRESH_HOURS,
): VixReading {
  const n = vix == null || vix === '' ? NaN : Number(vix)
  if (!Number.isFinite(n)) {
    return { state: 'UNAVAILABLE', value: null, age: null, label: 'VIX not available', current: false }
  }
  const value = n.toFixed(1)
  const src = String(source ?? '').trim()
  const t = Date.parse(String(observedIso ?? ''))
  // A number with no usable timestamp cannot be called current, whatever colour the value would earn.
  if (!Number.isFinite(t)) {
    return {
      state: 'UNDATED', value, age: null, current: false,
      label: `VIX ${value} — observation time not recorded, so its age is unknown${src ? ` (source ${src})` : ''}`,
    }
  }
  const ageMs = Math.max(0, nowMs - t)
  const age = ageWords(ageMs)
  const suffix = src ? ` · source ${src}` : ''
  if (ageMs > freshHours * HOUR) {
    return { state: 'STALE', value, age, current: false,
      label: `VIX ${value} is ${age}, past the ${freshHours} h limit — not current${suffix}` }
  }
  return { state: 'FRESH', value, age, current: true, label: `VIX ${value}, ${age}${suffix}` }
}
