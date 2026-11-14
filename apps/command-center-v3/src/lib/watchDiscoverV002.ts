/** Watch → Discover: recent discoveries (S7/WR-04/WR-05, operator 09:30 correction).
 *
 *  Reads the live candidate-discovery events (candidate_discovery_events over the existing
 *  /api/v2/candidate-discovery/recent contract), shows each discovery's source, reason and captured time, and supports
 *  Add to My List through the existing membership write (POST /api/v2/prospects/add-to-watchlist) with a PERSISTED
 *  readback (GET /api/v2/watchlist/symbols?source=ai_watchlist). An accepted POST is never shown as stored: only the
 *  readback decides. Watching/research only — no order, no size, no stop, no provider substitution. */
import { etText, unwrap } from './watchSetupsV002'

export const RECENT_API = '/api/v2/candidate-discovery/recent?limit=50'
export const ADD_API = '/api/v2/prospects/add-to-watchlist'
/** No `source` filter: `source=ai_watchlist` filters `in_ai_watchlist = true`, so the endpoint could never
 *  answer "not in My List" and the false branch would be dead code (review F2). Unfiltered, a row carries its
 *  own `in_ai_watchlist`, and a symbol beyond the endpoint's LIMIT 200 is simply absent → UNKNOWN, not false.
 *  The freshly added row upserts updated_at=NOW(), so sort=updated puts it first. */
export const MEMBERSHIP_API = '/api/v2/watchlist/symbols?sort=updated'

/** What actually writes candidate_discovery_events, and when (read from the repo, 2026-11-14):
 *  the premarket pipeline runs `scripts/candidate_discovery_orchestrator.py --apply` as step
 *  candidate_discovery_orchestrator on weekdays (cron line verbatim `15 6 * * 1-5`, stage start 05:45 ET,
 *  rows land ~05:51 ET — 100 rows/day, 4 sources). It does not run on weekends or market holidays. A flat
 *  max-age therefore grades every Sunday STALE while the producer is perfectly healthy: staleness is
 *  measured against the last run that was DUE, not against wall-clock age. */
export type DiscoverySchedule = {
  label: string
  runHourEt: number
  runMinuteEt: number
  /** Rows land a few minutes after the slot opens; a run inside this window is simply not due yet. */
  graceMinutes: number
}
export const DISCOVERY_SCHEDULE: DiscoverySchedule = {
  label: 'premarket pipeline · step candidate_discovery_orchestrator · weekdays 05:45 ET',
  runHourEt: 5,
  runMinuteEt: 45,
  graceMinutes: 30,
}

const ET_FMT = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
})
/** ET wall-clock parts for an instant (handles EST/EDT). */
export function etParts(ms: number): { y: number; mo: number; d: number; h: number; mi: number } {
  const p: Record<string, string> = {}
  for (const x of ET_FMT.formatToParts(new Date(ms))) if (x.type !== 'literal') p[x.type] = x.value
  return { y: Number(p.year), mo: Number(p.month), d: Number(p.day), h: Number(p.hour) % 24, mi: Number(p.minute) }
}
/** The instant at which the ET wall clock reads y-mo-d h:mi (offset measured, not assumed). */
export function etWallToMs(y: number, mo: number, d: number, h: number, mi: number): number {
  const guess = Date.UTC(y, mo - 1, d, h, mi)
  const q = etParts(guess)
  const offMinutes = (Date.UTC(q.y, q.mo - 1, q.d, q.h, q.mi) - guess) / 60000
  return guess - offMinutes * 60000
}
const isWeekday = (y: number, mo: number, d: number) => {
  const wd = new Date(Date.UTC(y, mo - 1, d)).getUTCDay()
  return wd >= 1 && wd <= 5
}
const slotOn = (y: number, mo: number, d: number, s: DiscoverySchedule) => etWallToMs(y, mo, d, s.runHourEt, s.runMinuteEt)

/** The most recent scheduled run slot at or before now (weekdays only; market holidays are not modelled). */
export function lastScheduledRun(nowMs: number, s: DiscoverySchedule = DISCOVERY_SCHEDULE): number {
  const t = etParts(nowMs)
  for (let back = 0; back < 10; back++) {
    const day = new Date(Date.UTC(t.y, t.mo - 1, t.d - back))
    const y = day.getUTCFullYear(), mo = day.getUTCMonth() + 1, d = day.getUTCDate()
    if (!isWeekday(y, mo, d)) continue
    const slot = slotOn(y, mo, d, s)
    if (slot <= nowMs) return slot
  }
  return slotOn(t.y, t.mo, t.d, s)
}
/** The next scheduled run slot strictly after now. */
export function nextScheduledRun(nowMs: number, s: DiscoverySchedule = DISCOVERY_SCHEDULE): number {
  const t = etParts(nowMs)
  for (let fwd = 0; fwd < 10; fwd++) {
    const day = new Date(Date.UTC(t.y, t.mo - 1, t.d + fwd))
    const y = day.getUTCFullYear(), mo = day.getUTCMonth() + 1, d = day.getUTCDate()
    if (!isWeekday(y, mo, d)) continue
    const slot = slotOn(y, mo, d, s)
    if (slot > nowMs) return slot
  }
  return slotOn(t.y, t.mo, t.d + 1, s)
}

export type DiscoveryClock = {
  state: 'OK' | 'STALE' | 'UNKNOWN'
  label: string
  reason: string | null
  asOfText: string | null
  /** Last run that was already due to have produced rows. */
  dueText: string
  /** Next scheduled run instead of a bare max-age. */
  nextText: string
  /** Named recovery action, only when STALE. */
  recovery: string | null
}

export type DiscoveryRow = { symbol: string; source: string; reason: string; at: string | null; degraded: boolean }
const str = (v: unknown): string => (typeof v === 'string' ? v : '')

export function discoveryRows(body: unknown): DiscoveryRow[] {
  // The page's `useApi` hands subscribers `json.data`, not the envelope (useApi.ts apply()), so the live read arrives as
  // the bare ARRAY of events — an object-only reader saw 0 rows and the panel then asserted an empty successful read,
  // which contradicted the API (SEV-2, R5c f7faf772d). Accept the array first; keep the enveloped shapes for fixtures and
  // for any caller that passes the whole body.
  const b = unwrap(body)
  const list = Array.isArray(body) ? body
    : Array.isArray(b?.data) ? b.data
    : Array.isArray(b?.events) ? b.events
    : Array.isArray(b?.items) ? b.items
    : []
  return list.flatMap((r: any) => {
    const symbol = str(r?.symbol).toUpperCase()
    if (!symbol) return []
    return [{ symbol, source: str(r?.source_key) || 'unknown source', reason: str(r?.reason), at: str(r?.created_at) || null, degraded: r?.degraded === true }]
  })
}

/** The newest event is the clock. No rows means no window, not a green read: an empty successful read is labelled
 *  separately by the component. */
export function discoveryAsOf(rows: DiscoveryRow[]): string | null {
  let best: number | null = null
  let iso: string | null = null
  for (const r of rows) {
    const t = r.at ? Date.parse(r.at) : NaN
    if (Number.isFinite(t) && (best === null || t > best)) { best = t; iso = r.at }
  }
  return iso
}

/** Grade against the last run that was DUE (weekday 05:45 ET + grace), not against wall-clock age. */
export function discoveryClock(rows: DiscoveryRow[], nowMs: number, s: DiscoverySchedule = DISCOVERY_SCHEDULE): DiscoveryClock {
  const asOf = discoveryAsOf(rows)
  const asOfText = etText(asOf)
  const t = asOf ? Date.parse(asOf) : NaN
  const last = lastScheduledRun(nowMs, s)
  // A slot is satisfied by any row at or after its START (rows land ~05:51, inside the grace). The grace
  // only decides which slot must be satisfied yet: inside the run window, grade the slot before it.
  const cutoff = nowMs >= last + s.graceMinutes * 60000 ? last : lastScheduledRun(last - 1, s)
  const dueText = etText(new Date(cutoff).toISOString()) ?? 'an unknown time'
  const nextText = etText(new Date(nextScheduledRun(nowMs, s)).toISOString()) ?? 'an unknown time'
  const base = { asOfText, dueText, nextText }
  if (!Number.isFinite(t)) {
    return { ...base, state: 'UNKNOWN', label: 'UNKNOWN · no timestamp', reason: 'The read carries no usable event time.', recovery: null }
  }
  if (t > nowMs + 120_000) {
    return { ...base, state: 'UNKNOWN', label: 'UNKNOWN · event time in the future', reason: 'The newest event is later than this clock.', recovery: null }
  }
  if (t >= cutoff) {
    return { ...base, state: 'OK', label: `OK · newest event ${asOfText}`, reason: null, recovery: null }
  }
  return {
    ...base,
    state: 'STALE',
    label: `STALE · newest event ${asOfText ?? 'unknown'}`,
    reason: `No discovery event since the run due ${dueText} (${s.label}; next run ${nextText}).`,
    recovery: `Check logs/candidate_discovery.log and the premarket pipeline run for ${dueText}; then re-run step candidate_discovery_orchestrator.`,
  }
}

export type AddPost = (body: { symbol: string; strategy_type: string; source: string }) => Promise<{ ok: boolean; status: number; body: unknown }>
/** The membership write as a testable unit. `added:true` in the answer is an ACCEPTED write, not a stored one. */
export async function addToMyList(symbol: string, post: AddPost): Promise<{ ok: boolean; message: string }> {
  try {
    const r = await post({ symbol, strategy_type: 'discovery', source: 'discovery' })
    const j = unwrap(r.body)
    if (!r.ok || j?.ok === false) throw new Error(String(j?.error || `HTTP ${r.status}`))
    return { ok: true, message: `Add sent for ${symbol}. The readback below decides whether it is stored.` }
  } catch (e) {
    return { ok: false, message: `Failed: ${String((e as Error).message || e).slice(0, 100)}` }
  }
}

/** true = persisted and read back; false = the readback lists the symbol as not in My List; null = the readback did not
 *  include the symbol, so membership is UNKNOWN (never rendered as "not in My List"). */
export function isInMyList(body: unknown, symbol: string): boolean | null {
  const b = unwrap(body)
  const list = Array.isArray(b?.symbols) ? b.symbols : []
  const want = symbol.toUpperCase()
  const row = list.find((r: any) => str(r?.symbol).toUpperCase() === want)
  if (!row) return null
  return row?.in_ai_watchlist === true
}
