import { useEffect, useRef, useState } from 'react'
import { getJson } from '../../api/client'
import { useDrawer } from '../../components/Drawer'
import { Note } from '../../components/primitives'
import { StateView } from '../../components/StateView'
import { HomeTodayPage } from './HomeTodayPage'
import { HomeNeedsPage } from './HomeNeedsPage'
import { HomeOutlookPage } from './HomeOutlookPage'
import { ageLabel, cioContextModel, state } from './homeAdapter'
import type { Read } from './homeAdapter'
import { homeV2Model } from './homeV2Adapter'
import { useOperatingHeader } from '../../shell/OperatingHeader'

// The refresh interval arrives later from the shared header (60 or 300 s). It is read through a ref so a header
// timing change re-times the next poll instead of aborting and resetting the read in flight (P1 2026-11-16).
export function useReads(paths:Record<string,string>,refreshSeconds?:number) { return useReadsControl(paths,refreshSeconds).reads }
// retry(): runs one refresh now unless a refresh is already in flight (never a duplicate request). loading is true while
// a refresh is in flight, so a Retry control can be disabled instead of queueing requests (H01 2026-11-16).
export function useReadsControl(paths:Record<string,string>,refreshSeconds?:number) {
 const [reads,setReads]=useState<Record<string,Read>>({}),[loading,setLoading]=useState(true),key=JSON.stringify(paths)
 const every=useRef(refreshSeconds),retime=useRef<(()=>void)|null>(null),again=useRef<(()=>void)|null>(null)
 useEffect(()=>{const changed=every.current!==refreshSeconds;every.current=refreshSeconds;if(changed)retime.current?.()},[refreshSeconds])
 useEffect(()=>{
  const ctl=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined
  setReads({})
  async function refresh(){
   await Promise.allSettled(Object.entries(paths).map(async([name,path])=>{
    const read=await getJson<unknown>(path,ctl.signal)
    if(!ctl.signal.aborted)setReads(previous=>({...previous,[name]:read}))
   }))
   busy=false;if(!ctl.signal.aborted)setLoading(false);schedule()
  }
  let busy=true
  setLoading(true)
  function schedule(){
   if(timer!==undefined){clearTimeout(timer);timer=undefined}
   const secs=every.current
   if(secs&&!busy&&!ctl.signal.aborted)timer=setTimeout(()=>{timer=undefined;busy=true;void refresh()},secs*1000)
  }
  retime.current=schedule
  again.current=()=>{if(busy||ctl.signal.aborted)return;if(timer!==undefined){clearTimeout(timer);timer=undefined};busy=true;setLoading(true);void refresh()}
  void refresh()
  return()=>{ctl.abort();retime.current=null;again.current=null;if(timer!==undefined)clearTimeout(timer)}
 },[key])
 return {reads,loading,retry:()=>again.current?.()}
}
function CioContext({now,labels}:{now:number;labels:Map<string,string>}) {
 const reads=useReads({cio:'/api/v2/home/cio-card'}),s=state(reads.cio??null,r=>cioContextModel(r,labels),now)
 return <StateView state={s}>{c=><><Note>Read-only stored CIO context · advisory only. Generated {c.built||'unknown'}; this is a build time.</Note><h3>Advice</h3>{c.eligible?c.facts.length?c.facts.map((f,i)=><section key={i}><h4>{f.label}</h4><p>{f.value}</p><p>{ageLabel(f.at,now)}</p></section>):<p>No stored advice text supplied.</p>:<p>Current advice unavailable.</p>}<p>{c.reason}</p><h3>Inputs &amp; clocks</h3>{c.inputs.map((v,i)=><section key={i}><h4>{v.name}</h4><p>{v.present?'Source supplied':'Source presence unproven'} · {v.stale?'Stale':'Health unproven'} · {v.role}</p><p>{ageLabel(v.at,now)}</p></section>)}<h3>Recorded notes</h3>{c.notes.length?c.notes.map((n,i)=><section key={i}><h4>{n.title||'Recorded note'}</h4><p>{n.text}</p><p>{ageLabel(n.at,now)}</p></section>):<p>No comparison notes supplied.</p>}<p>Protection records do not establish active protection. Conflicting dated inputs remain separate from a newly synthesized answer.</p></>}</StateView>
}
const DASHBOARD={dashboard:'/api/v2/wealth/home-v2'}
export function HomeLive({view='today'}:{view?:'today'|'needs'|'outlook'}) {
 const header=useOperatingHeader(),{reads,loading,retry}=useReadsControl(DASHBOARD,header.pollAfterSeconds),drawer=useDrawer(),model=homeV2Model(reads.dashboard??null)
 const now=Date.now()
 return <><Note>Stored advisory observations · source times and eligibility differ by section. Open Evidence for coverage, dated protection and missing fields; a successful read does not establish freshness.</Note>{model.error?<Note>Home stored read failed: {model.error}. {reads.dashboard?.lastGood!=null?'Retained values below are the last successful read, shown with their original source clocks.':'No earlier Home read succeeded in this session, so no values are retained.'} <button type="button" onClick={retry} disabled={loading}>{loading?'Retrying…':'Retry'}</button></Note>:null}{view==='needs'?<HomeNeedsPage sections={model.needs} now={now}/>:view==='outlook'?<HomeOutlookPage sections={model.outlook} now={now}/>:<HomeTodayPage sections={model.today} now={now} cio={()=>drawer.open({title:'CIO context · dated evidence',body:<CioContext now={Date.now()} labels={model.labels}/>})}/>}</>
}
