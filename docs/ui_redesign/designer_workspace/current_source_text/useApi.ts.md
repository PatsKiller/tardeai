# Source Export: useApi.ts

- **Original path:** apps/command-center-v2/src/hooks/useApi.ts
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:38:05-04:00
- **SHA256:** 31d95de0befd6fb913603133088c0d55ae70fc69c3c14ce239cf640b69ee0cae
- **File size:** 2216 bytes
- **Exists:** YES

```typescript
import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Fetch from a /api/v2/* endpoint. Unwraps the { ok, data } envelope.
 * Returns data as T, or null while loading / on error.
 * Retries once after 2s if the initial fetch fails (handles server restart).
 * Optional intervalMs: re-fetch every N milliseconds (for polling).
 */
export function useApi<T>(path: string, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const retried = useRef(false)
  const [tick, setTick] = useState(0)

  const refetch = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    let cancelled = false
    retried.current = false
    setLoading(true)

    const doFetch = () => {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 15000)
      fetch(path, { signal: controller.signal })
        .then(r => {
          clearTimeout(timeout)
          if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
          return r.json()
        })
        .then(envelope => {
          if (cancelled) return
          if (envelope.ok && envelope.data !== undefined) {
            setData(envelope.data)
          } else if (envelope.ok) {
            setData(envelope as T)
          } else {
            setError(envelope.error || 'API error')
          }
          setLoading(false)
        })
        .catch(e => {
          clearTimeout(timeout)
          if (cancelled) return
          if (!retried.current) {
            retried.current = true
            setTimeout(() => { if (!cancelled) doFetch() }, 2000)
            return
          }
          setError(e.name === 'AbortError' ? 'Request timed out — try refreshing' : e.message)
          setLoading(false)
        })
    }

    doFetch()
    return () => { cancelled = true }
  }, [path, tick])

  // Polling interval
  useEffect(() => {
    if (!intervalMs || intervalMs < 5000) return
    const id = setInterval(() => setTick(t => t + 1), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])

  return { data, loading, error, refetch }
}
```
