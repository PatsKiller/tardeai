/** LQ-20261107-1253 amendments 3/4 + 1260/1261 — the UPDATED badge, per-source chips and schedule chip row.
 *  The server wrote the real source clocks and today's slots; the client only compares them with its own clock. */

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
  return {
    badge: badgeText(s.updated_at), ago: agoText(nowMs - upd), missed: missedAt != null,
    missedText: missedAt ? `The ${missedAt} update did not run — this page may be out of date` : null,
    nextText: `next ${s.next_refresh_text}`, chips: s.sources, slots,
  }
}
