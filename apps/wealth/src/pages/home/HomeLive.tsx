import { useEffect, useState } from 'react'
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

export function useReads(paths:Record<string,string>,refreshSeconds?:number) {
 const [reads,setReads]=useState<Record<string,Read>>({}),key=JSON.stringify(paths)
 useEffect(()=>{
  const ctl=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined
  setReads({})
  async function refresh(){
   await Promise.allSettled(Object.entries(paths).map(async([name,path])=>{
    const read=await getJson<unknown>(path,ctl.signal)
    if(!ctl.signal.aborted)setReads(previous=>({...previous,[name]:read}))
   }))
   if(refreshSeconds&&!ctl.signal.aborted)timer=setTimeout(()=>void refresh(),refreshSeconds*1000)
  }
  void refresh()
  return()=>{ctl.abort();if(timer!==undefined)clearTimeout(timer)}
 },[key,refreshSeconds])
 return reads
}
function CioContext({now,labels}:{now:number;labels:Map<string,string>}) {
 const reads=useReads({cio:'/api/v2/home/cio-card'}),s=state(reads.cio??null,r=>cioContextModel(r,labels),now)
 return <StateView state={s}>{c=><><Note>Read-only stored CIO context · advisory only. Generated {c.built||'unknown'}; this is a build time.</Note><h3>Advice</h3>{c.eligible?c.facts.length?c.facts.map((f,i)=><section key={i}><h4>{f.label}</h4><p>{f.value}</p><p>{ageLabel(f.at,now)}</p></section>):<p>No stored advice text supplied.</p>:<p>Current advice unavailable.</p>}<p>{c.reason}</p><h3>Inputs &amp; clocks</h3>{c.inputs.map((v,i)=><section key={i}><h4>{v.name}</h4><p>{v.present?'Source supplied':'Source presence unproven'} · {v.stale?'Stale':'Health unproven'} · {v.role}</p><p>{ageLabel(v.at,now)}</p></section>)}<h3>Recorded notes</h3>{c.notes.length?c.notes.map((n,i)=><section key={i}><h4>{n.title||'Recorded note'}</h4><p>{n.text}</p><p>{ageLabel(n.at,now)}</p></section>):<p>No comparison notes supplied.</p>}<p>Protection records do not establish active protection. Conflicting dated inputs remain separate from a newly synthesized answer.</p></>}</StateView>
}
const DASHBOARD={dashboard:'/api/v2/wealth/home-v2'}
export function HomeLive({view='today'}:{view?:'today'|'needs'|'outlook'}) {
 const header=useOperatingHeader(),reads=useReads(DASHBOARD,header.pollAfterSeconds),drawer=useDrawer(),model=homeV2Model(reads.dashboard??null)
 const now=Date.now()
 return <>{model.error?<Note>Home stored read failed: {model.error}. Any retained values below are last known, with their original source clocks.</Note>:null}{view==='needs'?<HomeNeedsPage sections={model.needs} now={now}/>:view==='outlook'?<HomeOutlookPage sections={model.outlook} now={now}/>:<HomeTodayPage sections={model.today} now={now} cio={()=>drawer.open({title:'CIO context · dated evidence',body:<CioContext now={Date.now()} labels={model.labels}/>})}/>}</>
}
