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
 const outer=row(input),body=row(outer.data??input),unsupported=body.schema!==undefined&&body.schema!=='WealthOperatingHeader@v1',cells=outer.ok===false||body.ok===false||unsupported?{}:row(body.cells),session=row(body.session)
 const missing=(unsupported?'Unsupported operating-header schema':null)||string(body.reason??body.error)||readError||'The stored operating-header contract has not been served.'
 return {pollAfterSeconds:body.poll_after_s===60?60:300,sessionKey:string(session.key)||'unknown',servedAt:clock(body.as_of),queueTotal:(()=>{const n=number(body.queue_total??row(row(cells.health).value).queue_total);return n!==null&&n>=0&&Number.isInteger(n)?n:null})(),
 cells:HEADER_CELLS.map(([id,label,icon])=>{
  const c=row(cells[id]),v=row(c.value),stale=String(c.verdict??c.staleness??'').toLowerCase(),unavailable=c.value===null||!Object.keys(c).length
  const rawDisplay=unavailable?null:string(c.display??v.display)??(typeof c.value==='string'?string(c.value):null)
  const score=number(v.score),display=id==='temperature'&&score!==null?`${string(v.tier)||'Score'} · ${score.toFixed(1)}`:rawDisplay
  const source=string(c.source)||'/api/v2/wealth/operating-header'
  const stamp=clock(c.clock??c.as_of),declared=string(c.state??c.tone)
  const tone:WealthTone=id==='vix'||id==='account_value'||readError||unavailable||!display?'grey':stale.includes('stale')?'amber':declared==='green'||declared==='amber'||declared==='red'?declared:'grey'
  const reason=readError||string(c.reason)||(!display?missing:null)
  const parts=Array.isArray(c.secondary??v.secondary)?(c.secondary??v.secondary) as unknown[]:[]
  const secondary=parts.flatMap(x=>{const s=string(x);return s?[s]:[]})
  return {id,label:id==='session'?'NYSE cash session':string(c.label)||label,icon,display:display||'not served',secondary,tone,clock:stamp,source,
   tooltip:[string(c.tooltip)||reason||'Stored observation',readError?'Last successful read; current read failed':null,`Source: ${source}`,`Source clock: ${stamp||'not served'}`,`Freshness: ${stale||'unknown'}`,id==='temperature'&&score!==null?`Raw engine score: ${score}`:null].filter(Boolean).join(' · '),
   verdict:readError?'read failed':stale||'unknown',ageSeconds:number(c.age_s),staleAfterSeconds:number(c.stale_after_s),numeric:display?number(v.amount??v.usd??v.index??v.value??c.value):null}
 })}
}
export function clockDiagnostics(stamp:string|null,now:number,servedAt:string|null=null) {
 const source=stamp?Date.parse(stamp):NaN,server=servedAt?Date.parse(servedAt):NaN
 const known=Number.isFinite(source)&&Number.isFinite(now)
 // No invented skew allowance: observation-after-server-response is a real error.
 const future=known&&(Number.isFinite(server)?source>server:source>now)
 const clientBehind=known&&!future&&source>now
 return {sourceDeltaMs:known?source-now:null,responseDeltaMs:Number.isFinite(server)?server-now:null,future,clientBehind}
}
export function sourceClockLabel(stamp:string|null,now:number,servedAt:string|null=null):string {
 if(!stamp||!/(?:Z|[+-]\d\d:\d\d)$/.test(stamp)||!Number.isFinite(Date.parse(stamp)))return 'source time not served'
 const diagnostic=clockDiagnostics(stamp,now,servedAt)
 if(diagnostic.future)return 'source clock is in the future'
 if(diagnostic.clientBehind)return 'client clock precedes server response · age unverified'
 const age=now-Date.parse(stamp)
 const formatted=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(stamp))
 return `${formatted} ET · ${age<60000?'<1 min':age<3600000?`${Math.floor(age/60000)} min`:`${(age/3600000).toFixed(1)} h`} old`
}
