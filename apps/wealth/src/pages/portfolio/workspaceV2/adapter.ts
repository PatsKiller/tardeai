// Display-only aggregates over served rows. No price reconstruction, advice, identity or broker calls.
import type { HoldingsBook, HoldingsRow } from '../contract'
import { displayOf } from '../displayIdentity'
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
export function sectorOf(r:HoldingsRow):string {
 if(r.kind==='CASH')return 'Cash'
 if(['ETF','MUTUAL_FUND','FUND'].includes(r.assetType||''))return 'Funds'
 return r.profileSource==='unavailable'?'Sector unavailable':r.fundamentals?.sector||'Unclassified'
}
export const applicability=(r:HoldingsRow)=>r.kind==='CASH'?'Cash · not applicable':r.assetType==='MUTUAL_FUND'?'Mutual fund · resting stop not applicable':r.protection?.state||'UNKNOWN'
export function fromSearch(p:URLSearchParams):Filters {
 const f={...DEFAULT}
 for(const k of Object.keys(f) as (keyof Filters)[]) {const v=p.get('hv_'+k);if(v!==null)(f as Record<string,string>)[k]=v}
 if(!['session','purchase'].includes(f.period))f.period='session'
 if(!['security','account'].includes(f.group))f.group='security'
 if(!['','gainers','losers'].includes(f.result))f.result=''
 if(!['','PROTECTED','GAP','UNKNOWN','not-applicable'].includes(f.protection))f.protection=''
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
  const v=periodValue(r,f.period),notApplicable=r.kind==='CASH'||r.assetType==='MUTUAL_FUND'
  return (!f.account||r.accountKey===f.account)&&(!f.sector||sectorOf(r)===f.sector)
   &&(!f.result||(v!==null&&(f.result==='gainers'?v>0:v<0)))
   &&(!f.protection||(f.protection==='not-applicable'?notApplicable:!notApplicable&&(r.protection?.state||'UNKNOWN')===f.protection))
   &&(!f.size||(f.size==='unpriced'?r.marketValue===null:r.marketValue!==null&&(f.size==='small'?Math.abs(r.marketValue)<100:f.size==='material'?Math.abs(r.marketValue)>=100:Math.abs(r.marketValue)>=1000)))
   &&(!q||[r.symbol,r.name,displayOf(r).nameText,r.accountLabel,sectorOf(r)].some(s=>s.toLowerCase().includes(q)))
 })
}
export interface Group {
 key:string; label:string; rows:HoldingsRow[]; kind:'cash'|'small'|'security'|'account'
 value:Aggregate; shares:Aggregate; pnl:Aggregate; unrealized:Aggregate; cost:Aggregate
 price:number|null; mixedPrice:boolean; costPct:number|null; weight:number|null; investedWeight:number|null
}
export function totals(rows:HoldingsRow[],p:Period) {
 const securities=rows.filter(r=>r.kind!=='CASH'),cash=rows.filter(r=>r.kind==='CASH')
 const value=sum(rows.map(r=>r.marketValue)),cashValue=sum(cash.map(r=>r.marketValue)),invested=sum(securities.map(r=>r.marketValue))
 return {value,cash:cashValue,invested,pnl:sum(securities.map(r=>periodValue(r,p))),unrealized:sum(securities.map(r=>r.gainLoss)),cashPct:value.value!==null&&value.value!==0&&value.n===value.m&&cashValue.n===cashValue.m?(cashValue.value??(cash.length?null:0))===null?null:(cashValue.value??0)/value.value*100:null}
}
function group(key:string,label:string,kind:Group['kind'],rows:HoldingsRow[],p:Period,t:ReturnType<typeof totals>):Group {
 const value=sum(rows.map(r=>r.marketValue)),shares=sum(rows.map(r=>r.shares)),pnl=sum(rows.filter(r=>r.kind!=='CASH').map(r=>periodValue(r,p))),unrealized=sum(rows.filter(r=>r.kind!=='CASH').map(r=>r.gainLoss))
 const basis=sum(rows.map(r=>r.avgCost!==null&&Number.isFinite(r.shares)?r.shares*r.avgCost:null))
 const cost={value:basis.n===basis.m&&shares.value!==null&&shares.value!==0?basis.value!/shares.value:null,n:basis.n,m:basis.m}
 if(rows.length===1)cost.value=rows[0].avgCost
 const prices=[...new Set(rows.map(r=>r.price))]
 return {key,label,kind,rows,value,shares,pnl,unrealized,cost,price:prices.length===1?prices[0]:null,mixedPrice:prices.length>1,
  costPct:basis.n===basis.m&&basis.value!==null&&basis.value!==0&&unrealized.n===unrealized.m&&unrealized.value!==null?unrealized.value/basis.value*100:null,
  weight:t.value.n===t.value.m&&t.value.value!==null&&t.value.value!==0&&value.n===value.m&&value.value!==null?value.value/t.value.value*100:null,
  investedWeight:kind==='cash'||t.invested.n!==t.invested.m||t.invested.value===null||t.invested.value===0||value.n!==value.m||value.value===null?null:value.value/t.invested.value*100}
}
export function workspace(book:HoldingsBook,f:Filters) {
 const rows=selectRows(book.rows,f),t=totals(rows,f.period),groups:Group[]=[]
 if(f.group==='account')for(const [i,r]of rows.entries())groups.push(group('row-'+i,r.symbol,'account',[r],f.period,t))
 else {
  const cash=rows.filter(r=>r.kind==='CASH'),small:HoldingsRow[]=[],by=new Map<string,HoldingsRow[]>()
  for(const r of rows)if(r.kind!=='CASH'){
   if(r.marketValue!==null&&Math.abs(r.marketValue)<100&&!(r.gainLoss!==null&&r.gainLoss<=-100)){small.push(r);continue}
   const found=by.get(r.symbol)||[];found.push(r);by.set(r.symbol,found)
  }
  for(const [s,rs]of by)groups.push(group('security-'+s,s,'security',rs,f.period,t))
  groups.sort((a,b)=>(b.value.value??-Infinity)-(a.value.value??-Infinity))
  if(small.length)groups.push(group('small','Small positions','small',small,f.period,t))
  if(cash.length)groups.push(group('cash','Cash & sweep','cash',cash,f.period,t))
 }
 const material=rows.filter(r=>r.kind!=='CASH'&&r.marketValue!==null&&Math.abs(r.marketValue)>=100)
 const movers=groups.filter(g=>g.kind!=='cash'&&g.kind!=='small'&&g.pnl.value!==null&&g.pnl.n===g.pnl.m)
 const contributors=[...movers].filter(g=>g.pnl.value!>0).sort((a,b)=>b.pnl.value!-a.pnl.value!).slice(0,3)
 const detractors=[...movers].filter(g=>g.pnl.value!<0).sort((a,b)=>a.pnl.value!-b.pnl.value!).slice(0,3)
 const picked=new Set([...contributors,...detractors].flatMap(g=>g.rows))
 const other=sum(rows.filter(r=>r.kind!=='CASH'&&!picked.has(r)).map(r=>periodValue(r,f.period)))
 return {rows,groups,totals:t,contributors,detractors,other,material,gaps:material.filter(r=>r.protection?.state==='GAP'&&r.assetType!=='MUTUAL_FUND')}
}

/** Display the reported verdict without promoting stale/pending records to active protection. */
export function protectionSummary(rows:HoldingsRow[]) {
 const applicable=rows.filter(r=>r.kind!=='CASH'&&r.assetType!=='MUTUAL_FUND')
 const active=applicable.filter(r=>r.protection?.state==='PROTECTED'&&r.protection.stale===false&&r.protection.stop!==null&&Number.isFinite(r.protection.stop)&&r.protection.stop>0&&r.protection.asOf!==null&&Number.isFinite(Date.parse(r.protection.asOf))&&!/pending|activation/i.test(r.protection.reason+' '+r.protection.nextStep)).length
 const recorded=applicable.filter(r=>r.protection?.state==='PROTECTED').length
 const gaps=applicable.filter(r=>r.protection?.state==='GAP').length
 const unknown=applicable.length-recorded-gaps
 const m=applicable.length
 if(!m)return {icon:'na' as const,tone:'unknown',label:rows.every(r=>r.kind==='CASH')?'Cash · not applicable':'Resting stop not applicable',detail:'Applicability from served asset type'}
 if(active===m)return {icon:'locked' as const,tone:'gain',label:'Protected · recorded',detail:active+' of '+m+' applicable rows; see read clocks'}
 if(recorded===m)return {icon:'unlocked' as const,tone:'partial',label:'Recorded · pending or not current',detail:recorded+' of '+m+' stop records; active protection not established'}
 if(gaps===m)return {icon:'unlocked' as const,tone:'loss',label:'Unprotected · reported gap',detail:gaps+' of '+m+' applicable rows'}
 if(unknown===m)return {icon:'warning' as const,tone:'unknown',label:'Protection unknown',detail:unknown+' of '+m+' applicable rows'}
 return {icon:'unlocked' as const,tone:'partial',label:'Partially protected / unknown',detail:active+' current recorded · '+(recorded-active)+' pending/stale · '+gaps+' gap · '+unknown+' unknown of '+m}
}

const field=(v:unknown)=>'"'+String(v??'not served').replace(/"/g,'""')+'"'
export function exportCsv(v:ReturnType<typeof workspace>,f:Filters) {
 const lines=[['Security','Account','Shares (served)','Price (served)','Average cost (adapted)','Value (served)',f.period==='session'?'Last session price change (served, clock UNKNOWN)':'Since purchase unrealized only (served)','Unrealized (served)','Protection','Sector']]
 for(const r of v.rows)lines.push([r.symbol+' · '+displayOf(r).nameText+(displayOf(r).label?' · '+displayOf(r).label:''),r.accountLabel,String(r.shares),r.price===null?'not served':String(r.price),r.avgCost===null?'not served':String(r.avgCost),r.marketValue===null?'not served':String(r.marketValue),periodValue(r,f.period)===null?'not served':String(periodValue(r,f.period)),r.gainLoss===null?'not served':String(r.gainLoss),applicability(r),sectorOf(r)])
 return lines.map(line=>line.map(field).join(',')).join('\r\n')+'\r\n'
}
