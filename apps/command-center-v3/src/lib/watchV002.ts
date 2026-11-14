/** Watch v002 — the Overview model (LQ-20261107-2993a).
 *
 *  Pure: takes the one `/api/v2/watch/status` read, returns what the page draws. Engineering Constitution: unknown beats
 *  wrong, and a verdict is computed, never declared. So:
 *   - a read that failed is UNKNOWN / TIMED OUT, never OK and never "empty";
 *   - the chip is OK only when the body is well formed, EVERY required input is OK after this client re-checks each one
 *     against its own as_of and threshold, and the read itself is recent (a tab left open demotes to STALE);
 *   - the server's verdict can only make the chip worse, never better than what the inputs prove.
 */
import { ageText, etTime, type Read } from './homeV010.ts'
import type { DiagRecordModel } from './homeV010.ts'

export const WATCH_STATUS_API = '/api/v2/watch/status'
/** A served status read older than this is shown STALE: the page may have been open for hours. */
export const STATUS_MAX_AGE_S = 120
const FUTURE_SKEW_S = 300

export type WState = 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export type Tone = 'ok' | 'warn' | 'bad' | 'neutral'

export interface WatchInputWire {
  id?: string; label?: string; required?: boolean; state?: string; source_id?: string; owner?: string
  as_of?: string | null; age_s?: number | null; threshold_s?: number | null; reason?: string | null
  needs_backend?: boolean; timed_out?: boolean
}
export interface WatchStatusWire {
  schema?: string; verdict?: string; cause?: string; computed_at?: string | null; session?: string
  read_from?: string | null; required_inputs?: string[]; inputs?: WatchInputWire[]
  /** Present only when the server answered from its cache: how many seconds that cached body had been held. */
  cache_age_s?: number | null
}

export interface WatchInputRow {
  id: string; label: string; state: WState; age: string; asOf: string | null; asOfText: string; threshold: string
  reason: string | null; owner: string; source: string; needsBackend: boolean
}
export interface WatchChip { state: WState; tone: Tone; text: string }
export interface WatchStatusModel {
  chip: WatchChip
  cause: string
  checkedAt: string | null
  session: string
  inputs: WatchInputRow[]
  /** Required inputs that are not OK: what the Why sheet lists. */
  blockers: WatchInputRow[]
  /** The Watch gates: one per required input, same states as the chip is built from. */
  gates: WatchInputRow[]
  /** WL-05: the served body's own cache age, when it said. null = this body did not carry `cache_age_s` (a miss, or an
   *  error body), so how long it had been cached is unknown — never assumed to be zero. */
  cacheAgeS: number | null
}

/** The cache window the status route documents (`CACHE_TTL_S` in scripts/lib/watch_status_live.py). The page names it as
 *  the read's cache window; a body claiming a larger cache age is reported as an inconsistent body, not quoted as fact. */
export const STATUS_CACHE_WINDOW_S = 30

const toneOf = (s: WState): Tone => (s === 'OK' ? 'ok' : s === 'STALE' ? 'warn' : s === 'LOADING' ? 'neutral' : 'bad')
const rank: Record<WState, number> = { OK: 0, LOADING: 1, STALE: 2, 'TIMED OUT': 3, UNKNOWN: 4 }
const worst = (a: WState, b: WState): WState => (rank[b] > rank[a] ? b : a)

function parseMs(iso: unknown): number | null {
  if (typeof iso !== 'string' || !iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

/** One input, re-graded here: the server's `OK` is accepted only if the as_of we were given proves it. */
export function gradeInput(w: WatchInputWire, nowMs: number): WatchInputRow {
  const id = String(w.id || 'unknown')
  const asOfMs = parseMs(w.as_of)
  const limit = typeof w.threshold_s === 'number' && w.threshold_s > 0 ? w.threshold_s : null
  let state: WState
  let reason: string | null = w.reason || null
  const server = String(w.state || '').toUpperCase()
  if (w.timed_out) state = 'TIMED OUT'
  else if (server === 'OK' || server === 'STALE') state = server as WState
  else state = 'UNKNOWN'
  let ageS: number | null = null
  if (asOfMs !== null) {
    ageS = Math.max(0, Math.round((nowMs - asOfMs) / 1000))
    if (asOfMs - nowMs > FUTURE_SKEW_S * 1000) { state = 'UNKNOWN'; reason = reason || 'as_of is in the future (clock or writer fault)' }
    else if (state === 'OK' && limit !== null && ageS > limit) { state = 'STALE'; reason = reason || `last write ${ageText(ageS)} ago, limit ${ageText(limit)}` }
  } else if (state === 'OK' || state === 'STALE') {
    // A usable state without a timestamp is a claim with no evidence.
    state = 'UNKNOWN'; reason = reason || 'no as_of on this input'
  }
  if (state === 'OK' && limit === null) { state = 'UNKNOWN'; reason = reason || 'no threshold on this input' }
  if (state === 'UNKNOWN' && !reason) reason = 'not read'
  return {
    id, label: String(w.label || id), state, age: ageS !== null ? ageText(ageS) : '—', asOf: asOfMs !== null ? String(w.as_of) : null,
    asOfText: asOfMs !== null ? etTime(String(w.as_of), true) : 'no as_of', threshold: limit !== null ? ageText(limit) : '—',
    reason: state === 'OK' ? null : reason, owner: String(w.owner || 'unknown'), source: String(w.source_id || 'unknown'),
    needsBackend: !!w.needs_backend,
  }
}

export function buildWatchStatus(read: Read<WatchStatusWire> | undefined, nowMs: number): WatchStatusModel {
  const empty = (state: WState, text: string, cause: string): WatchStatusModel =>
    ({ chip: { state, tone: toneOf(state), text }, cause, checkedAt: read?.at ?? null, session: 'unknown', inputs: [], blockers: [], gates: [], cacheAgeS: null })
  if (!read || read.state === 'LOADING') return empty('LOADING', 'Watch data · reading…', 'reading /api/v2/watch/status')
  if (read.state === 'TIMED OUT') return empty('TIMED OUT', 'Watch data · TIMED OUT', `${WATCH_STATUS_API}: ${read.error || 'no answer'}`)
  if (read.state !== 'OK' || !read.data) {
    return empty('UNKNOWN', 'Watch data · UNKNOWN', `${WATCH_STATUS_API}: ${read.error || 'could not be read'}`)
  }
  const d = read.data
  if (d.schema !== 'WatchStatus@v1' || !Array.isArray(d.inputs) || d.inputs.length === 0) {
    return empty('UNKNOWN', 'Watch data · UNKNOWN', 'the status body is not WatchStatus@v1 with inputs')
  }
  const inputs = d.inputs.map(i => gradeInput(i, nowMs))
  const required = new Set(Array.isArray(d.required_inputs) && d.required_inputs.length ? d.required_inputs : inputs.map(i => i.id))
  const gates = inputs.filter(i => required.has(i.id))
  // A required input the server never listed is an unread input, not an absent one.
  const missing = [...required].filter(id => !inputs.some(i => i.id === id))
  const missingRows: WatchInputRow[] = missing.map(id => ({ id, label: id, state: 'UNKNOWN' as WState, age: '—', asOf: null,
    asOfText: 'no as_of', threshold: '—', reason: 'required input missing from the status body', owner: 'unknown', source: 'unknown', needsBackend: false }))
  const allGates = [...gates, ...missingRows]
  let state: WState = allGates.reduce<WState>((acc, g) => worst(acc, g.state), 'OK')
  // The server verdict may only make this worse.
  const sv = String(d.verdict || '').toUpperCase()
  if (sv === 'UNKNOWN') state = worst(state, 'UNKNOWN')
  else if (sv === 'STALE') state = worst(state, 'STALE')
  else if (sv !== 'OK') state = worst(state, 'UNKNOWN')
  // The read itself must be recent and well dated.
  const computed = parseMs(d.computed_at)
  let readNote = ''
  if (computed === null) { state = worst(state, 'UNKNOWN'); readNote = 'status has no computed_at' }
  else if (computed - nowMs > FUTURE_SKEW_S * 1000) { state = worst(state, 'UNKNOWN'); readNote = 'status computed_at is in the future' }
  else if ((nowMs - computed) / 1000 > STATUS_MAX_AGE_S) { state = worst(state, 'STALE'); readNote = `status read ${ageText(Math.round((nowMs - computed) / 1000))} ago` }
  const bad = allGates.filter(g => g.state !== 'OK')
  const causeParts = bad.map(g => `${g.label}: ${g.state}${g.reason ? ` — ${g.reason}` : ''}`)
  if (readNote) causeParts.push(readNote)
  const cause = state === 'OK' ? 'All required Watch inputs are within their thresholds'
    : (causeParts.join(' · ') || d.cause || 'the Watch data could not be verified')
  // The age on the chip is the OLDEST required input's age (the data the verdict covers), not the age of this read —
  // and when optional inputs exist the label says "required", because an older optional input is not in that number.
  const ages = allGates.map(g => (g.asOf ? Math.max(0, Math.round((nowMs - Date.parse(g.asOf)) / 1000)) : null)).filter((x): x is number => x !== null)
  const optional = inputs.filter(i => !required.has(i.id)).length
  const age = ages.length
    ? ` · oldest ${optional > 0 ? 'required ' : ''}input ${ageText(Math.max(...ages))}`
    : ' · no input timestamps'
  return {
    chip: { state, tone: toneOf(state), text: `Watch data · ${state}${age}` }, cause,
    checkedAt: d.computed_at ?? null, session: String(d.session || 'unknown'), inputs, blockers: bad, gates: allGates,
    cacheAgeS: cacheAgeOf(d.cache_age_s),
  }
}

const diagStatus = (s: WState): DiagRecordModel['status'] => (s === 'LOADING' ? 'UNKNOWN' : s)

/** WL-05: `cache_age_s` as the model keeps it. A number the page can quote, or null — a body that did not report its
 *  cache age (a miss, an error body) is unknown, never read as "0 s, fresh". */
const cacheAgeOf = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.round(v) : null)

/** WL-05: the "Refresh rate" cell. The status body carries NO per-input cadence — every row is recomputed on the same
 *  request — so the cell says that outright instead of letting a body-wide sentence read as this input's schedule. The
 *  one schedule fact the body does carry is how long it had been cached; that is quoted when it is present and within
 *  the window the route documents, and said to be unknown when it is absent or outside it. Each row's own age and
 *  threshold stay in the Age and Threshold columns. */
export function refreshText(cacheAgeS: number | null): string {
  const base = `no per-input cadence: the read is recomputed on request and answered from a cache of up to ${STATUS_CACHE_WINDOW_S} s; each row's own age and limit are the Age and Threshold columns`
  if (cacheAgeS === null) return `${base}. This body did not report its cache age, so how long it had been held is unknown.`
  if (cacheAgeS > STATUS_CACHE_WINDOW_S) {
    return `${base}. The body reported a cache age of ${cacheAgeS} s — outside the ${STATUS_CACHE_WINDOW_S} s window it documents — so its age is not quoted as fact.`
  }
  return `${base}. This body was ${cacheAgeS} s into that cache when read.`
}

/** Diagnostics rows: one per input the verdict is made of — source, observed time (as_of), refresh, threshold, failure,
 *  owner. WL-05: that includes a REQUIRED input the body never listed. Such a row exists nowhere in `inputs` (the server
 *  simply omitted it) but it is the loudest diagnostic there is — a required input nobody can read — so mapping `inputs`
 *  alone used to hide exactly the failure this table exists to show. */
export function watchDiagnostics(m: WatchStatusModel): DiagRecordModel[] {
  const gateIds = new Set(m.gates.map(g => g.id))
  const rows = [...m.gates, ...m.inputs.filter(i => !gateIds.has(i.id))]
  const refresh = refreshText(m.cacheAgeS)
  return rows.map(i => ({
    widget: `${i.label} · owner: ${i.owner}`, source: i.source,
    refreshRate: refresh, age: i.asOf ? `${i.age} · observed ${i.asOfText}` : '—',
    threshold: i.threshold, status: diagStatus(i.state), failureMode: i.reason || (i.state === 'OK' ? 'none' : i.state),
    needsBackend: i.needsBackend,
  }))
}

/** The OLDEST required input's `as_of` — the data clock, i.e. what the chip's age is drawn from. Deliberately not the
 *  moment the page read the verdict: a recheck can move that and must never be mistaken for new source data (WL-05). */
export function sourceClockOf(m: WatchStatusModel): string | null {
  const rows = m.gates.length ? m.gates : m.inputs
  const times = rows.map(r => (r.asOf ? Date.parse(r.asOf) : NaN)).filter((t): t is number => Number.isFinite(t))
  if (!times.length) return null
  return new Date(Math.min(...times)).toISOString()
}

/** What the operator's "Recheck status" did, in their terms. The control re-reads the stored verdict and the overview
 *  lists; it starts no source writer. So the only thing it can prove about the data is whether the source clock moved,
 *  and on failure it keeps the last good verdict (with its own, growing age) instead of replacing good data with
 *  nothing (WL-05: "a slow read times out with last good values and age"). */
export type RecheckState = 'IDLE' | 'PENDING' | 'OK' | 'FAILED'
export interface Recheck {
  state: RecheckState
  /** Pressed at, from this page's clock. */
  at: string | null
  sourceBefore: string | null
  sourceAfter: string | null
  /** null = not comparable (a side carried no input timestamp, or no new body arrived). */
  sourceMoved: boolean | null
  /** Set on failure: when the verdict now on screen was read. */
  lastGoodAt: string | null
  error: string | null
}
export const RECHECK_IDLE: Recheck = { state: 'IDLE', at: null, sourceBefore: null, sourceAfter: null, sourceMoved: null, lastGoodAt: null, error: null }

const hhmmss = (iso: string): string => {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? `${new Date(t).toISOString().slice(11, 19)}Z` : 'unknown time'
}

export function recheckText(r: Recheck, nowMs: number): string {
  if (r.state === 'IDLE') return ''
  if (r.state === 'PENDING') {
    return 'Rechecking the stored verdict and the overview lists. This control issues reads and records your visit; it starts no source writer, so source clocks stay where they were.'
  }
  if (r.state === 'FAILED') {
    const held = r.lastGoodAt
      ? `Showing the last good verdict read ${ageText(Math.max(0, Math.round((nowMs - Date.parse(r.lastGoodAt)) / 1000)))} ago — its age keeps growing until a read succeeds.`
      : 'No last good verdict is held, so the status below is not certified by anything.'
    return `Recheck failed${r.error ? `: ${r.error}` : ''}. ${held}`
  }
  const at = r.at ? hhmmss(r.at) : 'an unknown time'
  if (r.sourceMoved === true && r.sourceBefore && r.sourceAfter) {
    return `Recheck complete ${at}. The source clock moved ${r.sourceBefore.slice(0, 16).replace('T', ' ')}Z → ${r.sourceAfter.slice(0, 16).replace('T', ' ')}Z during the recheck: that change came from the source, not from this page.`
  }
  if (r.sourceMoved === false) {
    return `Recheck complete ${at}. The stored verdict was re-read; the oldest source clock did not move — a new read time is not new data.`
  }
  return `Recheck complete ${at}. The readback arrived, but the source clock could not be compared: one side carried no input timestamps.`
}
