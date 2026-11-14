// FQ-085 (HQ-01) — the Home regime line reads the clock the envelope carries BESIDE the row.
//
// /api/v2/risk-regime/latest answers {ok, data: <regime row>, as_of, age_hours, stale, stale_after_hours, gap}.
// `useApi` unwraps `data`, so a component that only receives `data` has already lost the clock: `regime.stale` is
// undefined and a stale snapshot renders as a current verdict. cc-deepseek-5's BLOCK on PR 2642 (2026-11-05) is exactly
// that: the first repair read the clock off the row and could never be true. This module takes the ROW and the
// ENVELOPE and says what may be claimed.

export type RegimeState = {
  /** the regime label in words, '' when the row carries none */
  label: string
  /** true when the envelope (or the row's own stale_data) says stale, or when no clock was reported at all */
  stale: boolean
  /** the envelope's age in hours, null when it carried none */
  ageHours: number | null
  /** the envelope's as_of, null when it carried none */
  asOf: string | null
  /** what the line may print */
  text: string
  /** LQ-20261113-3048: how many of the three core legs (volatility, trend, breadth) the row says were measured;
   *  null when the row reports none of the three fields (an older or partial shape: unknown, not "all measured") */
  legsMeasured: number | null
  /** the core legs the row reports as unmeasured (`not_measured`, `unknown`, empty or null) */
  legsMissing: string[]
  /** at least one reported core leg is unmeasured: the label weighs less evidence than it claims */
  incomplete: boolean
  /** the label may carry a confident tone: current clock, not stale, every reported leg measured */
  confident: boolean
}

/** The three core legs the classifier weighs, and the row field each one is published in. */
export const REGIME_LEGS: ReadonlyArray<[string, string]> = [
  ['volatility', 'volatility_state'], ['trend', 'trend_state'], ['breadth', 'breadth_state'],
]
/** Mirrors UNMEASURED_STATES in scripts/market_regime_classifier.py; tests/test_market_regime_legs_lq3048_20261113.py
 *  parses this line and pins the two sets equal (LQ-20261113-3061, review 3048 C2). */
const UNMEASURED = new Set(['', 'unknown', 'not_measured', 'not measured', 'n/a', 'none'])
/** Fewer measured core legs than this is never a current verdict (mirrors MIN_CORE_LEGS in the classifier). */
export const MIN_REGIME_LEGS = 2

/** Which core legs the row reports, and which were not measured. A row carrying NONE of the three fields reports
 *  no legs (an older shape: legs unknown). Once a row carries any of them, every core leg counts: a field present
 *  with a null/empty/`not_measured`/`unknown` value, or a field absent from that partial row, is unmeasured
 *  (fail-closed and named, never silently dropped; LQ-20261113-3061, review 3048 C3). */
export function regimeLegs(row: any): { reported: string[]; missing: string[] } {
  const reported: string[] = []
  const missing: string[] = []
  if (!row || typeof row !== 'object') return { reported, missing }
  if (!REGIME_LEGS.some(([, field]) => field in row)) return { reported, missing }
  for (const [leg, field] of REGIME_LEGS) {
    reported.push(leg)
    const v = row[field]
    if (v == null || UNMEASURED.has(String(v).trim().toLowerCase())) missing.push(leg)
  }
  return { reported, missing }
}

/** "1 of 3 legs measured (trend, breadth not measured)" — '' when every leg is measured or none is reported. */
export function regimeLegsNote(state: RegimeState): string {
  if (state.legsMeasured == null || !state.legsMissing.length) return ''
  return `${state.legsMeasured} of ${REGIME_LEGS.length} legs measured (${state.legsMissing.join(', ')} not measured)`
}

export function regimeState(regime: any, envelope: any): RegimeState {
  const row: any = regime?.data ?? regime
  // The envelope is the authoritative clock; the row is the fallback for shapes that carry the clock inline.
  const clock: any = envelope ?? regime
  const label = String(row?.regime_label ?? '').replace(/_/g, ' ')
  // A clock is REPORTED only when the body states one explicitly. A body that carries the row but none of these has
  // told us nothing about freshness, and silence must never flatten into a plausible "current" verdict (the repo's
  // producer-flattens-failure trap): a clockless body carrying a row is not current. An absent row stays `unknown`.
  const clockReported =
    typeof clock?.stale === 'boolean' ||
    typeof clock?.age_hours === 'number' ||
    typeof clock?.as_of === 'string'
  const clockless = Boolean(regime) && !clockReported
  const staleByBody = Boolean(clock?.stale) || Boolean(row?.stale_data)
  const ageHours = typeof clock?.age_hours === 'number' ? clock.age_hours : null
  const asOf = typeof clock?.as_of === 'string' ? clock.as_of : null
  // LQ-20261113-3048 (A06): an unmeasured core leg is missing evidence. Rows written before the classifier counted
  // legs say stale_data=false with trend and breadth `not_measured` (11-13 05:51 ET: risk_on_trend on the VIX bucket
  // alone), so the page derives the count from the row itself rather than trusting the row's freshness flag. One
  // measured leg (or none) is not a current verdict: it is shown as not current, never with a confident tone.
  const legs = regimeLegs(row)
  const legsMeasured = legs.reported.length ? legs.reported.length - legs.missing.length : null
  const thin = legsMeasured != null && legsMeasured < MIN_REGIME_LEGS
  const incomplete = legs.missing.length > 0
  const legsText = legsMeasured != null && incomplete ? `${legsMeasured} of ${REGIME_LEGS.length} legs measured` : ''
  const ageText = ageHours != null ? `${ageHours.toFixed(1)} h old` : ''
  const text = !regime
    ? 'unknown'
    : !label
      ? 'not reported'
      : staleByBody
        ? `${label} (stale${ageText ? `, ${ageText}` : ''}${legsText ? `, ${legsText}` : ''})`
        : clockless
          ? `${label} (clock not reported${legsText ? `, ${legsText}` : ''})`
          : legsText
            ? `${label} (${legsText})`
            : label
  const stale = staleByBody || clockless || thin
  return {
    label, stale, ageHours, asOf, text,
    legsMeasured, legsMissing: legs.missing, incomplete,
    confident: Boolean(regime) && Boolean(label) && !stale && !incomplete,
  }
}

/** The element's title: the clock when the envelope carried one, an explicit admission when it did not. */
export function regimeClockTitle(state: RegimeState): string {
  if (!state.asOf) return 'regime clock not reported'
  return `regime as_of ${state.asOf}${state.ageHours != null ? ` (${state.ageHours.toFixed(1)} h old)` : ''}`
}
