// FQ-085 (HQ-01) — the Home regime line reads the clock the envelope carries BESIDE the row.
//
// /api/v2/risk-regime/latest answers {ok, data: <regime row>, as_of, age_hours, stale, stale_after_hours, gap}.
// `useApi` unwraps `data`, so a component that only receives `data` has already lost the clock: `regime.stale` is
// undefined and a stale snapshot renders as a current verdict. cc-deepseek-5's BLOCK on #2642 (2026-11-05) is exactly
// that: the first repair read the clock off the row and could never be true. This module takes the ROW and the
// ENVELOPE and says what may be claimed.

export type RegimeState = {
  /** the regime label in words, '' when the row carries none */
  label: string
  /** true only when the envelope (or the row's own stale_data) says stale */
  stale: boolean
  /** the envelope's age in hours, null when it carried none */
  ageHours: number | null
  /** the envelope's as_of, null when it carried none */
  asOf: string | null
  /** what the line may print */
  text: string
}

export function regimeState(regime: any, envelope: any): RegimeState {
  const row: any = regime?.data ?? regime
  // The envelope is the authoritative clock; the row is the fallback for shapes that carry the clock inline.
  const clock: any = envelope ?? regime
  const label = String(row?.regime_label ?? '').replace(/_/g, ' ')
  const stale = Boolean(clock?.stale) || Boolean(row?.stale_data)
  const ageHours = typeof clock?.age_hours === 'number' ? clock.age_hours : null
  const asOf = typeof clock?.as_of === 'string' ? clock.as_of : null
  const text = !regime
    ? 'unknown'
    : !label
      ? 'not reported'
      : stale
        ? `${label} (stale${ageHours != null ? `, ${ageHours.toFixed(1)} h old` : ''})`
        : label
  return { label, stale, ageHours, asOf, text }
}

/** The element's title: the clock when the envelope carried one, an explicit admission when it did not. */
export function regimeClockTitle(state: RegimeState): string {
  if (!state.asOf) return 'regime clock not reported'
  return `regime as_of ${state.asOf}${state.ageHours != null ? ` (${state.ageHours.toFixed(1)} h old)` : ''}`
}
