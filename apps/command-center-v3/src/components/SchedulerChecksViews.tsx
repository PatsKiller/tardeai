import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import DetailHeader from './DetailHeader'
import { measuredNumber, operatorTime } from '../lib/schedulerOperations'
import {
  CHECK_KINDS, SCHEDULER_CHECKS_API, SCHEDULER_PILLS, checkKinds, checkLabel, checkTone, driftText, filterChecks, freshnessText,
  isUnregistered, kindCounts, observationExpired, outputText, schedulerLaneApi, schedulerPillLabel,
  type CheckKind, type CheckRow, type ChecksWire, type LaneWire, type SchedulerPill,
} from '../lib/schedulerChecks'

// Ops › Jobs & n8n › Scheduler checks, and the "Scheduler & output" block of a job's detail sheet. Merged here from
// Coordination › Automation (operator 2026-11-06), which is retired. Read-only: GET /api/v2/scheduler-operations
// ?view=checks and ?lane=<id>. Phone first: cards, 44 px targets, detail as a full-screen sheet.

const panel: CSSProperties = { padding: 12, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }
const chip = (tone: Tone): CSSProperties => ({ display: 'inline-block', padding: '2px 8px', borderRadius: RADIUS.pill, fontSize: TYPE.sm, fontWeight: 600, color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${toneVars(tone).border}`, whiteSpace: 'nowrap' })
const pill = (on: boolean): CSSProperties => ({ minHeight: 44, padding: '6px 12px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', whiteSpace: 'nowrap',
  color: on ? TOKENS.info : TOKENS.text[1], border: `1px solid ${on ? TOKENS.info : TOKENS.border}`, background: on ? toneVars('info').bg : TOKENS.bg[1] })
const openBtn: CSSProperties = { minHeight: 44, width: '100%', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer', textAlign: 'center', textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', boxSizing: 'border-box' }
const sheet: CSSProperties = { position: 'fixed', inset: 0, zIndex: 1500, background: TOKENS.bg[0], color: TOKENS.text[0], display: 'flex', flexDirection: 'column', padding: 16, boxSizing: 'border-box', overflowY: 'auto', overflowX: 'hidden', fontFamily: FONT.sans }
const searchInput: CSSProperties = { minHeight: 44, padding: '0 12px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontSize: TYPE.base, boxSizing: 'border-box', width: '100%' }
const NM = 'Not measured'

function Fact({ label, tip, children }: { label: string; tip: string; children: ReactNode }) {
  return <div style={{ minWidth: 0 }} title={tip}><div style={muted}>{label}</div><div style={{ ...wrap, fontSize: TYPE.base }}>{children}</div></div>
}

/** The scheduler/host facts Automation showed: output + freshness, duration, next due, failures and lock skips (24 h),
 *  code SHA, drift / duplicate, SLO. `stale` turns every measured value into "Not measured". */
export function SchedulerFactsGrid({ row, stale }: { row: CheckRow; stale: boolean }) {
  const v = (s: string | null) => (stale || !s ? NM : s)
  const n = (x: string) => (stale || x === 'NOT_MEASURED' ? NM : x)
  return <div className="job-history-facts" data-testid="scheduler-facts">
    <Fact label="Scheduler" tip="Where the host runs it, and its schedule.">{row.scheduler_type}{row.schedule ? <span style={{ fontFamily: FONT.mono }}> · {row.schedule}</span> : ''}</Fact>
    <Fact label="Last run finished" tip="Last completed run seen on the host.">{v(row.last_completed ? operatorTime(row.last_completed) : null)}</Fact>
    <Fact label="Next due" tip="Next scheduled start.">{v(row.next_due ? operatorTime(row.next_due) : null)}</Fact>
    <Fact label="Duration" tip="How long the last run took; p50/p95 over recent runs.">{n(measuredNumber(row.duration, ' s'))}{row.p95_runtime_s != null && !stale ? <span style={muted}> · p50 {measuredNumber(row.p50_runtime_s, ' s')} · p95 {measuredNumber(row.p95_runtime_s, ' s')}</span> : null}</Fact>
    <Fact label="Output" tip="The file or table that proves a run did its work.">{outputText(row.output_signal) ?? NM}</Fact>
    <Fact label="Output freshness" tip="How old that output is against the job's freshness limit.">{v(freshnessText(row))}</Fact>
    <Fact label="Failures · lock skips (24 h)" tip="Failed runs and runs skipped because the previous one still held the lock, last 24 hours.">{n(measuredNumber(row.failures_24h))} · {n(measuredNumber(row.lock_skips_24h))}</Fact>
    <Fact label="Scheduler match" tip="Drift: it runs somewhere the registry does not say. Scheduled twice: the same command in two schedulers.">{v(driftText(row))}</Fact>
    <Fact label="Code" tip="Code version the last run used, and where it ran from.">{row.code_sha ? <span style={{ fontFamily: FONT.mono }}>{row.code_sha.slice(0, 12)}</span> : NM}{row.code_root ? <span style={{ ...muted, display: 'block' }}>{row.code_root}</span> : null}</Fact>
    <Fact label="Owner · domain" tip="Who owns the job in the registry.">{[row.owner, row.domain].filter(Boolean).join(' · ') || NM}</Fact>
  </div>
}

function KindChips({ row }: { row: CheckRow }) {
  const kinds = checkKinds(row)
  return <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
    {kinds.map(k => <span key={k} style={chip(checkTone(k))}>{checkLabel(k)}</span>)}
    {isUnregistered(row) && !kinds.includes('orphaned') ? <span style={chip('neutral')}>Not in the registry</span> : null}
  </span>
}

/** One scheduler problem as a card. */
export function CheckCard({ row, stale, onOpen }: { row: CheckRow; stale: boolean; onOpen: (id: string) => void }) {
  return <article aria-label={row.lane_id} data-testid="scheduler-check-card" style={{ ...panel, display: 'grid', gap: 8 }}>
    <div style={{ display: 'grid', gap: 4 }}>
      <strong style={{ ...wrap, fontSize: TYPE.md, fontFamily: FONT.mono }}>{row.lane_id}</strong>
      <KindChips row={row} />
    </div>
    {row.health_reason && <div style={{ ...wrap, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{row.health_reason}</div>}
    <SchedulerFactsGrid row={row} stale={stale} />
    <button type="button" style={openBtn} onClick={() => onOpen(row.lane_id)}>Run timeline &amp; details</button>
  </article>
}

/** One lane's full host record: facts plus the run timeline with lock receipts. Fetches ?lane=<id>. */
export function SchedulerLaneDetail({ laneId, compact = false }: { laneId: string; compact?: boolean }) {
  const api = useApi<LaneWire>(schedulerLaneApi(laneId), 60_000)
  const row = api.data?.row ?? null
  const stale = observationExpired(api.data?.as_of) || !!api.stale
  if (!row) return <p role="status" style={muted} data-testid="scheduler-lane-missing">{api.loading ? 'Loading scheduler record…' : api.error ? 'The scheduler record could not be read.' : 'The host scheduler has no record of this job.'}</p>
  return <section aria-label="Scheduler and output" data-testid="scheduler-lane-detail" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    {compact && <h3 style={{ margin: 0, fontSize: TYPE.md }}>Scheduler &amp; output</h3>}
    <p style={muted}>Host record observed {operatorTime(api.data?.as_of)}{stale ? ' · older than 5 minutes, values shown as not measured' : ''}.</p>
    {checkKinds(row).length || isUnregistered(row) ? <KindChips row={row} /> : null}
    {row.health_reason && <div style={{ ...wrap, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{row.health_reason}</div>}
    <SchedulerFactsGrid row={row} stale={stale} />
    {row.consumer && <p style={muted}>Read by: {row.consumer}</p>}
    <h3 style={{ margin: 0, fontSize: TYPE.base }}>Host run timeline</h3>
    {row.timeline?.length ? <ol style={{ paddingLeft: 20, margin: 0, display: 'grid', gap: 10 }}>{row.timeline.map((run, i) => <li key={run.run_id || i} style={{ ...wrap, color: TOKENS.text[1], fontSize: TYPE.sm }}>
      <strong>{run.state || NM}{run.mode ? ` · ${run.mode}` : ''}</strong>
      <div>Requested {operatorTime(run.requested_at)} → started {operatorTime(run.started_at)} → finished {operatorTime(run.finished_at)}</div>
      <div>Lock {run.receipt ? run.receipt.lock_skipped ? 'skipped (previous run held it)' : 'no skip recorded' : NM} · exit {run.exit_code ?? NM}</div>
      {run.receipt?.output_signal ? <div>Output {run.receipt.output_signal}</div> : null}
    </li>)}</ol> : <p style={muted}>No host run timeline recorded.</p>}
  </section>
}

/** Ops › Jobs & n8n › Scheduler checks: drift, orphaned, quiet output, slow, lock skips and failures from the host,
 *  including scheduler entries no registered job owns. `?check=<kind>`, `?lane=<id>` for the detail sheet. */
export function SchedulerChecksTab({ onTotal }: { onTotal?: (tab: string, total: number) => void }) {
  const api = useApi<ChecksWire>(SCHEDULER_CHECKS_API, 60_000)
  const data = api.data
  const [params, setParams] = useSearchParams()
  const rawKind = params.get('check')
  const kind = CHECK_KINDS.some(([k]) => k === rawKind) ? rawKind as CheckKind : null
  const selected = params.get('lane')
  const [scheduler, setScheduler] = useState<SchedulerPill>('all')
  const [q, setQ] = useState('')
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { if (data && onTotal) onTotal('checks', data.rows.length) }, [data, onTotal])
  useEffect(() => { if (selected) title.current?.focus() }, [selected])
  const setParam = (k: string, v: string | null, push = false) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v); else next.delete(k)
    setParams(next, push ? undefined : { replace: true })
  }
  const stale = observationExpired(data?.as_of) || !!api.stale
  const all = data?.rows ?? []
  const rows = filterChecks(all, { kind, scheduler, q })
  const counts = kindCounts(all)
  const sel = all.find(r => r.lane_id === selected)
  return <section aria-label="Scheduler checks" data-testid="jobs-n8n-checks" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <p style={muted}>What the host schedulers (cron, systemd, n8n, OpenClaw) show that run history cannot: drift, entries no job owns, output that went quiet, slow runs and lock skips.{data ? ` ${all.length} of ${data.total} scheduler entries need a look · observed ${operatorTime(data.as_of)}${data.source_sha ? ` · code ${data.source_sha.slice(0, 12)}` : ''}.` : ''}</p>
    {stale && data && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>This observation is older than 5 minutes; measured values show as not measured until the next read.</div>}
    {api.error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Scheduler checks could not be read: {api.error}.{data ? ' The last observation remains below.' : ''}</div>}
    {data && <div style={{ ...muted, display: 'flex', gap: 10, flexWrap: 'wrap' }} data-testid="scheduler-checks-summary">
      <span>Not measured: {data.state_counts.NOT_MEASURED ?? 0}</span><span>Live and proven: {data.state_counts.LIVE ?? 0}</span>
      <span>Expected silent: {data.state_counts.EXPECTED_SILENT ?? 0}</span><span>Not in the registry: {data.unregistered}</span>
    </div>}
    <div role="group" aria-label="Filter by check" className="jobs-n8n-tiles" data-testid="scheduler-check-kinds">
      {counts.map(c => {
        const on = c.kind === kind
        return <button key={c.kind} type="button" aria-pressed={on} data-check={c.kind} onClick={() => setParam('check', on ? null : c.kind)}
          title={CHECK_KINDS.find(([k]) => k === c.kind)?.[2]}
          style={{ ...panel, padding: '8px 10px', minHeight: 44, textAlign: 'left', cursor: 'pointer', font: 'inherit', color: TOKENS.text[0], borderColor: toneVars(checkTone(c.kind)).border, background: on ? toneVars(checkTone(c.kind)).bg : TOKENS.bg[1], borderWidth: on ? 2 : 1 }}>
          <strong style={{ display: 'block', fontFamily: FONT.mono, fontSize: TYPE.lg, color: toneVars(checkTone(c.kind)).color }}>{c.count}</strong>
          <span style={{ ...muted, display: 'block', textTransform: 'uppercase', letterSpacing: '.04em', fontSize: TYPE.xs, color: on ? TOKENS.text[0] : TOKENS.text[2] }}>{on ? '✓ ' : ''}{c.label}</span>
        </button>
      })}
    </div>
    {kind && <p style={muted}>{CHECK_KINDS.find(([k]) => k === kind)?.[2]} <button type="button" style={pill(false)} onClick={() => setParam('check', null)}>Clear filter</button></p>}
    <div role="group" aria-label="Filter by scheduler" style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2 }}>
      {SCHEDULER_PILLS.map(p => <button key={p} type="button" aria-pressed={p === scheduler} onClick={() => setScheduler(p)} style={pill(p === scheduler)}>{schedulerPillLabel(p)}</button>)}
    </div>
    <label style={{ display: 'grid', gap: 4, maxWidth: 420 }}><span style={muted}>Find a job or scheduler entry</span>
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Name, owner or reason" style={searchInput} />
    </label>
    <div className="jobs-n8n-list">{rows.map(r => <CheckCard key={r.lane_id} row={r} stale={stale} onOpen={id => setParam('lane', id, true)} />)}</div>
    {!rows.length && <p style={{ ...panel, ...muted }}>{api.loading && !data ? 'Loading scheduler checks…' : data ? (all.length ? 'No entries match.' : 'No scheduler problems observed.') : 'Scheduler checks are not available.'}</p>}
    {selected && <div role="dialog" aria-modal="true" aria-labelledby="scheduler-lane-title" data-testid="scheduler-lane-sheet"
      onKeyDown={e => { if (e.key === 'Escape') setParam('lane', null) }} style={sheet}>
      <DetailHeader back="Scheduler checks" title={selected} titleId="scheduler-lane-title" titleRef={title} onClose={() => setParam('lane', null)} style={{ margin: '-16px -16px 12px' }} />
      <div style={{ maxWidth: 960, width: '100%', minWidth: 0, display: 'grid', gap: 12 }}>
        <SchedulerLaneDetail laneId={selected} />
        {sel && !isUnregistered(sel) ? <Link to={`/ops/jobs-n8n?tab=all&history=${encodeURIComponent(selected)}`} style={openBtn}>Run history &amp; fixes</Link>
          : <p style={muted}>No registered job owns this entry, so it has no run history page. Registering or retiring it is a code change.</p>}
      </div>
    </div>}
  </section>
}

