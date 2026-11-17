import { safeText } from '../pages/home/homeAdapter'
import type { WealthIconName, WealthTone } from '../components/WealthStatus'
export const HEADER_CELLS = [
 ['session','Session','clock'],['session_pl','Session profit / loss','pulse'],
 ['account_value','Account value · household','wallet'],['temperature','Temperature','thermometer'],
 ['regime','Regime','compass'],['vix','VIX','pulse'],
 ['operating_mode','Operating mode','target'],['health','Health & data','heart'],
] as const satisfies readonly (readonly [string,string,WealthIconName])[]
// Presentation of already-served engine states; these are not scoring rules.
const REGIME_PRESENTATION:Record<string,{label:string;tone:WealthTone;pending?:boolean}>={
 risk_on_trend:{label:'Risk-on trend',tone:'green'},risk_off:{label:'Risk off',tone:'red'},
 choppy_range:{label:'Choppy range',tone:'grey'},high_volatility:{label:'High volatility',tone:'amber'},
 low_volatility_grind:{label:'Low-volatility grind',tone:'green'},
 broad_momentum:{label:'Broad momentum',tone:'grey',pending:true},unknown:{label:'Unknown',tone:'grey'},
}
const TEMPERATURE_COLORS:Record<string,string>={GREEN:'var(--status-green)',BLUE:'var(--status-blue)',YELLOW:'var(--status-amber)',ORANGE:'var(--status-orange)',RED:'var(--status-red)'}
export interface OperatingCell {
 id:string; label:string; icon:WealthIconName; display:string; secondary:string[];
 tone:WealthTone; clock:string|null; source:string; tooltip:string; verdict:string;
 ageSeconds:number|null; staleAfterSeconds:number|null; numeric:number|null;
 temperatureTier:string|null; temperatureScore:number|null; temperatureColor:string|null;
 regimeTone:WealthTone; regimeScore:number|null; confidence:number|null; qualification:string|null;
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
  const rawTier=typeof v.tier==='string'?v.tier:null
  const temperatureTier=id==='temperature'&&!unavailable&&rawTier&&(Object.prototype.hasOwnProperty.call(TEMPERATURE_COLORS,rawTier)||rawTier==='NONE'||rawTier==='UNKNOWN')?rawTier:null
  const rawScore=number(v.score),score=id==='temperature'&&!unavailable&&rawScore!==null&&rawScore>=0&&rawScore<=100?rawScore:null
  const regimeKey=id==='regime'&&!unavailable?(typeof v.label==='string'?v.label:typeof c.display==='string'?c.display:null):null
  const regime=regimeKey&&Object.prototype.hasOwnProperty.call(REGIME_PRESENTATION,regimeKey)?REGIME_PRESENTATION[regimeKey]:null
  const display=id==='temperature'?(temperatureTier?`${temperatureTier}${score!==null?` · ${score.toFixed(1)}`:''}`:score!==null?`Unclassified tier · ${score.toFixed(1)}`:null):id==='regime'&&regimeKey?(regime?.label||'Unrecognized regime'):rawDisplay
  const regimeScore=id==='regime'&&!unavailable&&rawScore!==null&&Number.isInteger(rawScore)&&rawScore>=0?rawScore:null
  const rawConfidence=number(v.confidence),confidence=id==='regime'&&!unavailable&&rawConfidence!==null&&rawConfidence>=0&&rawConfidence<=1?rawConfidence:null
  const source=string(c.source)||'/api/v2/wealth/operating-header'
  const stamp=clock(c.clock??c.as_of),declared=string(c.state??c.tone)
  const tone:WealthTone=id==='temperature'||id==='vix'||id==='account_value'||readError||unavailable||!display?'grey':stale.includes('stale')?'amber':declared==='green'||declared==='amber'||declared==='red'?declared:'grey'
  const reason=readError||string(c.reason)||(!display?missing:null)
  const ttl=number(c.stale_after_s),limit=ttl!==null&&ttl>=0?ttl:null
  const freshness=readError?'Current read failed · retained observation':!display?'Not served':stale.includes('stale')?'Stale observation':stale==='partial'?'Partial observation':stale!=='known'?'Freshness unknown':!stamp||limit===null||c.currentness==='unproven'?'Freshness policy unproven':null
  const mapping=id==='regime'&&(regime?.pending||regimeKey&&!regime)?'State mapping pending review':null
  const qualification=[freshness,mapping].filter(Boolean).join(' · ')||null
  const parts=Array.isArray(c.secondary??v.secondary)?(c.secondary??v.secondary) as unknown[]:[]
  const secondary=parts.flatMap(x=>{const s=string(x);return s?[s]:[]})
  return {id,label:id==='session'?'NYSE cash session':string(c.label)||label,icon,display:display||'not served',secondary,tone,clock:stamp,source,
   tooltip:[string(c.tooltip)||reason||'Stored observation',readError?'Last successful read; current read failed':null,`Source: ${source}`,`Source clock: ${stamp||'not served'}`,`Freshness: ${stale||'unknown'}`,limit!==null?`Freshness limit: ${limit} seconds (stored policy)`:null,id==='temperature'&&score!==null?`Raw engine score: ${score}`:null,id==='regime'&&regimeScore!==null?`Engine score: ${regimeScore} points`:null,confidence!==null?`Confidence: ${confidence}`:null,mapping].filter(Boolean).join(' · '),
   verdict:readError?'read failed':stale||'unknown',ageSeconds:number(c.age_s),staleAfterSeconds:limit,numeric:display?number(v.amount??v.usd??v.index??v.value??c.value):null,
   temperatureTier,temperatureScore:score,temperatureColor:temperatureTier&&Object.prototype.hasOwnProperty.call(TEMPERATURE_COLORS,temperatureTier)?TEMPERATURE_COLORS[temperatureTier]:null,
   regimeTone:readError||unavailable||!display?'grey':regime?.tone||'grey',regimeScore,confidence,qualification}
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
