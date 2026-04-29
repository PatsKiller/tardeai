import { useState, useEffect } from 'react'

/**
 * Fetch from a /api/v2/* endpoint. Unwraps the { ok, data } envelope.
 * Returns data as T, or null while loading / on error.
 */
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(path)
      .then(r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
        return r.json()
      })
      .then(envelope => {
        if (!cancelled) {
          if (envelope.ok && envelope.data !== undefined) {
            setData(envelope.data)
          } else if (envelope.ok) {
            // Some endpoints (reports/catalog) don't use the data wrapper
            setData(envelope as T)
          } else {
            setError(envelope.error || 'API error')
          }
        }
      })
      .catch(e => { if (!cancelled) setError(e.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [path])

  return { data, loading, error }
}
