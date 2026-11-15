import type { Read } from './homeAdapter'
import { accountMap, accountNamespace, body, clock, record, rows, safeText, text } from './homeAdapter'
import type { HomeV2Fact, HomeV2Link, HomeV2Row, HomeV2Section, HomeV2Sections } from './HomeV2Parts'
import type { WealthTone, WealthIconName } from '../../components/WealthStatus'
const TONES=new Set(['green','amber','red','grey'])
const ICONS=new Set(['closed','open','warning','na','plug','calendar','news','shield','check','ban','clock','thermometer','compass','pulse','heart','wallet','target','bell','swap','gear'])
const tone=(v:unknown):WealthTone=>TONES.has(text(v))?text(v) as WealthTone:'grey'
const icon=(v:unknown):WealthIconName|undefined=>ICONS.has(text(v))?text(v) as WealthIconName:undefined
export interface HomeV2Model {today:HomeV2Sections;outlook:HomeV2Sections;needs:HomeV2Sections;labels:Map<string,string>;error:string|null}
export function homeV2Model(read:Read):HomeV2Model {
 const wire=read?.data??read?.lastGood,r=body(wire),labels=accountNamespace(accountMap(r),r)
 const clean=(v:unknown)=>safeText(v,labels)
 const error=read?.error||((r.ok===false||r.error)?clean(r.reason||r.error)||'Stored Home projection unavailable':null)
 const links=(v:unknown):HomeV2Link[]=>rows(v).flatMap(l=>text(l.href)?[{label:clean(l.label)||'Read context',href:text(l.href)}]:[])
 const fact=(f:Record<string,unknown>):HomeV2Fact=>({label:clean(f.label),value:typeof(f.value??f.display)==='string'?clean(f.value??f.display):null,state:error?'grey':tone(f.state),icon:icon(f.icon),signed:f.signed===true,qualifier:[error?'Last known observation; current read failed':null,clean(f.qualifier)].filter(Boolean).join(' · ')||undefined,clock:clock(f.clock??f.as_of),source:clean(f.source)||undefined,href:text(f.href)||undefined})
 const item=(v:Record<string,unknown>):HomeV2Row=>({id:clean(v.id)||undefined,label:clean(v.label??v.title)||'Stored item',detail:clean(v.detail)||undefined,symbol:clean(v.symbol)||undefined,href:text(v.href)||undefined,facts:rows(v.facts??v.metrics).map(fact),state:error?'grey':tone(v.state),clock:clock(v.clock??v.as_of),source:clean(v.source)||undefined,progress:Array.isArray(v.progress)&&v.progress.length===5?v.progress.map(x=>x===true):undefined,neutralbar:typeof v.neutralbar==='string'?v.neutralbar:undefined,candidate:v.candidate===true,issuerVerified:v.issuerVerified===true,scope:['held','watch'].includes(text(v.scope))?text(v.scope) as 'held'|'watch':'unknown',links:links(v.links)})
 const section=(input:unknown):HomeV2Section=>{
  const raw=record(input),s={...raw,...record(raw.data)},g=record(s.gauge),bands=rows(g.bands),ticks=rows(g.ticks)
  const available=s.available===true||(s.available===undefined&&s.data!==null&&['known','partial','stale'].includes(text(s.verdict??s.state)))
  const hasEvidence=available&&(Array.isArray(s.metrics)||Array.isArray(s.rows)||Array.isArray(s.notes))
  return {available:hasEvidence,title:clean(s.title)||undefined,reason:[error,clean(s.reason)].filter(Boolean).join(' · ')||(!hasEvidence?'This element is not served by the stored Home projection.':undefined),source:clean(s.source)||undefined,clock:clock(s.clock??s.as_of),state:error?'amber':tone(s.state),metrics:rows(s.metrics).map(fact),rows:rows(s.rows).map(item),notes:Array.isArray(s.notes)?s.notes.flatMap(n=>typeof n==='string'?[clean(n)]:[]):[],links:links(s.links),totalLabel:clean(s.totalLabel)||undefined,collapsed:s.collapsed===true,
   gauge:hasEvidence&&typeof g.scoreLabel==='string'&&typeof g.marker==='string'&&bands.length?{scoreLabel:clean(g.scoreLabel),marker:g.marker,bands:bands.map(b=>({width:text(b.width),state:tone(b.state)})),ticks:ticks.map(t=>({position:text(t.position),label:clean(t.label)}))}:undefined}
 }
 const sections=(v:unknown):HomeV2Sections=>Object.fromEntries(Object.entries(record(v)).map(([k,v])=>[k,section(v)]))
 return {today:sections(r.today),outlook:sections(r.outlook),needs:sections(r.needs),labels,error}
}
