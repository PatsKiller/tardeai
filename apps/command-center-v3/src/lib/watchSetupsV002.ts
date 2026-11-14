/** Watch v002 Setups / Sectors / Discover / Alerts (LQ-20261107-2993c).
 *
 *  Pure model. Every tab carries its own stamp and grades it OK / STALE / UNKNOWN with an age; nothing is green without a
 *  timestamp and an unread list is never an empty list. Alerts are graded on the EVALUATOR's last run (`liveness_at`),
 *  not on the newest alert row: an armed alert on a dead evaluator is exactly the failure this page must show. */

export const SETUPS_API = '/api/v2/watchpool'
export const SECTORS_API = '/api/v2/watch/sectors'
export const DISCOVER_API = '/api/v2/screener-finds/candidates'
export const ALERTS_API = '/api/v2/watch/alerts/list'
export const ALERTS_POST = '/api/v2/watch/alerts'
export const PULLBACK_API = '/api/v2/pullback-macd/candidates'
export const PAGE_LIMIT = 25
export const SETUPS_MAX_AGE_S = 72 * 3600
export const SECTORS_MAX_AGE_S = 36 * 3600
export const DISCOVER_MAX_AGE_S = 36 * 3600
// Two evaluator periods (cron every 20 min, 09-16 ET): lead ruling until the lane moves to n8n every 5 min.
export const ALERTS_MAX_AGE_S = 2400
// The pullback/MACD screener is cron-scheduled (not per request); its candidates are stamped by the last completed
// scan. A day without a scan is stale, not current.
export const PULLBACK_MAX_AGE_S = 36 * 3600

export type TabKey = 'setups' | 'sectors' | 'discover' | 'alerts' | 'pullback'
export type State = 'OK' | 'STALE' | 'UNKNOWN'
export type Grade = { state: State; ageS: number | null; label: string; basis: string; reason: string | null }

const asRec = (v: unknown): Record<string, any> | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, any>) : null)
export const unwrap = (v: unknown): Record<string, any> | null => { const r = asRec(v); return asRec(r?.data) ?? r }

export function ageText(s: number | null): string {
  if (s === null || !Number.isFinite(s)) return 'age unknown'
  if (s < 90) return '<2 min'
  if (s < 5400) return `${Math.round(s / 60)} min`
  if (s < 172800) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}

/** US Eastern, minute precision, e.g. "Nov 12, 1:20 PM ET". Unparseable or missing → null (never a raw ISO slice). */
export function etText(iso: unknown): string | null {
  const t = typeof iso === 'string' ? Date.parse(iso) : NaN
  if (!Number.isFinite(t)) return null
  const s = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(t))
  return `${s} ET`
}

export function gradeStamp(asOf: unknown, basis: unknown, nowMs: number, maxAgeS: number, expectedMs: number | null = null): Grade {
  const b = typeof basis === 'string' && basis ? basis : 'unspecified'
  const t = typeof asOf === 'string' ? Date.parse(asOf) : NaN
  if (!Number.isFinite(t)) return { state: 'UNKNOWN', ageS: null, label: 'UNKNOWN · no timestamp', basis: b, reason: 'The list carries no usable timestamp.' }
  const ageS = Math.round((nowMs - t) / 1000)
  if (ageS < -120) return { state: 'UNKNOWN', ageS: null, label: 'UNKNOWN · timestamp in the future', basis: b, reason: 'The timestamp is later than this clock.' }
  const age = Math.max(0, ageS)
  // Staleness is measured against when a run was last EXPECTED (market hours), but the label shows the real age.
  const late = expectedMs === null ? age : Math.round((expectedMs - t) / 1000)
  if (late > maxAgeS) return { state: 'STALE', ageS: age, label: `STALE · ${ageText(age)} old`, basis: b, reason: `Older than ${ageText(maxAgeS)}.` }
  return { state: 'OK', ageS: age, label: `OK · ${ageText(age)} old`, basis: b, reason: null }
}

/** Most recent scheduled evaluator tick (every 20 min, 09-16 ET, Mon-Fri) at or before `nowMs`; null if none within 5 days. */
export function lastRthTickMs(nowMs: number): number | null {
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: 'numeric', hour12: false })
  const step = 20 * 60 * 1000
  let t = Math.floor(nowMs / step) * step
  for (let i = 0; i < 5 * 72; i++, t -= step) {
    const p = Object.fromEntries(fmt.formatToParts(new Date(t)).map(x => [x.type, x.value]))
    const h = Number(p.hour) % 24
    if (p.weekday !== 'Sat' && p.weekday !== 'Sun' && h >= 9 && h <= 16) return t
  }
  return null
}

/** Alerts are graded on the last SUCCESSFUL evaluator run. A run that failed (rc != 0) never reads OK: it is STALE with the
 *  failure named, however recent. No `evaluator` block, or no OK run on record, is UNKNOWN (never the last run of any rc). */
export function gradeAlerts(body: unknown, nowMs: number): Grade {
  const b = unwrap(body)
  const ev = asRec(b?.evaluator)
  const basis = 'evaluator_last_ok_run'
  if (!ev || ev.readable === false) return gradeStamp(null, basis, nowMs, ALERTS_MAX_AGE_S)
  const g = gradeStamp(ev.last_ok_at, basis, nowMs, ALERTS_MAX_AGE_S, lastRthTickMs(nowMs))
  if (g.state === 'UNKNOWN' && ev.last_run_at) {
    return { ...g, reason: `The evaluator ran ${etText(ev.last_run_at) ?? 'at an unknown time'} but has no successful run on record${failText(ev)}.` }
  }
  if (ev.last_rc !== null && ev.last_rc !== undefined && Number(ev.last_rc) !== 0) {
    return { ...g, state: 'STALE', label: g.ageS === null ? 'STALE · last run failed' : `STALE · last OK ${ageText(g.ageS)} ago`,
      reason: `The last run${ev.last_run_at ? ` (${etText(ev.last_run_at)})` : ''} failed${failText(ev)}.` }
  }
  return g
}
function failText(ev: Record<string, any>): string {
  const parts: string[] = []
  if (ev.last_rc !== null && ev.last_rc !== undefined) parts.push(`rc ${Number(ev.last_rc)}`)
  if (typeof ev.last_error === 'string' && ev.last_error) parts.push(ev.last_error.slice(0, 80))
  return parts.length ? ` (${parts.join(': ')})` : ''
}

export function gradeSetups(body: unknown, nowMs: number): Grade {
  const b = unwrap(body)
  return b?.status === 'unavailable' ? gradeStamp(null, null, nowMs, SETUPS_MAX_AGE_S) : gradeStamp(b?.as_of, b?.as_of_basis, nowMs, SETUPS_MAX_AGE_S)
}
export function gradeSectors(body: unknown, nowMs: number): Grade {
  const b = unwrap(body)
  return b?.status === 'unavailable' || b?.status === 'empty' ? gradeStamp(null, null, nowMs, SECTORS_MAX_AGE_S) : gradeStamp(b?.as_of, b?.as_of_basis, nowMs, SECTORS_MAX_AGE_S)
}
/** Discover is stamped by the clock of the rows it lists (the screener-find pins). The discovery feed behind it
 *  (watch_candidate_events) is a separate, labelled gap; it never grades the tab. */
export function gradeDiscover(body: unknown, nowMs: number): Grade {
  const b = unwrap(body)
  return gradeStamp(b?.pins_as_of, b?.pins_as_of_basis ?? 'screener_find_pins', nowMs, DISCOVER_MAX_AGE_S)
}

/** The discovery-feed gap, from the envelope's own `stale` / `gap` (honoured whenever the envelope is used). Null = no gap declared. */
export function discoveryGap(body: unknown): string | null {
  const b = unwrap(body)
  const env = asRec(asRec(b?.feeds)?.watch_candidate_events) ?? b
  const gap = asRec(env?.gap) ?? asRec(b?.gap)
  const last = etText(gap?.last_as_of ?? env?.as_of)
  if (gap?.kind === 'no_producer') return `Discovery feed: no producer${last ? `; last event ${last}` : ''}. The rows below are saved screener finds, not new discoveries.`
  if (gap?.kind === 'no_coverage') return 'Discovery feed: no coverage — it has never produced an event.'
  if (env?.stale === true || b?.stale === true) return `Discovery feed is stale${last ? `; last event ${last}` : ''}.`
  return null
}

export type DiscoverCard = { key: 'feed' | 'pins'; title: string; state: State; detail: string }
/** WR-04/WR-05: the discovery feed and the saved screener finds are two sources with two clocks, each carrying its own
 *  state. A dead feed never grades the pins card, and a fresh pins card never certifies the feed. */
export function discoverCards(body: unknown, nowMs: number, findCount: number): DiscoverCard[] {
  const b = unwrap(body)
  const env = asRec(asRec(b?.feeds)?.watch_candidate_events) ?? b
  const gap = asRec(env?.gap) ?? asRec(b?.gap)
  const last = etText(gap?.last_as_of ?? env?.as_of)
  const feed: DiscoverCard = gap?.kind === 'no_producer'
    ? { key: 'feed', title: 'Discovery feed', state: 'UNKNOWN', detail: `no producer${last ? `; last event ${last}` : '; no event on record'}` }
    : gap?.kind === 'no_coverage'
      ? { key: 'feed', title: 'Discovery feed', state: 'UNKNOWN', detail: 'no coverage — it has never produced an event' }
      : env?.stale === true || b?.stale === true || !last
        ? { key: 'feed', title: 'Discovery feed', state: 'UNKNOWN', detail: `feed clock ${last ? `last event ${last}` : 'missing'}` }
        : { key: 'feed', title: 'Discovery feed', state: 'OK', detail: `last event ${last}` }
  const g = gradeStamp(b?.pins_as_of, b?.pins_as_of_basis ?? 'screener_find_pins', nowMs, DISCOVER_MAX_AGE_S)
  const pinsAt = etText(b?.pins_as_of)
  const pins: DiscoverCard = {
    key: 'pins',
    title: 'Saved screener finds',
    state: g.state,
    detail: `${findCount} find${findCount === 1 ? '' : 's'}${pinsAt ? ` · pins as of ${pinsAt}` : ' · no pins clock'}`,
  }
  return [feed, pins]
}

export type Certified = { text: string; mismatch: boolean; unknown: boolean }
/** The evaluator's own count from its last OK run, with that run's age, next to the table count.
 *  Missing → "no certified count"; a run that could not read its table (armed null) → "count unknown". Never 0 by default. */
export function certifiedOf(body: unknown, nowMs: number = Date.now()): Certified {
  const b = unwrap(body)
  const ev = asRec(b?.evaluator)
  const c = asRec(ev?.certified)
  if (ev?.readable === false) return { text: 'Evaluator record unreadable', mismatch: false, unknown: true }
  if (!c) return { text: 'No certified count — the evaluator has no successful run on record', mismatch: false, unknown: true }
  const t = typeof c.as_of === 'string' ? Date.parse(c.as_of) : NaN
  const when = Number.isFinite(t) ? `as of ${ageText(Math.max(0, Math.round((nowMs - t) / 1000)))} ago` : 'age unknown'
  const runs = Number(c.runs_24h)
  const okRuns = c.ok_runs_24h === undefined ? null : Number(c.ok_runs_24h)
  const tail = `${runs} runs${okRuns === null ? '' : ` (${okRuns} ok)`} / 24 h · ${Number(c.fired_24h)} fired`
  if (c.armed === null || c.armed === undefined) {
    return { text: `Evaluator armed count unknown (its alert read failed) · ${when} · ${tail}`, mismatch: false, unknown: true }
  }
  const armed = Number(c.armed)
  const active = typeof b?.active_count === 'number' ? b.active_count : null
  const mismatch = active !== null && armed !== active
  return { text: `Evaluator armed ${armed} · ${when} · ${tail}`, mismatch, unknown: false }
}

export type AlertRow = { id: number; symbol: string; condition: string; threshold: string; active: boolean; lastFired: string | null
  /** The row's own symbol, or null when the label came from a directive id — a directive id is not a symbol route. */
  link: string | null }
/** WR-07: a row's `active` flag is the DEFINITION's state, not evidence that anything is being evaluated. The label says
 *  so, so an armed row can never read as monitoring assurance. */
export const alertDefinitionState = (active: boolean): string => (active ? 'definition armed' : 'definition disarmed')

/** WR-07/WR-05: the evaluator as its own source card — producer, schedule and whether a successful run is on record. */
export type EvaluatorSource = { producer: string; schedule: string; record: string; state: State }
export function evaluatorSource(body: unknown, nowMs: number): EvaluatorSource {
  const ev = asRec(unwrap(body)?.evaluator)
  const g = gradeAlerts(body, nowMs)
  const record = !ev || ev.readable === false ? 'run record unreadable'
    : ev.last_ok_at ? `last successful run ${etText(ev.last_ok_at) ?? 'at an unknown time'}`
    : 'no successful run on record'
  return { producer: 'watch_alerts_eval.py', schedule: 'every 20 min, 09:00–16:00 ET, Mon–Fri', record, state: g.state }
}

export function alertRows(body: unknown): AlertRow[] {
  const list = unwrap(body)?.alerts
  if (!Array.isArray(list)) return []
  return list.flatMap((r: any) => {
    const id = Number(r?.id)
    if (!Number.isFinite(id)) return []
    const th = r?.threshold
    return [{ id, symbol: String(r?.symbol || r?.directive_id || '—'), condition: String(r?.condition_type || '—'),
      threshold: th === null || th === undefined ? '' : String(th), active: r?.active === true,
      lastFired: typeof r?.last_fired_at === 'string' ? r.last_fired_at : null,
      link: r?.symbol ? String(r.symbol) : null }]
  })
}

export type SectorRow = { sector: string; count: number; sample: string[] }
export function sectorRows(body: unknown): SectorRow[] {
  const list = unwrap(body)?.sectors
  return Array.isArray(list) ? list.flatMap((r: any) => (r?.sector ? [{ sector: String(r.sector), count: Number(r.count) || 0, sample: Array.isArray(r.sample) ? r.sample.map(String) : [] }] : [])) : []
}

/** WR-03: what the Sectors inventory actually is — absolute time, named producer, limit. A missing stamp stays null
 *  (the page then shows its UNKNOWN grade); no part of this is derived from the counts. */
export type SectorContext = {
  asOfText: string | null
  producer: string
  limitText: string
  /** WR-02: counts are per raw provider label; a symbol may appear under more than one. Never a universe total. */
  labelNote: string
  /** WR-01: the approved momentum/regime blocks have no projection in this build and must say so. */
  momentum: { state: 'UNKNOWN'; reason: string }
}
const SECTOR_PRODUCER: Record<string, string> = {
  'incubator_universe.updated_at': 'incubator universe refresh',
}
export function sectorContext(body: unknown, nowMs: number): SectorContext {
  const b = unwrap(body)
  const basis = typeof b?.as_of_basis === 'string' ? b.as_of_basis : ''
  const producer = SECTOR_PRODUCER[basis] || (basis ? basis.replace(/[_.]/g, ' ') : 'producer unknown')
  const asOfText = etText(b?.as_of)
  return {
    asOfText,
    producer,
    limitText: ageText(SECTORS_MAX_AGE_S),
    labelNote: 'Counts are per raw provider sector label; one symbol can appear under more than one label, so these do not add up to a universe total.',
    momentum: { state: 'UNKNOWN', reason: 'No sector momentum/strength projection exists in this build.' },
  }
}

export type PoolRow = { symbol: string; strategy: string; status: string; origin: string; enteredAt: string | null }
export function poolRows(body: unknown): PoolRow[] {
  const list = unwrap(body)?.rows
  return Array.isArray(list) ? list.flatMap((r: any) => (r?.symbol ? [{ symbol: String(r.symbol), strategy: String(r.strategy_id || '—'), status: String(r.current_status || '?'), origin: String(r.origin_system || 'screener'), enteredAt: typeof r.entered_at === 'string' ? r.entered_at : null }] : [])) : []
}

/** Pullback/MACD (W-04 in-page nested view). Stamped by the last completed SCAN, not by request time: the screener is
 *  cron-scheduled, so an empty list means either "no candidates" or "no scan" and the two must never look alike. The
 *  candidates endpoint itself refreshes the idempotent trigger-history recorder on read; this model only reads. */
export type PullbackRow = {
  symbol: string; tier: string; price: number | null; pullbackPct: number | null; macdProxPct: number | null
  barsToCross: number | null; entry: number | null; stop: number | null; target1: number | null; rr: number | null
  score: number | null; whyNot: string | null; held: string | null; heldConflict: boolean
  proposalLive: boolean | null; proposalStatus: string | null; firstSeenAt: string | null; redisplay: string | null
}
const num = (v: unknown): number | null => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v))
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

/** WR-10: the scan's technical signal and the proposal's readiness are different facts. A triggering candidate with no
 *  live proposal is BLOCKED, not ready, and says which state blocks it. Never resurrects a rejected/expired proposal. */
export type ProposalState = { key: 'in_queue' | 'rejected' | 'expired' | 'stale' | 'missing'; text: string; blocking: boolean }
export function proposalState(proposalLive: boolean | null, status: string | null): ProposalState {
  if (proposalLive === true) return { key: 'in_queue', text: 'Proposal: in queue', blocking: false }
  const st = (status || '').toUpperCase()
  if (proposalLive === false) {
    if (st === 'REJECTED') return { key: 'rejected', text: 'Proposal: rejected — no live proposal', blocking: true }
    if (st === 'EXPIRED') return { key: 'expired', text: 'Proposal: expired — no live proposal', blocking: true }
    return { key: 'stale', text: `Proposal: not live${st ? ` (${st})` : ''}`, blocking: true }
  }
  return { key: 'missing', text: 'Proposal: none — no live proposal', blocking: true }
}
/** The technical signal, named as a signal (the green pill alone can read as readiness). */
export const signalText = (tier: string): string => (tier === 'trigger' ? 'Signal: triggered' : `Signal: ${tier}`)

/** WR-11/WR-12: what the pullback read does NOT carry. Every one of these renders UNKNOWN rather than borrowing the scan
 *  stamp; a monitor tick, a quote time and a per-candidate evaluation are not in this payload. */
export type PullbackUnknowns = { monitor: null; quote: null; candidateEvaluated: null }

export function pullbackRows(body: unknown): PullbackRow[] {
  const list = unwrap(body)?.candidates
  if (!Array.isArray(list)) return []
  return list.flatMap((r: any) => {
    const symbol = str(r?.symbol)
    if (!symbol) return []
    const held = r?.held && typeof r.held === 'object' ? str(r.held.reason || r.held.note || r.held.status) || 'held' : str(r?.held)
    return [{
      symbol, tier: str(r?.tier) || 'watch', price: num(r?.price), pullbackPct: num(r?.pullback_pct), macdProxPct: num(r?.macd_prox_pct),
      barsToCross: num(r?.bars_to_cross_est), entry: num(r?.entry), stop: num(r?.stop), target1: num(r?.target1), rr: num(r?.rr),
      score: num(r?.score), whyNot: str(r?.why_not), held, heldConflict: r?.held_conflict === true,
      proposalLive: typeof r?.proposal_live === 'boolean' ? r.proposal_live : null, proposalStatus: str(r?.proposal_status),
      firstSeenAt: str(r?.first_seen_at), redisplay: str(r?.redisplay_reason),
    }]
  })
}

/** Graded on the last completed scan run. No run on record is UNKNOWN with 0 candidates still 0 — the page says "no scan",
 *  never "no candidates". */
export function gradePullback(body: unknown, nowMs: number): Grade {
  const b = unwrap(body)
  return gradeStamp(b?.generated_at, 'pullback_scan_run', nowMs, PULLBACK_MAX_AGE_S)
}

export type PullbackProvenance = {
  universe: string; screened: number | null; schedule: string | null; lastRun: string | null
  /** Every count is null when the body did not state it: a missing count must never read as 0 on this page. */
  triggers: number | null; triggersLive: number | null; triggersStale: number | null
  watch: number | null; held: number | null; dismissed: number | null
  /** WR-11: not in the pullback read today — always null, so the page names them UNKNOWN instead of inheriting the scan. */
  monitor: string | null; quote: string | null; candidateEvaluated: string | null
  hit: { windowDays: number | null; triggers: number | null; target1First: number | null; evaluated: number | null; medianDays: number | null } | null
}
/** What the scan covered and when — stated on the page instead of implied (D3 provenance). Missing pieces stay null. */
export function pullbackProvenance(body: unknown): PullbackProvenance {
  const b = unwrap(body)
  const p = asRec(b?.scan_provenance)
  const h = asRec(b?.hit_stats)
  return {
    universe: str(p?.universe) || '', screened: num(p?.screened), schedule: str(p?.schedule), lastRun: str(b?.generated_at),
    triggers: num(b?.trigger_count), triggersLive: num(b?.trigger_live_count), triggersStale: num(b?.trigger_stale_count),
    watch: num(b?.watch_count), held: num(b?.held_count), dismissed: num(b?.dismissed_in_cooldown),
    monitor: null, quote: null, candidateEvaluated: null,
    hit: h ? { windowDays: num(h.window_days), triggers: num(h.triggers), target1First: num(h.target1_first),
      evaluated: num(h.evaluated), medianDays: num(h.median_days) } : null,
  }
}

export type FindRow = { symbol: string; note: string }
export function findRows(body: unknown): FindRow[] {
  const b = unwrap(body)
  const list = Array.isArray(b?.items) ? b?.items : Array.isArray(b?.candidates) ? b?.candidates : []
  return list.flatMap((r: any) => (r?.symbol ? [{ symbol: String(r.symbol), note: String(r.reason || r.source || r.cio_action || '') }] : []))
}

export function setupsUrl(offset = 0): string { return `${SETUPS_API}?status=all&offset=${offset}&limit=${PAGE_LIMIT}` }
export function disarmBody(id: number): { action: 'disarm'; id: number } { return { action: 'disarm', id } }

/** WR-08/WR-X3: the disarm ACTION as a testable unit. The POST answers `ok:true` even when no row changed, so success is
 *  never claimed here: the caller must refetch and let the stored row say `definition disarmed`. A failure keeps the
 *  server state and names the error. */
export type DisarmPost = (body: { action: 'disarm'; id: number }) => Promise<{ ok: boolean; status: number; body: unknown }>
export async function disarmAlert(id: number, symbol: string, post: DisarmPost): Promise<{ ok: boolean; message: string }> {
  try {
    const r = await post(disarmBody(id))
    const j = unwrap(r.body)
    if (!r.ok || j?.ok === false) throw new Error(String(j?.error || `HTTP ${r.status}`))
    return { ok: true, message: `Disarm sent for ${symbol}. Check the row below: it reads "definition disarmed" once the change is stored.` }
  } catch (e) {
    return { ok: false, message: `Failed: ${String((e as Error).message || e).slice(0, 100)}` }
  }
}
