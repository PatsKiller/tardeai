/**
 * FQ-088 (HQ-04): the opportunity list carries a list as-of and a per-row quote time; Home rendered neither, so a
 * reward-to-risk number computed from a quote of unknown age and unknown session looked exactly like a current one.
 *
 * This module is the only place that decides whether such a value may be presented as current. The rule is one-way:
 * anything unreadable, missing, in the future or older than the session window is NOT current. It never guesses.
 */

/** A quote older than this many minutes is not presented as current. One regular session, with slack for a scan. */
export const QUOTE_STALE_MINUTES = 30

export type QuoteState = 'current' | 'stale' | 'unknown'
export type QuoteAge = {
  state: QuoteState
  /** short, visible caption under the value — never the raw timestamp */
  short: string
  /** the full sentence for a tooltip or a technical detail */
  words: string
  /** the session the observation belongs to, when the clock is readable */
  session: 'pre-market' | 'regular' | 'after-hours' | 'overnight' | null
}

const ET = 'America/New_York'

/** ET clock position → session word. 09:30–16:00 regular; 04:00–09:30 pre-market; 16:00–20:00 after-hours. */
export function sessionOf(at: Date): QuoteAge['session'] {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: ET, hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(at)
  const hour = Number(parts.find(p => p.type === 'hour')?.value ?? 'NaN')
  const minute = Number(parts.find(p => p.type === 'minute')?.value ?? 'NaN')
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null
  const mins = hour * 60 + minute
  if (mins >= 570 && mins < 960) return 'regular'
  if (mins >= 240 && mins < 570) return 'pre-market'
  if (mins >= 960 && mins < 1200) return 'after-hours'
  return 'overnight'
}

function etClock(at: Date): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: ET, hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(at)
}

/**
 * A timestamp we may act on, or an invalid Date. A string must say WHICH clock it is on — `Z` or a numeric offset —
 * because `new Date('2026-11-04T17:00:00')` silently reads the host's local zone, and an ET reading derived from that
 * is a guess about a clock the producer never named (cx-openai-4 R1 at c50f1110, AGENTS.md §5: never infer identity or
 * time). A `Date` object already carries its instant, so it is accepted as-is.
 */
const ZONED = /(?:Z|[+-]\d{2}:?\d{2})$/i
function parseStamped(value: unknown): Date {
  if (value instanceof Date) return value
  if (typeof value !== 'string') return new Date(NaN)
  const text = value.trim()
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text) || !ZONED.test(text)) return new Date(NaN)
  return new Date(text)
}

/**
 * `quoteAge(rowAsOf, quoteAt, now)` — the row's own as-of is accepted as a fallback for the quote time, and only a
 * readable, zoned, non-future timestamp inside the window counts as current.
 */
export function quoteAge(quoteAt: unknown, now: Date = new Date()): QuoteAge {
  const at = parseStamped(quoteAt)
  if (Number.isNaN(at.getTime())) {
    return {
      state: 'unknown', short: 'no list-time quote · not current',
      words: 'No list-time quote was supplied for this row, so its reward-to-risk is not a current reading.',
      session: null,
    }
  }
  // R3 (codex BLOCK at 77b94efa3a): the decision uses exact elapsed milliseconds. Rounding first let a quote 30m20s old
  // read as "30m" and pass, and a 60-second future allowance let a clock 30s ahead read as current. Neither is in the rule
  // the page states, so neither is in the code: any future instant is not current, and "older than 30 minutes" is a strict
  // comparison on the real age. Rounding happens only in the words a person reads.
  const ageMs = now.getTime() - at.getTime()
  const session = sessionOf(at)
  const clock = etClock(at)
  const shown = ageMs < 60_000 ? 'under a minute' : `${Math.floor(ageMs / 60_000)} minutes`
  if (ageMs < 0) {
    return {
      state: 'unknown', short: 'quote time is ahead · not current',
      words: `The quote claims a time of ${clock} ET, which is in the future, so it is not trusted.`,
      session,
    }
  }
  if (ageMs > QUOTE_STALE_MINUTES * 60_000) {
    return {
      state: 'stale', short: `quote ${shown} old · not current`,
      words: `The quote is ${shown} old (${clock} ET, ${session ?? 'session unknown'}), older than the ` +
        `${QUOTE_STALE_MINUTES}-minute window, so this reward-to-risk is not a current reading.`,
      session,
    }
  }
  return {
    state: 'current', short: `${shown} old · ${session ?? 'session unknown'}`,
    words: `Quote observed ${clock} ET (${session ?? 'session unknown'}), ${shown} old.`,
    session,
  }
}

/** The list's own as-of, in words, or null when the payload did not carry a ZONED one (never guessed, §5). */
export function listAsOfWords(asOf: unknown): string | null {
  const at = parseStamped(asOf)
  if (Number.isNaN(at.getTime())) return null
  return `Opportunity list as of ${etClock(at)} ET`
}

/**
 * What the Best-opportunities card is allowed to say, from four transport facts and a row count.
 *
 * R1 (cc-deepseek-8 BLOCK at f44f21fbe): the first version announced "showing the last list" whenever the poll had
 * failed — and on a FAILED FIRST LOAD there is no last list. The card said a retained list was on screen while the
 * screen was empty, and the empty state said "Loading…" over a request that had already failed. Both are freshness
 * claims the data does not support, which is the class this page exists to stop; so the composition lives here, where
 * it can be tested, instead of in three inline ternaries.
 */
export type OpportunitiesCardState = {
  /** the poll failed or is retained AND there are rows: the rows may be shown, qualified */
  retained: boolean
  /** the retained banner's sentence, or '' when no banner is shown */
  retainedText: string
  /** the sentence for an empty card, or '' when the card has rows */
  emptyText: string
}

export function opportunitiesCardState(a: {
  loading: boolean; error: boolean; stale: boolean; itemCount: number
  /** the response arrived, carried a real `items` ARRAY and did not report a source error */
  listLoaded: boolean
  /** P2651-R4 (codex at c50f1110): the producer answered `ok:false` — a source error, which is not an empty list */
  sourceError?: boolean
  /** FQ-114: the producer sent its `top_list` receipt, so an empty list means "no candidate", not "unavailable" */
  qualificationPresent?: boolean
}): OpportunitiesCardState {
  const failed = !a.loading && (a.error || a.stale)
  const rows = Number.isFinite(a.itemCount) && a.itemCount > 0
  return {
    retained: failed && rows,
    retainedText: failed && rows ? 'Refresh failed — showing the last list; not current' : '',
    // A failed load is not an empty result, and it is not still loading: say which one it is. Then, with a list that
    // answered, an empty card says which of the two empties it is — no candidate, or no qualification to judge by.
    emptyText: rows ? ''
      : failed ? 'The list could not be loaded — this is a failed request, not an empty list.'
      : a.sourceError ? 'The list could not be read from its source — this is a source error, not an empty list.'
      : !a.listLoaded ? 'Loading…'
      : a.qualificationPresent ? 'No reviewed name clears the bar right now.'
      : 'Top list qualification unavailable; open the research list.',
  }
}
