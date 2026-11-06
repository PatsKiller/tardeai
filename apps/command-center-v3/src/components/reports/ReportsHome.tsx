/**
 * Reports home (Reports redesign v001, operator-approved 2026-11-06; mockup
 * persistent-state/data/design/pages/reports/v001/mockups/ReportsRedesign.html).
 *   one search (every store, sector:/trend: still work) with a Filter sheet (range · quick views + counts · category)
 *   → the newest market report on top, as-of + gaps ahead of the bottom line
 *   → one list grouped by type, one row per category with its age ("stopped 71d" is visible)
 *   → tap → that category's reports → tap → the reader (full-screen sheet on a phone, right pane on desktop).
 * Advisory only — this page reads reports; it never sizes, orders or stops anything.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { useNarrowViewport } from '../../hooks/useNarrowViewport'
import { parseReport, extractAsOf, ageLabel, CADENCE_DAYS, splitQuery } from './reportFormat'
import { RichInline } from './RichText'
import ReportReader, { fmtWhen, type ReaderRef } from './ReportReader'
import './reportsRedesign.css'

export type ToolMode = 'library' | 'brief' | 'analyst' | 'system'
type QV = '' | 'today' | 'needs_action' | 'risk' | 'approvals' | 'hermes' | 'system' | 'critical'

export const GROUPS: { key: string; label: string; cats: string[]; comms?: boolean }[] = [
  { key: 'daily', label: 'Daily briefs & digests', cats: ['morning_briefs', 'digests', 'recovery', 'eod_trades'] },
  { key: 'periodic', label: 'Weekly & monthly', cats: ['weekly_reviews', 'monthly', 'portfolio_briefs', 'dividends', 'regime'] },
  { key: 'research', label: 'Research, analyst & trade reviews', cats: ['research', 'critique', 'learning', 'incubator', 'paper', 'health_agent', 'escalations'] },
  { key: 'alerts', label: 'Alerts & messages', cats: ['alerts', 'advisories', 'trade_ai_live', 'hermes_alerts', 'system'], comms: true },
]
const QUICK_VIEWS: { key: QV; label: string }[] = [
  { key: '', label: 'All' }, { key: 'today', label: 'Today' }, { key: 'needs_action', label: 'Needs action' },
  { key: 'risk', label: 'Risk / stops' }, { key: 'approvals', label: 'Approvals' }, { key: 'hermes', label: 'Hermes' },
  { key: 'system', label: 'System' }, { key: 'critical', label: 'Critical' },
]
const RANGES: { v: number | ''; label: string }[] = [{ v: 1, label: 'Today' }, { v: 7, label: '7d' }, { v: 30, label: '30d' }, { v: 90, label: '90d' }, { v: '', label: 'All' }]
const RUN_DISABLED_WHY = 'coming with the market-move-report lane'

function Sheet({ title, onClose, children, testid }: { title: string; onClose: () => void; children: ReactNode; testid?: string }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="rp-scrim" onClick={onClose} data-testid={testid}>
      <div className="rp-sheetbox" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <h3 style={{ flex: 1 }}>{title}</h3>
          <button type="button" className="rp-btn ghost" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Row({ item, sel, onOpen }: { item: any; sel: boolean; onOpen: (it: any) => void }) {
  const sev = String(item.severity || 'info').toLowerCase()
  return (
    <button type="button" className={`rp-row${sel ? ' sel' : ''}`} onClick={() => onOpen(item)} data-testid="report-row">
      <span className="main">
        <span className="t" style={{ display: 'block' }}>{item.title || item.type}</span>
        <span className="s" style={{ display: 'block' }}>
          {(item.category_label || item.type || '').toString().replace(/_/g, ' ')} · {fmtWhen(item.created_at)}
          {item.repeat_count > 1 ? ` · ×${item.repeat_count}` : ''}{item.docx_file ? ' · .docx' : ''}
        </span>
      </span>
      {sev !== 'info' && <span className={`rp-sev ${sev}`}>{sev}</span>}
      <span className="chev" aria-hidden>›</span>
    </button>
  )
}

function MarketCard({ onOpen, onShowAll }: { onOpen: (it: any) => void; onShowAll: () => void }) {
  const { data, loading } = useApi<any>('/api/v2/reports/list?category=market_reports&page=1&per_page=1', 300_000)
  const { data: mr } = useApi<any>('/api/v2/market-risk/latest', 300_000)
  const it = data?.items?.[0]
  const parsed = useMemo(() => parseReport(it?.summary || '', it?.title || ''), [it])
  const asOf = useMemo(() => extractAsOf(parsed, it?.meta), [parsed, it])
  const bottom = parsed.sections.find(s => /bottom line|summary/i.test(s.title)) || parsed.sections[0]
  const bullets = (bottom?.body || '').split('\n').map(l => l.match(/^\s*[-•*]\s+(.*)$/)?.[1]).filter(Boolean).slice(0, 3) as string[]
  const tier = mr?.tier ? String(mr.tier).toUpperCase() : null
  return (
    <section className="rp-card" data-testid="market-card" aria-label="Latest market report">
      <div className="rp-eyebrow">
        <span>Latest market report</span>
        {tier && <span className={`rp-tier ${tier}`} title="Market Risk Engine tier now (GET /api/v2/market-risk/latest)">{tier}{mr?.score != null ? ` ${Math.round(mr.score)}` : ''}</span>}
        {it && <span>· {fmtWhen(it.created_at)}</span>}
      </div>
      {!it && <div className="rp-meta" style={{ marginTop: 6 }}>{loading ? 'Loading…' : 'No market report yet.'}</div>}
      {it && (<>
        <div className="rp-title">{parsed.title || it.title}</div>
        <dl className={`rp-asof${asOf.text ? '' : ' stale'}`}>
          <dt>As of</dt>
          <dd>{asOf.text ? <RichInline text={asOf.text} /> : <span className="none">as-of not recorded</span>}</dd>
          {asOf.gaps.length > 0 && (<><dt>Gaps</dt><dd>{asOf.gaps.length} known gap{asOf.gaps.length === 1 ? '' : 's'}, listed in the report</dd></>)}
        </dl>
        {bullets.length > 0 && <ul className="rp-bl">{bullets.map((b, i) => <li key={i}><RichInline text={b} /></li>)}</ul>}
      </>)}
      <div className="rp-actions">
        {it && <button type="button" className="rp-btn pri" onClick={() => onOpen(it)} data-testid="market-read">Read report</button>}
        <button type="button" className="rp-btn" onClick={onShowAll}>All market reports</button>
        <button type="button" className="rp-btn" disabled aria-disabled="true" title={RUN_DISABLED_WHY} data-testid="market-run">Run market report now</button>
        <span className="rp-why">Run now: {RUN_DISABLED_WHY}.</span>
      </div>
    </section>
  )
}

export default function ReportsHome({ categories, initialOpen, onTool, onPurge, onAlertSettings, onCategoryChange }: {
  categories: any[]
  initialOpen?: ReaderRef | null
  onTool: (m: ToolMode) => void
  onPurge: (cat: string, label: string) => void
  onAlertSettings: () => void
  onCategoryChange?: (cat: string | null) => void
}) {
  const narrow = useNarrowViewport(820)
  const [open, setOpen] = useState<ReaderRef | null>(initialOpen || null)
  const [view, setView] = useState<string | null>(initialOpen?.category || null)   // null = grouped home
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [days, setDays] = useState<number | ''>(30)
  const [qv, setQv] = useState<QV>('')
  const [page, setPage] = useState(1)
  const [filterOpen, setFilterOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => { const t = setTimeout(() => setQ(qInput.trim()), 350); return () => clearTimeout(t) }, [qInput])
  useEffect(() => { setPage(1) }, [view, q, days, qv])
  useEffect(() => { onCategoryChange?.(view) }, [view]) // eslint-disable-line

  const catBy = useMemo(() => Object.fromEntries(categories.map((c: any) => [c.key, c])), [categories])
  const sq = splitQuery(q)
  const searching = !!(sq.text || sq.sector || sq.trend)
  const effDays = qv === 'today' ? 1 : days
  const { data: found, loading: searchLoading } = useApi<any>(
    `/api/v2/reports/search?q=${encodeURIComponent(sq.text || sq.sector || sq.trend || '')}&days=${effDays || 365}&limit=50`, 0, { enabled: searching && !view })
  const searchItems = useMemo(() => (found?.items || []).filter((it: any) =>
    (!sq.sector || String(it.sector || '').toLowerCase().includes(sq.sector.toLowerCase())) &&
    (!sq.trend || String(it.trend || '').toLowerCase().includes(sq.trend.toLowerCase()))), [found, sq.sector, sq.trend])
  const listPath = view
    ? `/api/v2/reports/list?category=${encodeURIComponent(view)}&q=${encodeURIComponent(sq.text)}&page=${page}&per_page=20${effDays ? `&days=${effDays}` : ''}${qv && qv !== 'today' ? `&qv=${qv}` : ''}`
    : ''
  const { data: list, loading: listLoading } = useApi<any>(listPath || '/api/v2/reports/categories', 0, { enabled: !!view })
  const { data: summary } = useApi<any>(`/api/v2/reports/portal-summary?days=${effDays || 30}`, 0, { enabled: filterOpen })
  const k = summary?.kpis || {}

  const openItem = (it: any) => setOpen({ source: it.source, id: it.id, category: it.category || view || undefined, title: it.title, created_at: it.created_at })
  const selKey = open ? `${open.source}-${open.id}` : ''
  const filterCount = (days !== 30 ? 1 : 0) + (qv ? 1 : 0) + (view ? 1 : 0)
  const viewCat = view ? catBy[view] : null

  const groupRows = (g: typeof GROUPS[number]) => g.cats.map(c => catBy[c]).filter(Boolean)
  const home = (
    <>
      <MarketCard onOpen={openItem} onShowAll={() => setView('market_reports')} />
      {GROUPS.map(g => {
        const rows = groupRows(g)
        const total = rows.reduce((n: number, c: any) => n + (c.count || 0), 0)
        if (g.comms) {
          return (
            <section key={g.key} className="rp-group" aria-label={g.label}>
              <div className="rp-ghead"><span>{g.label}</span><span className="n">{total.toLocaleString()}</span></div>
              <div className="rp-list">
                <a className="rp-row" href="/v3/communications?tab=analytics" data-testid="comms-link" style={{ textDecoration: 'none' }}>
                  <span className="main">
                    <span className="t" style={{ display: 'block' }}>Alerts, advisories, Trade AI LIVE, Hermes, system messages</span>
                    <span className="s" style={{ display: 'block' }}>Messages, not reports · search still finds them · analytics moved to Communications</span>
                  </span>
                  <span className="r">Comms</span><span className="chev" aria-hidden>›</span>
                </a>
              </div>
            </section>
          )
        }
        return (
          <section key={g.key} className="rp-group" aria-label={g.label}>
            <div className="rp-ghead"><span>{g.label}</span><span className="n">{total.toLocaleString()}</span></div>
            <div className="rp-list">
              {rows.map((c: any) => {
                const age = ageLabel(c.last_at, CADENCE_DAYS[c.key] ?? 7)
                return (
                  <button key={c.key} type="button" className="rp-row" onClick={() => setView(c.key)} data-testid={`cat-${c.key}`}>
                    <span className="main">
                      <span className="t" style={{ display: 'block' }}>{c.label}</span>
                      <span className="s" style={{ display: 'block' }}>{(c.count || 0).toLocaleString()} report{c.count === 1 ? '' : 's'}{c.last_at ? ` · last ${fmtWhen(c.last_at)}` : ''}</span>
                    </span>
                    <span className={`rp-age ${age.tone}`}>{age.text}</span>
                    <span className="chev" aria-hidden>›</span>
                  </button>
                )
              })}
            </div>
          </section>
        )
      })}
    </>
  )

  const items: any[] = list?.items || []
  const catList = viewCat && (
    <section aria-label={viewCat.label}>
      <div className="rp-ghead">
        <button type="button" className="rp-btn ghost" onClick={() => setView(null)} aria-label="Back to all reports" data-testid="cat-back">‹</button>
        <span>{viewCat.label}</span><span className="n">{list ? `${list.matching ?? list.total ?? 0}` : ''}</span><span className="sp" />
        <span className={`rp-age ${ageLabel(viewCat.last_at, CADENCE_DAYS[viewCat.key] ?? 7).tone}`}>{ageLabel(viewCat.last_at, CADENCE_DAYS[viewCat.key] ?? 7).text}</span>
      </div>
      <div className="rp-list">
        {items.map(it => <Row key={`${it.source}-${it.id}`} item={{ ...it, category_label: undefined }} sel={selKey === `${it.source}-${it.id}`} onOpen={openItem} />)}
        {!items.length && <div className="rp-empty">{listLoading ? 'Loading…' : `No reports in this range${effDays ? ` (${effDays === 1 ? 'today' : `${effDays}d`})` : ''}. Widen the range in Filter.`}</div>}
      </div>
      {(list?.pages ?? 1) > 1 && (
        <div className="rp-pager">
          <button type="button" className="rp-btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>‹ Newer</button>
          <span>page {page} / {list.pages}</span>
          <button type="button" className="rp-btn" disabled={page >= list.pages} onClick={() => setPage(p => p + 1)}>Older ›</button>
        </div>
      )}
    </section>
  )

  const searchList = (
    <section aria-label="Search results">
      <div className="rp-ghead"><span>Results</span><span className="n">{searchItems.length}{found?.total > searchItems.length ? ` of ${found.total}` : ''}</span></div>
      <div className="rp-list">
        {searchItems.map((it: any) => <Row key={`${it.source}-${it.id}`} item={it} sel={selKey === `${it.source}-${it.id}`} onOpen={openItem} />)}
        {!searchItems.length && <div className="rp-empty">{searchLoading ? 'Searching every store…' : 'No reports match. Try a ticker, sector:Name or trend:bullish.'}</div>}
      </div>
    </section>
  )

  const leftCol = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
      <div className="rp-search" role="search">
        <span aria-hidden style={{ color: 'var(--text-3)' }}>⌕</span>
        <input value={qInput} onChange={e => setQInput(e.target.value)} placeholder={view ? `Search ${viewCat?.label || 'this category'}…` : 'Search every report · ticker, topic, sector:…'}
          aria-label="Search reports" data-testid="reports-search" />
        {qInput && <button type="button" className="rp-btn ghost" aria-label="Clear search" onClick={() => setQInput('')}>✕</button>}
        <button type="button" className="rp-btn" onClick={() => setFilterOpen(true)} data-testid="filter-btn">Filter{filterCount ? ` · ${filterCount}` : ''}</button>
      </div>
      {(qv || days !== 30) && (
        <div className="rp-filterchips">
          {days !== 30 && <button type="button" className="rp-chip on" onClick={() => setDays(30)}>{RANGES.find(r => r.v === days)?.label} ✕</button>}
          {qv && <button type="button" className="rp-chip on" onClick={() => setQv('')}>{QUICK_VIEWS.find(x => x.key === qv)?.label} ✕</button>}
        </div>
      )}
      {view ? catList : searching ? searchList : home}
    </div>
  )

  return (
    <div className="rp" data-testid="reports-home">
      <div className="rp-head">
        <h1>Reports</h1>
        <span className="sub" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>read-only · advisory</span>
        <button type="button" className="rp-btn" aria-label="More report tools" aria-haspopup="dialog" onClick={() => setMenuOpen(true)} data-testid="reports-menu">⋯</button>
      </div>
      {!narrow && open ? (
        <div className="rp-split">
          {leftCol}
          <div className="rp-pane"><ReportReader key={selKey} item={open} sheet={false} onClose={() => setOpen(null)} /></div>
        </div>
      ) : leftCol}
      {narrow && open && <ReportReader key={selKey} item={open} sheet onClose={() => setOpen(null)} />}

      {filterOpen && (
        <Sheet title="Filter" onClose={() => setFilterOpen(false)} testid="filter-sheet">
          <div className="lab">Range</div>
          <div className="opts">{RANGES.map(r => <button key={String(r.v)} type="button" className={`rp-chip${days === r.v ? ' on' : ''}`} onClick={() => setDays(r.v)}>{r.label}</button>)}</div>
          <div className="lab">Quick views{view ? '' : ' · pick a category to apply'}</div>
          <div className="opts">
            {QUICK_VIEWS.map(v => (
              <button key={v.key || 'all'} type="button" className={`rp-chip${qv === v.key ? ' on' : ''}`} onClick={() => setQv(v.key)}>
                {v.label}{view && list?.qv_counts && v.key ? <span className="n">{list.qv_counts[v.key] ?? 0}</span> : null}
              </button>
            ))}
          </div>
          {summary?.kpis && (
            <div className="rp-meta" style={{ marginTop: 8 }}>
              All categories · {effDays || 30}d: {k.total ?? 0} reports · {k.critical_urgent ?? 0} critical/urgent · {k.open_actions ?? 0} open actions ·
              {' '}{k.risk_stop ?? 0} risk/stop · {k.approvals ?? 0} approvals · {k.system_hermes ?? 0} system/Hermes · {k.today ?? 0} today
            </div>
          )}
          <div className="lab">Category</div>
          <div className="opts">
            <button type="button" className={`rp-chip${!view ? ' on' : ''}`} onClick={() => setView(null)}>All (grouped)</button>
            {categories.map((c: any) => (
              <button key={c.key} type="button" className={`rp-chip${view === c.key ? ' on' : ''}`} onClick={() => setView(c.key)}>
                {c.label}<span className="n">{c.count}</span>
              </button>
            ))}
          </div>
          <div className="rp-actions"><button type="button" className="rp-btn pri" onClick={() => setFilterOpen(false)}>Done</button></div>
        </Sheet>
      )}
      {menuOpen && (
        <Sheet title="Report tools" onClose={() => setMenuOpen(false)} testid="tools-menu">
          <div className="rp-list rp-menu">
            {([['brief', "Today's brief", 'Morning command, action list, the unified brief'],
              ['library', 'Library', 'Every report type, cadence lanes, freshness'],
              ['analyst', 'Analyst studio', 'Generate symbol reports, Word / PDF'],
              ['system', 'System rollup', 'Pipelines, agents, trades, research'],
            ] as [ToolMode, string, string][]).map(([m, l, s]) => (
              <button key={m} type="button" className="rp-row" onClick={() => { setMenuOpen(false); onTool(m) }}>
                <span className="main"><span className="t" style={{ display: 'block' }}>{l}</span><span className="s" style={{ display: 'block' }}>{s}</span></span><span className="chev" aria-hidden>›</span>
              </button>
            ))}
            <a className="rp-row" href="/v3/communications?tab=analytics" style={{ textDecoration: 'none' }}>
              <span className="main"><span className="t" style={{ display: 'block' }}>Alert analytics</span><span className="s" style={{ display: 'block' }}>Moved to Communications → Analytics</span></span><span className="chev" aria-hidden>›</span>
            </a>
            <button type="button" className="rp-row" onClick={() => { setMenuOpen(false); onAlertSettings() }}>
              <span className="main"><span className="t" style={{ display: 'block' }}>Alert settings</span></span><span className="chev" aria-hidden>›</span>
            </button>
            <button type="button" className="rp-row" onClick={() => { setMenuOpen(false); onPurge(view || '', viewCat?.label || 'All categories') }}>
              <span className="main"><span className="t" style={{ display: 'block' }}>Purge old reports</span><span className="s" style={{ display: 'block' }}>Preview first · archive-then-delete</span></span><span className="chev" aria-hidden>›</span>
            </button>
          </div>
        </Sheet>
      )}
    </div>
  )
}
