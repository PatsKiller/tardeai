/**
 * Market-session-aware freshness — the TypeScript mirror of scripts/lib/session_freshness.py.
 *
 * Live audit 2026-10-25 (a Sunday): Friday-close data read "STALE", "refresh overdue", "Updated 2d ago"
 * in amber, because each surface aged it in wall-clock hours. Friday's close is the latest data that can
 * exist while the exchange is shut. One rule, used by DeskPage source clocks, quote cells, the CIO market
 * view and Ready now:
 *
 *  - Market OPEN (regular hours): wall-clock age against maxAgeHours, unchanged.
 *  - Market CLOSED: a stamp at/after the last session close (less graceMinutes) is the latest possible →
 *    state 'latest_close' with the phrase "Market closed · last close Fri 4:00 PM ET · next update Mon".
 *  - Older than that close still ages, against closedMaxAgeHours (data_source_authority
 *    stale_after_hours_closed) when declared, else maxAgeHours. Nothing is made to look younger.
 *
 * NYSE holidays and 1:00 PM early closes follow cio_market_session.py (same rules, same test table).
 * No network, no clock reads except the `now` the caller passes.
 */

const ET = 'America/New_York'
const HOUR_MS = 3_600_000
const DAY_MS = 86_400_000
const RTH_OPEN_MIN = 9 * 60 + 30
const RTH_CLOSE_MIN = 16 * 60
const EARLY_CLOSE_MIN = 13 * 60
const LOOK_DAYS = 10

export type SessionFreshnessState = 'fresh' | 'latest_close' | 'stale' | 'unknown'
export type SessionFreshness = {
  state: SessionFreshnessState
  stale: boolean
  ageHours: number | null
  marketOpen: boolean
  lastClose: Date | null
  nextOpen: Date | null
  /** "Market closed · last close Fri 4:00 PM ET · next update Mon" while closed; null while open. */
  phrase: string | null
  reason: string | null
}

type Ymd = { y: number; m: number; d: number }
const ymdKey = ({ y, m, d }: Ymd) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
const fromUtcNoon = (ms: number): Ymd => { const t = new Date(ms); return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() } }
const noon = ({ y, m, d }: Ymd) => Date.UTC(y, m - 1, d, 12)
const addDays = (day: Ymd, n: number): Ymd => fromUtcNoon(noon(day) + n * DAY_MS)
const weekday = (day: Ymd) => new Date(noon(day)).getUTCDay() // 0 Sun … 6 Sat

function nthWeekday(y: number, m: number, wd: number, n: number): Ymd {
  if (n > 0) {
    const first = { y, m, d: 1 }
    return addDays(first, ((wd - weekday(first) + 7) % 7) + (n - 1) * 7)
  }
  const last = addDays({ y: m === 12 ? y + 1 : y, m: m === 12 ? 1 : m + 1, d: 1 }, -1)
  return addDays(last, -((weekday(last) - wd + 7) % 7))
}

function easter(y: number): Ymd {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4
  const g = Math.floor((8 * b + 13) / 25), h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7, mm = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * mm + 114) / 31), day = ((h + l - 7 * mm + 114) % 31) + 1
  return { y, m: month, d: day }
}

function observed(day: Ymd): Ymd {
  const wd = weekday(day)
  return wd === 6 ? addDays(day, -1) : wd === 0 ? addDays(day, 1) : day
}

const holidayCache = new Map<number, { hol: Set<string>; early: Set<string> }>()
function calendar(y: number) {
  const hit = holidayCache.get(y)
  if (hit) return hit
  const hol = new Set<string>()
  const jan1 = { y, m: 1, d: 1 }
  if (weekday(jan1) === 0) hol.add(ymdKey({ y, m: 1, d: 2 }))
  else if (weekday(jan1) !== 6) hol.add(ymdKey(jan1))
  hol.add(ymdKey(nthWeekday(y, 1, 1, 3)))           // MLK
  hol.add(ymdKey(nthWeekday(y, 2, 1, 3)))           // Washington's Birthday
  hol.add(ymdKey(addDays(easter(y), -2)))           // Good Friday
  hol.add(ymdKey(nthWeekday(y, 5, 1, -1)))          // Memorial Day
  if (y >= 2022) hol.add(ymdKey(observed({ y, m: 6, d: 19 })))
  hol.add(ymdKey(observed({ y, m: 7, d: 4 })))
  hol.add(ymdKey(nthWeekday(y, 9, 1, 1)))           // Labor Day
  const thanks = nthWeekday(y, 11, 4, 4)
  hol.add(ymdKey(thanks))
  hol.add(ymdKey(observed({ y, m: 12, d: 25 })))
  const early = new Set<string>()
  for (const d of [{ y, m: 7, d: 3 }, { y, m: 12, d: 24 }]) {
    const wd = weekday(d)
    if (wd >= 1 && wd <= 5 && !hol.has(ymdKey(d))) early.add(ymdKey(d))
  }
  early.add(ymdKey(addDays(thanks, 1)))
  const out = { hol, early }
  holidayCache.set(y, out)
  return out
}

export function isTradingDay(day: Ymd): boolean {
  const wd = weekday(day)
  return wd >= 1 && wd <= 5 && !calendar(day.y).hol.has(ymdKey(day))
}

function etParts(at: Date): Ymd & { minutes: number } {
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: ET, hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  const p = Object.fromEntries(fmt.formatToParts(at).filter(x => x.type !== 'literal').map(x => [x.type, x.value])) as Record<string, string>
  return { y: Number(p.year), m: Number(p.month), d: Number(p.day), minutes: (Number(p.hour) % 24) * 60 + Number(p.minute) }
}

/** The UTC instant of an ET wall-clock minute on `day` (DST measured for that date, no table). */
function etInstant(day: Ymd, minutes: number): Date {
  const guess = Date.UTC(day.y, day.m - 1, day.d, Math.floor(minutes / 60), minutes % 60)
  // ET is UTC-4 or UTC-5; probe both and keep the one whose ET reading matches.
  for (const off of [4, 5]) {
    const cand = new Date(guess + off * HOUR_MS)
    const p = etParts(cand)
    if (p.y === day.y && p.m === day.m && p.d === day.d && p.minutes === minutes) return cand
  }
  return new Date(guess + 5 * HOUR_MS)
}

function closeMinutes(day: Ymd): number { return calendar(day.y).early.has(ymdKey(day)) ? EARLY_CLOSE_MIN : RTH_CLOSE_MIN }

export function marketIsOpen(now: Date): boolean {
  const p = etParts(now)
  return isTradingDay(p) && p.minutes >= RTH_OPEN_MIN && p.minutes < closeMinutes(p)
}

export function lastSessionClose(now: Date): Date | null {
  let day: Ymd = etParts(now)
  for (let i = 0; i < LOOK_DAYS; i++) {
    if (isTradingDay(day)) {
      const close = etInstant(day, closeMinutes(day))
      if (close.getTime() <= now.getTime()) return close
    }
    day = addDays(day, -1)
  }
  return null
}

export function nextSessionOpen(now: Date): Date | null {
  let day: Ymd = etParts(now)
  for (let i = 0; i < LOOK_DAYS; i++) {
    if (isTradingDay(day)) {
      const open = etInstant(day, RTH_OPEN_MIN)
      if (open.getTime() > now.getTime()) return open
    }
    day = addDays(day, 1)
  }
  return null
}

const clockText = (at: Date) => `${new Intl.DateTimeFormat('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit', hour12: true }).format(at)} ET`
const dow = (at: Date) => new Intl.DateTimeFormat('en-US', { timeZone: ET, weekday: 'short' }).format(at)
const sameEtDay = (a: Date, b: Date) => ymdKey(etParts(a)) === ymdKey(etParts(b))
const etDayDiff = (a: Date, b: Date) => Math.round((noon(etParts(b)) - noon(etParts(a))) / DAY_MS)

/** "Market closed · last close Fri 4:00 PM ET · next update Mon"; null during regular hours. */
export function closedPhrase(now: Date): string | null {
  if (marketIsOpen(now)) return null
  const parts = ['Market closed']
  const close = lastSessionClose(now)
  if (close) parts.push(`last close ${sameEtDay(close, now) ? 'today' : dow(close)} ${clockText(close)}`)
  const next = nextSessionOpen(now)
  if (next) {
    if (sameEtDay(next, now)) parts.push(`next update today ${clockText(next)}`)
    else if (etDayDiff(now, next) < 7) parts.push(`next update ${dow(next)}`)
    else parts.push(`next update ${new Intl.DateTimeFormat('en-US', { timeZone: ET, weekday: 'short', month: 'short', day: 'numeric' }).format(next).replace(',', '')}`)
  }
  return parts.join(' · ')
}

function parseInstant(value: unknown): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value !== 'string' || !value.trim()) return null
  // An instant needs a zone; a naive or date-only stamp is not one (never invent midnight).
  if (!/T.*(?:Z|[+-]\d\d:?\d\d)$/.test(value.trim())) return null
  const ms = Date.parse(value.trim())
  return Number.isFinite(ms) ? new Date(ms) : null
}

export function sessionFreshness(opts: {
  asOf: unknown
  now: Date | number
  maxAgeHours: number
  closedMaxAgeHours?: number
  graceMinutes?: number
  futureSkewMinutes?: number
}): SessionFreshness {
  const now = typeof opts.now === 'number' ? new Date(opts.now) : opts.now
  const at = parseInstant(opts.asOf)
  const marketOpen = marketIsOpen(now)
  const lastClose = lastSessionClose(now)
  const nextOpen = nextSessionOpen(now)
  const base = { marketOpen, lastClose, nextOpen, phrase: null as string | null }
  if (!at) return { ...base, state: 'unknown', stale: true, ageHours: null, reason: 'no usable update time' }
  const ageHours = (now.getTime() - at.getTime()) / HOUR_MS
  if (at.getTime() > now.getTime() + (opts.futureSkewMinutes ?? 5) * 60_000) return { ...base, state: 'unknown', stale: true, ageHours, reason: 'update time is in the future' }
  if (marketOpen) {
    const stale = ageHours > opts.maxAgeHours
    return { ...base, state: stale ? 'stale' : 'fresh', stale, ageHours, reason: stale ? `older than ${opts.maxAgeHours} h while the market is open` : null }
  }
  const phrase = closedPhrase(now)
  if (lastClose && at.getTime() >= lastClose.getTime() - (opts.graceMinutes ?? 0) * 60_000) {
    return { ...base, phrase, state: 'latest_close', stale: false, ageHours, reason: null }
  }
  const limit = opts.closedMaxAgeHours ?? opts.maxAgeHours
  const stale = ageHours > limit
  return { ...base, phrase, state: stale ? 'stale' : 'fresh', stale, ageHours, reason: stale ? `older than the last session close and than ${limit} h` : null }
}

/** Wall-clock hours minus hours on non-trading ET calendar days (weekends, exchange holidays). */
export function tradingAgeHours(asOf: unknown, now: Date | number): number | null {
  const end = typeof now === 'number' ? new Date(now) : now
  const start = parseInstant(asOf)
  if (!start) return null
  if (end.getTime() <= start.getTime()) return 0
  let total = end.getTime() - start.getTime()
  let day: Ymd = etParts(start)
  const last = ymdKey(etParts(end))
  for (let i = 0; i < 400; i++) {
    if (!isTradingDay(day)) {
      const lo = Math.max(start.getTime(), etInstant(day, 0).getTime())
      const hi = Math.min(end.getTime(), etInstant(addDays(day, 1), 0).getTime())
      if (hi > lo) total -= hi - lo
    }
    if (ymdKey(day) === last) break
    day = addDays(day, 1)
  }
  return Math.max(0, total) / HOUR_MS
}

/** CIO market view freshness window (the regime classifier publishes after each session). */
export const MARKET_VIEW_MAX_AGE_H = 26

/**
 * Clock suffix for the CIO market view (Home, any page showing the regime): " · Market closed · last close …"
 * when the view is the latest possible, " · Last published view; refresh overdue" only when it really is overdue
 * (market-session aware), '' otherwise. `backendStale` is used only when the stamp is unusable.
 */
export function marketViewNote(asOf: unknown, backendStale: unknown, now: Date | number = Date.now()): string {
  const view = sessionFreshness({ asOf, now, maxAgeHours: MARKET_VIEW_MAX_AGE_H })
  if (view.state === 'latest_close' && view.phrase) return ` · ${view.phrase}`
  if (view.state === 'unknown') return backendStale ? ' · Last published view; refresh overdue' : ''
  return view.stale ? ' · Last published view; refresh overdue' : ''
}
