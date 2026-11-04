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
 * `quoteAge(rowAsOf, quoteAt, now)` — the row's own as-of is accepted as a fallback for the quote time, and only a
 * readable, non-future timestamp inside the window counts as current.
 */
export function quoteAge(quoteAt: unknown, now: Date = new Date()): QuoteAge {
  const raw = typeof quoteAt === 'string' || quoteAt instanceof Date ? quoteAt : null
  const at = raw == null ? new Date(NaN) : new Date(raw as string | Date)
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

/** The list's own as-of, in words, or null when the payload did not carry one. */
export function listAsOfWords(asOf: unknown): string | null {
  const at = typeof asOf === 'string' ? new Date(asOf) : asOf instanceof Date ? asOf : new Date(NaN)
  if (Number.isNaN(at.getTime())) return null
  return `Opportunity list as of ${etClock(at)} ET`
}
