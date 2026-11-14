/** LQ-20261107-1253 amendments 3/4 + 1260/1261 — the UPDATED badge, per-source chips and schedule chip row.
 *  The server wrote the real source clocks and today's slots; the client only compares them with its own clock.
 *  LQ-20261107-1269: a snapshot whose own clock is older than the operator's limit is a STALE badge even when no
 *  fixed slot was missed (the lane can run and write nothing, and a dead producer must not look fresh). */

/** Operator limits (LQ-20261107-1269): 30 min while the market is open, 4 h while it is closed. */
export const STALE_MARKET_MS = 30 * 60_000
export const STALE_CLOSED_MS = 4 * 3_600_000

export interface StampChip { key: string; label: string; at: string | null; at_text: string | null; age_text: string; warn: boolean; warn_text: string | null; note: string | null }
export interface StampSchedule {
  trading_day: boolean; fixed: Array<{ at: string; text: string }>; cio: string[]
  market_open: string | null; market_close: string | null; grace_min?: number
}
export interface StampWire {
  updated_at: string; updated_text: string; next_refresh_at: string; next_refresh_text: string
  sources: StampChip[]; any_warn: boolean; schedule: StampSchedule
}
export interface SlotView { text: string; at: string; state: 'done' | 'next' | 'later' | 'missed'; cio: boolean }
export interface StampModel {
  badge: string; ago: string; missed: boolean; missedText: string | null; nextText: string; chips: StampChip[]; slots: SlotView[]
  /** LQ-20261107 H4: the server's frozen next refresh is already in the past — named, never shown as "next". */
  missedRefreshText: string | null
  /** LQ-1269: the snapshot is older than the operator's limit for the current session (see STALE_MARKET_MS). */
  stale: boolean; staleText: string | null; staleLimitText: string
}

export function agoText(ms: number): string {
  const m = Math.floor(ms / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  if (m < 1440) return `${Math.floor(m / 60)} h ago`
  return `${Math.floor(m / 1440)} d ago`
}

/** "UPDATED 6:00 PM ET · SUN 11-08" from the instant, in ET. */
export function badgeText(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', month: '2-digit', day: '2-digit', hour: 'numeric', minute: '2-digit', hour12: true }).formatToParts(new Date(iso))
  const p: Record<string, string> = {}
  for (const x of parts) p[x.type] = x.value
  return `UPDATED ${p.hour}:${p.minute} ${String(p.dayPeriod).toUpperCase()} ET · ${String(p.weekday).toUpperCase()} ${p.month}-${p.day}`
}

export function stampModel(s: StampWire | null | undefined, nowMs: number = Date.now()): StampModel | null {
  if (!s?.schedule) return null
  const upd = new Date(s.updated_at).getTime()
  const grace = (s.schedule.grace_min ?? 30) * 60_000
  const sch = s.schedule
  const open = sch.market_open ? new Date(sch.market_open).getTime() : null
  const close = sch.market_close ? new Date(sch.market_close).getTime() + 15 * 60_000 : null
  const cio = new Set(sch.cio)
  let nextSeen = false
  let missedAt: string | null = null
  const slots: SlotView[] = sch.fixed.map(f => {
    const t = new Date(f.at).getTime()
    let state: SlotView['state'] = 'later'
    if (t <= nowMs) {
      state = 'done'
      // a fixed slot in market hours, more than 30 min past, with no build since it: the lane failed
      if (sch.trading_day && open != null && close != null && t >= open && t <= close && nowMs - t > grace && upd < t) {
        state = 'missed'
        missedAt ??= f.text
      }
    } else if (!nextSeen) {
      state = 'next'
      nextSeen = true
    }
    return { text: f.text, at: f.at, state, cio: cio.has(f.at) }
  })
  // LQ-1269: the snapshot's OWN clock decides staleness. 30 min while the regular session is open. Otherwise the
  // limit follows the cadence the schedule itself declares: on a day the producer runs a slower registered cadence
  // (weekends/holidays = 0 */6 * * 0,6), one gap + grace instead of a fixed 4 h, which would call a healthy
  // six-hourly snapshot stale for hours of every cycle (LQ-20261107 H4). No slot list -> the 4 h limit stands, and
  // the derived limit never drops BELOW the operator's 4 h: a payload written by an older table can declare a
  // two-hourly weekend that no scheduler fires, and reading that as a 2.5 h limit would flag a healthy snapshot.
  const inMarket = sch.trading_day && open != null && close != null && nowMs >= open && nowMs <= close
  let limitMs = inMarket ? STALE_MARKET_MS : STALE_CLOSED_MS
  let staleLimitText = inMarket ? '30 min during market hours' : '4 h while the market is closed'
  if (!sch.trading_day && sch.fixed.length >= 2) {
    const ts = sch.fixed.map(f => new Date(f.at).getTime()).sort((a, b) => a - b)
    const gaps = ts.slice(1).map((t, i) => t - ts[i]).filter(g => Number.isFinite(g) && g > 0)
    if (gaps.length > 0) {
      limitMs = Math.max(Math.max(...gaps) + grace, STALE_CLOSED_MS)
      staleLimitText = `${Math.round((limitMs / 3_600_000) * 10) / 10} h while the market is closed`
    }
  }
  const ageMs = nowMs - upd
  const stale = Number.isFinite(ageMs) && ageMs > limitMs
  // LQ-20261107 H4: next_refresh_at is frozen at build time. Once it is in the past, printing it as "next" promises a
  // refresh that has already failed to happen; say so, and name the next slot the schedule actually still has ahead.
  // The alarm is only raised when that instant is one of the schedule's OWN slots: a snapshot built by an older table
  // can carry a time no scheduler ever fires, and calling that a missed refresh would be a claim about a fire that
  // never existed. The schedule row is authoritative; the frozen value is only evidence when the two agree.
  const serverNextMs = new Date(s.next_refresh_at).getTime()
  const nextIsPast = Number.isFinite(serverNextMs) && serverNextMs <= nowMs
  const nextWasScheduled = sch.fixed.some(f => new Date(f.at).getTime() === serverNextMs)
  const nextSlot = slots.find(x => x.state === 'next') ?? null
  return {
    badge: badgeText(s.updated_at), ago: agoText(nowMs - upd), missed: missedAt != null,
    missedText: missedAt ? `The ${missedAt} update did not run — this page may be out of date` : null,
    nextText: nextIsPast ? (nextSlot ? `next ${nextSlot.text}` : 'no further slot scheduled today') : `next ${s.next_refresh_text}`,
    missedRefreshText: nextIsPast && nextWasScheduled
      ? `The ${s.next_refresh_text} refresh did not run — ${nextSlot ? `the next slot is ${nextSlot.text}` : 'no later slot is scheduled today'}`
      : null,
    chips: s.sources, slots,
    stale, staleLimitText,
    staleText: stale ? `This snapshot is ${agoText(ageMs)} — past the ${staleLimitText} limit` : null,
  }
}
