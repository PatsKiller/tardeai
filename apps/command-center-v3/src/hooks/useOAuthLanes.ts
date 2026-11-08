import { useCallback, useEffect, useState } from 'react'
import { sharedGetJSON } from '../lib/sharedGet'

export type OAuthLane = {
  lane: string
  label?: string
  ready?: boolean
  reachable?: boolean
  authenticated?: boolean
  token_expired?: boolean
  status?: string
  hint?: string | null
  reason_code?: string | null
  billing?: string
  kind?: string
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
      // Every card that renders the run buttons mounts its own copy of this hook — the classic
      // intelligence page mounts twenty in one paint — and the answer is identical for all of them.
      // One shared read serves the burst; 21 identical GETs in 27 s were measured without it.
      const json = await sharedGetJSON<any>('/api/v2/llm/oauth-lanes', 5_000)
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
  const deepseekFlash = byLane('deepseek-flash')
  const deepseekPro = byLane('deepseek-v4-pro')
  // Metered DeepSeek: trust explicit ready; fall back to status === 'ready'
  const deepseekFlashReady = Boolean(deepseekFlash?.ready ?? (deepseekFlash?.status === 'ready'))
  const deepseekProReady = Boolean(deepseekPro?.ready ?? (deepseekPro?.status === 'ready'))

  return {
    lanes: data?.lanes || [],
    grok: byLane('grok'),
    chatgpt: byLane('chatgpt'),
    deepseek_flash: deepseekFlash,
    deepseek_pro: deepseekPro,
    grokReady: laneReady(byLane('grok')),
    chatgptReady: laneReady(byLane('chatgpt')),
    deepseekReady: deepseekFlashReady,
    deepseekProReady,
    readyCount: data?.ready_count,
    note: data?.note,
    loading,
    error,
    refresh,
  }
}