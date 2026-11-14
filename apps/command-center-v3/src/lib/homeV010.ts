/** Home v010 (operator-approved 2026-11-11, design/pages/home/v010) — the page model.
 *
 *  Engineering Constitution: unknown beats wrong. Every value drawn here comes from a read that succeeded; a failed
 *  read is UNKNOWN (or TIMED OUT after 30 s), never OK, never "clear", never "0". Anything this build has no
 *  production source for is NOT AVAILABLE / UNKNOWN with a NEEDS BACKEND tag:
 *    - Trade-ready verdict + gates come from GET /api/v2/home/status (HomeStatus@v1: trade_ready + gates[]). The
 *      server computes YES / NO / UNKNOWN from stored data; the client never derives a verdict. Endpoint absent (404)
 *      -> UNKNOWN "not served" + NEEDS BACKEND; any other failed read -> UNKNOWN / TIMED OUT with the reason.
 *    - Portfolio freshness  (no light Home source; /api/v2/overview is 2 MB and broker-backed, so not called)
 *    - Schedulers           (no per-lane late-run source)
 *    - FIXED / UNPROVEN / MONITORING labels (no validation_events store)
 *
 *  Reads (one per load, no polling): since-close, approvals/summary, incidents, ui/prefs home.last_seen, home/status.
 *  /api/v2/home/diagnostics is read only when the operator opens the drawer. Pure functions; the page owns fetching. */

import { sinceCloseModel, type SinceCloseWire } from './sinceClose.ts'

export const HOME_V010_TIMEOUT_MS = 30_000
export const API = {
  sinceClose: '/api/v2/home/since-close',
  approvals: '/api/v2/home' + '/approvals/summary',
  incidents: '/api/v2/home/incidents',
  lastSeen: '/api/v2/ui/prefs/get?key=home.last_seen',
  diagnostics: '/api/v2/home/diagnostics',
  status: '/api/v2/home/status',
} as const

export type ReadState = 'OK' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
export interface Read<T> { state: ReadState; data: T | null; error: string | null; at: string | null; source: string }

export const loadingRead = <T,>(source: string): Read<T> => ({ state: 'LOADING', data: null, error: null, at: null, source })

/** One GET with a hard 30 s timeout. Never throws: the result says what happened. */
export async function readOnce<T>(source: string, timeoutMs = HOME_V010_TIMEOUT_MS, fetchImpl: typeof fetch = fetch): Promise<Read<T>> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; ctl?.abort() }, timeoutMs)
  const at = new Date().toISOString()
  try {
    const r = await fetchImpl(source, { signal: ctl?.signal, cache: 'no-store', credentials: 'same-origin' })
    if (!r.ok) return { state: 'UNKNOWN', data: null, error: `HTTP ${r.status}`, at, source }
    const body: unknown = await r.json()
    // Every /api/v2 route wraps its payload as { ok, data }. Unwrap it here so the readers below see the payload;
    // ok:false is a failed read (UNKNOWN with the server's reason), never OK. An un-enveloped body passes through.
    if (body && typeof body === 'object' && !Array.isArray(body)) {
      const env = body as { ok?: unknown; data?: unknown; reason?: unknown; code?: unknown }
      if (env.ok === false) {
        const why = (typeof env.reason === 'string' && env.reason) || (typeof env.code === 'string' && env.code) || 'ok:false'
        return { state: 'UNKNOWN', data: null, error: why, at, source }
      }
      if (env.ok === true && env.data && typeof env.data === 'object' && !Array.isArray(env.data)) {
        return { state: 'OK', data: env.data as T, error: null, at, source }
      }
    }
    return { state: 'OK', data: body as T, error: null, at, source }
  } catch (e) {
    if (timedOut) return { state: 'TIMED OUT', data: null, error: `no answer after ${Math.round(timeoutMs / 1000)} s`, at, source }
    return { state: 'UNKNOWN', data: null, error: e instanceof Error ? e.message : String(e), at, source }
  } finally {
    clearTimeout(timer)
  }
}

// ── wire shapes (only the fields this page reads) ─────────────────────────────────────────────────────
export interface IncidentItem {
  incident_id?: string | number; alert_type?: string; category?: string; priority?: string; blocks_trading?: boolean
  symbol?: string | null; account_label?: string | null; first_seen_at?: string | null; last_seen_at?: string | null
  failed_checks?: number | null; owner?: string | null; cause?: string | null; stale_condition?: boolean | null
  /** Only if a later backend adds them (validation_events, LQ-2143); never derived here. */
  validation_label?: string | null
}
export interface IncidentsWire {
  state?: string; reason?: string | null; counts?: { P0?: number; P1?: number; UNCLASSIFIED?: number } | null
  items?: IncidentItem[] | null; served_at?: string
  data_integrity_24h?: { state?: string; value?: { events?: number } | null; age_s?: number | null; source_id?: string; owner?: string; reason?: string } | null
}
/** After readOnce unwraps the { ok, data } envelope the counts sit at the top; the nested shape is still accepted. */
export interface ApprovalsWire { ok?: boolean; count?: number; urgent_count?: number; as_of?: string; data?: { count?: number; urgent_count?: number; as_of?: string } }
/** The unwrapped prefs payload ({ ok, key, value, read }); `read` is what this page uses. */
export interface LastSeenWire { ok?: boolean; key?: string; value?: unknown; read?: { status?: string; seen_at?: string | null; previous_seen_at?: string | null; fallback_text?: string } }
export type TradeReady = 'YES' | 'NO' | 'UNKNOWN'
export interface HomeStatusGateWire {
  id?: string; label?: string; required?: boolean; state?: string; source_id?: string | null; as_of?: string | null
  age_s?: number | null; threshold_s?: number | null; value?: number | null; reason?: string | null; needs_backend?: boolean; blocks_trading?: boolean | null
}
export interface HomeStatusWire {
  schema?: string; verdict?: string; read_from?: string | null
  trade_ready?: { verdict?: string; cause?: string; computed_at?: string | null; read_from?: string | null }
  gates?: HomeStatusGateWire[] | null
  blockers?: Array<{ category?: string; cause?: string; count?: number | null; goto?: string | null }> | null
  unknown_inputs?: Array<{ input?: string; state?: string; reason?: string; needs_backend?: boolean }> | null
}
export interface DiagWireRow {
  widget_id?: string; widget?: string; state?: string; source_id?: string | null; source?: string | null; refresh_rate?: string | null
  age_s?: number | null; threshold_s?: number | null; failure_mode?: string | null; cause?: string | null; needs_backend?: boolean | null
}

// ── formatting ─────────────────────────────────────────────────────────────────────────────────────────
export function etTime(iso: string | null | undefined, withDay = false): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', ...(withDay ? { weekday: 'short' } : {}), hour: 'numeric', minute: '2-digit' }) + ' ET'
}
export function ageText(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const m = Math.floor(seconds / 60)
  if (m < 1) return '<1 m'
  if (m < 60) return `${m} m`
  const h = Math.floor(m / 60)
  return h < 48 ? `${h} h ${m % 60} m` : `${Math.floor(h / 24)} d`
}
const ageFrom = (iso: string | null | undefined, nowMs: number): number | null => {
  if (!iso) return null
  const t = new Date(iso).getTime()
  return Number.isNaN(t) ? null : Math.max(0, Math.round((nowMs - t) / 1000))
}

/** A read is only usable when the HTTP read worked AND the body itself does not say it failed. */
function incidentsState(r: Read<IncidentsWire>): ReadState {
  if (r.state !== 'OK') return r.state
  const s = String(r.data?.state || '')
  if (s === 'OK' && Array.isArray(r.data?.items)) return 'OK'
  return s === 'TIMED_OUT' ? 'TIMED OUT' : 'UNKNOWN'
}

// ── model ──────────────────────────────────────────────────────────────────────────────────────────────
export type RowState = 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'WARN' | 'GAP' | 'LOADING'
export interface GateRow { id: string; label: string; required: boolean; state: RowState; age: string; asOf: string | null; source: string; reason: string | null; needsBackend: boolean; count: number | null; blocks: boolean | null }
export interface StatusRow { id: string; name: string; state: RowState; value: string; cause?: string; source?: string; owner?: string; needsBackend?: boolean }
export interface ActionRow { id: string; kind: 'P0' | 'STOP'; title: string; detail: string[] }
export interface UnreadSource { source: string; label: string; state: ReadState; lastGood: string | null }
export interface SinceRow { id: string; label: string | null; text: string; time: string }

export interface HomeV010Inputs {
  sinceClose: Read<SinceCloseWire>
  approvals: Read<ApprovalsWire>
  incidents: Read<IncidentsWire>
  lastSeen: Read<LastSeenWire>
  /** GET /api/v2/home/status; absent (older callers) is treated like a 404: not served. */
  status?: Read<HomeStatusWire>
}

export interface HomeV010Model {
  loading: boolean
  checkedAt: string | null
  tradeReady: TradeReady
  /** One line: the first blocker (NO), the unread inputs (UNKNOWN), or why the verdict is not served. */
  tradeReadyCause: string
  /** true when /api/v2/home/status answered with a valid verdict; false -> NEEDS BACKEND / unread. */
  tradeReadyServed: boolean
  /** null when the endpoint gave no gates (then the card says "not available", never "0"). */
  gates: GateRow[] | null
  p0: ActionRow[]
  stops: ActionRow[]
  p1Count: number | null
  approvalsCount: number | null
  unread: UnreadSource[]
  actionEmpty: boolean
  since: { header: string; rows: SinceRow[]; state: ReadState; note: string | null }
  /** The Watch card: Home reads no watch-item source, so it says UNKNOWN and why (never an empty list, never "No source yet"). */
  watch: { state: 'UNKNOWN'; title: string; reason: string }
  status: StatusRow[]
  why: { blockers: Array<{ category: string; detail: string; targetId?: string; needsBackend?: boolean }>; inputs: Array<{ name: string; state: 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'WARN' | 'GAP' | 'NOT AVAILABLE'; ageText?: string; needsBackend?: boolean }> }
}

const NB_OWNER = 'NEEDS BACKEND'

/** Home reads no watch-item feed (the Watch page has its own reads), so the card is UNKNOWN with this reason. */
const WATCH_UNKNOWN: HomeV010Model['watch'] = {
  state: 'UNKNOWN', title: 'Watch',
  reason: 'Home reads no watch-item source, so what to watch today or tonight is not known here; the Watch page has its own lists',
}

/** The FIXED / UNPROVEN / MONITORING lifecycle of each "since" row: null when every row carries a label (or there
 *  is nothing to label); otherwise an UNKNOWN sentence counting the unlabelled rows and saying why. */
export function lifecycleNote(rows: SinceRow[], state: ReadState): string | null {
  if (state !== 'OK' || rows.length === 0) return null
  const missing = rows.filter(r => !r.label).length
  if (missing === 0) return null
  return `Lifecycle UNKNOWN for ${missing} of ${rows.length} incident${rows.length === 1 ? '' : 's'}: the incidents feed carries no FIXED / UNPROVEN / MONITORING label (validation_events is not read by Home)`
}
const VALID_LABELS = new Set(['FIXED', 'FIXED · UNPROVEN OVER TIME', 'MONITORING'])

const VERDICTS = new Set<TradeReady>(['YES', 'NO', 'UNKNOWN'])
const GATE_STATES = new Set<RowState>(['OK', 'STALE', 'UNKNOWN', 'TIMED OUT', 'WARN', 'GAP'])

/** How old a served YES may be before this page stops showing it (REVIEW-2446 F-1; the server cache is 30 s). */
export const YES_MAX_AGE_MS = 2 * 60_000

interface StatusView {
  verdict: TradeReady; cause: string; served: boolean; notServed: boolean; loading: boolean; state: ReadState
  gates: GateRow[] | null; blockers: HomeV010Model['why']['blockers']; computedAt: string | null
}

/** The server's verdict, or UNKNOWN with the reason. The client never computes YES/NO itself. */
export function statusFrom(r: Read<HomeStatusWire> | undefined, nowMs: number): StatusView {
  const base = { served: false, notServed: false, loading: false, gates: null, blockers: [] as HomeV010Model['why']['blockers'], computedAt: null }
  if (!r || (r.state !== 'OK' && r.error === 'HTTP 404')) {
    return { ...base, verdict: 'UNKNOWN', cause: 'not served: /api/v2/home/status is not deployed in this build', notServed: true, state: 'UNKNOWN' }
  }
  if (r.state === 'LOADING') return { ...base, verdict: 'UNKNOWN', cause: 'reading…', loading: true, state: 'LOADING' }
  if (r.state !== 'OK') {
    return { ...base, verdict: 'UNKNOWN', state: r.state,
      cause: r.state === 'TIMED OUT' ? 'verdict read timed out (no answer after 30 s)' : `verdict could not be read (${r.error || 'read failed'})` }
  }
  const d = r.data || {}
  const v = String(d.trade_ready?.verdict ?? d.verdict ?? '') as TradeReady
  if (!VERDICTS.has(v)) return { ...base, verdict: 'UNKNOWN', state: 'UNKNOWN', cause: 'verdict unreadable: response carried no YES / NO / UNKNOWN' }
  const gates: GateRow[] | null = Array.isArray(d.gates) ? d.gates.map((g, i) => {
    const s = String(g.state || 'UNKNOWN').replace('_', ' ') as RowState
    const asOf = g.as_of || null
    const age = typeof g.age_s === 'number' ? g.age_s : (asOf ? Math.max(0, Math.round((nowMs - new Date(asOf).getTime()) / 1000)) : null)
    return { id: g.id || `gate-${i}`, label: g.label || g.id || 'input', required: !!g.required, state: GATE_STATES.has(s) ? s : 'UNKNOWN',
      age: ageText(age), asOf, source: g.source_id || 'unknown', reason: g.reason || null, needsBackend: !!g.needs_backend,
      count: typeof g.value === 'number' ? g.value : null,
      blocks: typeof g.blocks_trading === 'boolean' ? g.blocks_trading : null }
  }) : null
  const blockers: HomeV010Model['why']['blockers'] = [
    ...(d.blockers || []).map(b => ({ category: b.category || 'Blocker', detail: `${b.cause || 'cause not recorded'}${b.count ? ` · ${b.count} open` : ''}`,
      targetId: b.goto ? b.goto.replace(/^#/, '') : undefined })),
    ...(d.unknown_inputs || []).map(u => ({ category: `Could not read: ${u.input || 'input'}`, detail: u.reason || u.state || 'UNKNOWN', needsBackend: !!u.needs_backend })),
  ]
  const computedAt = typeof d.trade_ready?.computed_at === 'string' ? d.trade_ready.computed_at : null
  return { ...base, verdict: v, served: true, state: 'OK', gates, blockers, computedAt,
    cause: d.trade_ready?.cause || 'cause not recorded' }
}

/** F-1 (REVIEW-2446): YES is the only verdict this page may second-guess. A served YES is not shown when the page
 *  itself contradicts it — a required gate not OK, a page read that failed, an open P0 on this page, no gate list,
 *  or a verdict older than YES_MAX_AGE_MS. NO is never softened and UNKNOWN is never upgraded. */
export function guardServedYes(st: StatusView, unread: UnreadSource[], p0: ActionRow[], nowMs: number):
  { verdict: TradeReady; cause: string } | null {
  if (st.verdict !== 'YES') return null
  const why: string[] = []
  if (!st.gates || st.gates.length === 0) why.push('no gate list was read')
  else {
    const bad = st.gates.filter(g => g.required && g.state !== 'OK')
    if (bad.length) why.push(`required gate${bad.length === 1 ? '' : 's'} not OK: ${bad.map(g => `${g.id} ${g.state}`).join(', ')}`)
  }
  if (unread.length) why.push(`${unread.length} page read${unread.length === 1 ? '' : 's'} unread: ${unread.map(u => u.label).join(', ')}`)
  if (p0.length) why.push(`${p0.length} open P0 on this page: ${p0.map(p => p.title).join(', ')}`)
  const t = st.computedAt ? Date.parse(st.computedAt) : NaN
  if (!Number.isFinite(t)) why.push('verdict has no readable computed_at')
  else {
    const age = nowMs - t
    if (age > YES_MAX_AGE_MS) why.push(`verdict computed ${ageText(Math.round(age / 1000))} ago (limit ${YES_MAX_AGE_MS / 60_000} m)`)
    else if (age < -YES_MAX_AGE_MS) why.push('verdict computed_at is in the future')
  }
  if (!why.length) return null
  return { verdict: 'UNKNOWN', cause: `served YES not shown — ${why.join('; ')}` }
}

export function buildModel(inp: HomeV010Inputs, nowMs: number = Date.now(), lastGood: Record<string, string | null> = {}): HomeV010Model {
  let loadingAll = [inp.sinceClose, inp.approvals, inp.incidents, inp.lastSeen].some(r => r.state === 'LOADING')
  const incState = incidentsState(inp.incidents)
  const items = incState === 'OK' ? (inp.incidents.data?.items || []) : []

  // Trade-ready + gates (server verdict only) -------------------------------------------------------------
  const st = statusFrom(inp.status, nowMs)
  if (st.loading) loadingAll = true

  // Action Required ------------------------------------------------------------------------------------
  const p0: ActionRow[] = items.filter(i => i.priority === 'P0').map((i, n) => ({
    id: `p0-${i.incident_id ?? n}`, kind: 'P0',
    title: [i.category || i.alert_type || 'Incident', i.symbol, i.account_label].filter(Boolean).join(' · '),
    detail: [
      i.cause && i.cause !== 'UNKNOWN' ? `Why: ${i.cause}` : 'Why: cause not recorded',
      i.first_seen_at ? `Detected: ${etTime(i.first_seen_at, true)}${i.failed_checks != null ? ` · ${i.failed_checks} checks` : ''}` : 'Detected: not recorded',
    ],
  }))
  const scOk = inp.sinceClose.state === 'OK' && inp.sinceClose.data?.status === 'ok'
  const sc = scOk ? sinceCloseModel(inp.sinceClose.data, nowMs) : null
  const stopRead = sc?.stops?.read ?? null
  const stops: ActionRow[] = (sc?.stops && stopRead?.status === 'read' ? sc.stops.actions : []).map(s => ({
    id: `stop-${s.n}-${s.symbol}`, kind: 'STOP',
    title: [s.verb, s.symbol, s.account].filter(Boolean).join(' · '),
    detail: [s.reason || s.what || ''].filter(Boolean),
  }))
  const apprRaw = inp.approvals.state === 'OK' ? (inp.approvals.data?.count ?? inp.approvals.data?.data?.count) : undefined
  const apprOk = typeof apprRaw === 'number' && Number.isFinite(apprRaw)
  const approvalsCount = apprOk ? (apprRaw as number) : null
  const p1Count = incState === 'OK' ? items.filter(i => i.priority === 'P1').length : null

  const unread: UnreadSource[] = []
  const pushUnread = (r: Read<unknown>, label: string, ok: boolean, state: ReadState) => {
    if (!ok && r.state !== 'LOADING') unread.push({ source: r.source, label, state: state === 'OK' ? 'UNKNOWN' : state, lastGood: lastGood[r.source] ?? null })
  }
  pushUnread(inp.incidents, 'incidents', incState === 'OK', incState)
  pushUnread(inp.approvals, 'approvals', apprOk, inp.approvals.state)
  const stopsReadable = scOk && (stopRead == null || stopRead.status !== 'unread')
  pushUnread(inp.sinceClose, 'stop advice', stopsReadable, inp.sinceClose.state)
  const loading = loadingAll
  const actionEmpty = !loading && unread.length === 0 && p0.length === 0 && stops.length === 0 && (approvalsCount ?? 0) === 0 && (p1Count ?? 0) === 0
  // F-1: the page never shows a YES its own reads contradict (NO stays NO; UNKNOWN stays UNKNOWN).
  const guarded = loading ? null : guardServedYes(st, unread, p0, nowMs)
  const tradeReady = guarded?.verdict ?? st.verdict
  const tradeReadyCause = guarded?.cause ?? st.cause

  // Since Your Last Visit -------------------------------------------------------------------------------
  const lsRead = inp.lastSeen.state === 'OK' ? inp.lastSeen.data?.read : null
  const recorded = lsRead?.status === 'RECORDED' && !!lsRead.seen_at
  const windowStart = recorded ? new Date(lsRead!.seen_at!).getTime() : nowMs - 24 * 3600_000
  const header = recorded ? `since ${etTime(lsRead!.seen_at, true)}`
    : inp.lastSeen.state === 'OK' ? 'last 24 h — last visit not recorded'
    : 'last 24 h — last visit could not be read'
  const sinceRows: SinceRow[] = items
    .filter(i => { const t = i.first_seen_at ? new Date(i.first_seen_at).getTime() : NaN; return Number.isFinite(t) && t >= windowStart })
    .map((i, n) => ({
      id: `since-${i.incident_id ?? n}`,
      label: i.validation_label && VALID_LABELS.has(i.validation_label) ? i.validation_label : null,
      text: [i.category || i.alert_type || 'Incident', i.symbol].filter(Boolean).join(' · '),
      time: etTime(i.first_seen_at, true),
    }))

  // System Status -----------------------------------------------------------------------------------------
  const unknownRow = (id: string, name: string, source: string, state: RowState = 'UNKNOWN', nb = true, cause = 'unknown'): StatusRow =>
    ({ id, name, state, value: state === 'TIMED OUT' ? 'no answer after 30 s' : state === 'LOADING' ? 'reading…' : 'not measured', cause, source, owner: NB_OWNER, needsBackend: nb })

  const pg = st.gates?.find(g => g.id === 'portfolio')
  const portfolio: StatusRow = pg && pg.state !== 'UNKNOWN' && pg.state !== 'TIMED OUT'
    ? { id: 'row-portfolio', name: 'Portfolio', state: pg.state,
        value: `positions as of ${etTime(pg.asOf, true) || 'time not recorded'}${pg.age ? ` · ${pg.age} old` : ''}`,
        ...(pg.state !== 'OK' ? { cause: pg.reason || pg.state.toLowerCase(), source: pg.source, owner: NB_OWNER } : {}) }
    : pg ? { ...unknownRow('row-portfolio', 'Portfolio', pg.source, pg.state, pg.needsBackend, pg.reason || 'unknown') }
    : unknownRow('row-portfolio', 'Portfolio', 'no light Home source (positions store)')
  let orders: StatusRow
  if (inp.sinceClose.state === 'LOADING') orders = unknownRow('row-orders', 'Stop read', API.sinceClose, 'LOADING', false)
  else if (!scOk || !stopRead || stopRead.status !== 'read') {
    const st: RowState = inp.sinceClose.state === 'TIMED OUT' ? 'TIMED OUT' : 'UNKNOWN'
    orders = unknownRow('row-orders', 'Stop read', API.sinceClose + ' (stop read)', st, false,
      !scOk ? 'read failed' : stopRead?.status === 'missing' ? 'no stop read on record' : 'stop read failed')
  } else {
    const age = ageFrom(stopRead.asOf, nowMs)
    const stale = !!sc?.stale
    orders = { id: 'row-orders', name: 'Stop read', state: stale ? 'STALE' : 'OK',
      value: `stops read ${etTime(stopRead.asOf, true) || stopRead.asOfText || 'time not recorded'}${age != null ? ` · ${ageText(age)} old` : ''}`,
      ...(stale ? { cause: 'Since-close snapshot stale', source: API.sinceClose, owner: NB_OWNER } : {}) }
  }
  let data: StatusRow
  const di = incState === 'OK' ? inp.incidents.data?.data_integrity_24h : null
  if (inp.incidents.state === 'LOADING') data = unknownRow('row-data', 'Data', API.incidents, 'LOADING', false)
  else if (!di || di.state !== 'OK' || typeof di.value?.events !== 'number') {
    data = unknownRow('row-data', 'Data', di?.source_id || 'alert_events:data_integrity', incState === 'TIMED OUT' || di?.state === 'TIMED_OUT' ? 'TIMED OUT' : 'UNKNOWN', false,
      di?.reason || 'data-integrity read failed')
    if (di?.owner && di.owner !== 'UNREGISTERED') data.owner = di.owner
  } else {
    const ev = di.value.events
    data = { id: 'row-data', name: 'Data', state: ev > 0 ? 'WARN' : 'OK', value: `${ev} data-integrity event${ev === 1 ? '' : 's'} · 24 h`,
      ...(ev > 0 ? { cause: 'Data Integrity Alert', source: di.source_id || 'alert_events', owner: di.owner && di.owner !== 'UNREGISTERED' ? di.owner : NB_OWNER } : {}) }
  }
  // A04 (LQ-20261113-3046): the server already grades schedulers (gates[id=schedulers], lane_health_current). Show that
  // gate, never a hard-coded "no source", so this row and the Why sheet's gate list cannot disagree about one source.
  const sg = st.gates?.find(g => g.id === 'schedulers')
  const schedulers: StatusRow = sg && sg.state !== 'UNKNOWN' && sg.state !== 'TIMED OUT'
    ? { id: 'row-schedulers', name: 'Schedulers', state: sg.state,
        value: `lane health as of ${etTime(sg.asOf, true) || 'time not recorded'}${sg.age ? ` · ${sg.age} old` : ''}`,
        ...(sg.state !== 'OK' ? { cause: sg.reason || sg.state.toLowerCase(), source: sg.source, owner: NB_OWNER, needsBackend: sg.needsBackend } : {}) }
    : sg ? unknownRow('row-schedulers', 'Schedulers', sg.source, sg.state, sg.needsBackend, sg.reason || 'unknown')
    : st.gates ? unknownRow('row-schedulers', 'Schedulers', 'no schedulers gate in /api/v2/home/status')
    // The status read itself has no gates (loading / timed out / failed / not served): carry its own state and cause (review 3054 F3).
    : unknownRow('row-schedulers', 'Schedulers', '/api/v2/home/status', st.loading ? 'LOADING' : st.state === 'TIMED OUT' ? 'TIMED OUT' : 'UNKNOWN', st.notServed, st.cause)
  let alerts: StatusRow
  if (inp.incidents.state === 'LOADING') alerts = unknownRow('row-alerts', 'Alerts', API.incidents, 'LOADING', false)
  else if (incState !== 'OK') alerts = unknownRow('row-alerts', 'Alerts', API.incidents, incState === 'TIMED OUT' ? 'TIMED OUT' : 'UNKNOWN', false,
    inp.incidents.data?.reason || inp.incidents.error || 'read failed')
  else if (items.length === 0) alerts = { id: 'row-alerts', name: 'Alerts', state: 'OK', value: '0 open incidents' }
  else {
    const top = items[0]
    alerts = { id: 'row-alerts', name: 'Alerts', state: 'WARN', value: `${items.length} open incident${items.length === 1 ? '' : 's'}`,
      cause: top.category || top.alert_type || 'unknown', source: 'alert_incidents',
      owner: top.owner && top.owner !== 'UNREGISTERED' ? top.owner : NB_OWNER, needsBackend: !top.owner || top.owner === 'UNREGISTERED' }
  }
  const status = [portfolio, orders, schedulers, alerts, data]

  // Why sheet -------------------------------------------------------------------------------------------
  const toWhy = (s: RowState): 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'WARN' | 'GAP' => (s === 'LOADING' ? 'UNKNOWN' : s)
  const blockers: HomeV010Model['why']['blockers'] = [
    ...(guarded ? [{ category: 'Trade-ready YES not shown', detail: guarded.cause }] : []),
    ...(st.served ? st.blockers : [
      { category: 'Trade-ready verdict not served', detail: `${st.cause} — the page never guesses YES or NO.`, needsBackend: st.notServed },
      { category: 'Validation gates not available', detail: 'No gate list was read.', targetId: 'card-gates', needsBackend: st.notServed },
    ]),
    ...status.filter(r => r.state !== 'OK').map(r => ({ category: `${r.name}: ${r.state}`, detail: `Cause: ${r.cause || 'unknown'} · Source: ${r.source || 'unknown'}`, targetId: r.id, needsBackend: r.needsBackend })),
    ...p0.map(p => ({ category: 'Open P0', detail: p.title, targetId: 'card-action' })),
  ]
  const inputs: HomeV010Model['why']['inputs'] = [
    ...(st.served && st.gates ? st.gates.map(g => ({ name: `Gate · ${g.label}`, state: toWhy(g.state), ageText: g.age || undefined, needsBackend: g.needsBackend }))
      : [{ name: 'Trade-ready verdict (/api/v2/home/status)', state: st.state === 'TIMED OUT' ? 'TIMED OUT' as const : st.notServed ? 'NOT AVAILABLE' as const : 'UNKNOWN' as const, needsBackend: st.notServed },
         { name: 'Validation gates', state: 'NOT AVAILABLE' as const, needsBackend: st.notServed }]),
    { name: 'P0 incidents', state: toWhy(incState === 'OK' ? 'OK' : incState) },
    ...status.map(r => ({ name: r.name, state: toWhy(r.state), needsBackend: r.needsBackend })),
  ]

  const ats = [inp.sinceClose, inp.approvals, inp.incidents, inp.lastSeen, ...(inp.status ? [inp.status] : [])].map(r => r.at).filter(Boolean) as string[]
  return {
    loading, checkedAt: ats.length ? ats.sort().slice(-1)[0] : null, tradeReady, tradeReadyCause, tradeReadyServed: st.served, gates: st.gates, p0, stops, p1Count, approvalsCount, unread, actionEmpty,
    since: { header, rows: sinceRows, state: incState, note: lifecycleNote(sinceRows, incState) },
    watch: WATCH_UNKNOWN,
    status, why: { blockers, inputs },
  }
}

// ── diagnostics ────────────────────────────────────────────────────────────────────────────────────────
export type DiagStatus = 'OK' | 'STALE' | 'UNKNOWN' | 'TIMED OUT' | 'WARN' | 'NOT AVAILABLE'
export interface DiagRecordModel { widget: string; source: string; refreshRate: string; age: string; threshold: string; status: DiagStatus; failureMode: string; needsBackend?: boolean }
const DIAG_STATES = new Set<DiagStatus>(['OK', 'STALE', 'UNKNOWN', 'TIMED OUT', 'WARN', 'NOT AVAILABLE'])

export function diagFromWire(body: unknown): DiagRecordModel[] | null {
  const rows = (body && typeof body === 'object' && Array.isArray((body as { rows?: unknown }).rows)) ? (body as { rows: DiagWireRow[] }).rows : null
  if (!rows || rows.length === 0) return null
  return rows.map(r => {
    const st = String(r.state || 'UNKNOWN').replace('_', ' ') as DiagStatus
    return {
      widget: r.widget || r.widget_id || 'unknown widget', source: r.source || r.source_id || 'unknown',
      refreshRate: r.refresh_rate || '—', age: r.age_s != null ? ageText(r.age_s) : '—',
      threshold: r.threshold_s != null ? ageText(r.threshold_s) : '—',
      status: DIAG_STATES.has(st) ? st : 'UNKNOWN', failureMode: r.failure_mode || r.cause || '—', needsBackend: !!r.needs_backend,
    }
  })
}

/** No diagnostics rows: one record per widget, built only from this page's own reads. */
export function diagFallback(m: HomeV010Model, inp: HomeV010Inputs): DiagRecordModel[] {
  const rs = (r: Read<unknown>): DiagStatus => (r.state === 'OK' ? 'OK' : r.state === 'TIMED OUT' ? 'TIMED OUT' : 'UNKNOWN')
  const row = (widget: string, source: string, status: DiagStatus, failureMode: string, needsBackend = false): DiagRecordModel =>
    ({ widget, source, refreshRate: 'on load', age: '—', threshold: '—', status, failureMode, needsBackend })
  const fromRow = (r: StatusRow): DiagStatus => (r.state === 'LOADING' || r.state === 'GAP' ? 'UNKNOWN' : r.state)
  return [
    row('Action · Unprotected Position', API.incidents, rs(inp.incidents), 'UNKNOWN, not an all-clear'),
    row('Action · Approvals', API.approvals, rs(inp.approvals), '"could not be checked"'),
    row('Action · Stop advice', API.sinceClose, rs(inp.sinceClose), 'UNKNOWN with last good time'),
    m.gates ? row('Validation gates', API.status, rs(inp.status ?? { state: 'UNKNOWN' } as Read<unknown>), '"not available", never "0 open"')
      : row('Validation gates', 'none', 'NOT AVAILABLE', '"not available", never "0 open"', true),
    row('Since your last visit', API.lastSeen, rs(inp.lastSeen), 'falls back to "last 24 h"'),
    ...m.status.map(r => row(`Status · ${r.name}`, r.source || 'none', r.needsBackend && r.state === 'UNKNOWN' ? 'NOT AVAILABLE' : fromRow(r), r.state === 'OK' ? 'last value with age' : `Cause: ${r.cause || 'unknown'}`, !!r.needsBackend)),
    m.tradeReadyServed ? row('Trade-ready', API.status, m.tradeReady === 'UNKNOWN' ? 'UNKNOWN' : 'OK',
      m.tradeReady === 'UNKNOWN' ? m.tradeReadyCause : 'UNKNOWN, never YES by default')
      : row('Trade-ready', API.status, inp.status?.state === 'TIMED OUT' ? 'TIMED OUT' : inp.status && inp.status.error !== 'HTTP 404' ? 'UNKNOWN' : 'NOT AVAILABLE', 'UNKNOWN, never YES by default', !inp.status || inp.status.error === 'HTTP 404'),
    row('Diagnostics registry', API.diagnostics, 'NOT AVAILABLE', 'this table is built from the page’s own reads', true),
  ]
}
