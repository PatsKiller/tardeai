// Display-only aggregates over served rows. No price reconstruction, advice, identity or broker calls.
import type { HoldingsBook, HoldingsRow } from '../contract'
import { displayOf } from '../displayIdentity'
import { allocationOf, sectorOf } from '../../fundamentals/modelV2'
import { matchesProtection } from './discovery'
export { sectorOf } from '../../fundamentals/modelV2'
export type Period = 'session' | 'purchase'
export interface Filters {period:Period; sector:string; account:string; result:string; protection:string; size:string; query:string; group:string}
export const DEFAULT:Filters={period:'session',sector:'',account:'',result:'',protection:'',size:'',query:'',group:'security'}
export type Aggregate={value:number|null; n:number; m:number}
export function sum(values:(number|null)[]):Aggregate {
 const good=values.filter((v):v is number=>typeof v==='number'&&Number.isFinite(v))
 return {value:good.length?good.reduce((a,b)=>a+b,0):null,n:good.length,m:values.length}
}
export const coverage=(a:Aggregate)=>a.n<a.m?`partial · ${a.n} of ${a.m}`:`${a.n} of ${a.m}`
export const periodValue=(r:HoldingsRow,p:Period)=>r.kind==='CASH'?null:p==='session'?r.dayChange:r.gainLoss

/** Asset type does not override the retained producer verdict. Missing non-cash proof stays unknown. */
export const applicability=(r:HoldingsRow)=>r.kind==='CASH'?'Cash · not applicable':r.protection?.state||'UNKNOWN'
export function fromSearch(p:URLSearchParams):Filters {
 const f={...DEFAULT}
 for(const k of Object.keys(f) as (keyof Filters)[]) {const v=p.get('hv_'+k);if(v!==null)(f as Record<string,string>)[k]=v}
 if(!['session','purchase'].includes(f.period))f.period='session'
 if(!['security','account'].includes(f.group))f.group='security'
 if(!['','gainers','losers'].includes(f.result))f.result=''
 // Audit C1: one normalized class per row; a legacy PROTECTED link now means verified-active only.
 // The raw URL value is kept (old bookmarks round-trip); matching always goes through the normalized class.
 // An unrecognized non-empty value is KEPT so it matches nothing (fail closed); the page says so. It is never read as "all rows".
 if(!['','small','material','large','unpriced'].includes(f.size))f.size=''
 return f
}
export function searchFor(p:URLSearchParams,f:Filters):URLSearchParams {
 const next=new URLSearchParams(p)
 for(const k of Object.keys(DEFAULT) as (keyof Filters)[]) {
  if(f[k]===DEFAULT[k])next.delete('hv_'+k);else next.set('hv_'+k,f[k])
 }
 return next
}
export function selectRows(rows:HoldingsRow[],f:Filters):HoldingsRow[] {
 const q=f.query.trim().toLowerCase()
 return rows.filter(r=>{
  const v=periodValue(r,f.period)
  return (!f.account||r.accountKey===f.account)&&(!f.sector||sectorOf(r)===f.sector)
   &&(!f.result||(v!==null&&(f.result==='gainers'?v>0:v<0)))
   &&matchesProtection(r,f.protection)
   &&(!f.size||(f.size==='unpriced'?r.marketValue===null:r.marketValue!==null&&(f.size==='small'?Math.abs(r.marketValue)<100:f.size==='material'?Math.abs(r.marketValue)>=100:Math.abs(r.marketValue)>=1000)))
   &&(!q||[r.symbol,r.name,displayOf(r).nameText,r.accountLabel,sectorOf(r)].some(s=>s.toLowerCase().includes(q)))
 })
}
export interface Group {
 key:string; label:string; moverLabel:string; rows:HoldingsRow[]; kind:'cash'|'small'|'security'|'account'; cash:boolean
 value:Aggregate; shares:Aggregate; pnl:Aggregate; unrealized:Aggregate; cost:Aggregate
 price:number|null; mixedPrice:boolean; costPct:number|null; weight:number|null; investedWeight:number|null
 children:Group[]
}
export function totals(rows:HoldingsRow[],p:Period) {
 const securities=rows.filter(r=>r.kind!=='CASH'),cash=rows.filter(r=>r.kind==='CASH')
 const value=sum(rows.map(r=>r.marketValue)),cashValue=cash.length?sum(cash.map(r=>r.marketValue)):{value:0,n:0,m:0},invested=securities.length?sum(securities.map(r=>r.marketValue)):{value:0,n:0,m:0}
 return {value,cash:cashValue,invested,pnl:sum(securities.map(r=>periodValue(r,p))),unrealized:sum(securities.map(r=>r.gainLoss)),cashPct:value.value!==null&&value.value!==0&&value.n===value.m&&cashValue.n===cashValue.m?(cashValue.value??(cash.length?null:0))===null?null:(cashValue.value??0)/value.value*100:null}
}
function group(key:string,label:string,kind:Group['kind'],rows:HoldingsRow[],p:Period,t:ReturnType<typeof totals>):Group {
 const cash=rows.every(r=>r.kind==='CASH')
 const value=sum(rows.map(r=>r.marketValue)),shares=sum(rows.map(r=>r.shares)),pnl=sum(rows.filter(r=>r.kind!=='CASH').map(r=>periodValue(r,p))),unrealized=sum(rows.filter(r=>r.kind!=='CASH').map(r=>r.gainLoss))
 const basis=sum(rows.map(r=>r.avgCost!==null&&Number.isFinite(r.shares)?r.shares*r.avgCost:null))
 const cost={value:basis.n===basis.m&&shares.value!==null&&shares.value!==0?basis.value!/shares.value:null,n:basis.n,m:basis.m}
 if(rows.length===1)cost.value=rows[0].avgCost
 const prices=[...new Set(rows.map(r=>r.price))]
 return {key,label,moverLabel:kind==='account'?label+' · '+rows[0].accountLabel:label,kind,cash,rows,value,shares,pnl,unrealized,cost,price:prices.length===1?prices[0]:null,mixedPrice:prices.length>1,
  costPct:!cash&&basis.n===basis.m&&basis.value!==null&&basis.value!==0&&unrealized.n===unrealized.m&&unrealized.value!==null?unrealized.value/basis.value*100:null,
  weight:t.value.n===t.value.m&&t.value.value!==null&&t.value.value!==0&&value.n===value.m&&value.value!==null?value.value/t.value.value*100:null,
  investedWeight:cash||t.invested.n!==t.invested.m||t.invested.value===null||t.invested.value===0||value.n!==value.m||value.value===null?null:value.value/t.invested.value*100,
  children:[]}
}
/** Per-account display models share their parent's filtered denominators; no arithmetic in the component. */
export function childGroup(row:HoldingsRow,index:number,parent:Group,p:Period,t:ReturnType<typeof totals>):Group {
 return group(parent.key+'-'+index,row.symbol,'account',[row],p,t)
}
export function workspace(book:HoldingsBook,f:Filters) {
 const rows=selectRows(book.rows,f),t=totals(rows,f.period),groups:Group[]=[],by=new Map<string,HoldingsRow[]>()
 for(const r of rows)if(r.kind!=='CASH'){const found=by.get(r.symbol)||[];found.push(r);by.set(r.symbol,found)}
 const securities=[...by].map(([symbol,rs])=>group('security-'+symbol,symbol,'security',rs,f.period,t))
 if(f.group==='account')for(const [i,r]of rows.entries())groups.push(group('row-'+i,r.symbol,'account',[r],f.period,t))
 else {
  const cash=rows.filter(r=>r.kind==='CASH'),small:HoldingsRow[]=[]
  for(const g of securities){
   const pin=g.rows.some(r=>r.gainLoss!==null&&r.gainLoss<=-100)||(g.unrealized.n===g.unrealized.m&&g.unrealized.value!==null&&g.unrealized.value<=-100)
   if(g.value.n===g.value.m&&g.value.value!==null&&Math.abs(g.value.value)<100&&!pin)small.push(...g.rows)
   else groups.push(g)
  }
  groups.sort((a,b)=>(b.value.value??-Infinity)-(a.value.value??-Infinity))
  if(small.length)groups.push(group('small','Small positions','small',small,f.period,t))
  if(cash.length)groups.push(group('cash','Cash & sweep','cash',cash,f.period,t))
 }
 for(const g of groups)if(g.kind!=='account')g.children=g.rows.map((r,i)=>childGroup(r,i,g,f.period,t))
 const material=rows.filter(r=>r.kind!=='CASH'&&r.marketValue!==null&&Math.abs(r.marketValue)>=100)
 // Collapsed display sections never remove a security from the mover ranking.
 const movers=(f.group==='account'?groups:securities).filter(g=>!g.cash&&g.pnl.value!==null&&g.pnl.n===g.pnl.m)
 const contributors=[...movers].filter(g=>g.pnl.value!>0).sort((a,b)=>b.pnl.value!-a.pnl.value!).slice(0,3)
 const detractors=[...movers].filter(g=>g.pnl.value!<0).sort((a,b)=>a.pnl.value!-b.pnl.value!).slice(0,3)
 const picked=new Set([...contributors,...detractors].flatMap(g=>g.rows))
 const remaining=rows.filter(r=>r.kind!=='CASH'&&!picked.has(r))
 const other=remaining.length?sum(remaining.map(r=>periodValue(r,f.period))):{value:0,n:0,m:0}
 const newsSymbols=securities.filter(g=>g.value.n===g.value.m&&g.value.value!==null&&Math.abs(g.value.value)>=100).map(g=>g.label)
 const shell=book.measures.find(m=>m.id==='price_move_estimate')
 const fullPopulation=rows.length===book.rows.length&&book.rows.every(r=>rows.includes(r))
 const reconciliation={fullPopulation,storedRows:totals(book.rows,'session').pnl,canonical:shell?.status==='MEASURED'?shell.valueUsd:null,canonicalAt:shell?.asOf||null,definition:shell?.definition||'Canonical baseline definition not served',difference:null as number|null}
 if(fullPopulation&&reconciliation.storedRows.n===reconciliation.storedRows.m&&reconciliation.storedRows.value!==null&&reconciliation.canonical!==null)reconciliation.difference=reconciliation.canonical-reconciliation.storedRows.value
 const identities={nonCashPositions:rows.filter(r=>r.kind!=='CASH').length,securities:new Set(rows.filter(r=>r.kind!=='CASH').map(r=>r.symbol)).size}
 const allocation=allocationOf(rows,'security'),sectorChips=allocationOf(selectRows(book.rows,{...f,sector:''})).segments
 return {allocation,sectorChips,rows,groups,totals:t,contributors,detractors,other,material,newsSymbols,reconciliation,identities,gaps:material.filter(r=>r.protection?.state==='GAP')}
}

/** Resolve an exact symbol deep link to the existing display row; floor and loss rules stay unchanged. */
export function holdingLinkTarget(groups:Group[],f:Pick<Filters,'query'|'account'>):{expand:string[];rowKey:string}|null {
 const symbol=f.query.trim().toUpperCase()
 if(!symbol)return null
 const matches=(r:HoldingsRow)=>r.symbol.toUpperCase()===symbol&&(!f.account||r.accountKey===f.account)
 for(const g of groups) {
  if(!g.rows.some(matches))continue
  if(g.kind==='account')return {expand:[],rowKey:g.key}
  const child=g.children.find(c=>c.rows.some(matches))
  if(child)return {expand:[g.key],rowKey:child.key}
 }
 return null
}

/** Display reported protection without promoting pending, undated or stale records to active. */
export function protectionSummary(rows:HoldingsRow[]) {
 const applicable=rows.filter(r=>r.kind!=='CASH')
 const active=applicable.filter(r=>r.protection?.state==='PROTECTED'&&r.protection.stale===false&&r.protection.stop!==null&&Number.isFinite(r.protection.stop)&&r.protection.stop>0&&r.protection.asOf!==null&&Number.isFinite(Date.parse(r.protection.asOf))&&!/pending|activation/i.test(r.protection.reason+' '+r.protection.nextStep)).length
 const recorded=applicable.filter(r=>r.protection?.state==='PROTECTED').length
 const gaps=applicable.filter(r=>r.protection?.state==='GAP').length
 const materialGap=applicable.some(r=>r.protection?.state==='GAP'&&r.marketValue!==null&&Math.abs(r.marketValue)>=100)
 const unknown=applicable.length-recorded-gaps,m=applicable.length
 const notes=rows.map(r=>r.accountLabel+': '+(r.protection?.reason||applicability(r))+'; next '+(r.protection?.nextStep||'not served')+'; read '+(r.protection?.asOf||'not served')+'; freshness '+(r.protection?.stale===false?'reported current':r.protection?.stale===true?'stale':'unknown')).join(' · ')
 const detail=active+' current recorded · '+(recorded-active)+' pending/stale · '+gaps+' gap · '+unknown+' unknown of '+m+' applicable rows. '+notes
 if(!m)return {icon:'na' as const,tone:'unknown',label:'Cash · not applicable',detail:'Applicability from served cash classification. '+notes}
 if(active===m)return {icon:'locked' as const,tone:'gain',label:'Protected · recorded',detail}
 if(active>0)return {icon:'locked' as const,tone:'partial',label:gaps?'Partially protected · '+gaps+' reported gap'+(gaps===1?'':'s'):'Partially protected',detail}
 if(recorded&&materialGap)return {icon:'unlocked' as const,tone:'loss',label:'Reported gap · other records pending or not current',detail}
 if(recorded)return {icon:'unlocked' as const,tone:'partial',label:'Recorded · pending or not current',detail}
 if(gaps===m)return {icon:'unlocked' as const,tone:materialGap?'loss':'unknown',label:materialGap?'Unprotected · reported gap':'Reported gap · below floor or value unknown',detail}
 if(unknown===m)return {icon:'na' as const,tone:'unknown',label:'Protection unknown',detail}
 return {icon:'unlocked' as const,tone:materialGap?'loss':'unknown',label:'Reported gap / protection unknown',detail}
}

const field=(v:unknown)=>'"'+String(v??'not served').replace(/"/g,'""')+'"'
export function exportCsv(v:ReturnType<typeof workspace>,f:Filters) {
 const lines=[['Security','Account','Shares (served)','Price (served)','Average cost (adapted)','Value (served)',f.period==='session'?'Last session price change (served, clock UNKNOWN)':'Since purchase unrealized only (served)','Unrealized (served)','Protection','Sector']]
 for(const r of v.rows)lines.push([r.symbol+' · '+displayOf(r).nameText+(displayOf(r).label?' · '+displayOf(r).label:''),r.accountLabel,String(r.shares),r.price===null?'not served':String(r.price),r.avgCost===null?'not served':String(r.avgCost),r.marketValue===null?'not served':String(r.marketValue),periodValue(r,f.period)===null?'not served':String(periodValue(r,f.period)),r.gainLoss===null?'not served':String(r.gainLoss),applicability(r),sectorOf(r)])
 return lines.map(line=>line.map(field).join(',')).join('\r\n')+'\r\n'
}
