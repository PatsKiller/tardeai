// Page-owned Performance and canonical label reads. No polling, source build or fixture fallback.
import { useEffect, useMemo, useState } from 'react'
import type { Envelope } from '../../api/client'
import { getJson } from '../../api/client'
import { Note } from '../../components/primitives'
import { PerformancePage } from './PerformancePage'
import { PERFORMANCE_PATH, performanceRead, selectPerformance } from './performanceAdapter'
import { useSearchParams } from 'react-router-dom'
import { usePublishPerformanceAccounts } from './performanceScope'
import { performanceAccountLabel } from './performanceView'
import { accountMap, body } from '../home/homeAdapter'

export function PerformanceLive() {
  const [params, setParams] = useSearchParams()
  const [env, setEnv] = useState<Envelope<unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [labelEnv, setLabelEnv] = useState<Envelope<unknown> | null>(null)
  const [labelsSettled, setLabelsSettled] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const ctl = new AbortController()
    let live = true
    getJson<unknown>(PERFORMANCE_PATH, ctl.signal).then(value => {
      if (live) { setEnv(value); setNow(Date.now()) }
    }).catch((e: unknown) => {
      if (live) { setError(e instanceof Error ? e.message : 'Performance request failed'); setNow(Date.now()) }
    })
    // Display metadata only: this read never updates the Performance observation clock.
    getJson<unknown>('/api/v2/overview', ctl.signal).then(value => {
      if (live) { setLabelEnv(value); setLabelsSettled(true) }
    }).catch(() => { if (live) setLabelsSettled(true) })
    return () => { live = false; ctl.abort() }
  }, [])
  const labels = useMemo(() => {
    if (!labelEnv?.ok) return new Map<string, string>()
    const source = body(labelEnv.data)
    if (source.ok === false || source.error || ['UNKNOWN', 'UNAVAILABLE', 'unavailable', 'no_snapshot', 'not_evaluated'].includes(String(source.status ?? source.state))) return new Map<string, string>()
    return accountMap(source)
  }, [labelEnv])
  const read = useMemo(() => performanceRead(env, now, error, labels), [env, now, error, labels])
  const choices = useMemo(() => read.props?.accounts.map(account => ({ key: account.key, label: performanceAccountLabel(account) })) ?? null, [read.props])
  usePublishPerformanceAccounts(choices, read.state === 'loading' || read.props !== null ? null : read.reason ?? 'Performance source unavailable.')
  const selection = read.props ? selectPerformance(read.props, params.get('account'), params.get('period')) : null
  if (read.state === 'loading') return <Note>Reading Performance source. No values substituted while loading.</Note>
  if (read.props === null) return <div role="status"><Note>{read.reason ?? 'Unknown — Performance source not served.'}</Note></div>
  return <>
    {read.props.accounts.some(account => !account.label) && <Note>{labelsSettled ? 'Account labels unavailable; numbered placeholders identify source rows.' : 'Reading account labels; numbered placeholders identify source rows.'}</Note>}
    {read.notice && <div role="status"><Note>{read.notice}</Note></div>}
    {selection?.notice && <Note>{selection.notice}</Note>}
    <PerformancePage {...selection!.props} onPeriodChange={period => {
      const next = new URLSearchParams(params); next.set('period', period === 'Latest session' ? '1D' : period); setParams(next)
    }} />
  </>
}
