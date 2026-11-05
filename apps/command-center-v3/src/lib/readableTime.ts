/**
 * Readable times for operator-facing text (site sweep 2026-10-25).
 *
 * The sweep found raw ISO stamps ("2026-10-25T13:53:48.866966+00:00") printed on Home source clocks,
 * Re-Entry, Look-through, the Journal freshness chips, Calendar event provenance and Replay. Every one
 * of those is rendered through `fmtAsOf` (the house as-of formatter: zoned → "Oct 25 09:53 ET",
 * date-only → "Oct 22 (date only)", unzoned → as published without the "T").
 *
 * `readableTimesInText` rewrites ISO stamps embedded in a server-composed sentence ("Ledger synced
 * 2026-10-23T22:15:02+00:00 · ledger row write"); bare calendar dates are left alone. Callers keep the
 * raw value in a title / dateTime attribute so the exact stamp stays one hover or long-press away.
 */
import { fmtAsOf } from './asOfDisplay.ts'

// A date, a T or space, a clock, optional seconds/fraction, optional zone. A bare date never matches.
const ISO_STAMP = /\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?(?![\d:])/g

/** One stamp → display text; null/blank → null. */
export function readableTime(raw: unknown, opts?: { timeOnly?: boolean }): string | null {
  return fmtAsOf(raw, opts)
}

/** Replace every ISO stamp inside `text` with its display form. Non-strings pass through as ''. */
export function readableTimesInText(text: unknown): string {
  if (text == null) return ''
  return String(text).replace(ISO_STAMP, stamp => fmtAsOf(stamp) ?? stamp)
}

/** True when `text` still carries a raw ISO stamp (date + "T" + clock). Used by tests and guards. */
export function hasRawIsoStamp(text: unknown): boolean {
  return /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(String(text ?? ''))
}
