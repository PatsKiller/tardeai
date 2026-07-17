import { useState, useEffect, useRef, useCallback } from 'react'

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

export type UseApiOptions = { enabled?: boolean }

// v3.1 (WS-A): manual ETag revalidation — server answers 304 before any JSON
// serialize/gzip, which is where the CPU actually went. Keyed by path.
const _etags = new Map<string, string>()

// Exponential backoff with jitter: 1s → 2s → 4s … cap 30s. A retry hammer over
// a busy single-process server just keeps it busy.
function backoffMs(attempt: number): number {
  const base = Math.min(30_000, 1_000 * Math.pow(2, attempt))
  return Math.round(base * (0.5 + Math.random() * 0.5))
}

export function useApi<T>(path: string, intervalMs?: number, options?: UseApiOptions) {
  const enabled = options?.enabled !== false
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false) // manual refetch in flight (keeps last data)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)   // showing last-good data after a failed refetch
  const [tick, setTick] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()
  const retryRef = useRef<ReturnType<typeof setTimeout>>()
  const dataRef = useRef<T | null>(null)       // latest good data, readable inside the fetch closure
  const failingRef = useRef(false)             // this hook's current contribution to the global fail count
  const manualRef = useRef(false)              // true when user-triggered refetch

  const refetch = useCallback(() => {
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
    let retries = 0
    let slowRetryRef: ReturnType<typeof setTimeout> | undefined
    const clearFailing = () => { if (failingRef.current) { failingRef.current = false; _bumpFail(-1) } }
    const clearManual = () => {
      if (manualRef.current) {
        manualRef.current = false
        setRefreshing(false)
      }
    }

    const load = async () => {
      const controller = new AbortController()
      // broker-proposals: 15s hard timeout (P0 2026-07-14) — the endpoint is now bounded
      // server-side (quote budget + background autocal/summary); anything slower should
      // surface the error/Retry state instead of an endless "Loading broker queue…".
      const timeoutMs = path.includes('broker-proposals') ? 15_000 : 30_000
      const timer = setTimeout(() => controller.abort(), timeoutMs)
      // Initial load only — interval polls keep last data without blanking the UI
      if (dataRef.current == null) setLoading(true)
      try {
        // cache-bust so "Refresh" and polls never serve a stale browser cache
        const sep = path.includes('?') ? '&' : '?'
        const url = `${path}${sep}_=${Date.now()}`
        const etag = _etags.get(path)
        const headers: Record<string, string> = etag ? { 'If-None-Match': etag } : {}
        const r = await fetch(url, { signal: controller.signal, cache: 'no-store', headers })
        clearTimeout(timer)
        if (r.status === 304) {
          // Snapshot unchanged — last data is CURRENT, not stale
          setError(null)
          setStale(false)
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
            const j = await r.json()
            if (j?.retry_after_sec) retryAfter = Number(j.retry_after_sec) || 2
          } catch { /* ignore */ }
          if (dataRef.current != null) {
            setStale(true)
            setError(null) // last-good is valid; no hard error chip
          } else {
            setError('server busy — retrying')
          }
          // Do NOT _bumpFail for 503-with-data — only hard timeouts/network bump the banner
          if (retries < 10) {
            retries++
            clearTimeout(retryRef.current)
            retryRef.current = setTimeout(load, Math.max(retryAfter * 1000, backoffMs(retries)))
          }
          return
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const et = r.headers.get('ETag')
        if (et) _etags.set(path, et)
        const json = await r.json()
        if (cancelled) return
        const next = json.ok !== undefined ? (json.data ?? json) : json
        dataRef.current = next
        setData(next)
        setError(null)
        setStale(false)
        clearFailing()
        retries = 0
      } catch (e: any) {
        clearTimeout(timer)
        if (cancelled) return
        const msg = e?.name === 'AbortError' ? 'request timed out — server busy, retry' : (e?.message || 'fetch failed')
        setError(msg)
        // Keep last-good data; flag it stale so the UI can show a 'reconnecting' hint instead of
        // collapsing to zeros. Only mark stale when we actually have prior data to keep showing.
        if (dataRef.current != null) setStale(true)
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
        if (!cancelled) {
          setLoading(false)
          clearManual()
        }
      }
    }
    load()
    if (intervalMs && intervalMs > 0) intervalRef.current = setInterval(load, intervalMs)
    return () => {
      cancelled = true
      clearInterval(intervalRef.current)
      clearTimeout(retryRef.current)
      clearTimeout(slowRetryRef)
      clearFailing()   // don't leave a stuck failure registered when this hook unmounts / path changes
    }
  }, [path, intervalMs, tick, enabled])

  return { data, loading, refreshing, error, stale, refetch }
}
