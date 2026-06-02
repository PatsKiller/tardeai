import { useState, useEffect, useRef, useCallback } from 'react'

export function useApi<T>(path: string, intervalMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const refetch = useCallback(() => setTick(t => t + 1), [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const r = await fetch(path)
        if (!r.ok) throw new Error(`${r.status}`)
        const json = await r.json()
        if (!cancelled) {
          setData(json.ok !== undefined ? json.data ?? json : json)
          setError(null)
        }
      } catch (e: any) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    if (intervalMs && intervalMs > 0) {
      intervalRef.current = setInterval(load, intervalMs)
    }
    return () => { cancelled = true; clearInterval(intervalRef.current) }
  }, [path, intervalMs, tick])

  return { data, loading, error, refetch }
}
