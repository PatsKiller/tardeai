/**
 * Operator-facing words for internal gap/diagnostic strings (operator page audit 2026-11-04, FQ-061;
 * review of PR 2619 at c266e340 by cx-openai-4, P2 R1/R2).
 *
 * Pages used to print a producer's own reason verbatim, e.g. on /risk:
 *   "Conflict check unavailable: conflict engine accepted source not yet integrated"
 * which names the engine, not what the operator loses. Every function here returns a plain sentence
 * that says WHAT could not be checked and HOW that limits the figures on screen, and keeps the raw
 * producer string as `raw` so the caller can place it behind a technical-detail toggle (nothing is
 * removed — AGENTS.md §9.5, audit brief Rule 2).
 *
 * R1: this banner is shared by every /risk tab — Market risk and Correlation draw their figures from
 * separate, independently supplied projections. So no sentence here may state the basis of "the risk
 * figures below"; it can only speak for the conflict cross-check itself.
 *
 * R2: a missing or unreadable conflict section proves that its results were not provided or could not
 * be read. It does not prove the engine did not execute — these helpers read produced records and never
 * invoke the engine — so "did not run" is reserved for a producer reason that says so.
 */

export type PlainGap = { text: string; raw: string | null }

/** Known producer reasons → what the operator needs to understand. Keys are matched, not displayed. */
const GAP_TEXT: Array<[RegExp, string]> = [
  [
    /accepted source not yet integrated/i,
    'Cross-checks are incomplete: the comparison source is not connected yet, so overlapping positions and conflicting signals are not counted.',
  ],
  [
    /more conflict records available/i,
    'Some conflict records could not be loaded. The findings shown are the ones that were read; more may exist.',
  ],
  [
    /conflict section not supplied/i,
    'Cross-check results were not provided for this page, so these figures may omit overlapping positions or conflicting signals.',
  ],
  [
    /engine result not supplied/i,
    'Cross-check results were not provided for this page, so these figures may omit overlapping positions or conflicting signals.',
  ],
  [
    /disabled|turned off|switched off/i,
    'Cross-checks are switched off by configuration, so overlapping positions and conflicting signals are not counted on this page.',
  ],
  [
    /no positions/i,
    'There are no positions to cross-check, so there is nothing to compare on this page.',
  ],
]

// The fallback names no mechanism. It is reached only by a producer reason this helper cannot
// interpret, so "could not be read" would assert an execution outcome we do not see (PR 2619
// review F1, cc-deepseek-3 at e3eb2af13).
const COULD_NOT_READ =
  'Cross-check results are not available on this screen, so these figures may omit overlapping positions or conflicting signals.'

/**
 * `plainConflictGap(reason)` → one operator sentence plus the raw producer string (null when there
 * was no reason). An unrecognised reason still gets the honest consequence sentence; the caller
 * keeps the raw text in a details toggle rather than in the sentence.
 */
export function plainConflictGap(reason: unknown): PlainGap {
  const raw = typeof reason === 'string' && reason.trim() ? reason.trim() : null
  if (!raw) return { text: COULD_NOT_READ, raw: null }
  const hit = GAP_TEXT.find(([pattern]) => pattern.test(raw))
  return { text: hit?.[1] ?? COULD_NOT_READ, raw }
}
