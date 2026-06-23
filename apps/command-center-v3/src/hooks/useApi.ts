import { useState, useEffect, useRef, useCallback } from 'react'

// ── Global connection health ─────────────────────────────────────────────────────────────────────────
// useApi consumers register/clear when they enter/leave a failed state, so a single top-level indicator
// ("Reconnecting…") can reflect that the backend is briefly unreachable (e.g. a server restart) WITHOUT
// every hub collapsing its own view to authoritative-looking zeros.
let _failCount = 0
const _listeners = new Set<(n: number) => void>()
function _bumpFail(delta: number) {
  _failCount = Math.max(0, _failCount + delta)
  _listeners.forEach(l => l(_failCount))
}
export function useConnectionHealth() {
  const [n, setN] = useState(_failCount)
  useEffect(() => { _listeners.add(setN); setN(_failCount); return () => { _listeners.delete(setN) } }, [])
  return { degraded: n > 0, failing: n }
}

export function useApi<T>(path: string, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)   // showing last-good data after a failed refetch
  const [tick, setTick] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()
  const retryRef = useRef<ReturnType<typeof setTimeout>>()
  const dataRef = useRef<T | null>(null)       // latest good data, readable inside the fetch closure
  const failingRef = useRef(false)             // this hook's current contribution to the global fail count

  const refetch = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    let cancelled = false
    let retries = 0
    const clearFailing = () => { if (failingRef.current) { failingRef.current = false; _bumpFail(-1) } }

    const load = async () => {
      const controller = new AbortController()
      const timeoutMs = path.includes('broker-proposals') ? 45_000 : 30_000
      const timer = setTimeout(() => controller.abort(), timeoutMs)
      try {
        const r = await fetch(path, { signal: controller.signal })
        clearTimeout(timer)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
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
        if (retries < 5) {
          retries++
          clearTimeout(retryRef.current)
          retryRef.current = setTimeout(load, Math.min(1500 * retries, 8000))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    if (intervalMs && intervalMs > 0) intervalRef.current = setInterval(load, intervalMs)
    return () => {
      cancelled = true
      clearInterval(intervalRef.current)
      clearTimeout(retryRef.current)
      clearFailing()   // don't leave a stuck failure registered when this hook unmounts / path changes
    }
  }, [path, intervalMs, tick])

  return { data, loading, error, stale, refetch }
}
