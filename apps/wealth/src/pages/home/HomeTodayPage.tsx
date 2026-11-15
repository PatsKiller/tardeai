import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, Metric, MetricGrid, Note, Tag, TableWrap } from '../../components/primitives'
import { StateView } from '../../components/StateView'
import { useDrawer } from '../../components/Drawer'
import { ageLabel, money, percent, tone } from './homeAdapter'
import type { HomeTodayModel, Mover, Snapshot, Story } from './homeAdapter'
import '../portfolio/semantic.css'

export function HomeTodayPage({ model, now, cio }: { model: HomeTodayModel; now: number; cio: () => void }) {
 const drawer = useDrawer()
 const [bucket,setBucket]=useState('all'),[query,setQuery]=useState('')
 const clockLine=(stamp:string|null)=><p className="desk-source-note">{ageLabel(stamp,now)}</p>
 const showMovers=(moves:Mover[])=>{
  const visible=moves.filter(m=>(bucket==='all'||(bucket==='held'?m.held===true:m.held===false))&&m.symbol.toLowerCase().includes(query.toLowerCase()))
  return visible.length?<div className="mover-grid">{visible.map(m=><article className={`mover-tile ${m.change!==null&&m.change<0?'down':'neutral'}`} key={m.symbol}>
   <div className="row-between"><Link to="/portfolio/holdings">{m.symbol}</Link><Tag>{m.held===true?'Held · household':m.held===false?'Watch':'Scope unknown'}</Tag></div>
   <div className={`move-money ${tone(m.change)}`}>{percent(m.change)}</div>
   <p>Regular quote {money(m.price)} · {m.close||'Quote session unknown'}</p>
   {m.held===true?<p>Producer regular-session price-move impact: <span className={tone(m.impact)}>{money(m.impact)}</span> · not economic P&amp;L</p>:null}
   {m.ext?<><p>{m.extended||'Extended session unknown'} · quote {money(m.ext.price)} · {m.ext.state==='level_only'?'Level only; comparable change unavailable':percent(m.ext.change)}</p><p>Reference close date {m.ext.reference||'Unknown'}</p>{clockLine(m.ext.at)}</>:null}
  </article>)}</div>:<Note>No movers match these filters. Source coverage remains separate.</Note>
 }
 const showStory=(f:Story,i:number)=><article className="reading-card" key={i}><span className="rank">{i+1}</span><div><div className="story-clock">{f.publisher||'Publisher unknown'} · published {f.published||'time unknown'}</div><h3 className="story-title">{f.title}</h3>{f.why?<p>Why it matters: {f.why}</p>:null}{f.url?<a href={f.url} target="_blank" rel="noreferrer">Read source ↗</a>:<span>Source link unavailable</span>} <button onClick={e=>drawer.open({title:f.title,origin:e.currentTarget,body:<><p>Publication: {f.published||'Unknown'}</p><p>Publisher: {f.publisher||'Unknown'}</p><p>Desk context built from stored numbers: {f.why||'Unavailable'}</p>{clockLine(f.published)}{f.url?<a href={f.url} target="_blank" rel="noreferrer">Open source</a>:null}</>})}>Read context</button></div></article>
 const sourceDetail=<><Note>Source time describes the input. Build and request time do not establish freshness.</Note>{[
  ['Canonical overview','/api/v2/overview',model.overview.asOf],
  ['Stored since-close quotes','/api/v2/home/since-close',model.snapshot.asOf],
  ['Top-movers sample','/api/v2/market-movers',model.movers.asOf],
  ['Recorded review priorities','/api/v2/home/priorities-live',null],
 ].map(([label,path,stamp])=><section key={path}><h3>{label}</h3><p>{path}</p>{clockLine(stamp)}</section>)}<p>Morning-brief integration unavailable pending a safe stored reader.</p></>
 const snapshotContent=(s:Snapshot)=><>
  {s.brief?<Note>{s.brief}<p>Stored CIO brief · history, not a new answer · {s.briefSource||'Generation method unknown'}</p>{clockLine(s.briefAt)}</Note>:<Note>Stored CIO brief text unavailable. <Link to="/intel/questions">Read your questions</Link></Note>}
  <section className="desk-section"><h2>Your book &amp; watch movers</h2><div className="toolbar"><label>Show <select aria-label="Show movers" value={bucket} onChange={e=>setBucket(e.target.value)}><option value="all">Book &amp; watch</option><option value="held">Held · household</option><option value="watch">Watch</option></select></label><label>Find symbol <input aria-label="Find symbol" value={query} onChange={e=>setQuery(e.target.value)}/></label><button onClick={()=>{setBucket('all');setQuery('')}}>Reset movers</button></div>
   {s.moves.length?showMovers(s.moves):<Note>No stored movers returned; absence is unproven.</Note>}{clockLine(s.quoteClock)}<p className="desk-source-note">Snapshot built {s.build||'unknown'} · build time is not quote time</p></section>
  <section className="desk-section"><h2>What to read first</h2><p>Producer-ranked news and desk context built from stored numbers; the CIO brief is separate above.</p><div className="reading-grid">{s.feed.map(showStory)}</div>{!s.feed.length?<Note>No stored headlines returned; this does not prove there was no news.</Note>:null}{clockLine(s.quoteClock)}</section>
  <Panel title="Market backdrop" sub="Stored macro headlines and futures/index observations; each print keeps its own clock.">
   <div className="reading-grid">{s.macro.headlines.map(showStory)}</div>
   {s.macro.quotes.length?<div className="mover-grid">{s.macro.quotes.map((q,i)=><article className="mover-tile neutral" key={i}><h3>{q.label||'Instrument label unknown'}</h3><p>Level {q.level??'Unknown'} · {q.session||'Session unknown'}</p><p>{q.change===null?'Comparable change unavailable':percent(q.change)} · reference date {q.reference||'Unknown'}</p>{clockLine(q.at)}</article>)}</div>:<Note>Futures/index prints unavailable · {s.macro.status||'source status unknown'} · age unknown.</Note>}
   {s.macro.overseas?<p>{s.macro.overseas}</p>:<p>Overseas source coverage unknown.</p>}
   {!s.macro.headlines.length?<p>No stored macro headlines returned; absence is unproven.</p>:null}
  </Panel>
  <Panel title="Week ahead" sub={`Stored calendar · ${s.weekFrom||'start unknown'} – ${s.weekTo||'end unknown'} · source age unknown`}>
   {s.week.length?s.week.map((w,i)=><p key={i}>{w.when||'Date unknown'}{w.time?` · ${w.time} ET`:''} · {w.title||'Event label unknown'} · {w.kind||'Kind unknown'}</p>):<Note>No stored calendar events returned; coverage is unknown.</Note>}
   <p>Fed speakers: {s.fedSpeakers||'Coverage unknown'}</p>
  </Panel>
 </>
 return <><section className="hero"><div className="eyebrow">Home</div><h2>Investment desk</h2><p>Your book, the market and the decisions that deserve attention.</p><div className="toolbar"><button onClick={cio}>CIO context</button><button onClick={e=>drawer.open({title:'Investment desk evidence',origin:e.currentTarget,body:sourceDetail})}>Evidence</button></div></section>
  <StateView state={model.overview}>{o=><><MetricGrid><Metric label="Household portfolio value" value={money(o.value)} sub="Canonical overview · household scope"/><Metric label="Economic day P&L" value="Unknown" sub="Price moves are not economic profit"/><Metric label="Market session" value={o.session||'Unknown'} sub="Calendar reference; not a quote clock"/></MetricGrid>{clockLine(o.source)}<p className="desk-source-note">Valuation built {o.build||'unknown'} · build time is not a source observation.</p><details><summary>Account data clocks</summary><p>Oldest contributing account: {o.oldestAccount||'Unknown'} · {ageLabel(o.dataAsOf,now)}</p>{o.accounts.length?<TableWrap heads={['Account','Source-supplied value','Position observation / age']} rows={o.accounts.map(a=>[a.label,money(a.value),ageLabel(a.source,now)])}/>:<p>Account observations unavailable.</p>}</details></>}</StateView>
  <StateView state={model.snapshot} renderLastGood={s=><><Note>Last successful read; source freshness remains separately qualified.</Note>{snapshotContent(s)}</>}>{snapshotContent}</StateView>
  <details className="desk-disclosure"><summary>Market movers · top-movers sample</summary><Note>This is a sampled scanner population, not market breadth or your full portfolio.</Note><StateView state={model.movers}>{m=><>{showMovers(m)}{clockLine(model.movers.asOf)}</>}</StateView></details>
  <Panel title="Protection plan · what needs a review" sub="Recorded review items are advisory. They do not prove active protection."><StateView state={model.priorities}>{items=><div className="protection-grid">{items.map((p,i)=><article className="protection-card exception" key={i}><Tag>{p.kind||'Review'}</Tag><h3>{p.title||'Recorded review'}</h3><p>{p.why}</p><p>First recorded {p.since||'unknown'} · {p.owner||'Owner unknown'}</p><Link to="/home/needs">Review context</Link></article>)}{clockLine(null)}</div>}</StateView></Panel>
  <Note><Link to="/home/needs">Needs your review</Link> · <Link to="/home/outlook">Market outlook</Link> · <Link to="/intel/questions">My questions</Link> · <Link to="/portfolio/income">Income</Link></Note>
 </>
}
