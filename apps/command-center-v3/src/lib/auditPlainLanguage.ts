/**
 * Operator-facing words for internal gap/diagnostic strings (operator page audit 2026-11-04, FQ-061).
 *
 * Pages used to print a producer's own reason verbatim, e.g. on /risk:
 *   "Conflict check unavailable: conflict engine accepted source not yet integrated"
 * which names the engine, not what the operator loses. Every function here returns a plain sentence
 * that says WHAT could not be checked and HOW that limits the figures on screen, and keeps the raw
 * producer string as `raw` so the caller can place it behind a technical-detail toggle (nothing is
 * removed — AGENTS.md §9.5, audit brief Rule 2).
 */

export type PlainGap = { text: string; raw: string | null }

/** Known producer reasons → what the operator needs to understand. Keys are matched, not displayed. */
const GAP_TEXT: Array<[RegExp, string]> = [
  [
    /accepted source not yet integrated/i,
    'Cross-checks could not run: the comparison source is not connected yet. The risk figures below use stops and positions only, so overlapping positions and conflicting signals are not counted.',
  ],
  [
    /more conflict records available/i,
    'Some conflict records could not be loaded. The findings shown are the ones that were read; more may exist.',
  ],
  [
    /conflict section not supplied/i,
    'Cross-checks did not run on this page. The figures below may omit overlapping positions or conflicting signals.',
  ],
  [
    /engine result not supplied/i,
    'Cross-checks did not run on this page. The figures below may omit overlapping positions or conflicting signals.',
  ],
]

/**
 * `plainConflictGap(reason)` → one operator sentence plus the raw producer string (null when there
 * was no reason). An unrecognised reason still gets the honest consequence sentence; the caller
 * keeps the raw text in a details toggle rather than in the sentence.
 */
export function plainConflictGap(reason: unknown): PlainGap {
  const raw = typeof reason === 'string' && reason.trim() ? reason.trim() : null
  if (!raw) {
    return {
      text: 'Cross-checks did not run, so these figures may omit overlapping positions or conflicting signals.',
      raw: null,
    }
  }
  const hit = GAP_TEXT.find(([pattern]) => pattern.test(raw))
  return {
    text: hit?.[1] ?? 'Cross-checks could not run, so these figures may omit overlapping positions or conflicting signals.',
    raw,
  }
}
