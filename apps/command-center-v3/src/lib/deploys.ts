// Deploys (2026-10-27) — Home "Deploys" line + drawer: the latest DeployOnMainReceipt@v1 and the deploy STOP latch.
//
// Replaces the retired release-train projections (operator directive 2026-10-27: "Remove everything about the old
// train ... from the Command Center"). Mergify merges; the host deploy_on_main poller promotes and writes one receipt
// per decision (AGENTS.md §25.10). Read shape: GET /api/v2/ops/deploys (scripts/lib/deploys_view.py). STOP:
// GET/POST /api/v2/ops/deploys/stop (scripts/lib/deploy_stop.py; set-only). Every path lives in DEPLOYS_PATHS.
//
// Missing, failed or old data is UNAVAILABLE or STALE with its age — never green. A STOP that cannot be read is an
// effective STOP (fail closed). No imports: this module runs under `node --experimental-strip-types` (deploys.test.ts).

export const DEPLOYS_PATHS = Object.freeze({
  status: '/api/v2/ops/deploys',
  stop: '/api/v2/ops/deploys/stop',
})

export const RESUME_COMMAND_FALLBACK = 'python3 scripts/release_window.py clear-stop --reason "<why it is safe to resume>"'
export const HOST_STOP_FALLBACK = 'python3 scripts/lib/deploy_stop.py stop --reason "<why>"'
/** A response generated longer ago than this (a kept payload after failed polls) is STALE. */
export const RESPONSE_STALE_AFTER_S = 15 * 60
/** The STOP latch read is live per request; older than this is STALE. */
export const STOP_STALE_AFTER_S = 120

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type DataState = 'LOADING' | 'OK' | 'STALE' | 'UNAVAILABLE'

// ── wire shapes ──────────────────────────────────────────────────────────────────────────────────

export interface DeployReceiptWire {
  schema?: string
  as_of?: string | null
  path?: 'poller' | 'manual_emergency' | string
  outcome?: string
  main_sha?: string
  current_sha_before?: string
  current_sha_after?: string
  reason?: string
  detail?: Record<string, unknown>
}
export interface DeploysStatusWire {
  schema?: string
  generated_at?: string | null
  latest?: DeployReceiptWire | null
  latest_error?: string | null
  recent?: DeployReceiptWire[] | null
  stop?: StopStatusWire | null
  stop_error?: string | null
  stop_effective?: boolean | null
  how?: string
}

export interface StopLatchWire { status?: 'SET' | 'ABSENT' | 'UNREADABLE' | string; body?: Record<string, unknown> | null; path?: string; mtime?: string | null }
export interface StopStatusWire {
  schema?: string
  as_of?: string | null
  state_dir?: string
  latch?: StopLatchWire | null
  window_run_lock?: 'HELD' | 'FREE' | 'UNKNOWN' | string
  phase?: 'stopped' | 'settling' | 'running' | 'unknown' | string
  runner_reader?: string
  reader_note?: string | null
  audit_tail?: Array<Record<string, unknown>> | null
  resume?: { policy?: string; command?: string } | null
  separate_from_trading_kill_switch?: boolean
  kill_switch_note?: string
}
export interface StopResultWire {
  ok?: boolean
  schema?: string
  outcome?: 'STOP_SET' | 'ALREADY_STOPPED' | 'STOP_NOT_CONFIRMED' | 'REFUSED' | string
  refusal?: string
  error?: string
  phase?: string
  stop_id?: string | null
  actor?: string
  reason?: string
  requested_at?: string
  acknowledged_at?: string | null
  latch?: StopLatchWire | null
  replayed?: boolean
  resume?: { policy?: string; command?: string } | null
}

// ── freshness ────────────────────────────────────────────────────────────────────────────────────

export interface Freshness { state: DataState; asOf: string | null; ageS: number | null; ageLabel: string; reason: string | null }

export function ageLabel(ageS: number | null): string {
  if (ageS == null || !Number.isFinite(ageS)) return 'age unknown'
  if (ageS < -5) return 'clock skew'
  if (ageS < 90) return `${Math.max(0, Math.round(ageS))}s ago`
  if (ageS < 5400) return `${Math.round(ageS / 60)}m ago`
  if (ageS < 172800) return `${Math.round(ageS / 3600)}h ago`
  return `${Math.round(ageS / 86400)}d ago`
}

function ageOf(iso: string | null | undefined, nowMs: number): number | null {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? (nowMs - t) / 1000 : null
}

/** Transport-level freshness of one response: LOADING / UNAVAILABLE (no payload) / STALE (kept after a failed poll,
 *  undated, or older than staleAfterS) / OK. `clock` is the response's own timestamp (generated_at or as_of). */
export function freshness(
  clock: string | null | undefined,
  hasPayload: boolean,
  opts: { nowMs: number; loading?: boolean; error?: unknown; staleAfterS?: number },
): Freshness {
  if (!hasPayload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', asOf: null, ageS: null, ageLabel: '', reason: null }
    return { state: 'UNAVAILABLE', asOf: null, ageS: null, ageLabel: 'never read', reason: opts.error ? String(opts.error) : 'no payload' }
  }
  const asOf = typeof clock === 'string' ? clock : null
  const ageS = ageOf(asOf, opts.nowMs)
  const label = ageLabel(ageS)
  if (opts.error) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: `refresh failed: ${String(opts.error)}` }
  if (ageS == null) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: 'undated response' }
  if (ageS > (opts.staleAfterS ?? RESPONSE_STALE_AFTER_S)) return { state: 'STALE', asOf, ageS, ageLabel: label, reason: `as of ${asOf}` }
  return { state: 'OK', asOf, ageS, ageLabel: label, reason: null }
}

// ── STOP: requested → acknowledged → (settling) → stopped ───────────────────────────────────────

export interface StopRequestState {
  requestedAt: string | null       // client clock when the POST was sent
  inFlight: boolean
  result: StopResultWire | null    // server answer (acknowledged = latch read back by the server)
  httpStatus: number | null
  error: string | null             // transport failure: unknown whether the request arrived
}
export const NO_STOP_REQUEST: StopRequestState = { requestedAt: null, inFlight: false, result: null, httpStatus: null, error: null }

export type StopStepKey = 'requested' | 'acknowledged' | 'settling' | 'stopped'
export interface StopStep { key: StopStepKey; label: string; done: boolean; at: string | null; detail: string }
export interface StopModel {
  latch: 'SET' | 'ABSENT' | 'UNREADABLE' | 'UNKNOWN'
  latchTone: Tone
  headline: string
  steps: StopStep[]
  refused: string | null
  unconfirmed: string | null
  statusFresh: Freshness
  latchedAt: string | null
  latchedBy: string | null
  latchReason: string | null
  latchOutcome: string | null
  readerNote: string | null
  resumeCommand: string
}

function str(v: unknown): string | null { return typeof v === 'string' && v ? v : null }

export function stopModelFrom(status: StopStatusWire | null | undefined, req: StopRequestState, statusFresh: Freshness): StopModel {
  const usable = !!status && (statusFresh.state === 'OK' || statusFresh.state === 'STALE')
  const raw = usable ? String(status!.latch?.status || '') : ''
  const latch: StopModel['latch'] = raw === 'SET' || raw === 'ABSENT' || raw === 'UNREADABLE' ? raw : 'UNKNOWN'
  const body = ((usable && status!.latch?.body) || {}) as Record<string, unknown>
  const res = req.result
  const acknowledged = !!res && res.ok === true && res.latch?.status === 'SET'
  const ackAt = acknowledged ? (res!.acknowledged_at || null) : null
  // "stopped" needs an INDEPENDENT read of the latch (the status poll): fresh, SET, no window holding its run lock,
  // and — after a press — taken at or after the server's acknowledgement (both are server clocks).
  const readAt = usable && status!.as_of ? Date.parse(status!.as_of) : NaN
  const afterAck = !ackAt || (Number.isFinite(readAt) && readAt >= Date.parse(ackAt))
  const independentSet = usable && statusFresh.state === 'OK' && latch === 'SET' && afterAck
  const lock = usable ? String(status!.window_run_lock || 'UNKNOWN') : 'UNKNOWN'
  const settling = independentSet && lock === 'HELD'
  const stopped = independentSet && lock === 'FREE'
  const steps: StopStep[] = [
    { key: 'requested', label: 'Stop requested', done: !!req.requestedAt, at: req.requestedAt,
      detail: req.inFlight ? 'sent; waiting for the server' : req.requestedAt ? 'sent from this browser' : 'not requested from this page' },
    { key: 'acknowledged', label: 'Acknowledged (latch read back)', done: acknowledged, at: ackAt,
      detail: acknowledged ? `${res!.outcome === 'ALREADY_STOPPED' ? 'a STOP was already latched' : 'STOP.json written and read back'}${res!.replayed ? ' · replay of the same press' : ''}` : 'server has not confirmed a latch' },
    { key: 'settling', label: 'Settling', done: settling, at: settling ? (status!.as_of || null) : null,
      detail: settling ? 'a deploy holds the release lock: it finishes its bounded verify / rollback, then nothing new starts' : lock === 'UNKNOWN' ? 'run lock unreadable' : 'no window running' },
    { key: 'stopped', label: 'Stopped', done: stopped, at: stopped ? (status!.as_of || null) : null,
      detail: stopped ? 'independent read: latch SET, no window running; the host poller refuses to promote' : 'not yet confirmed by an independent read' },
  ]
  let refused: string | null = null
  if (res && (res.outcome === 'REFUSED' || res.ok === false) && res.refusal) refused = `${res.refusal}: ${res.error || 'refused'}`
  let unconfirmed: string | null = null
  if (req.error) unconfirmed = `No answer (${req.error}). The STOP may or may not have arrived — the latch state below is the truth. Retry uses the same key.`
  else if (res && res.outcome === 'STOP_NOT_CONFIRMED') unconfirmed = 'Server could not read the latch back. Use the host fallback.'
  const headline = latch === 'SET' ? (settling ? 'DEPLOYS STOPPING (window settling)' : statusFresh.state === 'STALE' ? 'DEPLOYS STOPPED (STALE read)' : 'DEPLOYS STOPPED')
    : latch === 'ABSENT' ? (statusFresh.state === 'STALE' ? 'Deploys not stopped (STALE read)' : 'Deploys not stopped')
      : latch === 'UNREADABLE' ? (status!.runner_reader === 'main_fail_open'
        ? 'STOP latch UNREADABLE — the served runner reads it as NOT SET: press STOP'
        : 'STOP latch UNREADABLE — effective STOP')
        : statusFresh.state === 'LOADING' ? 'reading STOP latch…' : 'STOP state UNAVAILABLE — treat as STOPPED'
  return {
    latch, latchTone: latch === 'ABSENT' ? 'neutral' : latch === 'SET' || latch === 'UNREADABLE' ? 'danger' : 'warning', headline, steps, refused, unconfirmed, statusFresh,
    latchedAt: str(body.latched_at), latchedBy: str(body.actor),
    latchReason: str(body.reason) || str(body.detail), latchOutcome: str(body.outcome),
    readerNote: usable ? (status!.reader_note || null) : null,
    resumeCommand: (usable && status!.resume?.command) || res?.resume?.command || RESUME_COMMAND_FALLBACK,
  }
}

export const STOP_REASON_MIN = 8
export const STOP_REASON_MAX = 500
export function stopReasonError(reason: string): string | null {
  const r = reason.trim()
  if (r.length < STOP_REASON_MIN) return `reason required (at least ${STOP_REASON_MIN} characters)`
  if (r.length > STOP_REASON_MAX) return `reason too long (max ${STOP_REASON_MAX})`
  return null
}
/** One key per button press, reused on a retry of that press (server dedupes). */
export function newIdempotencyKey(rand: () => string): string {
  return `cc-stop-${rand()}`.replace(/[^A-Za-z0-9._:-]/g, '').slice(0, 128)
}

// ── Deploys summary (Home line + drawer) ─────────────────────────────────────────────────────────

export function shortSha(sha: string | null | undefined): string {
  return typeof sha === 'string' && sha ? sha.slice(0, 9) : '—'
}

/** Outcome words the poller writes (scripts/lib/deploy_on_main.py) → tone. Unknown words are warnings, never green. */
export function outcomeTone(outcome: string | null | undefined): Tone {
  const o = String(outcome || '').toLowerCase()
  if (o === 'verified' || o === 'promoted') return 'success'
  if (o === 'noop') return 'neutral'
  if (o.includes('fail') || o.includes('rollback') || o === 'refuse' || o === 'refused') return 'danger'
  return 'warning'
}

export interface DeploysSummary {
  state: DataState
  stopEffective: boolean
  stopText: string
  stopTone: Tone
  lastText: string
  lastTone: Tone
  lastAt: string | null
  line: string
}

export function deploysSummary(wire: DeploysStatusWire | null | undefined, f: Freshness): DeploysSummary {
  const usable = !!wire && (f.state === 'OK' || f.state === 'STALE')
  const latch = usable ? String(wire!.stop?.latch?.status || '') : ''
  // Fail closed: an unreadable or missing STOP read is an effective STOP.
  const stopEffective = usable ? latch !== 'ABSENT' : f.state !== 'LOADING'
  const stopText = f.state === 'LOADING' ? 'STOP …'
    : !usable ? 'STOP UNAVAILABLE'
      : latch === 'ABSENT' ? 'STOP clear' : latch === 'SET' ? 'STOP SET' : 'STOP UNREADABLE'
  const r = usable ? wire!.latest : null
  const lastText = f.state === 'LOADING' ? 'reading…'
    : !usable ? 'UNAVAILABLE'
      : r ? `${r.outcome || 'unknown'} · main ${shortSha(r.main_sha)}${r.path === 'manual_emergency' ? ' · emergency' : ''}`
        : `no receipt${wire!.latest_error ? ` (${wire!.latest_error})` : ''}`
  const lastTone: Tone = !usable ? 'warning' : r ? outcomeTone(r.outcome) : 'warning'
  const line = `${stopText} · last ${lastText}${f.state === 'STALE' ? ' · STALE' : ''}`
  return { state: f.state, stopEffective, stopText, stopTone: stopEffective ? 'danger' : 'neutral', lastText, lastTone,
    lastAt: r?.as_of ?? null, line }
}
