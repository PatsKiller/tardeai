import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { WealthIcon, WealthStatus } from '../../components/WealthStatus'
import type { WealthIconName, WealthTone } from '../../components/WealthStatus'
import { useDrawer } from '../../components/Drawer'
import './home-v2.css'

export interface HomeV2Link { label: string; href: string }
export interface HomeV2Fact { label: string; value: string | null; state?: WealthTone; icon?: WealthIconName; signed?: boolean; qualifier?: string; clock?: string | null; source?: string; href?: string }
export interface HomeV2Row { id?: string; label: string; detail?: string; symbol?: string; href?: string; facts?: HomeV2Fact[]; state?: WealthTone; clock?: string | null; source?: string; progress?: boolean[]; neutralbar?: string; candidate?: boolean; issuerVerified?: boolean; scope?: 'held' | 'watch' | 'unknown'; links?: HomeV2Link[] }
export interface HomeV2Section { available: boolean; title?: string; reason?: string; source?: string; clock?: string | null; state?: WealthTone; metrics?: HomeV2Fact[]; rows?: HomeV2Row[]; notes?: string[]; links?: HomeV2Link[]; totalLabel?: string; collapsed?: boolean; gauge?: { scoreLabel: string; bands: { width: string; state: WealthTone }[]; marker: string; ticks: { position: string; label: string }[] } }
export type HomeV2Sections = Record<string, HomeV2Section | undefined>
export function homeLink(href: string): { href: string; external: boolean; classic?: boolean } | null {
 if (/^\/v3\/watch\/intelligence\/[A-Za-z0-9.%_-]+(?:[?#].*)?$/.test(href)) return {href,external:false,classic:true}
 if (href.startsWith('/') && !href.startsWith('//')) {
  const path=href.startsWith('/wealth/')?href.slice(7):href
  // Context links are navigation, never a mutation API or broker surface.
  if (!/^\/(?:home|portfolio|protection|risk|watch|reposition|trade|intel|ops)(?:[/?#]|$)/.test(path)) return null
  return {href:path,external:false}
 }
 try {const u=new URL(href);if(u.protocol==='https:'&&!u.username&&!u.password)return {href:u.href,external:true}} catch {}
 return null
}
export function HomeLink({href,children}:{href:string;children:ReactNode}) {
 const link=homeLink(href)
 return link?link.classic?<a href={link.href}>{children}</a>:link.external?<a href={link.href} target="_blank" rel="noreferrer noopener">{children} ↗</a>:<Link to={link.href}>{children}</Link>:<span className="home-v2-muted">Link not served</span>
}
export function HomeClock({clock,source}:{clock?:string|null;source?:string}) {
 const valid=typeof clock==='string'&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(clock)&&Number.isFinite(Date.parse(clock))
 return <div className="home-v2-clock">{source||'Source not served'} · {valid?<time dateTime={clock!} title={clock!}>{new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(clock!))} ET</time>:'source time not served'}</div>
}
export function HomeUnavailable({reason='This stored reader does not serve this element.'}:{reason?:string}) {
 return <div className="home-v2-unavailable"><WealthStatus icon="na" tone="grey" label="not served" detail={reason+' Source clock unavailable unless separately shown.'}/></div>
}
export function HomeFact({fact,section,large=false}:{fact:HomeV2Fact;section?:HomeV2Section;large?:boolean}) {
 const supplied=typeof fact.value==='string'&&fact.value.trim()!==''
 const tone=supplied?fact.state||'grey':'grey',clock=fact.clock??section?.clock,source=fact.source||section?.source
 return <div className={'home-v2-fact'+(large?' home-v2-fact-large':'')}><div className="home-v2-label">{fact.label}</div><div className="home-v2-fact-value">{!supplied?<WealthStatus icon="na" tone="grey" label="not served" detail={`${fact.label}: ${fact.qualifier||section?.reason||'Value missing from stored contract'}. ${source||'Source not served'}; ${clock||'source clock not served'}.`}/>:fact.icon?<WealthStatus icon={fact.icon} tone={tone} label={fact.value!} detail={`${fact.qualifier||fact.label}. ${source||'Source not served'}; ${clock||'source clock not served'}.`}/>:<span className={fact.signed?'wealth-sign':'home-v2-value'} data-tone={tone}>{fact.signed&&tone==='green'?'▲ ':fact.signed&&tone==='red'?'▼ ':''}{fact.value}</span>}</div>{fact.qualifier?<div className="home-v2-note">{fact.qualifier}</div>:null}{fact.clock||fact.source?<HomeClock clock={clock} source={source}/>:null}</div>
}
export function HomeGauge({section}:{section?:HomeV2Section}) {
 const gauge=section?.gauge,percentage=(v:string)=>/^\d+(?:\.\d+)?%$/.test(v)&&parseFloat(v)>=0&&parseFloat(v)<=100
 if(!gauge||!gauge.bands.length||!gauge.bands.every(b=>percentage(b.width))||!percentage(gauge.marker))return <HomeUnavailable reason="Engine-owned gauge cut-offs and marker are not served; design examples are not scoring policy."/>
 return <div className="home-v2-gauge-wrap" role="img" aria-label={gauge.scoreLabel}><div className="home-v2-gauge">{gauge.bands.map((b,i)=><span key={i} data-tone={b.state} style={{width:b.width}}/>)}</div><span className="home-v2-gauge-marker" style={{left:gauge.marker}}/><div className="home-v2-gauge-ticks">{gauge.ticks.filter(t=>percentage(t.position)).map((t,i)=><span key={i} style={{left:t.position}}>{t.label}</span>)}</div></div>
}
function RowBody({row,section,news=false}:{row:HomeV2Row;section?:HomeV2Section;news?:boolean}) {
 const qualified=!news||row.issuerVerified===true
 return <><div className="home-v2-row-title">{row.symbol?<span className="home-v2-ticker">{row.symbol}</span>:null}{row.href?<HomeLink href={row.href}>{row.label}</HomeLink>:<strong>{row.label}</strong>}</div>{news&&row.issuerVerified!==true?<div className="home-v2-candidate"><WealthStatus icon="na" tone="grey" label="Issuer match unverified" detail="Candidate headline only. A ticker tag or substring does not establish issuer relevance; no personalized financial explanation is established."/></div>:null}{qualified&&row.detail?<p className="home-v2-row-detail">{row.detail}</p>:null}{row.facts?.length?<div className="home-v2-row-facts">{row.facts.map((f,i)=><HomeFact key={i} fact={f} section={section}/>)}</div>:null}{row.progress?<div className="home-v2-progress" aria-label="Stored re-entry stage">{row.progress.map((on,i)=><span key={i} className={on?'on':''}/>)}</div>:null}{row.neutralbar&&/^\d+(?:\.\d+)?%$/.test(row.neutralbar)?<span className="home-v2-distance"><span style={{width:row.neutralbar}}/></span>:null}{row.links?.length?<div className="home-v2-links">{row.links.map((l,i)=><HomeLink key={i} href={l.href}>{l.label}</HomeLink>)}</div>:null}{row.clock||row.source?<HomeClock clock={row.clock} source={row.source||section?.source}/>:null}</>
}
export function HomeRows({section,limit,news=false,filterable=false}:{section?:HomeV2Section;limit?:number;news?:boolean;filterable?:boolean}) {
 const [expanded,setExpanded]=useState(false),[query,setQuery]=useState(''),[scope,setScope]=useState('all'),drawer=useDrawer(),rows=section?.rows||[],scopeServed=rows.some(r=>r.scope==='held'||r.scope==='watch'),all=rows.filter(r=>(scope==='all'||r.scope===scope)&&[r.symbol||'',r.label].join(' ').toLowerCase().includes(query.trim().toLowerCase())),visible=expanded||!limit?all:all.slice(0,limit)
 return <>{filterable?<div className="home-v2-row-filters"><label>Find symbol<input aria-label="Find mover symbol" value={query} onChange={e=>{setQuery(e.target.value);setExpanded(false)}}/></label><label>Scope<select aria-label="Mover scope" value={scope} disabled={!scopeServed} title={scopeServed?'Source-supplied held/watch scope':'Held/watch scope not served'} onChange={e=>{setScope(e.target.value);setExpanded(false)}}><option value="all">All served movers</option><option value="held">Held</option><option value="watch">Watch</option></select></label><button onClick={()=>{setQuery('');setScope('all');setExpanded(false)}}>Reset movers</button></div>:null}{visible.length?<div className={'home-v2-rows'+(news?' home-v2-news':'')}>{visible.map((row,i)=><article key={row.id||i} className="home-v2-row" data-tone={row.state||'grey'}><div className="home-v2-row-main"><RowBody row={row} section={section} news={news}/></div><button className="home-v2-context" onClick={e=>drawer.open({title:row.label,origin:e.currentTarget,body:<div className="home-v2 home-v2-detail">{news?<p>Desk context built from stored numbers. {row.issuerVerified===true?'Stored issuer evidence supplied.':'Issuer match is unverified; this candidate is not personalized financial advice.'}</p>:<p>Stored read-only context. This reader cannot approve, submit or change anything.</p>}<RowBody row={row} section={section} news={news}/><HomeClock clock={row.clock??section?.clock} source={row.source||section?.source}/>{section?.reason?<p>{section.reason}</p>:null}</div>})}>Evidence</button></article>)}</div>:section?.available&&!section.metrics?.length?<div className="home-v2-note">{query||scope!=='all'?'No movers match these filters. Source coverage is unchanged.':'No rows supplied. Coverage and source evidence remain qualified below.'}</div>:null}{limit&&all.length>limit?<button className="home-v2-show" aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?'Show fewer':'Show all'}{section?.totalLabel?' · '+section.totalLabel:''}</button>:null}</>
}
export function HomePanel({id,title,icon,section,children,limit,news=false,amber=false}:{id:string;title:string;icon:WealthIconName;section?:HomeV2Section;children?:ReactNode;limit?:number;news?:boolean;amber?:boolean}) {
 return <section className={'home-v2-panel'+(amber?' home-v2-amber':'')} data-home-panel={id} aria-labelledby={'home-v2-'+id}><h2 id={'home-v2-'+id} className="home-v2-label home-v2-panel-heading"><WealthIcon name={icon}/>{title}{section?.state?<span className="home-v2-panel-state"><WealthStatus icon={section.state==='grey'?'na':section.state==='red'?'warning':'clock'} tone={section.state} label={!section.available?'not served':section.state==='amber'?'qualified':'stored observation'} detail={`${section.reason||'Source-supplied state'}. ${section.source||'Source not served'}; ${section.clock||'source clock not served'}.`}/></span>:null}</h2>{!section?.available?<HomeUnavailable reason={section?.reason||`${title}: stored projection not served.`}/>:null}{children??<>{section?.metrics?.length?<div className="home-v2-metrics">{section.metrics.map((f,i)=><HomeFact key={i} fact={f} section={section}/>)}</div>:null}<HomeRows section={section} limit={limit} news={news} filterable={id==='movers'||id==='watch'}/></>}{section?.notes?.map((n,i)=><p className="home-v2-note" key={i}>{n}</p>)}<HomeClock clock={section?.clock} source={section?.source}/>{section?.links?.length?<div className="home-v2-links">{section.links.map((l,i)=><HomeLink href={l.href} key={i}>{l.label}</HomeLink>)}</div>:null}</section>
}
export function HomeMetricTiles({id,labels,section}:{id:string;labels:string[];section?:HomeV2Section}) {
 return <section className="home-v2-tile-grid" data-home-panel={id} aria-label={id==='tiles'?'Portfolio quick look':'Review queue summary'}>{labels.map((label,i)=>{const aliases=id==='tiles'?[['portfolio'],['session estimate','session p&l'],['approximate ytd','year to date','year to date ≈'],['realized p/l','realized'],['trading record']][i]:[label.toLowerCase()],fact=section?.metrics?.find(f=>aliases.includes(f.label.toLowerCase()));return <article className="home-v2-panel" key={label}><HomeFact large fact={fact||{label,value:null,qualifier:section?.reason||`${label}: field not served by stored projection`}} section={section}/><HomeClock clock={section?.clock} source={section?.source}/></article>})}</section>
}
export function HomeEvidenceButton({sections}:{sections:HomeV2Sections}) {
 const drawer=useDrawer()
 return <button onClick={e=>drawer.open({title:'Home source evidence',origin:e.currentTarget,body:<div className="home-v2 home-v2-detail"><p>Source observation, producer build and request time are separate. A successful read does not prove source freshness.</p>{Object.entries(sections).map(([name,s])=><section key={name}><h3>{s?.title||name}</h3><p>{s?.reason||'Source health is governed by its stored verdict.'}</p><HomeClock source={s?.source} clock={s?.clock}/></section>)}</div>})}>Sources &amp; clocks</button>
}
