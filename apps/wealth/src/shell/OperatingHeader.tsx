import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { client } from '../api/client'
import { WealthIcon, WealthStatus } from '../components/WealthStatus'
import { HEADER_CELLS, headerModel, sourceClockLabel } from './operatingHeaderModel'
import type { OperatingModel } from './operatingHeaderModel'
import './operating-header.css'
const HeaderContext=createContext<OperatingModel>(headerModel(null))
export const useOperatingHeader=()=>useContext(HeaderContext)
export function OperatingHeaderProvider({children}:{children:ReactNode}) {
 const [model,setModel]=useState(()=>headerModel(null))
 useEffect(()=>{
  const ctl=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined
  async function refresh(){
   const read=await client.get<unknown>('/api/v2/wealth/operating-header',{from:'shell',signal:ctl.signal})
   if(ctl.signal.aborted)return
   const next=headerModel(read.data??read.lastGood,read.error)
   setModel(next)
   timer=setTimeout(()=>void refresh(),next.pollAfterSeconds*1000)
  }
  void refresh()
  return()=>{ctl.abort();if(timer!==undefined)clearTimeout(timer)}
 },[])
 return <HeaderContext.Provider value={model}>{children}</HeaderContext.Provider>
}
export function OperatingHeader(){
 const model=useOperatingHeader(),[now,setNow]=useState(Date.now)
 useEffect(()=>{const t=setInterval(()=>setNow(Date.now()),15000);return()=>clearInterval(t)},[])
 return <section className="wealth-operating-header" aria-label="Operating overview · household" data-session={model.sessionKey} data-cell-count={HEADER_CELLS.length}>
  {model.cells.map(c=><article className="wealth-operating-cell" key={c.id} data-header-cell={c.id} data-tone={c.tone}>
   <div className="wealth-operating-label"><WealthIcon name={c.icon}/>{c.label}</div>
   <WealthStatus icon={c.id!=='vix'&&c.id!=='session_pl'&&c.verdict.includes('stale')?'warning':c.icon} tone={c.id==='session_pl'&&c.numeric!==null&&c.verdict!=='read failed'?c.numeric>0?'green':c.numeric<0?'red':'grey':c.tone} label={c.id==='session_pl'&&c.numeric!==null&&c.numeric!==0?`${c.numeric>0?'▲':'▼'} ${c.display}`:c.display} detail={c.tooltip}/>
   {c.id==='session_pl'&&c.numeric!==null?<WealthStatus icon="clock" tone="amber" label="Estimate" detail="Stored current-holdings price movement; a verified reconciliation is not served."/>:null}
   {(c.id==='vix'||c.id==='session_pl')&&c.verdict.includes('stale')?<WealthStatus icon="warning" tone="amber" label="Stale" detail={c.tooltip}/>:null}
   {c.secondary.map((line,i)=><small key={i}>{line}</small>)}
   <small className="wealth-operating-clock">{sourceClockLabel(c.clock,now)}</small>
  </article>)}
 </section>
}
