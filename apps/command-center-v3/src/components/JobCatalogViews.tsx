import { QualityChips, QualityReason } from './RunQualityViews'
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import DetailHeader from './DetailHeader'
import {
  RESULT_LABEL, STATUS_LABEL, ago, cadenceText, etTime, fixLabel, missedText, resultTone, schedulerLabel, statusTone,
} from '../lib/jobRunHistory'
import {
  JOBS_CATALOG_API, categoryKeyOf, categoryLabel, describedHistoryQuery, descriptionLines, jobTitle, matchesCategory, mixParts,
  mixText, mixTone, runHistoryHref, type CatalogCategory, type CatalogWire, type Category, type DescribedListWire, type DescribedRow,
} from '../lib/jobCatalog'

// Ops › Job catalog + the described job card (operator 2026-11-06). Read-only: no Run, Retry or Pause button exists
// here. Phone first: stacked cards, 44 px targets, category → full-screen sheet, no horizontal scroll at 390 px.

const panel: CSSProperties = { padding: 12, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }
const chip = (tone: Tone): CSSProperties => ({ display: 'inline-block', padding: '2px 8px', borderRadius: RADIUS.pill, fontSize: TYPE.sm, fontWeight: 600, color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${toneVars(tone).border}`, whiteSpace: 'nowrap' })
const openBtn: CSSProperties = { minHeight: 44, width: '100%', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer', textAlign: 'center', textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', boxSizing: 'border-box' }
const pill: CSSProperties = { minHeight: 44, padding: '6px 12px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', whiteSpace: 'nowrap', color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1] }
const sheet: CSSProperties = { position: 'fixed', inset: 0, zIndex: 1500, background: TOKENS.bg[0], color: TOKENS.text[0], display: 'flex', flexDirection: 'column', padding: 16, boxSizing: 'border-box', overflowY: 'auto', overflowX: 'hidden', fontFamily: FONT.sans }
const searchInput: CSSProperties = { minHeight: 44, padding: '0 12px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontSize: TYPE.base, boxSizing: 'border-box', width: '100%' }

function Fact({ label, tip, children }: { label: string; tip: string; children: ReactNode }) {
  return <div style={{ minWidth: 0 }} title={tip}><div style={muted}>{label}</div><div style={{ ...wrap, fontSize: TYPE.base }}>{children}</div></div>
}

/** "What it does" + "What breaks if it fails" under a job's name; says "No description yet" rather than inventing one. */
export function JobDescription({ row, categories }: { row: Pick<DescribedRow, 'does' | 'breaks' | 'category' | 'category_key' | 'category_fallback'>; categories?: Category[] | null }) {
  const d = descriptionLines(row)
  const cat = categoryLabel(categoryKeyOf(row), categories)
  return <div data-testid="job-description" style={{ display: 'grid', gap: 4, fontSize: TYPE.base, color: TOKENS.text[1], minWidth: 0 }}>
    {d.does && <div style={wrap}><span style={{ color: TOKENS.text[2] }}>What it does: </span>{d.does}</div>}
    {d.breaks && <div style={wrap}><span style={{ color: TOKENS.text[2] }}>If it fails: </span>{d.breaks}</div>}
    {d.missing && <div style={{ ...muted, fontStyle: 'italic' }} data-testid="job-description-missing">No description yet{row.category ? '' : ` · grouped under ${cat} by its owner`}</div>}
  </div>
}

/** One job, described. `onOpen` opens run history in place (Jobs & n8n); `href` links there (catalog). Pure. */
export function JobCard({ row, computedAt, categories, onOpen, href, showCategory = false }: {
  row: DescribedRow; computedAt: string; categories?: Category[] | null; onOpen?: (id: string) => void; href?: string; showCategory?: boolean
}) {
  const last = row.last_run
  const name = jobTitle(row)
  return <article aria-label={name} data-testid="history-card" className="job-history-card" style={{ ...panel, display: 'grid', gap: 10 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}>
      <div style={{ minWidth: 0, flex: '1 1 200px' }}>
        <strong style={{ ...wrap, fontSize: TYPE.md, display: 'block' }} data-testid="job-title">{name}</strong>
        <span style={{ ...muted, ...wrap, display: 'block' }}>{row.title ? <span style={{ fontFamily: FONT.mono }}>{row.lane_id} · </span> : null}{schedulerLabel(row.scheduler)} · {cadenceText(row.cadence)}</span>
      </div>
      <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <span style={chip(statusTone(row.status))}>{STATUS_LABEL[row.status] ?? row.status}</span>
        <QualityChips q={row.quality} />
      </span>
    </div>
    <QualityReason q={row.quality} />
    <JobDescription row={row} categories={categories} />
    {showCategory && <span style={{ ...muted }}>Category: {categoryLabel(categoryKeyOf(row), categories)}</span>}
    {row.status_reason && <div style={{ ...wrap, color: TOKENS.text[1], fontSize: TYPE.sm }}>{row.status_reason}</div>}
    <div className="job-history-facts">
      <Fact label="Last run" tip="When this job last started, and how that run ended.">{last ? <>{etTime(last.started_at || last.finished_at)} <span style={chip(resultTone(last.result))}>{RESULT_LABEL[last.result]}</span></> : 'No run recorded'}</Fact>
      <Fact label="Last success" tip="The last run that finished OK, and how long ago.">{row.last_success_at ? `${etTime(row.last_success_at)} (${ago(row.last_success_at, computedAt)})` : 'None recorded'}</Fact>
      <Fact label="Missed runs" tip="Scheduled runs that never started, measured against the expected cadence.">{missedText(row)}</Fact>
      <Fact label="Fixed (14 days)" tip="Self-heal or manual fixes recorded for this job in the last 14 days.">{row.fix_count && row.last_fix ? `${row.fix_count} event${row.fix_count === 1 ? '' : 's'} · latest ${fixLabel(row.last_fix.kind).toLowerCase()} ${etTime(row.last_fix.at)}` : 'None recorded'}</Fact>
    </div>
    {row.history_gap && <div style={{ ...muted, ...wrap }}>Run history: {row.history_gap}</div>}
    {href ? <Link to={href} style={openBtn} data-testid="job-card-history-link">Run history &amp; fixes</Link>
      : onOpen ? <button type="button" onClick={() => onOpen(row.lane_id)} style={openBtn}>Run history &amp; fixes</button> : null}
  </article>
}

/** One category as a tappable card: name, one-line blurb, job count and status mix. Pure. */
export function CategoryCard({ cat, onOpen }: { cat: CatalogCategory; onOpen: (key: string) => void }) {
  const parts = mixParts(cat.status_mix)
  return <button type="button" data-testid="catalog-category" aria-label={`${cat.label}: ${cat.jobs} jobs`} onClick={() => onOpen(cat.key)}
    style={{ ...panel, display: 'grid', gap: 6, textAlign: 'left', cursor: 'pointer', color: TOKENS.text[0], font: 'inherit', minHeight: 44, width: '100%', boxSizing: 'border-box' }}>
    <span style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap' }}>
      <strong style={{ ...wrap, fontSize: TYPE.md, flex: '1 1 160px' }}>{cat.label}</strong>
      <span style={{ fontFamily: FONT.mono, fontSize: TYPE.lg }}>{cat.jobs}<span style={{ ...muted, fontFamily: FONT.sans }}> jobs</span></span>
    </span>
    {cat.blurb && <span style={{ ...wrap, fontSize: TYPE.base, color: TOKENS.text[1] }}>{cat.blurb}</span>}
    <span data-testid="catalog-mix" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }} aria-label={mixText(cat.status_mix)}>
      {parts.length ? parts.map(p => <span key={p.key} style={chip(mixTone(p.key))}>{p.text}</span>) : <span style={muted}>No jobs</span>}
    </span>
    {cat.jobs > 0 && <span style={muted}>{cat.described === cat.jobs ? 'All described' : `${cat.described} of ${cat.jobs} described`}</span>}
  </button>
}

/** A category's jobs (or search results), paged, each linking into Jobs & n8n run history. */
function JobList({ query, categories, showCategory }: { query: (offset: number) => string; categories: Category[] | null; showCategory?: boolean }) {
  const [offset, setOffset] = useState(0)
  const path = query(offset)
  const list = useApi<DescribedListWire>(path, 60_000)
  const data = list.data
  return <div style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    {list.error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Jobs could not be read: {list.error}.</div>}
    <div className="jobs-n8n-list">
      {data?.rows.map(r => <JobCard key={r.lane_id} row={r} computedAt={data.computed_at} categories={categories} href={runHistoryHref(r.lane_id)} showCategory={showCategory} />)}
    </div>
    {!data?.rows.length && <p style={{ ...panel, ...muted }}>{list.loading ? 'Loading jobs…' : data ? 'No jobs match.' : 'Jobs are not available.'}</p>}
    {data && data.total > data.rows.length && <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', ...muted }}>
      <button type="button" style={pill} disabled={data.offset === 0} onClick={() => setOffset(Math.max(0, data.offset - data.limit))}>Previous</button>
      <span>{data.offset + 1}–{data.offset + data.rows.length} of {data.total}</span>
      <button type="button" style={pill} disabled={!data.has_more} onClick={() => setOffset(data.offset + data.limit)}>Next</button>
    </div>}
  </div>
}

/** The catalog body: search, category cards, category sheet (`?category=`). Read-only. */
export function JobCatalogView() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('category')
  const [q, setQ] = useState(params.get('q') ?? '')
  const [debounced, setDebounced] = useState(q)
  useEffect(() => { const t = setTimeout(() => setDebounced(q.trim()), 300); return () => clearTimeout(t) }, [q])
  const catalog = useApi<CatalogWire>(JOBS_CATALOG_API, 60_000)
  const data = catalog.data
  const cats = data?.categories ?? []
  const shown = cats.filter(c => matchesCategory(c, debounced))
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { if (selected) title.current?.focus() }, [selected])
  const open = (key: string | null) => {
    const next = new URLSearchParams(params)
    if (key) next.set('category', key); else next.delete('category')
    setParams(next, key ? undefined : { replace: true })
  }
  const cat = selected ? cats.find(c => c.key === selected) ?? null : null
  return <section aria-label="Job catalog" data-testid="job-catalog" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <p style={muted}>Every job grouped by what it is for. Tap a category to see its jobs and what each one does.{data ? ` ${data.jobs} jobs · ${data.described} described · checked ${etTime(data.computed_at)}.` : ''}</p>
    {catalog.error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>The job catalog could not be read: {catalog.error}.{data ? ' The last observation remains below.' : ''}</div>}
    <label style={{ display: 'grid', gap: 4, maxWidth: 420 }}><span style={muted}>Search jobs and categories</span>
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Job name, what it does, or category" style={searchInput} data-testid="catalog-search" />
    </label>
    {debounced && <section aria-label="Matching jobs" style={{ display: 'grid', gap: 8 }}>
      <h2 style={{ margin: 0, fontSize: TYPE.md }}>Jobs matching “{debounced}”</h2>
      <JobList key={debounced} query={offset => describedHistoryQuery({ filter: 'all', q: debounced, offset })} categories={cats} showCategory />
      <h2 style={{ margin: 0, fontSize: TYPE.md }}>Categories</h2>
    </section>}
    <div className="jobs-n8n-list" data-testid="catalog-categories">
      {shown.map(c => <CategoryCard key={c.key} cat={c} onOpen={open} />)}
    </div>
    {!shown.length && <p style={{ ...panel, ...muted }}>{catalog.loading && !data ? 'Loading the job catalog…' : data ? 'No category matches.' : 'The job catalog is not available.'}</p>}
    {data && !!data.gaps.length && <p style={{ ...muted, color: TOKENS.warning }}>Unavailable: {data.gaps.join('; ')}</p>}
    {data && <p style={muted}>{data.note}</p>}
    {selected && <div role="dialog" aria-modal="true" aria-labelledby="job-catalog-title" data-testid="job-catalog-sheet"
      onKeyDown={e => { if (e.key === 'Escape') open(null) }} style={sheet}>
      <DetailHeader back="Job catalog" title={cat?.label || 'Category'} titleId="job-catalog-title" titleRef={title} onClose={() => open(null)} style={{ margin: '-16px -16px 12px' }} />
      {cat ? <div style={{ display: 'grid', gap: 10, maxWidth: 960, width: '100%', minWidth: 0 }}>
        {cat.blurb && <p style={{ ...wrap, margin: 0, fontSize: TYPE.base }}>{cat.blurb}</p>}
        <p style={muted}>{cat.jobs} jobs · {mixText(cat.status_mix)}</p>
        <JobList key={cat.key} query={offset => describedHistoryQuery({ filter: 'all', category: cat.key, offset })} categories={cats} />
      </div> : <p role="status">{catalog.loading ? 'Loading…' : 'This category is not in the job catalog.'}</p>}
      <p style={{ ...muted, marginTop: 16 }}>Read-only page. To see a job's runs and fixes, tap Run history &amp; fixes.</p>
    </div>}
  </section>
}
