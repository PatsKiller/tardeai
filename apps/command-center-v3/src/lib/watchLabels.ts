/**
 * Plain-English labels for the Watch surfaces (BOARD row 38, P2/P3 audit 2026-11-04).
 *
 * The audit found internal codes rendered as if they were meaning: `DATA_UNAVAILABLE`, `DETERMINISTIC_FAIL`,
 * `ANSWERED_PENDING_CIO` on `/watchlist`. They are identifiers, not sentence text; a reader should get the fact
 * ("Data unavailable") and the identifier stays recoverable in the element's `title` (the same rule displayLabels.ts
 * uses) so a support question can still name the exact code.
 *
 * Pure: no React, no I/O. Unknown codes are NOT mapped by guesswork — they are humanised mechanically
 * (`SOME_NEW_CODE` → "Some new code") so a new state is legible the day it ships, and the raw value is still in the
 * caller's `title`. Nothing here ever invents a meaning it was not given.
 */

//: State of a card's Trade AI read. Values produced by the decision packet / data broker.
const TRADE_AI_STATE: Record<string, string> = {
  WAIT: 'Wait',
  READY: 'Ready',
  MANAGING: 'Managing',
  AVOID: 'Avoid',
  BLOCKED: 'Blocked',
  DETERMINISTIC_FAIL: 'Failed its checks',
  DATA_UNAVAILABLE: 'Data unavailable',
  STALE: 'Stale data',
  UNKNOWN: 'Unknown',
}

//: A review's status. NOT_RUN is the brokered default when a review has never run for the card.
const REVIEW_STATUS: Record<string, string> = {
  NOT_RUN: 'Not run',
  RUNNING: 'Running',
  UNREVIEWED: 'Unreviewed',
  ANSWERED_PENDING_CIO: 'Answer ready · CIO decision pending',
  COMPLETE: 'Complete',
  COMPLETED: 'Complete',
  FAILED: 'Failed',
  STALE: 'Stale',
  UNAVAILABLE: 'Unavailable',
}

//: How fresh the card's quote is. These are the filter vocabulary the page offers.
const QUOTE_FRESHNESS: Record<string, string> = {
  CURRENT: 'Current',
  PREMARKET_CURRENT: 'Current · pre-market',
  AFTER_HOURS_CURRENT: 'Current · after hours',
  STALE: 'Stale',
  DATA_UNAVAILABLE: 'Unavailable',
}

import { humanizeCode } from './displayLabels'

/** The Trade AI state as a sentence fragment. Unknown codes are humanised, never dropped or guessed. */
export function tradeAiStateLabel(raw: unknown): string {
  const code = String(raw ?? '').trim().toUpperCase()
  if (!code) return ''
  return TRADE_AI_STATE[code] ?? humanizeCode(code)
}

/** A review status as a sentence fragment. A missing status is the brokered default, "Not run". */
export function reviewStatusLabel(raw: unknown): string {
  const code = String(raw ?? '').trim().toUpperCase()
  if (!code) return REVIEW_STATUS.NOT_RUN
  return REVIEW_STATUS[code] ?? humanizeCode(code)
}

/** How fresh the quote is, as a sentence fragment. */
export function quoteFreshnessLabel(raw: unknown): string {
  const code = String(raw ?? '').trim().toUpperCase()
  if (!code) return ''
  return QUOTE_FRESHNESS[code] ?? humanizeCode(code)
}
