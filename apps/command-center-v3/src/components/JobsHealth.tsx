import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import ConflictLine from './conflicts/ConflictLine'
import AnthropicCreditPanel from './AnthropicCreditPanel'
import ConflictSheet, { useConflictSheet, type ConflictSection } from './conflicts/ConflictSheet'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import CountTile from './CountTile'
import { jobsCount, jobsMissed, jobsNotMeasured, type JobsSummary } from '../lib/measuredCount'

export type JobResult = 'succeeded' | 'failed' | 'missed' | 'paused' | 'retired' | 'unknown' | 'due' | 'outside_window'
/** Which fact makes an unknown row unmeasured. Three different facts, three different remedies. */
export type EvidenceGap = 'never_scheduled' | 'schedule_not_declared' | 'execution_not_measured'
export interface JobHealthRow {
  lane_id: string; job: string; scheduler: string; state: string; result: JobResult
  last_run_at: string | null; last_success_at: string | null; next_due_at: string | null
  cause: string; market_hours_only: boolean; successful_run_id?: string | null
  evidence_gap?: EvidenceGap | null; schedule_measured?: boolean
}
export interface JobsHealthWire {
  schema: string; as_of: string; rows: JobHealthRow[]; total: number; offset: number; limit: number; has_more: boolean
  summary: JobsSummary & Record<string, unknown>; coverage_gaps: string[]; incident_count: number
  data_errors?: { section: ConflictSection | null; unavailable_reason: string | null }
  monitor: { observed_at: string | null; status: string; cause: string | null; notification?: { status?: string; delivered?: boolean } | null }
  watchers?: WatcherLight[]
}
export type WatcherStatus = 'ok' | 'degraded' | 'down' | 'absent'
export interface WatcherLight { id: string; label: string; status: WatcherStatus; cause: string | null }
const watcherTone = (status: WatcherStatus): Tone => status === 'ok' ? 'success' : status === 'degraded' ? 'warning' : 'danger'
const watcherLabel: Record<WatcherStatus, string> = { ok: 'Watching', degraded: 'Not armed', down: 'Down', absent: 'Not registered' }
const filters = [['attention', 'Needs attention'], ['all', 'All jobs'], ['market', 'Market hours only'], ['n8n', 'n8n'], ['cron', 'Host cron (moving to n8n)']] as const
const panel: CSSProperties = { padding: 14, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const tone = (result: JobResult): Tone => result === 'failed' ? 'danger' : result === 'missed' || result === 'unknown' ? 'warning' : result === 'succeeded' ? 'success' : 'neutral'
const resultLabel: Record<JobResult, string> = { succeeded: 'Succeeded', failed: 'Failed', missed: 'Missed', paused: 'Paused', retired: 'Retired', unknown: 'Not measured', due: 'Due', outside_window: 'Outside window' }
const gapLabel: Record<EvidenceGap, string> = { never_scheduled: 'Unscheduled by design', schedule_not_declared: 'No schedule declared', execution_not_measured: 'No run receipt' }
const at = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET' : 'Not measured'

export default function JobsHealth({ enabled = true }: { enabled?: boolean }) {
  const [filter, setFilter] = useState('attention')
  const [offset, setOffset] = useState(0)
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('job')
  const conflict = useConflictSheet()
  const detailTitle = useRef<HTMLHeadingElement>(null)
  const { data, loading, error } = useApi<JobsHealthWire>(`/api/v2/jobs-health?filter=${filter}&offset=${offset}&limit=50`, 60_000, { enabled })
  const consumption = useApi<any>('/api/v2/consumption/overview', 90_000, { enabled })
  const dataErrors = data?.data_errors
  const conflictUnavailable = dataErrors?.unavailable_reason || (data && !dataErrors?.section ? 'The canonical data error section is unavailable.' : null)
  const inList = data?.rows.find(row => row.lane_id === selectedId)
  const detail = useApi<JobsHealthWire>(`/api/v2/jobs-health?job=${encodeURIComponent(selectedId || '')}&filter=all&limit=1`, 60_000, { enabled: enabled && !!selectedId && !inList })
  const selected = inList || detail.data?.rows.find(row => row.lane_id === selectedId)
  const select = (id: string | null) => {
    const next = new URLSearchParams(params)
    if (id) next.set('job', id); else next.delete('job')
    setParams(next, id ? undefined : { replace: true })
  }
  useEffect(() => { if (selectedId) detailTitle.current?.focus() }, [selectedId, selected])
  const metrics = [
    ['due_today', 'Jobs due today', 'neutral'], ['succeeded', 'Ran and succeeded', 'success'],
    ['failed', 'Failed', 'danger'], ['missed', 'Missed', 'warning'],
  ] as const
  return <section aria-label="Jobs and health" data-testid="jobs-health" style={{ display: 'grid', gap: 12, color: TOKENS.text[0], fontFamily: FONT.sans, minWidth: 0 }}>
    <AnthropicCreditPanel status={(consumption.data?.overview ?? consumption.data)?.anthropic} />
    <style>{`.jobs-health-row{display:grid;grid-template-columns:minmax(180px,1.3fr) 90px 130px 110px 130px minmax(200px,2fr);gap:10px;align-items:start}.jobs-health-mobile-label{display:none}@media(max-width:800px){.jobs-health-head{display:none}.jobs-health-row{grid-template-columns:1fr 1fr}.jobs-health-job,.jobs-health-cause{grid-column:1/-1}.jobs-health-mobile-label{display:block;font-size:11px;color:var(--text-2);margin-bottom:3px}}`}</style>
    <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
      <h2 style={{ margin: 0, fontSize: TYPE.lg }}>Jobs &amp; health</h2>
      <p style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[2] }}>Did every scheduled job run and succeed? One answer across operations.</p>
      <Link to="/ops/jobs" style={{ color: TOKENS.info, fontSize: TYPE.sm, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Open Jobs</Link>
    </div>
    {error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>Jobs could not be read: {error}. {data ? 'The last observation remains visible below.' : 'Execution health is not measured.'}</div>}
    <section aria-label="Watchers and alerts" data-testid="jobs-watchers" style={{ ...panel, display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.base }}>Watchers &amp; alerts</h3>
      {data?.watchers?.length
        ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 8 }}>
            {data.watchers.map(w => <div key={w.id} role="status" style={{ padding: 10, borderRadius: RADIUS.sm, border: `1px solid ${toneVars(watcherTone(w.status)).border}`, background: toneVars(watcherTone(w.status)).bg, minWidth: 0 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: '50%', background: toneVars(watcherTone(w.status)).color, flexShrink: 0 }} /><strong style={{ fontSize: TYPE.base }}>{w.label}</strong></div>
              <div style={{ fontSize: TYPE.sm, color: toneVars(watcherTone(w.status)).color, marginTop: 4 }}>{watcherLabel[w.status]}</div>
              {w.cause && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginTop: 4, overflowWrap: 'anywhere' }}>{w.cause}</div>}
            </div>)}
          </div>
        : <p style={{ margin: 0, color: TOKENS.text[2] }}>{loading ? 'Loading watchers…' : 'Watchers are not measured.'}</p>}
    </section>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10 }}>
      {metrics.map(([key, label, t]) => <CountTile key={key} testId={`jobs-tile-${key}`} label={label} tone={t} style={{ padding: 14 }}
        count={key === 'missed' ? jobsMissed(data?.summary) : jobsCount(data?.summary, key)} />)}
      <CountTile testId="jobs-tile-not-measured" label="Not measured" tone="warning" style={{ padding: 14 }} count={jobsNotMeasured(data?.summary)} />
      <div style={panel}><div style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>Paused / retired</div><strong style={{ fontFamily: FONT.mono, fontSize: TYPE.xl }}>{data ? `${data.summary.paused ?? '—'} / ${data.summary.retired ?? '—'}` : '—'}</strong></div>
    </div>
    {data?.monitor.cause && <div role="status" style={{ ...panel, borderColor: toneVars('warning').border, color: TOKENS.warning }}>{data.monitor.cause}</div>}
    <section aria-label="Data errors" style={{ ...panel, display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: TYPE.base }}>Data quality</h3>
      {conflictUnavailable && <p role="status" data-testid="jobs-conflict-unavailable" style={{ margin: 0, color: TOKENS.warning }}>{conflictUnavailable}</p>}
      {dataErrors?.section?.stale && <p role="status" style={{ margin: 0, color: TOKENS.warning }}>The data error comparison is out of date. The last supplied section remains visible.</p>}
      {dataErrors?.section && <ConflictLine section={dataErrors.section} onOpen={conflict.open} />}
      {conflict.key && !dataErrors?.section && <button type="button" onClick={conflict.close} style={{ minHeight: 44 }}>Back to jobs</button>}
    </section>
    {enabled && conflict.key && dataErrors?.section && <ConflictSheet title="Job data error" section={dataErrors.section} mobile={conflict.mobile} onBack={conflict.close} />}
    <div role="group" aria-label="Filter jobs" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {filters.map(([key, label]) => <button key={key} type="button" aria-pressed={key === filter} onClick={() => { setFilter(key); setOffset(0) }} style={{ minHeight: 44, padding: '6px 12px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', color: key === filter ? TOKENS.warning : TOKENS.text[1], border: `1px solid ${key === filter ? TOKENS.warning : TOKENS.border}`, background: key === filter ? toneVars('warning').bg : TOKENS.bg[1] }}>{label}</button>)}
    </div>
    <div style={{ ...panel, padding: 0, overflow: 'hidden' }}>
      <div className="jobs-health-row jobs-health-head" style={{ padding: '10px 14px', borderBottom: `1px solid ${TOKENS.border}`, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{['Job', 'Runs on', 'Last run', 'Result', 'Next due', 'Why'].map(x => <span key={x}>{x}</span>)}</div>
      {data?.rows.map(row => <article key={row.lane_id} className="jobs-health-row" aria-label={row.job} data-evidence-gap={row.evidence_gap ?? undefined} style={{ padding: '12px 14px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, fontSize: TYPE.base }}>
        <strong className="jobs-health-job">{row.job}</strong>
        <div><span className="jobs-health-mobile-label">Runs on</span>{row.scheduler === 'cron' ? 'Host cron' : row.scheduler}</div>
        <div style={{ fontFamily: FONT.mono, fontSize: TYPE.sm }}><span className="jobs-health-mobile-label">Last run</span>{at(row.last_run_at)}</div>
        <div><span className="jobs-health-mobile-label">Result</span><span style={{ display: 'inline-block', padding: '2px 7px', borderRadius: RADIUS.sm, color: toneVars(tone(row.result)).color, background: toneVars(tone(row.result)).bg }}>{resultLabel[row.result]}</span>
          {row.evidence_gap && <div data-testid="job-evidence-gap" style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginTop: 4 }}>{gapLabel[row.evidence_gap]}</div>}</div>
        <div style={{ fontFamily: FONT.mono, fontSize: TYPE.sm }}><span className="jobs-health-mobile-label">Next due</span>{row.state === 'PAUSED' || row.state === 'RETIRED' || row.state === 'DISABLED' ? '—' : at(row.next_due_at)}</div>
        <div className="jobs-health-cause" style={{ overflowWrap: 'anywhere', color: TOKENS.text[1] }}><span className="jobs-health-mobile-label">Why</span>{row.cause}<div style={{ marginTop: 4, fontSize: TYPE.sm, color: TOKENS.text[2] }}>Last success: {at(row.last_success_at)}</div><button type="button" onClick={() => select(row.lane_id)} style={{ minHeight: 44, marginTop: 8, width: '100%', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info }}>Review job</button></div>
      </article>)}
      {!data?.rows.length && <p style={{ padding: 14, color: TOKENS.text[2] }}>{loading ? 'Loading execution evidence…' : data ? 'No jobs in this filter.' : 'No execution observation is available.'}</p>}
    </div>
    {data && <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', color: TOKENS.text[2], fontSize: TYPE.sm }}>
      <button type="button" style={{ minHeight: 44 }} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
      <span>{data.total ? `${offset + 1}–${offset + data.rows.length} of ${data.total}` : '0 jobs in this filter'}</span>
      <button type="button" style={{ minHeight: 44 }} disabled={!data.has_more} onClick={() => setOffset(offset + 50)}>Next</button>
      <span>Observed {at(data.as_of)} · Independent monitor: {data.monitor.status}</span>
      {data.monitor.notification && <span>Alert delivery: {data.monitor.notification.delivered ? 'Delivered' : data.monitor.notification.status?.toLowerCase().replace(/_/g, ' ') || 'Not confirmed'}</span>}
      {!!data.coverage_gaps.length && <span>{data.coverage_gaps.length} evidence gaps</span>}
    </div>}
    {selectedId && <div role="dialog" aria-modal="true" aria-labelledby="job-evidence-title" data-testid="job-evidence-sheet" style={{ position: 'fixed', inset: 0, zIndex: 1500, background: TOKENS.bg[0], color: TOKENS.text[0], display: 'flex', flexDirection: 'column', padding: 16, boxSizing: 'border-box', overflowY: 'auto' }}>
      <button type="button" onClick={() => select(null)} style={{ minHeight: 44, alignSelf: 'flex-start', padding: '8px 16px', background: TOKENS.bg[1], color: TOKENS.info, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm }}>← Back</button>
      <h2 id="job-evidence-title" ref={detailTitle} tabIndex={-1} style={{ fontSize: TYPE.lg }}>{selected?.job || 'Job evidence'}</h2>
      {selected ? <div style={{ display: 'grid', gap: 14, maxWidth: 720 }}>
        <strong style={{ color: toneVars(tone(selected.result)).color }}>{resultLabel[selected.result]}</strong>
        <p style={{ overflowWrap: 'anywhere' }}>{selected.cause}</p>
        <dl style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <dt>Last run</dt><dd style={{ margin: 0 }}>{at(selected.last_run_at)}</dd>
          <dt>Last success</dt><dd style={{ margin: 0 }}>{at(selected.last_success_at)}</dd>
          <dt>Next due</dt><dd style={{ margin: 0 }}>{selected.next_due_at ? at(selected.next_due_at) : 'No next run scheduled'}</dd>
          <dt>Writer state</dt><dd style={{ margin: 0 }}>{selected.state.toLowerCase()}</dd>
        </dl>
        <p style={{ color: TOKENS.text[2] }}>A successful execution requires a matching completion receipt and exit code. Output correctness and alert delivery are separate evidence.</p>
      </div> : <p role="status">{detail.error ? 'Job evidence could not be read.' : detail.loading ? 'Loading job evidence…' : 'This job is not in the current observation.'}</p>}
      <button type="button" onClick={() => select(null)} style={{ marginTop: 'auto', minHeight: 44, width: '100%', padding: 12, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.info}`, background: TOKENS.bg[2], color: TOKENS.info }}>Back to jobs</button>
    </div>}
  </section>
}
