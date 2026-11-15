import { useEffect, useMemo, useState } from 'react'
import { getJson } from '../../api/client'
import { useDrawer } from '../../components/Drawer'
import { Note } from '../../components/primitives'
import { StateView } from '../../components/StateView'
import { HomeTodayPage } from './HomeTodayPage'
import { ageLabel, homeToday, record, rows, safeText, state, text } from './homeAdapter'
import type { Read, Row } from './homeAdapter'

function useReads(paths: Record<string, string>) {
  const [reads, setReads] = useState<Record<string, Read>>({})
  const key = JSON.stringify(paths)
  useEffect(() => {
    const ctl = new AbortController()
    setReads({})
    for (const [name, path] of Object.entries(paths)) void getJson<unknown>(path, ctl.signal).then(read => {
      if (!ctl.signal.aborted) setReads(previous => ({ ...previous, [name]: read }))
    })
    return () => ctl.abort()
  }, [key])
  return reads
}
function CioContext({ now }: { now: number }) {
  const reads = useReads({ cio: '/api/v2/home/cio-card' })
  const s = state(reads.cio ?? null, r => r, now)
  return <StateView state={s}>{r => {
    const advice = record(r.advice), inputs = record(r.inputs), card = record(r.card)
    return <><Note>Read-only stored CIO context · advisory only. Generated {text(r.generated_at) || 'unknown'}; this is a build time.</Note><h3>Advice</h3><p>{advice.ok === true && r.advisory_only === true ? safeText(record(card.posture).value) || 'No stored posture text.' : 'Current advice unavailable.'}</p><p>{safeText(advice.reason)}</p><h3>Inputs &amp; clocks</h3>{Object.entries(inputs).map(([name, value]) => <p key={name}>{name.replace(/_/g, ' ')} · {ageLabel(record(value).as_of, now)} · {record(value).stale === true ? 'Stale' : 'Health unproven'}</p>)}<h3>Recorded notes</h3>{rows(r.notes).map((n: Row, i: number) => <section key={i}><h4>{safeText(n.title || n.label)}</h4><p>{safeText(n.text || n.body)}</p><p>{ageLabel(n.as_of, now)}</p></section>)}<p>Protection records do not establish active protection.</p></>
  }}</StateView>
}
const TODAY = { overview: '/api/v2/overview', snapshot: '/api/v2/home/since-close', movers: '/api/v2/market-movers', priorities: '/api/v2/home/priorities-live' }
export function HomeLive() {
  const reads = useReads(TODAY), drawer = useDrawer()
  const now = Date.now()
  const model = useMemo(() => homeToday(reads, now), [reads, now])
  return <HomeTodayPage model={model} now={now} cio={() => drawer.open({ title: 'CIO context', body: <CioContext now={Date.now()} /> })} />
}
