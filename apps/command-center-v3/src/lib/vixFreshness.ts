// Is the VIX value on the screen CURRENT, and what is it worth if it is not (FQ-086 / HQ-02).
//
// The global VIX tile coloured itself by the VALUE alone (green <18, amber 18-25, red >=25). The observation time existed
// in provenance but was never compared to now, so a VIX carried over from a stale or failed transport - or one with no
// observation time at all - rendered exactly like a fresh one, in a confident colour. The Home panel made it worse by
// printing VIX beside the REGIME clock: regime freshness is not VIX freshness.
//
// This module answers the only question the tile needs: can this number be read as current? A value with no time is
// UNDATED, never FRESH. A dated value older than the threshold is STALE and carries its age. Nothing here invents a VIX.
//
// An observation time must carry its own timezone. `Date.parse` reads an unzoned string as the BROWSER's local time,
// so the same record would have a different age on every device and could cross back under the 36 h limit and regain
// the current colour (codex-cloud CX1 at a66cdde53; AGENTS.md "Time discipline": never infer a zone from format).
// scripts/api_v2.py's `generated_at` fallback is host-local and unzoned, so an unknown zone stays unknown - UNDATED.
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

// An explicit timezone designator, anchored at the end of the string: `Z`/`z`, or a numeric offset `±HH:MM` /
// `±HHMM` (after an optional fractional-seconds part). A date-only or wall-clock-only string has no zone and is
// therefore not an instant: it is never converted through the host's or the browser's local time.
const EXPLICIT_ZONE = /(?:[Zz]|[+-]\d{2}:?\d{2})$/

function hasExplicitZone(value: string): boolean {
  return EXPLICIT_ZONE.test(value)
}

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
  const raw = String(observedIso ?? '').trim()
  // A number with no usable timestamp cannot be called current, whatever colour the value would earn.
  if (!raw) {
    return {
      state: 'UNDATED', value, age: null, current: false,
      label: `VIX ${value} — observation time not recorded, so its age is unknown${src ? ` (source ${src})` : ''}`,
    }
  }
  // A timestamp without a stated zone is not an instant. Letting Date.parse read it would silently bind it to the
  // viewer's local time, so the same record would be a different age on every device; the honest answer is unknown.
  if (!hasExplicitZone(raw)) {
    return {
      state: 'UNDATED', value, age: null, current: false,
      label: `VIX ${value} — observation time has no stated timezone, so its age is unknown${src ? ` (source ${src})` : ''}`,
    }
  }
  const t = Date.parse(raw)
  if (!Number.isFinite(t)) {
    return {
      state: 'UNDATED', value, age: null, current: false,
      label: `VIX ${value} — observation time not recorded, so its age is unknown${src ? ` (source ${src})` : ''}`,
    }
  }
  // A stamp AHEAD of now is not a fresh reading; it is a clock we cannot read (cc-deepseek-6's F1 on PR 2654). The old
  // Math.max(0, ...) clamp turned any future timestamp into zero age, and zero age is the definition of FRESH — so the
  // most impossible clock on the page rendered as the most confident number. A small skew is tolerated; a real one is
  // admitted as unreadable rather than silently relabelled as "1 min old".
  const FUTURE_GRACE_MS = 5 * 60_000
  if (t - nowMs > FUTURE_GRACE_MS) {
    return {
      state: 'UNDATED', value, age: null, current: false,
      label: `VIX ${value} — observation time is in the future, so its age cannot be read${src ? ` (source ${src})` : ''}`,
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

/**
 * The same reading, judged by the SERVER's one accessor (LQ-20261107-1690).
 *
 * The fleet has exactly one VIX freshness rule: `scripts/lib/vix_quote.py` -> `lib.vix_headline` ->
 * `lib.market_regime.vix_complex` under `config/market_regime_vix_complex.yaml` (30 min through the weekday,
 * 30 min of the continuous feed; the off-hours line outside it). A browser-side hours threshold is a second
 * clock: it can call a print current that the engine refused, or refuse one the engine measured. So when the
 * payload carries `vix_state`, it wins outright and the server's own reason is the sentence shown. Only a
 * payload without a state falls back to the local rule above (an older served release).
 */
export function vixFromState(
  vix: number | string | null | undefined,
  state: string | null | undefined,
  reason: string | null | undefined,
  observedIso?: string | null,
  freshHours: number = VIX_FRESH_HOURS,
  nowMs: number = Date.now(),
): VixReading {
  const s = String(state ?? '').trim().toUpperCase()
  if (s !== 'FRESH' && s !== 'STALE' && s !== 'UNDATED' && s !== 'UNAVAILABLE') {
    return vixFreshness(vix, undefined, observedIso, nowMs, freshHours)
  }
  const n = vix == null || vix === '' ? NaN : Number(vix)
  const value = Number.isFinite(n) ? n.toFixed(1) : null
  const why = String(reason ?? '').trim()
  if (s === 'FRESH' && value !== null) {
    return { state: 'FRESH', value, age: null, current: true, label: why || `VIX ${value}, current` }
  }
  if (value === null) {
    return {
      state: 'UNAVAILABLE', value: null, age: null, current: false,
      label: `VIX not measured${why ? ` — ${why}` : ''}`,
    }
  }
  // A value the server did not measure is shown as a past print, never as today's VIX and never in a value colour.
  return {
    state: s === 'FRESH' ? 'UNAVAILABLE' : (s as VixState),
    value, age: null, current: false,
    label: `VIX not measured (last ${value})${why ? ` — ${why}` : ''}`,
  }
}
