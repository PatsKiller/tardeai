import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import DetailHeader from './DetailHeader'
import {
  HISTORY_FILTERS, RESULT_LABEL, SLOT_LABEL, STATUS_LABEL, ago, cadenceText, detailQuery, duration, etTime, fixLabel,
  fixTone, historyQuery, missedText, resultTone, schedulerLabel, slotTone, statusTone,
  type FixEvent, type HistoryDetailRow, type HistoryDetailWire, type HistoryListRow, type HistoryListWire,
} from '../lib/jobRunHistory'

// /ops/jobs → Run history. Every registered job: when it ran, when it did not, and what fixed it (operator 2026-11-06).
// Phone first: a stacked card list (no table, no horizontal scroll at 390 px) that opens one full-screen detail.

const panel: CSSProperties = { padding: 14, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const chip = (tone: Tone): CSSProperties => ({ display: 'inline-block', padding: '2px 8px', borderRadius: RADIUS.sm, fontSize: TYPE.sm, color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${toneVars(tone).border}`, whiteSpace: 'nowrap' })
const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div style={{ minWidth: 0 }}><div style={muted}>{label}</div><div style={{ ...wrap, fontSize: TYPE.base }}>{children}</div></div>
}

/** One job in the list. Pure: renders from the wire row and the projection's computed_at. */
export function HistoryCard({ row, computedAt, onOpen }: { row: HistoryListRow; computedAt: string; onOpen: (id: string) => void }) {
  const last = row.last_run
  return <article aria-label={row.job} data-testid="history-card" className="job-history-card" style={{ ...panel, display: 'grid', gap: 10 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap' }}>
      <div style={{ minWidth: 0, flex: '1 1 200px' }}>
        <strong style={{ ...wrap, fontSize: TYPE.base, display: 'block' }}>{row.job}</strong>
        <span style={muted}>{schedulerLabel(row.scheduler)} · {cadenceText(row.cadence)}</span>
      </div>
      <span style={chip(statusTone(row.status))}>{STATUS_LABEL[row.status]}</span>
    </div>
    {row.status_reason && <div style={{ ...wrap, color: TOKENS.text[1], fontSize: TYPE.sm }}>{row.status_reason}</div>}
    <div className="job-history-facts">
      <Fact label="Last run">{last ? <>{etTime(last.started_at || last.finished_at)} <span style={chip(resultTone(last.result))}>{RESULT_LABEL[last.result]}</span></> : 'No run recorded'}</Fact>
      <Fact label="Last success">{row.last_success_at ? `${etTime(row.last_success_at)} (${ago(row.last_success_at, computedAt)})` : 'None recorded'}</Fact>
      <Fact label="Missed runs">{missedText(row)}</Fact>
      <Fact label="Fixed (14 days)">{row.fix_count ? `${row.fix_count} event${row.fix_count === 1 ? '' : 's'} · latest ${fixLabel(row.last_fix!.kind).toLowerCase()} ${etTime(row.last_fix!.at)}` : 'None recorded'}</Fact>
    </div>
    {row.history_gap && <div style={{ ...muted, ...wrap }}>Run history: {row.history_gap}</div>}
    <button type="button" onClick={() => onOpen(row.lane_id)} style={{ minHeight: 44, width: '100%', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer' }}>Run history &amp; fixes</button>
  </article>
}

function FixList({ fixes }: { fixes: FixEvent[] }) {
  if (!fixes.length) return <p style={{ ...muted, margin: 0 }}>No retry, heal or incident is recorded for this job in the last 14 days.</p>
  return <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
    {fixes.map((f, i) => <li key={`${f.at}-${f.kind}-${i}`} data-testid="history-fix" style={{ borderLeft: `3px solid ${toneVars(fixTone(f)).color}`, paddingLeft: 10, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <strong style={{ fontSize: TYPE.base }}>{fixLabel(f.kind)}</strong><span style={muted}>{etTime(f.at)} · by {f.by}</span>
      </div>
      {f.detail && <div style={{ ...wrap, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{f.detail}</div>}
      {f.ref && <div style={{ ...muted, ...wrap, fontFamily: FONT.mono }}>{f.ref}</div>}
    </li>)}
  </ol>
}

/** Full detail body: runs (newest first), expected slots, fixes, evidence. Pure. */
export function HistoryDetail({ row, computedAt }: { row: HistoryDetailRow; computedAt: string }) {
  return <div style={{ display: 'grid', gap: 14, maxWidth: 760, width: '100%', minWidth: 0 }} data-testid="history-detail">
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <span style={chip(statusTone(row.status))}>{STATUS_LABEL[row.status]}</span>
      <span style={muted}>{schedulerLabel(row.scheduler)} · registry state {row.state.toLowerCase().replace(/_/g, ' ')}</span>
    </div>
    {row.status_reason && <p style={{ ...wrap, margin: 0 }}>{row.status_reason}</p>}
    <div className="job-history-facts">
      <Fact label="Expected">{cadenceText(row.cadence)}</Fact>
      <Fact label="Last success">{row.last_success_at ? `${etTime(row.last_success_at)} (${ago(row.last_success_at, computedAt)})` : 'None recorded'}</Fact>
      <Fact label="Missed runs">{missedText(row)}</Fact>
      <Fact label="Run history from">{row.history_sources.length ? row.history_sources.join(' + ') : 'No run store'}</Fact>
    </div>
    {row.history_gap && <p role="note" style={{ ...panel, margin: 0, borderColor: toneVars('warning').border, color: TOKENS.text[1] }}>Why the run history is limited: {row.history_gap}</p>}
    {row.output?.written_at && <p style={{ ...muted, margin: 0 }}>Output file last written {etTime(row.output.written_at)}. {row.output.note}.</p>}

    <section aria-label="Recent runs" style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.base }}>Recent runs</h3>
      {row.runs.length ? <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6 }}>
        {row.runs.map((r, i) => <li key={`${r.run_id ?? 'run'}-${i}`} data-testid="history-run" style={{ ...panel, padding: 10, display: 'grid', gap: 4 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <span style={chip(resultTone(r.result))}>{RESULT_LABEL[r.result]}</span>
            <span style={{ fontFamily: FONT.mono, fontSize: TYPE.sm }}>{etTime(r.started_at || r.requested_at)}</span>
            {r.finished_at && <span style={muted}>→ {etTime(r.finished_at)}</span>}
            {duration(r.duration_s) && <span style={muted}>{duration(r.duration_s)}</span>}
            {r.mode === 'dry_run' && <span style={chip('neutral')}>Dry run</span>}
            {r.attempt && r.attempt > 1 && <span style={chip('info')}>Retry, attempt {r.attempt}</span>}
          </div>
          {r.exit_code != null && r.result !== 'succeeded' && <div style={muted}>Exit code {r.exit_code}</div>}
          {r.inline_attempts && <div style={muted}>Tries inside this run: {r.inline_attempts.map(s => s.replace('RUN_', '').toLowerCase()).join(' → ')}</div>}
          {r.reason && <div style={{ ...wrap, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{r.reason}</div>}
          <div style={{ ...muted, ...wrap }}>From {r.source}{r.requested_by ? ` · started by ${r.requested_by}` : ''}</div>
        </li>)}
      </ol> : <p style={{ ...muted, margin: 0 }}>No run is recorded for this job.</p>}
    </section>

    <section aria-label="Expected runs" style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.base }}>Expected runs (last 10)</h3>
      {row.slots.length ? <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 6 }}>
        {row.slots.map(s => <li key={s.slot_at} data-testid="history-slot" style={{ padding: 8, borderRadius: RADIUS.sm, background: toneVars(slotTone(s.status)).bg, border: `1px solid ${toneVars(slotTone(s.status)).border}`, minWidth: 0 }}>
          <div style={{ fontFamily: FONT.mono, fontSize: TYPE.sm }}>{etTime(s.slot_at)}</div>
          <div style={{ fontSize: TYPE.sm, color: toneVars(slotTone(s.status)).color }}>{SLOT_LABEL[s.status]}</div>
        </li>)}
      </ol> : <p style={{ ...muted, margin: 0 }}>{row.cadence.schedule_gap || (row.state === 'ACTIVE' ? 'No expected run in the last 7 days.' : 'Not expected to run while it is not active.')}</p>}
    </section>

    <section aria-label="Fixes" style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.base }}>Retries, heals and incidents (14 days)</h3>
      <FixList fixes={row.fixes} />
      {row.fix_count > row.fixes.length && <p style={{ ...muted, margin: 0 }}>Showing the newest {row.fixes.length} of {row.fix_count}.</p>}
    </section>
  </div>
}

/** The list view, pure (the container below owns fetching and the URL). */
export function HistoryListView({ data, loading, error, filter, onFilter, query, onQuery, onOpen, onPage }: {
  data: HistoryListWire | null; loading: boolean; error: string | null; filter: string; onFilter: (f: string) => void
  query: string; onQuery: (q: string) => void; onOpen: (id: string) => void; onPage: (offset: number) => void
}) {
  const s = data?.summary
  const tiles: [string, number | null | undefined, Tone][] = [
    ['Failed', s?.failed ?? 0, 'danger'], ['Missed a run', s?.with_missed, 'warning'], ['Late', s?.late ?? 0, 'warning'],
    ['Fixed in 14 days', s?.fixed_14d, 'info'], ['No per-run history', s?.no_run_history, 'neutral'],
  ]
  return <section aria-label="Job run history" data-testid="job-run-history" style={{ display: 'grid', gap: 12, color: TOKENS.text[0], fontFamily: FONT.sans, minWidth: 0 }}>
    <style>{`.job-history-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.job-history-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr));gap:10px}@media(max-width:820px){.job-history-facts{grid-template-columns:1fr 1fr}}@media(max-width:420px){.job-history-facts{grid-template-columns:1fr}}`}</style>
    <div style={{ display: 'grid', gap: 4 }}>
      <h2 style={{ margin: 0, fontSize: TYPE.lg }}>Run history</h2>
      <p style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[2] }}>Every job: when it ran, when it did not, and what fixed it.</p>
    </div>
    {error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Run history could not be read: {error}.{data ? ' The last observation remains below.' : ''}</div>}
    {data && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
      {tiles.map(([label, count, tone]) => <div key={label} data-testid="history-tile" style={{ ...panel, padding: 10, borderColor: toneVars(tone).border }}>
        <div style={muted}>{label}</div><strong style={{ fontFamily: FONT.mono, fontSize: TYPE.xl, color: toneVars(tone).color }}>{count ?? '—'}</strong>
      </div>)}
    </div>}
    <div role="group" aria-label="Filter run history" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {HISTORY_FILTERS.map(([key, label]) => <button key={key} type="button" aria-pressed={key === filter} onClick={() => onFilter(key)} style={{ minHeight: 44, padding: '6px 12px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', color: key === filter ? TOKENS.warning : TOKENS.text[1], border: `1px solid ${key === filter ? TOKENS.warning : TOKENS.border}`, background: key === filter ? toneVars('warning').bg : TOKENS.bg[1] }}>{label}</button>)}
    </div>
    <label style={{ display: 'grid', gap: 4, maxWidth: 420 }}><span style={muted}>Find a job</span>
      <input type="search" value={query} onChange={e => onQuery(e.target.value)} placeholder="Job name" style={{ minHeight: 44, padding: '0 12px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontSize: TYPE.base, boxSizing: 'border-box', width: '100%' }} />
    </label>
    <div className="job-history-list">
      {data?.rows.map(row => <HistoryCard key={row.lane_id} row={row} computedAt={data.computed_at} onOpen={onOpen} />)}
    </div>
    {!data?.rows.length && <p style={{ ...panel, color: TOKENS.text[2], margin: 0 }}>{loading ? 'Loading run history…' : data ? 'No jobs in this filter.' : 'No run history is available.'}</p>}
    {data && <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', ...muted }}>
      <button type="button" style={{ minHeight: 44 }} disabled={data.offset === 0} onClick={() => onPage(Math.max(0, data.offset - data.limit))}>Previous</button>
      <span>{data.total ? `${data.offset + 1}–${data.offset + data.rows.length} of ${data.total}` : '0 jobs'}</span>
      <button type="button" style={{ minHeight: 44 }} disabled={!data.has_more} onClick={() => onPage(data.offset + data.limit)}>Next</button>
    </div>}
    {data && <details style={{ ...panel, ...muted }} data-testid="history-sources">
      <summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>Where this comes from · computed {etTime(data.computed_at)}</summary>
      <ul style={{ margin: '8px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}>
        {data.sources.map(src => <li key={src.name} style={wrap}>{src.name}: newest record {etTime(src.newest_record_at, 'not recorded')}{src.covers_from ? `, covers from ${etTime(src.covers_from)}` : ''}{src.note ? ` (${src.note})` : ''}</li>)}
      </ul>
      {!!data.gaps.length && <p style={{ margin: '8px 0 0', color: TOKENS.warning }}>Unavailable: {data.gaps.join('; ')}</p>}
      <p style={{ margin: '8px 0 0' }}>{data.note}</p>
    </details>}
  </section>
}

export default function JobRunHistory({ enabled = true }: { enabled?: boolean }) {
  const [filter, setFilter] = useState('attention')
  const [offset, setOffset] = useState(0)
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('history')
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { const t = setTimeout(() => { setDebounced(query); setOffset(0) }, 300); return () => clearTimeout(t) }, [query])
  const list = useApi<HistoryListWire>(historyQuery(filter, offset, debounced), 60_000, { enabled })
  const detail = useApi<HistoryDetailWire>(detailQuery(selectedId || ''), 60_000, { enabled: enabled && !!selectedId })
  const select = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('history', id); else next.delete('history')
    setParams(next, id ? undefined : { replace: true })
  }
  useEffect(() => { if (selectedId) title.current?.focus() }, [selectedId, detail.data])
  const row = detail.data?.row && detail.data.row.lane_id === selectedId ? detail.data.row : null
  const listName = list.data?.rows.find(r => r.lane_id === selectedId)?.job
  return <>
    <HistoryListView data={list.data} loading={list.loading} error={list.error} filter={filter}
      onFilter={f => { setFilter(f); setOffset(0) }} query={query} onQuery={setQuery} onOpen={id => select(id)} onPage={setOffset} />
    {selectedId && <div role="dialog" aria-modal="true" aria-labelledby="job-history-title" data-testid="job-history-sheet"
      onKeyDown={e => { if (e.key === 'Escape') select(null) }}
      style={{ position: 'fixed', inset: 0, zIndex: 1500, background: TOKENS.bg[0], color: TOKENS.text[0], display: 'flex', flexDirection: 'column', padding: 16, boxSizing: 'border-box', overflowY: 'auto', overflowX: 'hidden', fontFamily: FONT.sans }}>
      <DetailHeader back="Run history" title={row?.job || listName || 'Job run history'} titleId="job-history-title" titleRef={title} onClose={() => select(null)} style={{ margin: '-16px -16px 12px' }} />
      {row && detail.data ? <HistoryDetail row={row} computedAt={detail.data.computed_at} />
        : <p role="status">{detail.error ? 'Run history for this job could not be read.' : detail.loading ? 'Loading run history…' : 'This job is not in the job list.'}</p>}
    </div>}
  </>
}
