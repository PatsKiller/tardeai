import { useEffect, useMemo, useState } from 'react'
import { getJson } from '../../api/client'
import { useDrawer } from '../../components/Drawer'
import { Note } from '../../components/primitives'
import { StateView } from '../../components/StateView'
import { HomeTodayPage } from './HomeTodayPage'
import { HomeNeedsPage } from './HomeNeedsPage'
import { HomeOutlookPage } from './HomeOutlookPage'
import { ageLabel, cioContextModel, homeToday, marketState, overviewModel, reviewModel, record, rows, safeText, state, text } from './homeAdapter'
import type { Read, Row } from './homeAdapter'

export function useReads(paths: Record<string, string>) {
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
function CioContext({ now, labels }: { now: number; labels: Map<string,string> }) {
 const reads=useReads({cio:'/api/v2/home/cio-card'}), s=state(reads.cio??null,r=>cioContextModel(r,labels),now)
 return <StateView state={s}>{c=><><Note>Read-only stored CIO context · advisory only. Generated {c.built||'unknown'}; this is a build time.</Note><h3>Advice</h3>{c.eligible?c.facts.length?c.facts.map((f,i)=><section key={i}><h4>{f.label}</h4><p>{f.value}</p><p>{ageLabel(f.at,now)}</p></section>):<p>No stored advice text supplied.</p>:<p>Current advice unavailable.</p>}<p>{c.reason}</p><h3>Inputs &amp; clocks</h3>{c.inputs.map((v,i)=><section key={i}><h4>{v.name}</h4><p>{v.present?'Source supplied':'Source presence unproven'} · {v.stale?'Stale':'Health unproven'} · {v.role}</p><p>{ageLabel(v.at,now)}</p></section>)}<h3>Recorded notes</h3>{c.notes.length?c.notes.map((n,i)=><section key={i}><h4>{n.title||'Recorded note'}</h4><p>{n.text}</p><p>{ageLabel(n.at,now)}</p></section>):<p>No comparison notes supplied.</p>}<p>Protection records do not establish active protection.</p></>}</StateView>
}
const TODAY = { overview: '/api/v2/overview', snapshot: '/api/v2/home/since-close', movers: '/api/v2/market-movers', priorities: '/api/v2/home/priorities-live' }
const NEEDS = { queue: '/api/v2/home/do-now', market: '/api/v2/market-risk/latest' }
const OUTLOOK = { overview: '/api/v2/overview', market: '/api/v2/market-risk/latest' }
export function HomeLive({ view = 'today' }: { view?: 'today' | 'needs' | 'outlook' }) {
  const reads = useReads(view === 'today' ? TODAY : view === 'needs' ? NEEDS : OUTLOOK), drawer = useDrawer()
  const now = Date.now()
  const model = useMemo(() => homeToday(reads, now), [reads, now])
  if (view === 'needs') return <HomeNeedsPage queue={state(reads.queue ?? null, reviewModel, now)} market={marketState(reads.market ?? null, now)} now={now} />
  if (view === 'outlook') return <HomeOutlookPage market={marketState(reads.market ?? null, now)} overview={state(reads.overview ?? null, overviewModel, now, r => record(record(r.clock_provenance).quote).as_of)} now={now} />
  return <HomeTodayPage model={model} now={now} cio={() => drawer.open({ title: 'CIO context', body: <CioContext now={Date.now()} labels={model.labels} /> })} />
}
