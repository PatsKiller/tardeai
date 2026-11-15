import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, Metric, MetricGrid, Note, Tag } from '../../components/primitives'
import { StateView } from '../../components/StateView'
import { useDrawer } from '../../components/Drawer'
import { ageLabel, money, percent, tone } from './homeAdapter'
import type { HomeTodayModel, Mover, Snapshot } from './homeAdapter'
import '../portfolio/semantic.css'

export function HomeTodayPage({ model, now, cio }: { model: HomeTodayModel; now: number; cio: () => void }) {
  const drawer = useDrawer()
  const [bucket, setBucket] = useState('all'), [query, setQuery] = useState('')
  const clockLine = (stamp: string | null) => <p className="desk-source-note">{ageLabel(stamp, now)}</p>
  const showMovers = (moves: Mover[]) => <div className="mover-grid">{moves.filter(m => (bucket === 'all' || (bucket === 'held' ? m.held === true : m.held === false)) && m.symbol.toLowerCase().includes(query.toLowerCase())).map(m => <article className={`mover-tile ${m.change !== null && m.change < 0 ? 'down' : 'neutral'}`} key={m.symbol}>
    <div className="row-between"><Link to="/portfolio/holdings">{m.symbol}</Link><Tag>{m.held === true ? 'Held · household' : m.held === false ? 'Watch' : 'Scope unknown'}</Tag></div>
    <div className={`move-money ${tone(m.change)}`}>{percent(m.change)}</div>
    <p>Quote {money(m.price)} · {m.close || 'Quote session unknown'}</p>
    {m.held === true ? <p>Producer price-move impact: <span className={tone(m.impact)}>{money(m.impact)}</span> · not economic P&amp;L</p> : null}
    {m.extended ? <p>Extended-session label: {m.extended} · price and source time unavailable</p> : null}
  </article>)}</div>
  const sourceDetail = <><Note>Source time describes the input. Build and request time do not establish freshness.</Note>{[
    ['Canonical overview', '/api/v2/overview', model.overview.asOf],
    ['Stored since-close quotes', '/api/v2/home/since-close', model.snapshot.asOf],
    ['Top-movers sample', '/api/v2/market-movers', model.movers.asOf],
    ['Recorded review priorities', '/api/v2/home/priorities-live', null],
  ].map(([label, path, stamp]) => <section key={path}><h3>{label}</h3><p>{path}</p>{clockLine(stamp)}</section>)}<p>Morning-brief integration unavailable pending a safe stored reader. No account endpoint is called by this view.</p></>
  const snapshotContent = (s: Snapshot) => <>{s.brief ? <Note>{s.brief}<p>Stored CIO interpretation · history, not a new answer</p></Note> : <Note>Stored CIO brief text unavailable. <Link to="/intel/questions">Read your questions</Link></Note>}
    <section className="desk-section"><h2>Your book &amp; watch movers</h2><div className="toolbar"><label>Show <select value={bucket} onChange={e => setBucket(e.target.value)}><option value="all">Book &amp; watch</option><option value="held">Held · household</option><option value="watch">Watch</option></select></label><label>Find symbol <input value={query} onChange={e => setQuery(e.target.value)} /></label></div>
    {s.moves.length ? showMovers(s.moves) : <Note>No stored movers returned; absence is unproven.</Note>}{clockLine(s.quoteClock)}<p className="desk-source-note">Snapshot built {s.build || 'unknown'} · build time is not quote time</p></section>
    <section className="desk-section"><h2>What to read first</h2><p>Producer-ranked news, with the stored CIO interpretation kept separate.</p><div className="reading-grid">{s.feed.map((f, i) => <article className="reading-card" key={i}><span className="rank">{i + 1}</span><div><div className="story-clock">{f.publisher || 'Publisher unknown'} · published {f.published || 'time unknown'}</div><h3 className="story-title">{f.title}</h3>{f.why ? <p>CIO interpretation: {f.why}</p> : null}{f.url ? <a href={f.url} target="_blank" rel="noreferrer">Read source ↗</a> : <span>Source link unavailable</span>} <button onClick={e => drawer.open({ title: f.title, origin: e.currentTarget, body: <><p>Publication: {f.published || 'Unknown'}</p><p>Publisher: {f.publisher || 'Unknown'}</p><p>Stored CIO interpretation: {f.why || 'Unavailable'}</p>{clockLine(s.quoteClock)}{f.url ? <a href={f.url} target="_blank" rel="noreferrer">Open source</a> : null}</> })}>Read context</button></div></article>)}</div>{!s.feed.length ? <Note>No stored headlines returned; this does not prove there was no news.</Note> : null}{clockLine(s.quoteClock)}</section>
    {s.week.length ? <Panel title="Week ahead" sub="Stored calendar; no event inferred on page load">{s.week.map((w, i) => <p key={i}>{w.when || 'Date unknown'} · {w.title}</p>)}{clockLine(null)}</Panel> : null}</>
  return <><div className="page-title"><div><div className="eyebrow">Home</div><h1>Investment desk</h1><p>Your book, the market and the decisions that deserve attention.</p></div><div><button onClick={cio}>CIO context</button> <button onClick={e => drawer.open({ title: 'Investment desk evidence', origin: e.currentTarget, body: sourceDetail })}>Evidence</button></div></div>
    <StateView state={model.overview}>{o => <><MetricGrid><Metric label="Household portfolio value" value={money(o.value)} sub="Canonical overview · household scope" /><Metric label="Economic day P&L" value="Unknown" sub="Price moves are not economic profit" /><Metric label="Market session" value={o.session || 'Unknown'} sub="Calendar reference; not a quote clock" /></MetricGrid>{clockLine(o.source)}<p className="desk-source-note">Valuation built {o.build || 'unknown'} · account input times remain separate.</p></>}</StateView>
    <StateView state={model.snapshot} renderLastGood={s => <><Note>Last successful read; source freshness remains separately qualified.</Note>{snapshotContent(s)}</>}>{snapshotContent}</StateView>
    <details className="desk-disclosure"><summary>Market movers · top-movers sample</summary><Note>This is a sampled scanner population, not market breadth or your full portfolio.</Note><StateView state={model.movers}>{m => <>{showMovers(m)}{clockLine(model.movers.asOf)}</>}</StateView></details>
    <Panel title="Protection plan · what needs a review" sub="Recorded review items are advisory. They do not prove active protection."><StateView state={model.priorities}>{items => <div className="protection-grid">{items.map((p, i) => <article className="protection-card exception" key={i}><Tag>{p.kind || 'Review'}</Tag><h3>{p.title || 'Recorded review'}</h3><p>{p.why}</p><p>First recorded {p.since || 'unknown'} · {p.owner || 'Owner unknown'}</p><Link to="/home/needs">Review context</Link></article>)}{clockLine(null)}</div>}</StateView></Panel>
    <div className="note"><Link to="/home/needs">Needs your review</Link> · <Link to="/home/outlook">Market outlook</Link> · <Link to="/intel/questions">My questions</Link> · <Link to="/portfolio/income">Income</Link></div>
  </>
}
