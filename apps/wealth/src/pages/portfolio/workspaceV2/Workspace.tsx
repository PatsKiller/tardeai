import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { HoldingsBook, HoldingsRow } from '../contract'
import { displayOf } from '../displayIdentity'
import { useBookScope } from '../snapshot'
import { notCurrent, price as servedPrice } from '../format'
import { DEFAULT, fromSearch, searchFor, workspace, coverage, sectorOf, applicability, exportCsv, periodValue } from './adapter'
import type { Aggregate, Group, Filters } from './adapter'
import { WorkspaceIcon } from './icons'
import { StoredNews } from './StoredNews'
import { protectionSummary } from './adapter'
import './workspace.css'
const money=(v:number|null)=>v===null?'not served':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(Object.is(v,-0)?0:v)
const mark=(v:number|null)=>v===null?'not served':servedPrice(v)
const pct=(v:number|null)=>v===null?'not served':v.toFixed(2)+'%'
const qty=(v:number|null)=>v===null?'not served':new Intl.NumberFormat('en-US',{maximumFractionDigits:6}).format(v)
const sign=(v:number|null)=>v===null?'unknown':v<0?'loss':v>0?'gain':'neutral'
function Value({a}:{a:Aggregate}){return <>{money(a.value)}<small>{a.n<a.m?<WorkspaceIcon name="warning"/>:null}{coverage(a)}</small></>}
export function HoldingsWorkspace({book,notice,evidence,onRowOpen}:{book:HoldingsBook;notice:string|null;evidence:ReactNode;onRowOpen:(r:HoldingsRow,origin?:HTMLElement)=>void}) {
 const [params,setParams]=useSearchParams(), parsed=fromSearch(params),{scope,setScope}=useBookScope()
 const [expanded,setExpanded]=useState<Set<string>>(()=>new Set())
 const priorScope=useRef(scope)
 useEffect(()=>{setScope(parsed.account||'ALL')},[params.toString()])
 useEffect(()=>{if(priorScope.current!==scope){priorScope.current=scope;if((parsed.account||'ALL')!==scope)setParams(searchFor(params,{...parsed,account:scope==='ALL'?'':scope}))}},[scope])
 const f=parsed,view=useMemo(()=>workspace(book,f),[book,params.toString()])
 const update=(patch:Partial<Filters>)=>{const next={...f,...patch};setParams(searchFor(params,next));if(patch.account!==undefined)setScope(patch.account||'ALL')}
 const reset=()=>{setParams(searchFor(params,DEFAULT));setScope('ALL');setExpanded(new Set())}
 const sectors=[...new Set(book.rows.map(sectorOf))].sort(),accounts=[...new Map(book.rows.map(r=>[r.accountKey,r.accountLabel])).entries()]
 const period=f.period==='session'?'Last session':'Since purchase'
 const periodNote=f.period==='session'?'Served row price-change estimates · observation clock UNKNOWN; not economic P&L.':'Served unrealized gain/loss only · realized profit and received income not served.'
 const colour=(n:number|null)=>notCurrent(book.freshness)?'unknown':sign(n)
 const expand=(key:string)=>setExpanded(old=>{const n=new Set(old);n.has(key)?n.delete(key):n.add(key);return n})
 const download=()=>{const url=URL.createObjectURL(new Blob([exportCsv(view,f)],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='holdings-filtered.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),0)}
 const protection=(rows:HoldingsRow[])=>{const p=protectionSummary(rows);return <span className={'hv-status '+p.tone} tabIndex={0} aria-label={p.label+'. '+p.detail}><WorkspaceIcon name={p.icon}/>{p.label}<small>{p.detail.split('. ')[0]}</small><span className="hv-status-evidence">{p.detail}</span></span>}
 const row=(g:Group,child=false)=><tr className={child?'hv-child':undefined} key={g.key} data-group={g.key}>
  <th scope="row"><div className="hv-security">{!child&&g.kind!=='account'?<button className="hv-expand" aria-expanded={expanded.has(g.key)} aria-label={`${expanded.has(g.key)?'Collapse':'Expand'} ${g.label}`} onClick={()=>expand(g.key)}>{expanded.has(g.key)?'−':'+'}</button>:null}<div><strong>{g.label}</strong>{g.kind==='security'||g.kind==='account'?<small>{displayOf(g.rows[0]).nameText}{displayOf(g.rows[0]).label?<><br/>{displayOf(g.rows[0]).label}</>:null}</small>:null}<small>{[...new Set(g.rows.map(sectorOf))].join(' · ')}</small><small>{g.rows.length} account row{g.rows.length===1?'':'s'} · {qty(g.shares.value)} shares{g.cash?' / sweep units':''}{g.rows.length>1?' · grouped':''}</small><small>{[...new Set(g.rows.map(r=>r.accountLabel))].join(' · ')}</small>{(child||g.kind==='account')?<button className="hv-link" onClick={e=>onRowOpen(g.rows[0],e.currentTarget)}>Evidence & details</button>:null}</div></div></th>
  <td data-label="Price / average cost">{g.kind==='small'?'Multiple securities · see account rows':g.kind==='cash'?'Cash / sweep · see account rows':g.mixedPrice?'Mixed served marks':mark(g.price)}<small>Average {g.kind==='small'||g.kind==='cash'?'not applicable to this summary':mark(g.cost.value)}{g.kind==='security'&&g.rows.length>1?' · blended, derived':''}</small>{g.cost.n<g.cost.m?<small>{coverage(g.cost)}</small>:null}</td>
  <td data-label="Value"><Value a={g.value}/><small>{pct(g.weight)} of filtered value</small><small>{g.cash?'Not applicable to cash':pct(g.investedWeight)+' of filtered invested · derived'}</small></td>
  <td data-label={period} className={colour(g.pnl.value)}>{g.cash?'not applicable':<Value a={g.pnl}/>}<small>{f.period==='session'?'Clock UNKNOWN':'Unrealized only'}</small></td>
  <td data-label="Unrealized" className={colour(g.unrealized.value)}>{g.cash?'not applicable':<Value a={g.unrealized}/>}<small>{g.cash?'not applicable':g.kind==='small'?'Mixed securities · see account percentages':g.rows.length===1?pct(g.rows[0].gainLossPct):pct(g.costPct)}{g.kind==='security'&&g.rows.length>1?' · derived from covered basis':''}</small></td>
  <td data-label="Protection">{protection(g.rows)}{g.rows.length===1&&g.rows[0].protection?<><small>Stop {mark(g.rows[0].protection!.stop)}</small><small>Read {g.rows[0].protection!.asOf||'not served'}{g.rows[0].protection!.stale?' · stale':''}</small></>:null}</td>
 </tr>
 return <div className="holdings-v2">
  <header className="hv-header"><div><h2>Holdings workspace</h2><p>{book.counts.nonCash} security rows · marks {book.asOf} ({book.asOfClock} clock)</p></div><a className="hv-fresh" href="#holdings-evidence" onClick={()=>{const e=document.getElementById('holdings-evidence');if(e instanceof HTMLDetailsElement)e.open=true}}><WorkspaceIcon name={notCurrent(book.freshness)?'warning':'na'}/> Freshness {notCurrent(book.freshness)?'PARTIAL · not current':'producer verdict'} · evidence ↓</a></header>
  {book.source==='FIXTURE'?<p className="note">Synthetic fixture · no financial evidence.</p>:null}
  <section className="hv-filters" aria-label="Holdings filters">
   <div className="hv-filterline"><b>P&amp;L period</b>{(['session','purchase'] as const).map(p=><button key={p} aria-pressed={f.period===p} disabled={!book.rows.some(r=>periodValue(r,p)!==null)} onClick={()=>update({period:p})}>{p==='session'?'Last session':'Since purchase'}</button>)}{['1W','1M','3M','YTD','1Y','Custom range'].map(p=><button key={p} disabled title="Per-row profit for this period is not served">{p} · not served</button>)}</div>
   <p className="hv-note">{periodNote} Day/session date: {book.dayPnl.status==='KNOWN'?book.dayPnl.at||'UNKNOWN':'UNKNOWN'}.</p>
   <div className="hv-filterline"><b>Sector</b><button aria-pressed={!f.sector} onClick={()=>update({sector:''})}>All</button>{sectors.map(s=><button key={s} aria-pressed={s===f.sector} onClick={()=>update({sector:s})}>{s}</button>)}</div>
   <div className="hv-filterline">
    <label>Account<select aria-label="Holdings account" value={f.account} onChange={e=>update({account:e.target.value})}><option value="">All accounts</option>{accounts.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    <label>Result<select aria-label="Result" value={f.result} onChange={e=>update({result:e.target.value})}><option value="">All results</option><option value="gainers">Gainers only</option><option value="losers">Losers only</option></select></label>
    <label>Protection<select aria-label="Protection" value={f.protection} onChange={e=>update({protection:e.target.value})}><option value="">All protection</option>{['PROTECTED','GAP','UNKNOWN','not-applicable'].map(s=><option key={s} value={s}>{s}</option>)}</select></label>
    <label>Size<select aria-label="Size" value={f.size} onChange={e=>update({size:e.target.value})}><option value="">All sizes</option><option value="small">Under $100</option><option value="material">$100 or more</option><option value="large">$1,000 or more</option><option value="unpriced">Unpriced</option></select></label>
    <label>Search<input aria-label="Search holdings" value={f.query} onChange={e=>update({query:e.target.value})}/></label><button onClick={reset}>Reset</button><button onClick={download}>Export CSV</button>
   </div>
   {scope!=='ALL'&&scope!==f.account?<p className="hv-note">Top-bar scope differs from this bookmarked workspace. <button onClick={()=>update({account:scope})}>Use top-bar account</button></p>:null}
   <p className="hv-note">Tax type not served; its filter is withheld. All controls combine with AND. Display aggregates below describe {view.rows.length} filtered rows, not broker equity or verified profit.</p>
  </section>
  <section className="hv-tiles" aria-label="Filtered display totals">
   {[['Filtered value',view.totals.value],['Invested · non-cash rows',view.totals.invested],['Cash & sweep',view.totals.cash],[period+' · estimate / unrealized',view.totals.pnl],['Unrealized · non-cash rows',view.totals.unrealized]].map(([name,a])=><article key={name as string}><h3>{name as string}</h3><div className={name==='Filtered value'||name==='Invested · non-cash rows'||name==='Cash & sweep'?'neutral':colour((a as Aggregate).value)}><Value a={a as Aggregate}/></div><small>Derived display sum · {name==='Cash & sweep'?pct(view.totals.cashPct)+' of filtered value':'served input values preserved'}</small></article>)}
  </section>
  <section className="hv-movers" aria-label="What moved the book"><h3>What moved this slice · {period}</h3><p>{periodNote}</p><div>{[...view.detractors,...view.contributors].map(g=><span key={g.key} className={colour(g.pnl.value)}>{g.moverLabel} {money(g.pnl.value)} · {f.group==='account'?'account row':'grouped'}</span>)}<span>All other rows <Value a={view.other}/></span></div></section>
  <section className="hv-panels" aria-label="Holdings context">
   <article><h3><WorkspaceIcon name="news"/> News</h3><StoredNews symbols={view.newsSymbols}/></article>
   <article><h3><WorkspaceIcon name="calendar"/> Upcoming</h3><p>Earnings dates and declared ex-dividend dates not served by this reader. Calendar estimates remain separate from declarations and receipts.</p><a href="/wealth/portfolio/income">Income calendar →</a></article>
   <article><h3><WorkspaceIcon name="shield"/> Protection gaps</h3>{view.gaps.length?view.gaps.map((r,i)=><div key={i}><button className="hv-link" onClick={e=>onRowOpen(r,e.currentTarget)}>{r.symbol} · {r.accountLabel}</button><p>{r.protection?.reason} · read {r.protection?.asOf||'not served'}{r.protection?.stale?' · stale':''}</p></div>):<p>No served GAP rows at or above $100 match. UNKNOWN does not establish protection.</p>}{view.material.filter(r=>r.assetType==='MUTUAL_FUND').map((r,i)=><p key={i}>{r.symbol} · mutual fund · resting stop not applicable</p>)}</article>
  </section>
  <section className="hv-book" aria-label="Holdings table"><div className="hv-filterline"><h3>Positions · {view.rows.length} filtered account rows</h3><button aria-pressed={f.group==='security'} onClick={()=>update({group:'security'})}>By security</button><button aria-pressed={f.group==='account'} onClick={()=>update({group:'account'})}>By account</button></div>
   <p className="hv-note">Grouped and derived totals preserve missing inputs as partial counts. Under-$100 security groups collapse unless an account has unrealized loss of at least $100. Cash remains separate. Price change is not economic profit.</p>
   <div className="table-wrap"><table className="hv-table"><thead><tr>{['Security','Price / average cost','Value',period+' · '+(f.period==='session'?'clock UNKNOWN':'unrealized only'),'Unrealized','Protection'].map(c=><th key={c} scope="col">{c}</th>)}</tr></thead><tbody>{view.groups.map(g=><Fragment key={g.key}>{row(g)}{expanded.has(g.key)?g.children.map(c=>row(c,true)):null}</Fragment>)}</tbody></table></div>{!view.rows.length?<p>No rows match these filters. No zero totals are inferred.</p>:null}
  </section>
  <div className="hv-evidence">{evidence}</div>
 </div>
}
