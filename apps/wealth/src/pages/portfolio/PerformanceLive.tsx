// One page-owned read of the existing endpoint. No polling, source build or fixture fallback.
import { useEffect, useMemo, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { Note } from '../../components/primitives'
import { PerformancePage } from './PerformancePage'
import { PERFORMANCE_PATH, performanceRead, selectPerformance } from './performanceAdapter'
import { useSearchParams } from 'react-router-dom'
import { usePublishPerformanceAccounts } from './performanceScope'
import { performanceAccountLabel } from './performanceView'

export function PerformanceLive() {
  const [params, setParams] = useSearchParams()
  const [env, setEnv] = useState<Envelope<unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const ctl = new AbortController()
    let live = true
    getJson<unknown>(PERFORMANCE_PATH, ctl.signal).then(value => {
      if (live) { setEnv(value); setNow(Date.now()) }
    }).catch((e: unknown) => {
      if (live) { setError(e instanceof Error ? e.message : 'Performance request failed'); setNow(Date.now()) }
    })
    return () => { live = false; ctl.abort() }
  }, [])
  const read = useMemo(() => performanceRead(env, now, error), [env, now, error])
  const choices = useMemo(() => read.props?.accounts.map(account => ({ key: account.key, label: performanceAccountLabel(account) })) ?? null, [read.props])
  usePublishPerformanceAccounts(choices, read.state === 'loading' || read.props !== null ? null : read.reason ?? 'Performance source unavailable.')
  const selection = read.props ? selectPerformance(read.props, params.get('account'), params.get('period')) : null
  if (read.state === 'loading') return <Note>Reading Performance source. No values substituted while loading.</Note>
  if (read.props === null) return <div role="status"><Note>{read.reason ?? 'Unknown — Performance source not served.'}</Note></div>
  return <>
    {read.notice && <div role="status"><Note>{read.notice}</Note></div>}
    {selection?.notice && <Note>{selection.notice}</Note>}
    <PerformancePage {...selection!.props} onPeriodChange={period => {
      const next = new URLSearchParams(params); next.set('period', period === 'Latest session' ? '1D' : period); setParams(next)
    }} />
  </>
}
