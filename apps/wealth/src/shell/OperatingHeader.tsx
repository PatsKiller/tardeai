import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { client } from '../api/client'
import { useDrawer } from '../components/Drawer'
import { WealthIcon, WealthStatus } from '../components/WealthStatus'
import { HEADER_CELLS, headerModel, sourceClockLabel, clockDiagnostics } from './operatingHeaderModel'
import type { OperatingCell, OperatingModel } from './operatingHeaderModel'
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
// Shared by the actual header and synthetic rendering checks. State color and read freshness are separate facts.
export function OperatingHeaderReading({cell:c}:{cell:OperatingCell}) {
 const signed=c.id==='session_pl'&&c.numeric!==null&&c.verdict!=='read failed'
 const tone=signed?(c.numeric!>0?'green':c.numeric!<0?'red':'grey'):c.id==='regime'?c.regimeTone:c.tone
 const label=signed&&c.numeric!==0?`${c.numeric!>0?'▲':'▼'} ${c.display}`:c.display
 const caution=c.verdict.includes('stale')||c.verdict==='partial'||c.verdict==='read failed'||c.qualification?.includes('policy unproven')
 return <>
  {c.id==='temperature'&&c.temperatureTier?<div className="wealth-operating-temperature-reading" data-temperature-tier={c.temperatureTier}>
   <span className="wealth-operating-tier" style={c.temperatureColor?{color:c.temperatureColor}:undefined}><WealthStatus icon={c.icon} tone="grey" label={c.temperatureTier} detail={c.tooltip}/></span>
   {c.temperatureScore!==null?<span className="wealth-operating-score"> · {c.temperatureScore.toFixed(1)}</span>:null}
  </div>:<WealthStatus icon={c.icon} tone={tone} label={label} detail={c.tooltip}/>}
  {c.id==='regime'&&(c.confidence!==null||c.regimeScore!==null)?<small className="wealth-operating-regime-metrics">{[c.confidence!==null?`Confidence ${new Intl.NumberFormat('en-US',{style:'percent',maximumFractionDigits:1}).format(c.confidence)}`:null,c.regimeScore!==null?`Score ${c.regimeScore} points`:null].filter(Boolean).join(' · ')}</small>:null}
  {c.id==='session_pl'&&c.numeric!==null?<small>Estimate · interval unverified</small>:null}
  {c.qualification?<small className="wealth-operating-freshness" data-tone={caution?'amber':'grey'}><WealthIcon name={caution?'warning':'clock'}/>{c.qualification}</small>:null}
 </>
}
export function OperatingHeader(){
 const model=useOperatingHeader(),drawer=useDrawer(),[,tick]=useState(0),[expanded,setExpanded]=useState(false)
 // Every response-driven render gets a new evaluation time, after asynchronous completion.
 const now=Date.now()
 useEffect(()=>{const t=setInterval(()=>tick(n=>n+1),15000);return()=>clearInterval(t)},[])
 return <><section className="wealth-operating-header" aria-label="Operating overview · household" data-session={model.sessionKey} data-cell-count={HEADER_CELLS.length} data-expanded={expanded}>
  {model.cells.map((c,index)=><article className={'wealth-operating-cell'+(index>=4?' wealth-operating-secondary':'')} key={c.id} data-header-cell={c.id} data-tone={c.tone}>
   <button className="wealth-operating-label" aria-label={`Details: ${c.label}`} onClick={e=>drawer.open({title:c.label,origin:e.currentTarget,body:<div className="wealth-operating-detail"><p>{c.display}</p>{c.secondary.map((line,i)=><p key={i}>{line}</p>)}<p>{c.tooltip}</p><p>{sourceClockLabel(c.clock,Date.now(),model.servedAt)}</p><p>Source time: {c.clock||'not served'}. Server response evaluated: {model.servedAt||'not served'}.</p><p>Clock diagnostics: source minus client {clockDiagnostics(c.clock,now,model.servedAt).sourceDeltaMs??'unknown'} ms; response minus client {clockDiagnostics(c.clock,now,model.servedAt).responseDeltaMs??'unknown'} ms. No undocumented skew tolerance applied.</p>{c.id==='health'?<a href="/v3/health">Review health findings</a>:null}{c.id==='temperature'?<a href="/wealth/home/today#home-v2-stance">Review dated stance</a>:null}<p>Household scope. This view does not change account scope, approvals or operating capabilities.</p></div>})}><WealthIcon name={c.icon}/>{c.label}</button>
   <OperatingHeaderReading cell={c}/>
   <div className="wealth-operating-secondary-text">{c.secondary.slice(0,1).map((line,i)=><small key={i}>{line}</small>)}</div>
   <small className="wealth-operating-clock">{sourceClockLabel(c.clock,now,model.servedAt)}</small>
   {c.id==='health'?<a className="wealth-operating-review" href="/v3/health">Review findings →</a>:null}
  </article>)}
 </section><button className="wealth-operating-expand" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?'Less operating detail':'More operating detail · regime, VIX, mode, health'}</button></>
}
