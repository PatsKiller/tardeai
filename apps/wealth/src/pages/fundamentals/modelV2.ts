// Pure display adapter over served account positions. No fetch, provider, scheduler, or advice.
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { isFundRow, sectorDisplayLabel } from '../portfolio/analyticsAdapter'
import { displayOf } from '../portfolio/displayIdentity'
import { buildWorkspace, sectorText, type Group, type GroupBy, type Lens, type AccountLine } from './workspace'
export type Filters={sector:string;account:string;type:string;data:string;sort:string;query:string;group?:GroupBy;lens?:Lens}
export const DEFAULT:Required<Filters>={sector:'',account:'',type:'',data:'',sort:'weight',query:'',group:'security',lens:'valuation'}
export const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
export const isEquityRow=(r:HoldingsRow)=>r.kind!=='CASH'&&r.assetType==='EQUITY'
export const sectorOf=(r:HoldingsRow)=>r.kind==='CASH'?'Cash':isFundRow(r)?'Funds':!isEquityRow(r)?'Unknown instrument type':sectorDisplayLabel(r)
export const multipleOf=(r:HoldingsRow)=>isEquityRow(r)&&[r.fundamentals?.peTrailing,r.fundamentals?.peForward].some(v=>finite(v)&&v>0)
export function fromSearch(p:URLSearchParams):Required<Filters> {
 const f={...DEFAULT};for(const k of Object.keys(DEFAULT) as (keyof Required<Filters>)[])(f as Record<string,string>)[k]=p.get('fv_'+k)??DEFAULT[k]
 if(!['','equity','fund','cash','unknown'].includes(f.type))f.type=''
 if(!['','multiple','missing','forward','yield','stale'].includes(f.data))f.data=''
 if(!['weight','value','forward','peg','ytd','sma200','symbol','gain','yield','beta'].includes(f.sort))f.sort='weight'
 if(!['security','account'].includes(f.group))f.group='security'
 if(!['valuation','income','risk'].includes(f.lens))f.lens='valuation'
 return f
}
export function searchFor(p:URLSearchParams,f:Filters){const n=new URLSearchParams(p);for(const k of Object.keys(DEFAULT) as (keyof Required<Filters>)[]){const v=f[k]??DEFAULT[k];if(v===DEFAULT[k])n.delete('fv_'+k);else n.set('fv_'+k,v)}return n}
export function impliedGrowth(trailing:number|null,forward:number|null):number|null {
 return finite(trailing)&&finite(forward)&&trailing>0&&forward>0?(trailing/forward-1)*100:null
}
/** No exchange calendar means UNKNOWN. Older record does not, by itself, establish stale. */
export function tradingAge(record:string|null,quote:string|null,sessions:readonly string[]|null):number|null {
 if(!record||!quote||!sessions||!Number.isFinite(Date.parse(record))||!Number.isFinite(Date.parse(quote)))return null
 const et=(iso:string)=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(iso))
 const a=et(record),b=et(quote);if(a>b)return null
 const days=[...new Set(sessions)].sort()
 if(!days.length||days.some(d=>!/^\d{4}-\d{2}-\d{2}$/.test(d))||a<days[0]||b>days[days.length-1])return null
 return days.filter(d=>d>a&&d<=b).length
}
export function recordFlag(r:HoldingsRow,sessions:readonly string[]|null=null) {
 const age=tradingAge(r.profileUpdatedAt,r.priceAsOf,sessions)
 const valid=!!r.profileUpdatedAt&&!!r.priceAsOf&&Number.isFinite(Date.parse(r.profileUpdatedAt))&&Number.isFinite(Date.parse(r.priceAsOf))
 return {stale:age!==null&&age>1,age,older:valid&&Date.parse(r.profileUpdatedAt!)<Date.parse(r.priceAsOf!),
 detail:'Profile record '+(r.profileUpdatedAt||'not served')+'; quote '+(r.priceAsOf||'not served')+'; '+(age===null?'exchange-session age not served':age+' trading sessions apart')+'. Profile record clock is not a market-cap-specific clock.'}
}
export type Aggregate={value:number|null;n:number;m:number}
export function sumOf(values:readonly (number|null|undefined)[],emptyZero=false):Aggregate {
 const good=values.filter(finite);return {value:good.length?good.reduce((a,b)=>a+b,0):emptyZero&&values.length===0?0:null,n:good.length,m:values.length}
}
const securityCount=(rows:readonly HoldingsRow[])=>new Set(rows.filter(r=>r.kind!=='CASH').map(r=>r.symbol)).size
const compareText=(a:string,b:string)=>a<b?-1:a>b?1:0
export interface AllocationSegment {key:string;name:string;kind:'cash'|'fund'|'equity'|'unknown'|'other';value:number|null;n:number;m:number;pct:number|null}
export interface AllocationModel {
 segments:AllocationSegment[];denominator:number|null;denominatorLabel:string;valued:number;rows:number;securityCount:number
 partial:boolean;valid:boolean;duplicateRows:number;missingValueRows:number;valuedSecurities:number
}
/** Each underlying account position enters once. Unknown classification remains an explicit bucket.
 * Partial charts divide by the named served-value subtotal, never pretend to cover unpriced exposure.
 * Negative exposure or duplicate row identities withhold percentages: a positive stacked bar cannot represent them faithfully.
 */
export function allocationOf(rows:readonly HoldingsRow[],mode:'sector'|'security'='sector',majorCount=5):AllocationModel {
 const t=sumOf(rows.map(r=>r.marketValue),true),duplicateRows=rows.length-new Set(rows.map(r=>r.accountKey+':'+r.symbol)).size
 const valid=duplicateRows===0&&!rows.some(r=>finite(r.marketValue)&&r.marketValue<0)
 const denominator=t.n===0&&rows.length>0?null:t.value
 const grouped=new Map<string,{name:string;kind:AllocationSegment['kind'];rows:HoldingsRow[]}>()
 for(const r of rows){
  const kind=r.kind==='CASH'?'cash':isFundRow(r)?'fund':isEquityRow(r)?'equity':'unknown'
  const name=mode==='sector'?sectorOf(r):kind==='cash'?'Cash':kind==='unknown'?'Unknown instrument type':r.symbol
  const key=mode==='sector'?name:kind==='cash'?'cash':kind==='unknown'?'unknown':'security:'+r.symbol
  const g=grouped.get(key)||{name,kind,rows:[]};g.rows.push(r);grouped.set(key,g)
 }
 let segments:AllocationSegment[]=[...grouped].map(([key,g])=>{const a=sumOf(g.rows.map(r=>r.marketValue));return {key,name:g.name,kind:g.kind,value:a.value,n:a.n,m:a.m,pct:valid&&finite(denominator)&&denominator>0&&a.value!==null?a.value/denominator*100:null}})
 segments.sort((a,b)=>!finite(a.value)?!finite(b.value)?compareText(a.key,b.key):1:!finite(b.value)?-1:b.value-a.value||compareText(a.key,b.key))
 if(mode==='security'){
  const positions=segments.filter(s=>s.kind!=='cash'&&s.kind!=='unknown')
  const limit=Math.max(0,Math.floor(majorCount)),keep=new Set(positions.slice(0,limit)),other=positions.slice(limit)
  segments=segments.filter(s=>s.kind==='cash'||s.kind==='unknown'||keep.has(s))
  if(other.length){const a=sumOf(other.map(s=>s.value));segments.push({key:'other',name:'Other securities / funds',kind:'other',value:a.value,n:other.reduce((s,v)=>s+v.n,0),m:other.reduce((s,v)=>s+v.m,0),pct:valid&&finite(denominator)&&denominator>0&&a.value!==null?a.value/denominator*100:null})}
 }
 return {segments,denominator,denominatorLabel:'Served market value in current selection, including cash and funds; missing market values excluded with coverage',valued:t.n,rows:t.m,securityCount:securityCount(rows),partial:t.n<t.m,valid,duplicateRows,missingValueRows:t.m-t.n,valuedSecurities:securityCount(rows.filter(r=>finite(r.marketValue)))}
}
/** Positive comparable multiples only. Matched numerator and inverse denominator over the SAME eligible rows. */
export function harmonic(rows:HoldingsRow[],field:'peTrailing'|'peForward') {
 const all=rows.filter(isEquityRow)
 const rs=all.filter(r=>finite(r.marketValue)&&r.marketValue>0&&finite(r.fundamentals?.[field])&&r.fundamentals![field]!>0)
 const coveredValue=rs.reduce((s,r)=>s+r.marketValue!,0),inverse=rs.reduce((s,r)=>s+r.marketValue!/r.fundamentals![field]!,0)
 const allValue=sumOf(all.map(r=>r.marketValue)),totalValue=allValue.value??0
 const valued=allValue.n,eligibleSecurities=securityCount(rs),securities=securityCount(all)
 const nonnegative=!all.some(r=>finite(r.marketValue)&&r.marketValue<0)
 return {value:inverse>0?coveredValue/inverse:null,n:rs.length,m:all.length,coveredValue,totalValue,valued,
  eligibleSecurities,securities,coveredSecurities:eligibleSecurities,totalSecurities:securities,
  valueCoveragePct:nonnegative&&totalValue>0?coveredValue/totalValue*100:null,
  partial:rs.length<all.length||valued<all.length,fullBook:false as const,scope:'Covered equity sleeve only' as const}
}
function selectRows(rows:HoldingsRow[],f:Filters,sessions:readonly string[]|null,skipSector=false):HoldingsRow[] {
 const q=f.query.trim().toLowerCase()
 return rows.filter(r=>{
  const type=r.kind==='CASH'?'cash':isFundRow(r)?'fund':isEquityRow(r)?'equity':'unknown'
  const data=!f.data||f.data==='multiple'&&multipleOf(r)||f.data==='missing'&&(!multipleOf(r)||recordFlag(r,sessions).stale)||f.data==='stale'&&recordFlag(r,sessions).stale||f.data==='forward'&&isEquityRow(r)&&finite(r.fundamentals?.peForward)&&r.fundamentals!.peForward!>0||f.data==='yield'&&r.kind!=='CASH'&&finite(r.yieldPct)
  return (!f.account||r.accountKey===f.account)&&(skipSector||!f.sector||sectorOf(r)===f.sector)&&(!f.type||f.type===type)&&data&&(!q||[r.symbol,r.name,displayOf(r).nameText,r.accountLabel,sectorOf(r)].some(s=>s.toLowerCase().includes(q)))
 })
}
export interface DisplayGroup extends Omit<Group,'lines'> {
 lines:(Omit<AccountLine,'weightPct'>&{weightPct:number|null})[]
 children:DisplayGroup[];value:Aggregate;gain:Aggregate;basis:Aggregate;gainPct:number|null;shares:Aggregate;pinnedLoss:boolean
}
function enrich(g:Group,denominator:Aggregate,children=true):DisplayGroup {
 const rows=g.rows,value=sumOf(rows.map(r=>r.marketValue)),gain=sumOf(rows.map(r=>r.gainLoss)),shares=sumOf(rows.map(r=>r.shares))
 const basis=sumOf(rows.map(r=>finite(r.avgCost)&&finite(r.shares)?r.avgCost*r.shares:null))
 const weight=(v:number|null)=>denominator.n===denominator.m&&finite(denominator.value)&&denominator.value>0&&finite(v)?v/denominator.value*100:null
 const gainPct=rows.length===1?(finite(rows[0].gainLossPct)?rows[0].gainLossPct:null):gain.n===gain.m&&basis.n===basis.m&&finite(gain.value)&&finite(basis.value)&&basis.value>0?gain.value/basis.value*100:null
 const completeValue=value.n===value.m?value.value:null
 const lead=[...rows].sort((a,b)=>!finite(a.marketValue)?!finite(b.marketValue)?compareText(a.accountKey,b.accountKey):1:!finite(b.marketValue)?-1:b.marketValue-a.marketValue||compareText(a.accountKey,b.accountKey))[0]
 const out:DisplayGroup={...g,lead,symbol:lead.symbol,name:lead.name,assetType:lead.assetType,sectorText:sectorText(lead),value,gain,basis,gainPct,shares,pinnedLoss:rows.some(r=>finite(r.gainLoss)&&r.gainLoss<=-100)||(gain.n===gain.m&&finite(gain.value)&&gain.value<=-100),
  valueUsd:completeValue,weightPct:weight(completeValue),sortWeight:finite(completeValue)?completeValue:-Infinity,
  lines:g.lines.map(l=>({...l,weightPct:weight(l.valueUsd)})),children:[]}
 if(children&&rows.length>1)out.children=rows.map(r=>{
  const key=r.accountKey+':'+r.symbol
  return enrich({...g,key,rows:[r],lead:r,valueUsd:r.marketValue,lines:[{row:r,accountLabel:r.accountLabel,weightPct:r.portfolioPct,valueUsd:r.marketValue}]},denominator,false)
 }).sort((a,b)=>compareText(a.key,b.key))
 return out
}
function groupSort(f:Filters){
 const key=(g:DisplayGroup)=>f.sort==='forward'?g.lead.fundamentals?.peForward:f.sort==='peg'?g.lead.fundamentals?.peg:f.sort==='ytd'?g.lead.fundamentals?.perfYtdPct:f.sort==='sma200'?g.lead.fundamentals?.sma200Pct:f.sort==='gain'?g.gain.n===g.gain.m?g.gain.value:null:f.sort==='yield'?g.lead.yieldPct:f.sort==='beta'?g.lead.fundamentals?.beta:g.valueUsd
 const asc=f.sort==='forward'||f.sort==='peg'
 return (a:DisplayGroup,b:DisplayGroup)=>{
  if(f.sort==='symbol')return compareText(a.symbol,b.symbol)||compareText(a.key,b.key)
  const av=key(a),bv=key(b)
  return (!finite(av)?!finite(bv)?0:1:!finite(bv)?-1:(av-bv)*(asc?1:-1))||compareText(a.symbol,b.symbol)||compareText(a.key,b.key)
 }
}
export function viewOf(book:HoldingsBook,f:Filters,sessions:readonly string[]|null=null) {
 const rows=selectRows(book.rows,f,sessions),chipRows=selectRows(book.rows,f,sessions,true),denominatorAggregate=sumOf(rows.map(r=>r.marketValue),true)
 const w=buildWorkspace([...rows].sort((a,b)=>compareText(a.accountKey+':'+a.symbol,b.accountKey+':'+b.symbol)),f.group||'security'),sort=groupSort(f)
 const all=[...w.equities.groups,...w.funds.groups].map(g=>enrich(g,denominatorAggregate)).sort(sort)
 const small=all.filter(g=>g.valueUsd!==null&&Math.abs(g.valueUsd)<100&&!g.pinnedLoss),material=all.filter(g=>!small.includes(g))
 const cashGroups=rows.filter(r=>r.kind==='CASH').map(r=>enrich({key:r.accountKey+':'+r.symbol,symbol:r.symbol,name:r.name,assetType:r.assetType,sectorText:null,rows:[r],lead:r,weightPct:r.portfolioPct,sortWeight:r.portfolioPct,valueUsd:r.marketValue,lines:[{row:r,accountLabel:r.accountLabel,weightPct:r.portfolioPct,valueUsd:r.marketValue}]},denominatorAggregate,false)).sort(sort)
 const allocation=allocationOf(rows),mix=allocation.segments,sectorChips=allocationOf(chipRows).segments
 const equityRows=rows.filter(isEquityRow),equityAllocation=allocationOf(equityRows),classified=equityAllocation.segments.filter(s=>s.kind==='equity'&&!['Sector unavailable for this symbol','Unclassified'].includes(s.name)&&s.value!==null)
 const classificationPartial=equityRows.some(r=>['Sector unavailable for this symbol','Unclassified'].includes(sectorOf(r)))||equityAllocation.partial
 const largest=classified.length?{...classified[0],classificationPartial,scope:'Equity market value in current selection; cash, funds and unknown instrument types excluded'}:null
 const smallTotals=sumOf(small.flatMap(g=>g.rows.map(r=>r.marketValue)),true)
 const smallWeightPct=denominatorAggregate.n===denominatorAggregate.m&&finite(denominatorAggregate.value)&&denominatorAggregate.value>0?smallTotals.value!/denominatorAggregate.value*100:null
 const valued=denominatorAggregate.n,nonCash=rows.filter(r=>r.kind!=='CASH'),yieldRows=nonCash.filter(r=>finite(r.yieldPct))
 const yieldCoverage={n:yieldRows.length,m:nonCash.length,securities:securityCount(yieldRows),totalSecurities:securityCount(nonCash)}
 return {rows,w,equities:material.filter(g=>isEquityRow(g.lead)),funds:material.filter(g=>isFundRow(g.lead)),unknown:material.filter(g=>!isEquityRow(g.lead)&&!isFundRow(g.lead)),small,cashGroups,smallTotals,smallWeightPct,mix,sectorChips,allocation,
  sectorChipScope:'Current account, type, data and search selection before sector filter',largest,classificationPartial,equityDenominator:equityAllocation.denominator,denominator:allocation.denominator,
  trailing:harmonic(rows,'peTrailing'),forward:harmonic(rows,'peForward'),valued,
  stale:rows.filter(r=>recordFlag(r,sessions).stale),older:rows.filter(r=>recordFlag(r,sessions).older),yields:yieldRows.length,yieldCoverage,
  rowCount:rows.length,securityCount:securityCount(rows),nonCashRowCount:nonCash.length,equityRowCount:equityRows.length,equitySecurityCount:securityCount(equityRows)}
}
const csvField=(v:unknown)=>'"'+String(v??'not served').replace(/"/g,'""')+'"'
/** CSV follows filtered underlying rows, never display groups plus children. No rounding of served values. */
export function exportCsv(v:ReturnType<typeof viewOf>,f:Filters):string {
 const lines:(string|number|null)[][]=[['Security','Account','Asset type','Sector','Shares (served)','Market value (served)','Average cost (served)','Unrealized (served)','Unrealized percent (served)','Trailing P/E (served)','Forward P/E (served)','Yield percent (served)','Profile clock','Quote clock','View grouping','View lens']]
 for(const r of v.rows)lines.push([r.symbol,r.accountLabel,r.assetType,sectorOf(r),r.shares,r.marketValue,r.avgCost,r.gainLoss,r.gainLossPct,r.fundamentals?.peTrailing??null,r.fundamentals?.peForward??null,r.yieldPct,r.profileUpdatedAt,r.priceAsOf,f.group||'security',f.lens||'valuation'])
 return lines.map(row=>row.map(csvField).join(',')).join('\r\n')+'\r\n'
}

// Portfolio audit 2026-11-16 (B parity with Holdings): a collapsed Small or Cash section must never hide a row
// without saying so. `fv_show=all` opens both sections; a non-empty search opens the section holding a match; the
// disclosure line counts book rows, matching rows, filtered-out rows and rows still collapsed, and names them.
export const showAllFv=(p:URLSearchParams)=>p.get('fv_show')==='all'
export function withShowAllFv(p:URLSearchParams,on:boolean):URLSearchParams{const n=new URLSearchParams(p);if(on)n.set('fv_show','all');else n.delete('fv_show');return n}
type FvView=ReturnType<typeof viewOf>
/** Sections a query must open: rows only reach small/cash when they already passed selectRows' query filter. */
export function revealSectionsFv(v:FvView,query:string):string[]{
 if(!query.trim())return []
 const out:string[]=[];if(v.small.length)out.push('small');if(v.cashGroups.length)out.push('cash');return out
}
export function disclosureFv(totalRows:number,v:FvView,open:ReadonlySet<string>){
 const smallRows=v.small.flatMap(g=>g.rows),cashRows=v.cashGroups.flatMap(g=>g.rows)
 const hidden=[...(open.has('small')?[]:smallRows),...(open.has('cash')?[]:cashRows)]
 const matching=v.rows.length
 return {total:totalRows,matching,filteredOut:totalRows-matching,visible:matching-hidden.length,collapsed:hidden.length,collapsedSymbols:[...new Set(hidden.map(r=>r.symbol))].sort()}
}
export function disclosureTextFv(d:ReturnType<typeof disclosureFv>):string{
 const parts=[`${d.matching} of ${d.total} account positions match`];if(d.filteredOut)parts.push(`${d.filteredOut} filtered out`)
 parts.push(`${d.visible} shown`);if(d.collapsed)parts.push(`${d.collapsed} collapsed (${d.collapsedSymbols.join(', ')})`)
 return parts.join(' · ')
}
