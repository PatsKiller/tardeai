import { useCallback, useEffect, useState } from 'react'

export type OAuthLane = {
  lane: string
  label?: string
  ready?: boolean
  reachable?: boolean
  authenticated?: boolean
  token_expired?: boolean
  status?: string
  hint?: string | null
  billing?: string
  port?: number
  last_ok?: number
  consec_fail?: number
}

export function laneReady(ln: OAuthLane | undefined): boolean {
  if (!ln) return false
  return Boolean(ln.ready ?? (ln.status === 'ready' && ln.authenticated && !ln.token_expired))
}

export function useOAuthLanes(pollMs = 120_000) {
  const [data, setData] = useState<{ lanes: OAuthLane[]; ready_count?: number; note?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/v2/llm/oauth-lanes', { cache: 'no-store' })
      const json = await res.json()
      const payload = json?.data ?? json
      setData(payload)
      setError(null)
    } catch (e: any) {
      setError(String(e?.message || e).slice(0, 120))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    if (!pollMs) return
    const t = setInterval(() => void refresh(), pollMs)
    return () => clearInterval(t)
  }, [refresh, pollMs])

  const byLane = (id: string) => (data?.lanes || []).find(l => l.lane === id)

  return {
    lanes: data?.lanes || [],
    grok: byLane('grok'),
    chatgpt: byLane('chatgpt'),
    deepseekFlash: byLane('deepseek-flash'),
    deepseekV4: byLane('deepseek-v4'),
    grokReady: laneReady(byLane('grok')),
    chatgptReady: laneReady(byLane('chatgpt')),
    deepseekFlashReady: laneReady(byLane('deepseek-flash')),
    deepseekV4Ready: laneReady(byLane('deepseek-v4')),
    readyCount: data?.ready_count,
    note: data?.note,
    loading,
    error,
    refresh,
  }
}