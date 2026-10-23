/**
 * Date-only `as_of` values, rendered as dates (P3 site validation 2026-10-23, operator-approved mockups).
 *
 * Several producers hold only a calendar date for a clock: Schwab account `source_as_of`, holdings
 * `holdings_as_of`, a P&L session. Some publish it bare ("2026-10-22"); some widen it to a timestamp
 * at UTC midnight ("2026-10-22T00:00:00+00:00"). Rendered as a time, the second becomes
 * "Oct 21 20:00 ET": a clock nobody observed, on the wrong day.
 *
 * Rule: a bare date, or a stamp at exactly 00:00:00(.000…) UTC, is DATE-ONLY. It is shown as
 * "Oct 22 (date only)" and never converted to a zone. Every other zoned stamp is shown in ET.
 * An unzoned stamp is shown as published, because converting it means assuming a zone.
 *
 * Known edge: a genuine observation at exactly 20:00:00.000 EDT (00:00:00 UTC) reads as date-only.
 * Producers stamp with seconds and microseconds, so a whole-second UTC midnight is in practice a
 * widened date. The full raw value always stays in the tooltip or the drill.
 */

const BARE_DATE = /^(\d{4}-\d{2}-\d{2})$/
const UTC_MIDNIGHT = /^(\d{4}-\d{2}-\d{2})[T ]00:00(?::00(?:\.0+)?)?(?:Z|[+-]00:?00)$/i
const ZONED = /(?:Z|[+-]\d{2}:?\d{2})$/i
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** The calendar date when `raw` is a date-only value (bare, or widened to UTC midnight), else null. */
export function dateOnlyPart(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const s = raw.trim()
  const m = s.match(BARE_DATE) ?? s.match(UTC_MIDNIGHT)
  return m ? m[1] : null
}

export function isDateOnly(raw: unknown): boolean {
  return dateOnlyPart(raw) != null
}

/** "2026-10-22" → "Oct 22". Pure string arithmetic: no Date, no zone. */
export function monthDay(ymd: string): string {
  const [, mo, d] = ymd.split('-').map(Number)
  return `${MONTHS[(mo || 1) - 1]} ${d}`
}

function etParts(d: Date): { md: string; hm: string } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(d)
  const get = (t: string) => parts.find(p => p.type === t)?.value ?? ''
  return { md: `${get('month')} ${get('day')}`, hm: `${get('hour')}:${get('minute')}` }
}

/**
 * One display string for an `as_of`-style value.
 *   date-only            → "Oct 22 (date only)"
 *   zoned timestamp      → "Oct 23 08:09 ET"   (timeOnly: "08:09 ET")
 *   unzoned timestamp    → "2026-10-23 08:09"  (as published; no zone is assumed)
 *   missing              → null
 */
export function fmtAsOf(raw: unknown, opts?: { timeOnly?: boolean }): string | null {
  if (raw == null) return null
  const s = String(raw).trim()
  if (!s) return null
  const day = dateOnlyPart(s)
  if (day) return `${monthDay(day)} (date only)`
  if (!ZONED.test(s)) return s.slice(0, 16).replace('T', ' ')
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s.slice(0, 16).replace('T', ' ')
  const { md, hm } = etParts(d)
  return opts?.timeOnly ? `${hm} ET` : `${md} ${hm} ET`
}
