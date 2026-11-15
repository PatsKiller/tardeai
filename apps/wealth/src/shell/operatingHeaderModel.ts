import { safeText } from '../pages/home/homeAdapter'
import type { WealthIconName, WealthTone } from '../components/WealthStatus'
export const HEADER_CELLS = [
 ['session','Session','clock'],['session_pl','Session profit / loss','pulse'],
 ['account_value','Account value · household','wallet'],['temperature','Temperature','thermometer'],
 ['regime','Regime','compass'],['vix','VIX','pulse'],
 ['operating_mode','Operating mode','shield'],['health','Health & data','heart'],
] as const satisfies readonly (readonly [string,string,WealthIconName])[]
export interface OperatingCell {
 id:string; label:string; icon:WealthIconName; display:string; secondary:string[];
 tone:WealthTone; clock:string|null; source:string; tooltip:string; verdict:string;
 ageSeconds:number|null; staleAfterSeconds:number|null; numeric:number|null;
}
export interface OperatingModel {cells:OperatingCell[]; pollAfterSeconds:60|300; sessionKey:string; queueTotal:number|null; servedAt:string|null}
const row=(v:unknown):Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{}
const string=(v:unknown):string|null=>typeof v==='string'&&v.trim()?safeText(v):null
const number=(v:unknown):number|null=>typeof v==='number'&&Number.isFinite(v)?v:null
const clock=(v:unknown)=>{const s=string(v);return s&&/(?:Z|[+-]\d\d:\d\d)$/.test(s)&&Number.isFinite(Date.parse(s))?s:null}
export function headerModel(input:unknown, readError:string|null=null):OperatingModel {
 const outer=row(input),body=row(outer.data??input),cells=outer.ok===false||body.ok===false?{}:row(body.cells),session=row(body.session)
 const missing=string(body.reason??body.error)||readError||'The stored operating-header contract has not been served.'
 return {pollAfterSeconds:body.poll_after_s===60?60:300,sessionKey:string(session.key)||'unknown',servedAt:clock(body.as_of),queueTotal:(()=>{const n=number(body.queue_total??row(row(cells.health).value).queue_total);return n!==null&&n>=0&&Number.isInteger(n)?n:null})(),
 cells:HEADER_CELLS.map(([id,label,icon])=>{
  const c=row(cells[id]),v=row(c.value),stale=String(c.verdict??c.staleness??'').toLowerCase(),unavailable=c.value===null||!Object.keys(c).length
  const display=unavailable?null:string(c.display??v.display)??(typeof c.value==='string'?string(c.value):null)
  const source=string(c.source)||'/api/v2/wealth/operating-header'
  const stamp=clock(c.clock??c.as_of),declared=string(c.state??c.tone)
  const tone:WealthTone=id==='vix'||id==='account_value'||readError||unavailable||!display?'grey':stale.includes('stale')?'amber':declared==='green'||declared==='amber'||declared==='red'?declared:'grey'
  const reason=readError||string(c.reason)||(!display?missing:null)
  const parts=Array.isArray(c.secondary??v.secondary)?(c.secondary??v.secondary) as unknown[]:[]
  const secondary=parts.flatMap(x=>{const s=string(x);return s?[s]:[]})
  return {id,label:string(c.label)||label,icon,display:display||'not served',secondary,tone,clock:stamp,source,
   tooltip:[string(c.tooltip)||reason||'Stored observation',readError?'Last successful read; current read failed':null,`Source: ${source}`,`Source clock: ${stamp||'not served'}`,`Freshness: ${stale||'unknown'}`].filter(Boolean).join(' · '),
   verdict:readError?'read failed':stale||'unknown',ageSeconds:number(c.age_s),staleAfterSeconds:number(c.stale_after_s),numeric:display?number(v.amount??v.usd??v.index??v.value??c.value):null}
 })}
}
export function sourceClockLabel(stamp:string|null,now:number):string {
 if(!stamp)return 'source time not served'
 const age=now-Date.parse(stamp)
 if(age<0)return 'source clock is in the future'
 const formatted=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(stamp))
 return `${formatted} · ${age<60000?'<1 min':age<3600000?`${Math.floor(age/60000)} min`:`${(age/3600000).toFixed(1)} h`} old`
}
