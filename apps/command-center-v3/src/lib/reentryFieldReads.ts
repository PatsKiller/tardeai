/**
 * The two re-entry fields the page used to print as "unavailable", and how it now reads them.
 *
 * LQ-20261107-235 (2026-11-07): /v3/portfolio/re-entry/classic showed "MACD UNAVAILABLE" on every
 * row and "Catalyst: unavailable" on some. Neither was an absence of evidence:
 *
 *  - MACD: no endpoint the page reads carries a macd field at all (measured 2026-11-07: 0 of 55
 *    watchlist items, 0 of 55 symbol cards). The system's only MACD read is
 *    indicator_confluence_cache, which the re-entry decision desk composes as
 *    `macd_histogram_direction` (up/down) and `macd_signal` — a DIRECTION, never a magnitude. So
 *    the page reads the direction and stops claiming the magnitude exists.
 *  - Catalyst: `catalyst_headline` is guarded server-side (news_symbol_guard's identity match), so
 *    a null means one of three different things — no watchlist row, no catalyst on file that names
 *    the symbol, or a headline the guard refused. "unavailable" collapsed all three into one word
 *    that described none of them.
 *
 * Pure functions: no React, no network. Every string returned is a statement about what is on
 * disk, never an inference about the market.
 */

export type MacdRead = {
  /** Which way the histogram is moving, as the indicator snapshot reported it. */
  direction: 'up' | 'down' | null
  /** The snapshot's own signal word (BULLISH / BEARISH / NEUTRAL), uppercased as stored. */
  signal: string | null
}

export type MacdLabel = {
  /** What the row prints after "MACD ". */
  label: string
  /** Why there is no number, or null when the label is self-explanatory. */
  why: string | null
}

const NO_MACD_ON_SNAPSHOT = 'the indicator snapshot has no MACD for this symbol'
const NOT_ON_DESK = 'this symbol is not on the re-entry decision desk'

/** Read the desk row's MACD fields, refusing any direction the snapshot did not actually say. */
export function macdReadFromDeskRow(row: any): MacdRead {
  const direction = String(row?.macd_histogram_direction ?? '').trim().toLowerCase()
  const signal = String(row?.macd_signal ?? '').trim()
  return {
    direction: direction === 'up' || direction === 'down' ? direction : null,
    signal: signal || null,
  }
}

/**
 * The MACD label for a row.
 *
 * `histogram` is the magnitude a packet may carry. No producer measured on 2026-11-07 supplies one,
 * so this branch is dormant in practice — it exists so that a future producer is used rather than
 * ignored, and so the direction path is never a quiet downgrade of a real number.
 */
export function macdLabel(input: {
  histogram: number | null
  slope: number | null
  read: MacdRead
  /** Whether the decision desk has a row for this symbol at all — the difference between
   *  "no reading" and "never asked". */
  onDesk: boolean
}): MacdLabel {
  const { histogram, slope, read, onDesk } = input
  if (histogram !== null && histogram !== undefined) {
    const sign = histogram >= 0 ? 'pos' : 'neg'
    const arrow = slope === null || slope === undefined ? '' : slope > 0 ? '↑' : slope < 0 ? '↓' : ''
    return { label: `${sign}${arrow}`, why: null }
  }
  if (read.direction !== null) {
    // "down · neutral" is two facts the snapshot gave us; neither is a magnitude.
    const signal = read.signal ? ` · ${read.signal.toLowerCase()}` : ''
    return { label: `${read.direction}${signal}`, why: null }
  }
  return { label: 'n/a', why: onDesk ? NO_MACD_ON_SNAPSHOT : NOT_ON_DESK }
}

/**
 * The catalyst line for a row.
 *
 * `watch` is the watchlist item the page loaded for the symbol (null when the symbol has no
 * watchlist row). The three outcomes are distinguishable from what the page already holds.
 */
export function catalystLabel(watch: any): string {
  const headline = String(watch?.catalyst_headline ?? '').trim()
  if (headline) return headline
  if (!watch) return 'no watchlist row for this symbol'
  // Nothing on the row. The server picks the newest eligible headline and then applies an identity
  // guard, which can leave the field null even when older headlines on file do name the symbol
  // (measured 2026-11-07: 4 of 11 gap symbols; see the DONE note for LQ-20261107-235). The page
  // therefore says what it holds, not what the world contains.
  return 'no catalyst headline on this symbol\'s watchlist row'
}
