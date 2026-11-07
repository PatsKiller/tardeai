import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import DetailHeader from './DetailHeader'
import { HistoryDetail } from './JobRunHistory'
import { JobCard, JobDescription } from './JobCatalogViews'
import { SchedulerLaneDetail } from './SchedulerChecksViews'
import { detailQuery, etTime, type HistoryDetailWire } from '../lib/jobRunHistory'
import {
  JOB_CATALOG_PATH, describedHistoryQuery, effectiveHistoryFilter, jobTitle, toggleStatus, type Category, type DescribedListWire, type DescribedRow,
} from '../lib/jobCatalog'
import {
  ALL_JOBS_FILTERS, N8N_FILTERS, OPS_CONTROLS_PATH, TAB_HISTORY_FILTER, historyTiles, isN8nStatus, laneCard, matchesN8nFilter,
  matchesN8nQuery, matchesN8nStatus, moveToN8nSentence, n8nFilterCounts, n8nTiles, sortLanes, summaryOf, type LaneCard, type Tile,
} from '../lib/jobsN8n'
import type { N8nFilter, N8nRowX } from '../lib/opsControlsN8n'
import type { OpsControlsState } from '../lib/opsControls'
import { ageText, INCIDENTS_PATH, matchesFilter, sortIncidents, sourceText, type Incident, type IncidentsWire } from '../lib/incidents'
import { rowModel } from '../lib/incidentRow'

// Ops › Jobs & n8n (design pages/jobs v002, operator-approved 2026-11-06). Read-only views: no Run, Retry, Pause or
// live-list button exists here — the switches stay in Ops Controls behind the operator's sign-in. Phone first: stacked
// cards (no table at 390 px), 44 px tap targets, list → full-screen sheet.

const panel: CSSProperties = { padding: 12, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }
const chip = (tone: Tone): CSSProperties => ({ display: 'inline-block', padding: '2px 8px', borderRadius: RADIUS.pill, fontSize: TYPE.sm, fontWeight: 600, color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${toneVars(tone).border}`, whiteSpace: 'nowrap' })
const pill = (on: boolean): CSSProperties => ({ minHeight: 44, padding: '6px 12px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', whiteSpace: 'nowrap',
  color: on ? TOKENS.info : TOKENS.text[1], border: `1px solid ${on ? TOKENS.info : TOKENS.border}`, background: on ? toneVars('info').bg : TOKENS.bg[1] })
const openBtn: CSSProperties = { minHeight: 44, width: '100%', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer', textAlign: 'center', textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', boxSizing: 'border-box' }
const sheet: CSSProperties = { position: 'fixed', inset: 0, zIndex: 1500, background: TOKENS.bg[0], color: TOKENS.text[0], display: 'flex', flexDirection: 'column', padding: 16, boxSizing: 'border-box', overflowY: 'auto', overflowX: 'hidden', fontFamily: FONT.sans }
const searchInput: CSSProperties = { minHeight: 44, padding: '0 12px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontSize: TYPE.base, boxSizing: 'border-box', width: '100%' }

/** Three tiles per row on a phone (the mockup's 3 × 2 grid), wider on a desktop. A null value renders "—".
 *  With `onPick`, each keyed tile is a 44 px toggle button that filters the list below (operator 2026-11-06: "You
 *  can't click on the statuses to filter"); the active one is pressed, outlined and ticked. */
export function TileGrid({ tiles, label, active = null, onPick }: { tiles: Tile[]; label: string; active?: string | null; onPick?: (key: string) => void }) {
  return <div role="group" aria-label={label} data-testid="jobs-n8n-tiles" className="jobs-n8n-tiles">
    {tiles.map(t => {
      const tone = t.value ? t.tone : 'neutral'
      const on = !!t.key && t.key === active
      const body = <>
        <strong style={{ display: 'block', fontFamily: FONT.mono, fontSize: TYPE.lg, color: toneVars(on ? t.tone : tone).color }}>{t.value ?? '—'}</strong>
        <span style={{ ...muted, display: 'block', textTransform: 'uppercase', letterSpacing: '.04em', fontSize: TYPE.xs, color: on ? TOKENS.text[0] : TOKENS.text[2] }}>{on ? '✓ ' : ''}{t.label}</span>
      </>
      const base: CSSProperties = { ...panel, padding: '8px 10px', borderColor: toneVars(on ? t.tone : tone).border }
      if (!onPick || !t.key) return <div key={t.label} data-testid="jobs-n8n-tile" style={base}>{body}</div>
      return <button key={t.label} type="button" data-testid="jobs-n8n-tile" data-status={t.key} aria-pressed={on}
        aria-label={`${t.label}: ${t.value ?? 'not measured'}${on ? ', filtering the list; tap to clear' : ', tap to filter the list'}`}
        onClick={() => onPick(t.key!)}
        style={{ ...base, minHeight: 44, width: '100%', textAlign: 'left', cursor: 'pointer', font: 'inherit', color: TOKENS.text[0], boxSizing: 'border-box',
          background: on ? toneVars(t.tone).bg : TOKENS.bg[1], borderWidth: on ? 2 : 1, padding: on ? '7px 9px' : '8px 10px' }}>{body}</button>
    })}
  </div>
}

/** "Showing Failed · 3 jobs  [Clear]": what the tapped tile filters, with a 44 px way out. */
function StatusFilterBar({ label, count, onClear }: { label: string; count: number | null; onClear: () => void }) {
  return <div role="status" data-testid="jobs-n8n-status-filter" style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', ...panel, padding: '4px 4px 4px 12px', background: toneVars('info').bg, borderColor: toneVars('info').border }}>
    <span style={{ ...wrap, fontSize: TYPE.base }}>Showing <strong>{label}</strong>{count != null ? ` · ${count} ${count === 1 ? 'job' : 'jobs'}` : ''}</span>
    <button type="button" onClick={onClear} style={pill(false)}>Clear filter</button>
  </div>
}

/** `?status=` read and written on the current URL (shareable); replace, so Back leaves the page rather than a tile. */
function useStatusParam(valid: (s: string) => boolean): [string | null, (key: string | null) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('status')
  const status = raw && valid(raw) ? raw : null
  const set = (key: string | null) => {
    const next = new URLSearchParams(params)
    if (key) next.set('status', key); else next.delete('status')
    setParams(next, { replace: true })
  }
  return [status, set]
}

/** The shared style block for this page's grids (phone 3-up tiles; card list 1-up on a phone). */
export function JobsN8nStyles() {
  return <style>{`.jobs-n8n-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}@media(min-width:821px){.jobs-n8n-tiles{grid-template-columns:repeat(6,minmax(0,1fr))}}.jobs-n8n-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr));gap:10px}.job-history-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}@media(max-width:820px){.job-history-facts{grid-template-columns:1fr 1fr}}@media(max-width:420px){.job-history-facts{grid-template-columns:1fr}}`}</style>
}

// ── job tabs: Needs you, All jobs, Fixes (GET /api/v2/jobs-history) ─────────────────────────────────────────────
export function JobsHistoryTab({ tab, onTotal }: { tab: 'needs' | 'all' | 'fixes'; onTotal?: (tab: string, total: number) => void }) {
  const [filter, setFilter] = useState<string>(TAB_HISTORY_FILTER[tab])
  const [offset, setOffset] = useState(0)
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('history')
  const title = useRef<HTMLHeadingElement>(null)
  const tiles = historyTiles(null, tab)
  const [status, setStatus] = useStatusParam(s => tiles.some(t => t.key === s))
  useEffect(() => { const t = setTimeout(() => { setDebounced(query); setOffset(0) }, 300); return () => clearTimeout(t) }, [query])
  useEffect(() => { setOffset(0) }, [status])
  const list = useApi<DescribedListWire>(describedHistoryQuery({ filter: effectiveHistoryFilter(tab, filter, status), offset, q: debounced, status }), 60_000)
  const detail = useApi<HistoryDetailWire>(detailQuery(selectedId || ''), 60_000, { enabled: !!selectedId })
  const data = list.data
  useEffect(() => {
    if (data && onTotal && filter === TAB_HISTORY_FILTER[tab] && !debounced && !status) onTotal(tab, data.total)
  }, [data, filter, debounced, status, tab, onTotal])
  useEffect(() => { if (selectedId) title.current?.focus() }, [selectedId, detail.data])
  const select = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('history', id); else next.delete('history')
    setParams(next, id ? undefined : { replace: true })
  }
  const row = detail.data?.row && detail.data.row.lane_id === selectedId ? detail.data.row : null
  const listRow = data?.rows.find(r => r.lane_id === selectedId)
  const listName = listRow ? jobTitle(listRow) : undefined
  const detailRow = row as (typeof row & Partial<DescribedRow>) | null
  const activeTile = status ? historyTiles(data?.summary, tab).find(t => t.key === status) ?? null : null
  const intro = tab === 'needs' ? 'Failed, missed and late jobs, worst first.'
    : tab === 'fixes' ? 'Jobs with a retry, heal, incident or code fix in the last 14 days.' : 'Every registered job and where it runs.'
  return <section aria-label={tab === 'needs' ? 'Needs you' : tab === 'fixes' ? 'Fixes' : 'All jobs'} data-testid={`jobs-n8n-${tab}`} style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <p style={muted}>{intro}{data ? ` Checked ${etTime(data.computed_at)}.` : ''}</p>
    {list.error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Run history could not be read: {list.error}.{data ? ' The last observation remains below.' : ''}</div>}
    <TileGrid tiles={historyTiles(data?.summary, tab)} label="Run history summary — tap a status to filter" active={status} onPick={k => setStatus(toggleStatus(status, k))} />
    {activeTile && <StatusFilterBar label={activeTile.label} count={data && data.status === status ? data.total : null} onClear={() => setStatus(null)} />}
    {tab === 'all' && <>
      <div role="group" aria-label="Filter jobs by scheduler" style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2 }}>
        {ALL_JOBS_FILTERS.map(([k, label]) => <button key={k} type="button" aria-pressed={k === filter} onClick={() => { setFilter(k); setOffset(0) }} style={pill(k === filter)}>{label}</button>)}
      </div>
      <label style={{ display: 'grid', gap: 4, maxWidth: 420 }}><span style={muted}>Find a job</span>
        <input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Job name" style={searchInput} />
      </label>
    </>}
    <div className="jobs-n8n-list">
      {data?.rows.map(r => <JobCard key={r.lane_id} row={r} computedAt={data.computed_at} categories={data.categories} onOpen={select} />)}
    </div>
    {!data?.rows.length && <p style={{ ...panel, ...muted }}>{list.loading ? 'Loading run history…' : data ? (status ? 'No jobs with this status.' : tab === 'needs' ? 'Nothing needs you: no failed, missed or late job.' : 'No jobs in this view.') : 'No run history is available.'}</p>}
    {data && data.total > data.rows.length && <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', ...muted }}>
      <button type="button" style={pill(false)} disabled={data.offset === 0} onClick={() => setOffset(Math.max(0, data.offset - data.limit))}>Previous</button>
      <span>{data.offset + 1}–{data.offset + data.rows.length} of {data.total}</span>
      <button type="button" style={pill(false)} disabled={!data.has_more} onClick={() => setOffset(data.offset + data.limit)}>Next</button>
    </div>}
    {data && !!data.gaps.length && <p style={{ ...muted, color: TOKENS.warning }}>Unavailable: {data.gaps.join('; ')}</p>}
    {selectedId && <div role="dialog" aria-modal="true" aria-labelledby="jobs-n8n-history-title" data-testid="jobs-n8n-history-sheet"
      onKeyDown={e => { if (e.key === 'Escape') select(null) }} style={sheet}>
      <DetailHeader back="Jobs & n8n" title={(detailRow && jobTitle(detailRow)) || listName || 'Job run history'} titleId="jobs-n8n-history-title" titleRef={title} onClose={() => select(null)} style={{ margin: '-16px -16px 12px' }} />
      {detailRow && <div style={{ marginBottom: 12, maxWidth: 760 }}><JobDescription row={detailRow} categories={(detail.data as (HistoryDetailWire & { categories?: Category[] }) | null)?.categories} /></div>}
      {row && detail.data ? <HistoryDetail row={row} computedAt={detail.data.computed_at} />
        : <p role="status">{detail.error ? 'Run history for this job could not be read.' : detail.loading ? 'Loading run history…' : 'This job is not in the job list.'}</p>}
      <div style={{ marginTop: 16, maxWidth: 960, minWidth: 0 }}><SchedulerLaneDetail laneId={selectedId} compact /></div>
      <p style={{ ...muted, marginTop: 16 }}>See every job by category in the <Link to={JOB_CATALOG_PATH} style={{ color: TOKENS.info }}>Job catalog</Link>. Read-only page. No Run, Retry or Pause buttons here; those stay in <Link to={OPS_CONTROLS_PATH} style={{ color: TOKENS.info }}>Ops Controls</Link> behind your sign-in.</p>
    </div>}
  </section>
}

// ── n8n lanes tab (GET /api/v2/ops/controls/state → n8n) ─────────────────────────────────────────────────────────
/** One lane as a phone card. Pure. */
export function LaneCardView({ card, onOpen, info }: { card: LaneCard; onOpen: (id: string) => void; info?: DescribedRow | null }) {
  return <article aria-label={info?.title || card.id} data-testid="jobs-n8n-lane" style={{ ...panel, display: 'grid', gap: 8 }}>
    <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <span style={{ minWidth: 0, flex: '1 1 180px' }}>
        <strong style={{ ...wrap, fontSize: TYPE.md, display: 'block' }}>{info?.title || card.id}</strong>
        {info?.title && <span style={{ ...muted, ...wrap, display: 'block', fontFamily: FONT.mono }}>{card.id}</span>}
      </span>
      <span style={chip(card.health.tone)}>{card.health.label}</span>
    </div>
    {info !== undefined && <JobDescription row={info ?? { does: null, breaks: null }} />}
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <span style={chip(card.stage.tone)}>{card.stage.label}</span>
      <span style={chip(card.liveList.tone)}>{card.liveList.label}</span>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px', fontSize: TYPE.base }}>
      <span style={muted}>Last run</span><span style={{ ...wrap, color: toneVars(card.lastRun.tone).color }}>{card.lastRun.text}</span>
      <span style={muted}>Next run</span><span style={wrap}>{card.nextRun ?? '—'}</span>
      <span style={muted}>Promotion</span><span style={wrap}>{card.promotion.label}</span>
    </div>
    {card.why && <div data-testid="jobs-n8n-lane-why" style={{ ...wrap, fontSize: TYPE.base, color: TOKENS.text[1], background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '6px 8px' }}>{card.why}</div>}
    <button type="button" onClick={() => onOpen(card.id)} style={openBtn}>Lane details</button>
  </article>
}

function Facts({ items }: { items: Array<[string, ReactNode]> }) {
  return <div style={{ display: 'grid', gridTemplateColumns: 'minmax(110px,auto) 1fr', gap: '4px 12px', fontSize: TYPE.base }}>
    {items.map(([k, v]) => [<span key={`${k}:k`} style={muted}>{k}</span>, <span key={`${k}:v`} style={wrap}>{v}</span>])}
  </div>
}

/** Full lane detail for the sheet. Pure. */
export function LaneDetail({ row, card }: { row: N8nRowX; card: LaneCard }) {
  const o = row.outcome, rd = row.readiness
  const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))
  return <div data-testid="jobs-n8n-lane-detail" style={{ display: 'grid', gap: 14, maxWidth: 760, width: '100%', minWidth: 0 }}>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <span style={chip(card.health.tone)}>{card.health.label}</span><span style={chip(card.stage.tone)}>{card.stage.label}</span><span style={chip(card.liveList.tone)}>{card.liveList.label}</span>
    </div>
    {card.why && <p style={{ ...wrap, margin: 0 }}>{card.why}</p>}
    <Facts items={[
      ['Last run', card.lastRun.text], ['Next run', card.nextRun ?? '—'],
      ['Last success', o?.last_success_at ? etTime(o.last_success_at) : 'None recorded'],
      ['Last live success', o?.last_live_success_at ? etTime(o.last_live_success_at) : 'None recorded'],
      ['Runs, 7 days', o?.runs_7d ? `${o.runs_7d.live ?? 0} live · ${o.runs_7d.dry_run ?? 0} dry run` : 'Not measured'],
      ['Failures', o ? `${o.failures_24h ?? 0} in 24 h · ${o.failures_7d ?? 0} in 7 d` : 'Not measured'],
      ['Retries given up', o?.dead_letters_open ? `${o.dead_letters_open} in dead letter` : 'None open'],
      ['Breaker', o?.breaker_open ? 'Open (paused)' : 'Closed'],
      ['Schedule', o?.schedule?.length ? `${o.schedule.join(' · ')} (${o.tz === 'America/New_York' || !o.tz ? 'ET' : o.tz})` : 'Event-driven or none'],
      ['Registry', `stage ${s(row.stage)} · mode ${s(row.mode)} · state ${s(row.registry_state)} · workflow ${s(row.workflow)}`],
    ]} />
    {o?.health_reason && <p style={{ ...wrap, margin: 0, color: TOKENS.text[1] }}>Health: {o.health_reason}</p>}
    <section aria-label="Promotion" style={{ display: 'grid', gap: 6 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.md }}>Promotion{rd?.target ? ` to ${rd.target}` : ''}: {card.promotion.label}</h3>
      {(rd?.blocked_by || []).map((x, i) => <div key={`b${i}`} style={{ ...wrap, color: TOKENS.danger, fontSize: TYPE.base }}>Blocked: {x}</div>)}
      {(rd?.missing || []).map((x, i) => <div key={`m${i}`} style={{ ...wrap, color: TOKENS.warning, fontSize: TYPE.base }}>Missing: {x}</div>)}
      {(rd?.evidence || []).map((x, i) => <div key={`e${i}`} style={{ ...wrap, fontSize: TYPE.base }}>Evidence: {x}</div>)}
      {!rd && <p style={muted}>This server does not report promotion readiness for this lane.</p>}
      <p style={muted}>Promotion is your decision, made by a reviewed registry PR.</p>
    </section>
  </div>
}

export function N8nLanesTab({ state, loading, error }: { state: OpsControlsState | null; loading: boolean; error: string | null }) {
  const n = state?.n8n
  const rows = (n?.rows || []) as N8nRowX[]
  const [filter, setFilter] = useState<N8nFilter>('all')
  const [q, setQ] = useState('')
  const [status, setStatus] = useStatusParam(isN8nStatus)
  // Plain-English names and descriptions for the lanes (one cached jobs-history read; n8n has < 200 lanes).
  const described = useApi<DescribedListWire>(describedHistoryQuery({ filter: 'n8n', limit: 200 }), 300_000)
  const info = new Map((described.data?.rows ?? []).map(r => [r.lane_id, r]))
  const infoOf = (id: string): DescribedRow | null | undefined => (described.data ? info.get(id) ?? null : undefined)
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('lane')
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { if (selectedId) title.current?.focus() }, [selectedId])
  const nowMs = Date.parse(String(n?.outcomes_as_of || state?.as_of || '')) || Date.now()
  const counts = n8nFilterCounts(rows)
  const qq = q.trim().toLowerCase()
  const shown = sortLanes(rows.filter(r => matchesN8nFilter(r, filter) && (!status || !isN8nStatus(status) || matchesN8nStatus(r, status))
    && (matchesN8nQuery(r, q) || (!!qq && (info.get(r.lane_id)?.title || '').toLowerCase().includes(qq)))))
  const laneTiles = n8nTiles(summaryOf(rows, n?.summary), rows)
  const activeTile = status ? laneTiles.find(t => t.key === status) ?? null : null
  const select = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('lane', id); else next.delete('lane')
    setParams(next, id ? undefined : { replace: true })
  }
  const selected = selectedId ? rows.find(r => r.lane_id === selectedId) ?? null : null
  const sentence = moveToN8nSentence(rows)
  return <section aria-label="n8n lanes" data-testid="jobs-n8n-lanes" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <p style={muted}>Every lane n8n runs: its stage, whether it is on the live list, and in plain words why not.{n?.outcomes_as_of ? ` Run data as of ${etTime(n.outcomes_as_of)}.` : ''}</p>
    {error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>n8n lanes could not be read: {error}.{state ? ' The last observation remains below.' : ''}</div>}
    {n && n.state && n.state !== 'OK' && <div role="status" style={{ ...panel, color: TOKENS.warning }}>n8n lanes are {n.state}{n.reason ? `: ${n.reason}` : ''}.</div>}
    {n?.outcomes_state === 'UNAVAILABLE' && <div role="status" style={{ ...panel, color: TOKENS.warning }}>Run outcomes unavailable{n.outcomes_reason ? `: ${n.outcomes_reason}` : ''}. Last run and health are not measured; nothing is assumed.</div>}
    <TileGrid tiles={laneTiles} label="n8n lane summary — tap a status to filter" active={status} onPick={k => { setFilter('all'); setStatus(toggleStatus(status, k)) }} />
    {activeTile && <StatusFilterBar label={activeTile.label} count={rows.length ? shown.length : null} onClear={() => setStatus(null)} />}
    {sentence && <div data-testid="jobs-n8n-move-sentence" style={{ ...wrap, fontSize: TYPE.base, color: TOKENS.text[1], background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '8px 10px' }}>Move to n8n: {sentence}</div>}
    <div role="group" aria-label="Filter n8n lanes" style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2 }}>
      {N8N_FILTERS.map(([k, label]) => <button key={k} type="button" aria-pressed={k === filter} onClick={() => setFilter(k)} style={pill(k === filter)}>{label} · {counts[k]}</button>)}
    </div>
    <label style={{ display: 'grid', gap: 4, maxWidth: 420 }}><span style={muted}>Find a lane</span>
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Lane id" style={searchInput} />
    </label>
    <div className="jobs-n8n-list">
      {shown.map(r => <LaneCardView key={r.lane_id} card={laneCard(r, nowMs)} onOpen={select} info={infoOf(r.lane_id)} />)}
    </div>
    {!shown.length && <p style={{ ...panel, ...muted }}>{loading && !state ? 'Loading n8n lanes…' : rows.length ? 'No lanes match.' : 'No n8n lane is reported.'}</p>}
    <p style={muted} data-testid="jobs-n8n-switches-link">To add or remove a lane from the live list, use <Link to={`${OPS_CONTROLS_PATH}?tab=n8n`} style={{ color: TOKENS.info }}>Ops Controls › n8n lanes</Link> (passkey and typed phrase).</p>
    {selectedId && <div role="dialog" aria-modal="true" aria-labelledby="jobs-n8n-lane-title" data-testid="jobs-n8n-lane-sheet"
      onKeyDown={e => { if (e.key === 'Escape') select(null) }} style={sheet}>
      <DetailHeader back="n8n lanes" title={info.get(selectedId)?.title || selectedId} titleId="jobs-n8n-lane-title" titleRef={title} onClose={() => select(null)} style={{ margin: '-16px -16px 12px' }} />
      {info.get(selectedId) && <div style={{ marginBottom: 12, maxWidth: 760 }}><JobDescription row={info.get(selectedId)!} /></div>}
      {selected ? <LaneDetail row={selected} card={laneCard(selected, nowMs)} />
        : <p role="status">{loading ? 'Loading lane…' : 'This lane is not in the n8n lane list.'}</p>}
    </div>}
  </section>
}

// ── incidents tab (GET /api/v2/ops/incidents) ───────────────────────────────────────────────────────────────────
/** One incident as a phone card; opens the Incidents page's own detail (where Acknowledge / Close live). Pure. */
export function IncidentCardView({ inc, nowMs }: { inc: Incident; nowMs: number }) {
  const m = rowModel(inc, { age: ageText(inc.opened_at, inc.closed_at, nowMs), source: sourceText(inc) })
  return <article aria-label={m.headline} data-testid="jobs-n8n-incident" style={{ ...panel, display: 'grid', gap: 8 }}>
    <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <strong style={{ ...wrap, fontSize: TYPE.md, flex: '1 1 180px' }}>{m.headline}</strong>
      <span style={chip(m.status.tone)}>{m.status.label}</span>
    </div>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
      <span style={chip(m.priority.tone)}>{m.priority.code}</span><span style={muted}>{m.meta}</span>
    </div>
    <div style={{ ...wrap, fontSize: TYPE.base, color: TOKENS.text[1] }}>{m.nextAction}</div>
    <Link to={`/ops/incidents?detail=${encodeURIComponent(inc.id)}`} style={openBtn}>Open in Incidents</Link>
  </article>
}

export function IncidentsTab() {
  const { data, loading, error } = useApi<IncidentsWire>(INCIDENTS_PATH, 60_000)
  const [active, setActive] = useState(true)
  const nowMs = Date.now()
  const rows = sortIncidents((data?.incidents ?? []).filter(i => matchesFilter(i, active ? 'active' : 'all')))
  const c = data?.summary?.counts
  const tiles: Tile[] = [
    { label: 'Open', value: c ? c.open : null, tone: 'danger' }, { label: 'Fixing', value: c ? c.fixing : null, tone: 'warning' },
    { label: 'Blocked', value: c ? c.blocked : null, tone: 'danger' }, { label: 'Fixed', value: c ? c.fixed : null, tone: 'success' },
    { label: "Won't fix", value: c ? c.closed : null, tone: 'neutral' }, { label: 'Unresolved', value: data?.summary ? data.summary.unresolved : null, tone: 'warning' },
  ]
  return <section aria-label="Incidents" data-testid="jobs-n8n-incidents" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <p style={muted}>What broke and who or what is fixing it. To acknowledge or close one, open it in <Link to="/ops/incidents" style={{ color: TOKENS.info }}>Incidents</Link>.</p>
    {error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Incidents could not be read: {error}.</div>}
    {data && !data.ledger_present && <div role="status" style={{ ...panel, color: TOKENS.warning }}>The incident ledger has no events yet.</div>}
    <TileGrid tiles={tiles} label="Incident summary" />
    <div role="group" aria-label="Filter incidents" style={{ display: 'flex', gap: 6 }}>
      <button type="button" aria-pressed={active} onClick={() => setActive(true)} style={pill(active)}>Active</button>
      <button type="button" aria-pressed={!active} onClick={() => setActive(false)} style={pill(!active)}>All</button>
    </div>
    <div className="jobs-n8n-list">{rows.map(i => <IncidentCardView key={i.id} inc={i} nowMs={nowMs} />)}</div>
    {!rows.length && <p style={{ ...panel, ...muted }}>{loading && !data ? 'Loading incidents…' : data ? (active ? 'No active incident.' : 'No incident recorded.') : 'Incidents are not available.'}</p>}
  </section>
}
