import { useState, useEffect, useRef, useCallback } from 'react'
import type { TransportState } from '../lib/observationEnvelope.ts'
import { classifyStatus, classifyError, countsAsConnectionFailure, parseErrorBody } from '../lib/httpOutcome.ts'
import { coalesceInFlight } from '../lib/inflightGet.ts'

// ── Global connection health ─────────────────────────────────────────────────────────────────────────
// useApi consumers register/clear when they enter/leave a failed state, so a single top-level indicator
// ("Reconnecting…") can reflect that the backend is briefly unreachable (e.g. a server restart) WITHOUT
// every hub collapsing its own view to authoritative-looking zeros.
let _failCount = 0
const _listeners = new Set<(n: number) => void>()
const RECOVER_EVENT = 'cc-v3-api-recover'

function _bumpFail(delta: number) {
  _failCount = Math.max(0, _failCount + delta)
  _listeners.forEach(l => l(_failCount))
}

/** Clear a stuck global fail tally (e.g. backend recovered but poll hooks haven't cleared yet). */
export function resetConnectionHealth() {
  if (_failCount === 0) return
  _failCount = 0
  _listeners.forEach(l => l(0))
}

/** Backend is reachable again — clear the banner and nudge every active useApi hook to refetch. */
export function signalApiRecover() {
  resetConnectionHealth()
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(RECOVER_EVENT))
}

/** Manual reconnect — refetch all hooks; clear the banner only when /api/health succeeds. */
export async function retryApiConnection() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(RECOVER_EVENT))
  try {
    const r = await fetch('/api/health', { cache: 'no-store' })
    if (r.ok) resetConnectionHealth()
  } catch { /* hooks will re-register failures on the refetch */ }
}

export function useConnectionHealth() {
  const [n, setN] = useState(_failCount)
  useEffect(() => { _listeners.add(setN); setN(_failCount); return () => { _listeners.delete(setN) } }, [])
  return { degraded: n > 0, failing: n }
}

// `priority: 'background'` (perf 2026-10-25): app-chrome polls (status strip, gates, health) yield to the page's own
// reads. On a phone the shell's ~10 chrome requests filled the 3 shared slots first, so Watch / Portfolio data
// queued behind them for 4-5 s before it was even asked for. Background requests start only when no page request
// is waiting, and never take the last free slot. Nothing is dropped — they only run later.
export type UseApiOptions = { enabled?: boolean; priority?: 'background' }

// v3.1 (WS-A): manual ETag revalidation — server answers 304 before any JSON
// serialize/gzip, which is where the CPU actually went. Keyed by path.
const _etags = new Map<string, string>()

// One subscription per path (combined Home, operator controlling decision 2026-11-13).
//
// The combined Home mounts the classic Home and the operational section on one page, inside a shell whose chrome polls
// some of the same paths (approvals/summary in NavRail + MetricStrip; overview, risk-regime, trade-ai/summary in
// MetricStrip and HomeDoNow). Every hook for a path is a subscriber of ONE shared record:
//   - whichever subscriber's poll comes due first reads the server; the body is handed to every subscriber at once;
//   - a subscriber whose own poll comes due while the shared body is younger than 90% of its own interval takes that
//     body instead of issuing a second GET — so a path is read once per (shortest) poll cycle, never once per hook;
//   - concurrent reads of a path still join one in-flight GET (lib/inflightGet.ts);
//   - polling pauses while the document is hidden and resumes with one read when it becomes visible again
//     (lib/pageVisibility.ts, the 2026-10-22 memory incident).
// A body is never older than the subscriber's own cadence promised, and an operator refetch always reaches the server.
const _lastGood = new Map<string, { json: unknown; at: number }>()
type BodyListener = (json: unknown, at: number) => void
const _subscribers = new Map<string, Set<BodyListener>>()
const _anyListeners = new Set<(path: string) => void>()

/** The last 200 body read for exactly this path (cache-buster excluded), with the time it was last confirmed. */
export function peekLastGood(path: string): { json: unknown; at: number } | null {
  return _lastGood.get(path) ?? null
}

/** Record a 200 body for `path` and hand it to every subscriber of that path (except `from`, which applied it). */
export function noteLastGood(path: string, json: unknown, at: number = Date.now(), from?: BodyListener): void {
  _lastGood.set(path, { json, at })
  _subscribers.get(path)?.forEach(fn => { if (fn !== from) fn(json, at) })
  _anyListeners.forEach(fn => fn(path))
}

/** Every path that has a recorded body, with that body (the page's endpoint inventory, for the product-clock panel). */
export function listLastGood(): Array<[string, { json: unknown; at: number }]> {
  return [...(_lastGood.entries())]
}

/** Be told whenever any path records a new body. Returns the unsubscribe function. */
export function subscribeAnyBody(fn: (path: string) => void): () => void {
  _anyListeners.add(fn)
  return () => { _anyListeners.delete(fn) }
}

/** A 304 confirmed the recorded body is still current: its confirmation time moves, the body does not. */
function confirmLastGood(path: string, at: number): void {
  const held = _lastGood.get(path)
  if (held) _lastGood.set(path, { json: held.json, at })
}

/** Receive every body recorded for `path` from now on (a passive subscriber: it never polls). */
export function subscribeBody(path: string, fn: BodyListener): () => void { return subscribe(path, fn) }

function subscribe(path: string, fn: BodyListener): () => void {
  let set = _subscribers.get(path)
  if (!set) { set = new Set(); _subscribers.set(path, set) }
  set.add(fn)
  return () => { set!.delete(fn); if (set!.size === 0) _subscribers.delete(path) }
}

/** Test-only: forget every recorded body and subscriber. */
export function resetLastGood(): void {
  _lastGood.clear()
  _subscribers.clear()
  _anyListeners.clear()
}

/** A one-shot hook (no interval) takes a shared body only inside this burst window. */
export const SHARED_ONE_SHOT_MS = 5_000

export type PollReason = 'mount' | 'tick' | 'visible'
export type PollAction = 'fetch' | 'reuse' | 'paused'

/** What a subscriber does when its read comes due. Pure; exported for the regression test. */
export function sharedPollAction(input: {
  held: { at: number } | null; nowMs: number; intervalMs?: number; manual: boolean; visible: boolean; reason: PollReason
}): PollAction {
  const { held, nowMs, intervalMs, manual, visible, reason } = input
  if (manual) return 'fetch'
  if (!visible && reason === 'tick') return 'paused'
  const windowMs = intervalMs && intervalMs > 0 ? Math.floor(intervalMs * 0.9) : SHARED_ONE_SHOT_MS
  if (held && nowMs >= held.at && nowMs - held.at < windowMs) return 'reuse'
  return 'fetch'
}

function documentVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden'
}

// The portfolio server is intentionally a small single-process service. A hub
// mount can otherwise start 9–12 requests in the same render tick, turning a
// healthy backend into a burst of 503s/timeouts. Keep the browser-side fan-out
// bounded while preserving FIFO ordering and the existing last-good semantics.
const MAX_ACTIVE_API_REQUESTS = 3
// At most two chrome reads at once: one slot always stays free for the page.
const MAX_BACKGROUND_API_REQUESTS = MAX_ACTIVE_API_REQUESTS - 1
let _activeApiRequests = 0
type ApiRequestTask<T> = {
  run: () => Promise<T>
  resolve: (value: T | PromiseLike<T>) => void
  reject: (reason?: unknown) => void
  cancelled: boolean
  background: boolean
}
const _apiRequestQueue: ApiRequestTask<unknown>[] = []
const _backgroundQueue: ApiRequestTask<unknown>[] = []
let _activeBackground = 0

function startApiTask(task: ApiRequestTask<unknown>) {
  _activeApiRequests += 1
  if (task.background) _activeBackground += 1
  void task.run().then(task.resolve, task.reject).finally(() => {
    _activeApiRequests -= 1
    if (task.background) _activeBackground -= 1
    drainApiRequestQueue()
  })
}

function drainApiRequestQueue() {
  while (_activeApiRequests < MAX_ACTIVE_API_REQUESTS && _apiRequestQueue.length > 0) {
    const task = _apiRequestQueue.shift()!
    if (task.cancelled) continue
    startApiTask(task)
  }
  // Background work only when no page request waits, and never in the last free slot.
  while (_apiRequestQueue.length === 0 && _backgroundQueue.length > 0
    && _activeApiRequests < MAX_ACTIVE_API_REQUESTS && _activeBackground < MAX_BACKGROUND_API_REQUESTS) {
    const task = _backgroundQueue.shift()!
    if (task.cancelled) continue
    startApiTask(task)
  }
}

function scheduleApiRequest<T>(run: () => Promise<T>, background = false): { promise: Promise<T>; cancel: () => void } {
  let task!: ApiRequestTask<T>
  const queue = background ? _backgroundQueue : _apiRequestQueue
  const promise = new Promise<T>((resolve, reject) => {
    task = { run, resolve, reject, cancelled: false, background }
    queue.push(task as ApiRequestTask<unknown>)
    drainApiRequestQueue()
  })
  return {
    promise,
    cancel: () => {
      if (task.cancelled) return
      task.cancelled = true
      const index = queue.indexOf(task as ApiRequestTask<unknown>)
      if (index >= 0) queue.splice(index, 1)
      task.reject(Object.assign(new Error('request cancelled'), { name: 'AbortError' }))
    },
  }
}

// Exponential backoff with jitter: 1s → 2s → 4s … cap 30s. A retry hammer over
// a busy single-process server just keeps it busy.
function backoffMs(attempt: number): number {
  const base = Math.min(30_000, 1_000 * Math.pow(2, attempt))
  return Math.round(base * (0.5 + Math.random() * 0.5))
}

export function useApi<T>(path: string, intervalMs?: number, options?: UseApiOptions) {
  const enabled = options?.enabled !== false
  const background = options?.priority === 'background'
  const [data, setData] = useState<T | null>(null)
  // The whole JSON body, unwrap included. `data` is the payload only, so anything the server puts BESIDE it — a clock
  // like as_of / age_hours / stale on /api/v2/risk-regime/latest — is otherwise lost before any component sees it
  // (cc-deepseek-5's BLOCK on PR 2642, 2026-11-05). Additive: every existing consumer still reads `data`.
  const [envelope, setEnvelope] = useState<any>(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false) // manual refetch in flight (keeps last data)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)   // showing last-good data after a failed refetch
  // Transport receipt + state (cc-header-truth-v2): a 304 revalidates the body
  // but advances only `receivedAt`; the data clock must not move. Exposed so
  // consumers build an envelope that ages rather than resets to "fresh".
  const [receivedAt, setReceivedAt] = useState<string | null>(null)
  const [transport, setTransport] = useState<TransportState>('UNKNOWN')
  const [tick, setTick] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()
  const retryRef = useRef<ReturnType<typeof setTimeout>>()
  const dataRef = useRef<T | null>(null)       // latest good data, readable inside the fetch closure
  const failingRef = useRef(false)             // this hook's current contribution to the global fail count
  const manualRef = useRef(false)              // true when user-triggered refetch
  // A terminal outcome (401/403/404/validation) is remembered so the polling
  // interval does not quietly re-issue a request that cannot succeed. Only an
  // explicit operator action — refetch() — clears it.
  const terminalRef = useRef<string | null>(null)
  const [authState, setAuthState] = useState<'OK' | 'UNAUTHORIZED' | 'FORBIDDEN' | null>(null)
  // The server's typed refusal (its own `error` code + detail sentence), read from a failed response body. Before
  // this a 403 arrived as a generic sentence with the body dropped, so a surface could not name AGENT_CALLER_REFUSED
  // versus CSRF_REFUSED. Null when the body carried no usable code — never invented. `parseErrorBody` validates shape.
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

  const refetch = useCallback(() => {
    // The explicit credential-refresh contract: an operator asking again is the
    // only thing that re-arms a terminal outcome.
    terminalRef.current = null
    manualRef.current = true
    setRefreshing(true)
    setTick(t => t + 1)
  }, [])

  useEffect(() => {
    const onRecover = () => refetch()
    window.addEventListener(RECOVER_EVENT, onRecover)
    return () => window.removeEventListener(RECOVER_EVENT, onRecover)
  }, [refetch])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      setRefreshing(false)
      manualRef.current = false
      return () => {
        if (failingRef.current) { failingRef.current = false; _bumpFail(-1) }
      }
    }
    let cancelled = false
    let inFlight = false
    let retries = 0
    let slowRetryRef: ReturnType<typeof setTimeout> | undefined
    const controllers = new Set<AbortController>()
    const cancelQueued = new Set<() => void>()
    const clearFailing = () => { if (failingRef.current) { failingRef.current = false; _bumpFail(-1) } }
    const clearManual = () => {
      if (manualRef.current) {
        manualRef.current = false
        setRefreshing(false)
      }
    }

    // Apply a 200 body (this hook's own read, or one another subscriber of the path just read).
    const apply = (json: any, at: number) => {
      if (cancelled) return
      const next = json && typeof json === 'object' && json.ok !== undefined ? (json.data ?? json) : json
      dataRef.current = next
      setData(next)
      setEnvelope(json && typeof json === 'object' ? json : null)
      setError(null)
      setErrorCode(null)
      setErrorDetail(null)
      setStale(false)
      setReceivedAt(new Date(at).toISOString())
      setTransport('OK')
      setLoading(false)
    }
    const listener: BodyListener = (json, at) => { if (!terminalRef.current) apply(json, at) }
    const unsubscribe = subscribe(path, listener)

    const load = async (reason: PollReason = 'tick') => {
      // A terminal outcome stands until an operator explicitly asks again.
      if (terminalRef.current) return
      if (inFlight) return
      const action = sharedPollAction({ held: peekLastGood(path), nowMs: Date.now(), intervalMs, manual: manualRef.current, visible: documentVisible(), reason })
      if (action === 'paused') return
      if (action === 'reuse') {
        const held = peekLastGood(path)!
        apply(held.json, held.at)
        setAuthState('OK')
        clearFailing()
        retries = 0
        return
      }
      inFlight = true
      // broker-proposals: 15s hard timeout (P0 2026-07-14) — the endpoint is now bounded
      // server-side (quote budget + background autocal/summary); anything slower should
      // surface the error/Retry state instead of an endless "Loading broker queue…".
      // options/proposals + monitor: Schwab chain scan can take 60–90s on a cold
      // generate_proposals; the default 30s AbortError was mislabeled "server busy"
      // while the single-threaded :7777 was still honestly working (2026-09-25).
      // universe-theses builds living coverage over ~80 symbols (~4–8s warm,
      // longer under a busy single-thread :7777). The default 30s abort +
      // retry loop left Research stuck on "Loading universe…" while sibling
      // books already rendered from lighter endpoints.
      const timeoutMs = path.includes('broker-proposals')
        ? 15_000
        : (path.includes('/options/proposals') || path.includes('/options/monitor'))
          ? 120_000
          : path.includes('universe-theses')
            ? 90_000
            : 30_000
      // Initial load only — interval polls keep last data without blanking the UI
      if (dataRef.current == null) setLoading(true)
      try {
        // cache-bust so "Refresh" and polls never serve a stale browser cache
        const sep = path.includes('?') ? '&' : '?'
        const url = `${path}${sep}_=${Date.now()}`
        const etag = _etags.get(path)
        const headers: Record<string, string> = etag ? { 'If-None-Match': etag } : {}
        // Two hooks that poll the same path in the same tick (NavRail and MetricStrip both poll the
        // approvals summary) join ONE read — lib/inflightGet.ts. The body is read here, once: a
        // Response body can be consumed only once, so what is shared is its status, headers and text,
        // which every joined caller can read again.
        const r = await coalesceInFlight(path, async () => {
          const controller = new AbortController()
          controllers.add(controller)
          let timer: ReturnType<typeof setTimeout> | undefined
          const scheduled = scheduleApiRequest(async () => {
            timer = setTimeout(() => controller.abort(), timeoutMs)
            try {
              const res = await fetch(url, { signal: controller.signal, cache: 'no-store', headers })
              return { ok: res.ok, status: res.status, headers: res.headers, text: await res.text() }
            } finally {
              if (timer) clearTimeout(timer)
            }
          }, background)
          cancelQueued.add(scheduled.cancel)
          try {
            return await scheduled.promise
          } finally {
            // The read is over: this hook's cleanup must no longer abort it on unmount.
            cancelQueued.delete(scheduled.cancel)
            controllers.delete(controller)
          }
        })
        if (r.status === 304) {
          confirmLastGood(path, Date.now())
          // A subscriber that joined another hook's ETag revalidation has no body of its own yet: the recorded body is
          // the answer the 304 confirmed.
          if (dataRef.current == null) {
            const held = peekLastGood(path)
            if (held && !cancelled) apply(held.json, held.at)
          }
          // Snapshot unchanged — the retained body is still the last-good body.
          // Transport receipt advances; the DATA clock does not. Consumers keep
          // the complete prior payload and recompute age from the current clock,
          // so a repeatedly-revalidated observation still ages toward stale.
          setError(null)
          setErrorCode(null)
          setErrorDetail(null)
          setStale(false)
          setReceivedAt(new Date().toISOString())
          setTransport('RETAINED')
          clearFailing()
          retries = 0
          return
        }
        if (r.status === 503) {
          // server_busy — keep last-good data and soft-retry WITHOUT raising the global
          // reconnect banner. Counting 503 toward "failing feeds" made the amber bar stick
          // whenever heavy endpoints briefly saturated the semaphore (10 feeds × 503).
          let retryAfter = 2
          try {
            const j = JSON.parse(r.text)
            if (j?.retry_after_sec) retryAfter = Number(j.retry_after_sec) || 2
          } catch { /* ignore */ }
          const busy = parseErrorBody(r.text)
          setErrorCode(busy.code)
          setErrorDetail(busy.detail)
          if (dataRef.current != null) {
            setStale(true)
            setError(null) // last-good is valid; no hard error chip
            setTransport('RETAINED')
          } else {
            setError('server busy — retrying')
            setTransport('ERROR')
          }
          // Do NOT _bumpFail for 503-with-data — only hard timeouts/network bump the banner
          if (retries < 10) {
            retries++
            clearTimeout(retryRef.current)
            retryRef.current = setTimeout(load, Math.max(retryAfter * 1000, backoffMs(retries)))
          }
          return
        }
        if (!r.ok) {
          // 401/403 are authorization answers, not connectivity problems. They are
          // terminal: no retry, no backoff ladder, no reconnect banner. The
          // last-good body is kept (dropping it would be a second lie) but the
          // stale flag is NEVER cleared — nothing just got fresher.
          const outcome = classifyStatus(r.status, r.headers)
          if (cancelled) return
          setError(outcome.message)
          const refusal = parseErrorBody(r.text)
          setErrorCode(refusal.code)
          setErrorDetail(refusal.detail)
          if (outcome.kind === 'UNAUTHORIZED' || outcome.kind === 'FORBIDDEN') {
            setAuthState(outcome.kind)
          }
          if (dataRef.current != null) {
            setStale(true)
            setTransport('RETAINED')
          } else {
            setTransport('ERROR')
          }
          if (countsAsConnectionFailure(outcome)) {
            if (!failingRef.current) { failingRef.current = true; _bumpFail(1) }
          } else {
            clearFailing()
          }
          if (outcome.terminal) {
            terminalRef.current = outcome.kind
            clearTimeout(retryRef.current)
            clearTimeout(slowRetryRef)
            clearInterval(intervalRef.current)
            retries = 0
            return
          }
          if (retries < 8) {
            retries++
            clearTimeout(retryRef.current)
            const delay = outcome.retryAfterMs ?? backoffMs(retries)
            retryRef.current = setTimeout(load, delay)
          }
          return
        }
        setAuthState('OK')
        const et = r.headers.get('ETag')
        if (et) _etags.set(path, et)
        const json = JSON.parse(r.text)
        const at = Date.now()
        // Every other subscriber of this path gets the same body now; this hook applies it below.
        noteLastGood(path, json, at, listener)
        if (cancelled) return
        apply(json, at)
        clearFailing()
        retries = 0
      } catch (e: any) {
        if (cancelled) return
        const outcome = classifyError(e)
        setError(outcome.message)
        // A thrown request has no response body: the previous refusal code is not this failure's answer.
        setErrorCode(null)
        setErrorDetail(null)
        // Keep last-good data; flag it stale so the UI can show a 'reconnecting' hint instead of
        // collapsing to zeros. Only mark stale when we actually have prior data to keep showing.
        if (dataRef.current != null) {
          setStale(true)
          setTransport('RETAINED')
        } else {
          setTransport('ERROR')
        }
        if (!failingRef.current) { failingRef.current = true; _bumpFail(1) }
        // Quick backoff retry so a transient failure (e.g. a server-restart window) recovers in
        // seconds, not after the full polling interval.
        if (retries < 8) {
          retries++
          clearTimeout(retryRef.current)
          retryRef.current = setTimeout(load, backoffMs(retries))
        } else if (!slowRetryRef) {
          // Keep probing while degraded instead of waiting for the full poll interval — but calmly.
          slowRetryRef = setTimeout(() => { slowRetryRef = undefined; retries = 0; load() }, 30_000)
        }
      } finally {
        // Abandoned effects must not settle loading=false with data=null.
        // That is how Trade AI painted "No scanner data yet" after a tab
        // remount cancelled a still-in-flight 200.
        if (!cancelled) {
          setLoading(false)
          clearManual()
        }
        inFlight = false
      }
    }
    load('mount')
    if (intervalMs && intervalMs > 0) intervalRef.current = setInterval(() => { void load('tick') }, intervalMs)
    // Paused while hidden; one read (or the shared body) as soon as the page is visible again.
    const onVisibility = () => { if (documentVisible()) void load('visible') }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      unsubscribe()
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
      clearInterval(intervalRef.current)
      clearTimeout(retryRef.current)
      clearTimeout(slowRetryRef)
      slowRetryRef = undefined
      controllers.forEach(controller => controller.abort())
      controllers.clear()
      cancelQueued.forEach(cancel => cancel())
      cancelQueued.clear()
      clearFailing()   // don't leave a stuck failure registered when this hook unmounts / path changes
    }
  }, [path, intervalMs, tick, enabled, background])

  return { data, envelope, loading, refreshing, error, errorCode, errorDetail, stale, receivedAt, transport, authState, refetch }
}
