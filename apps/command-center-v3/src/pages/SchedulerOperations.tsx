import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import { SCHEDULER_FILTERS, filterSchedulerRows, measuredNumber, operatorTime, schedulerProblems, type SchedulerFilter, type SchedulerPayload, type SchedulerRow } from '../lib/schedulerOperations'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '8px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono }
const missing = (v: string | null | undefined) => v || 'NOT_MEASURED'
const drift = (v: boolean | null | undefined) => v === true ? 'DRIFT' : v === false ? 'aligned' : 'NOT_MEASURED'

export default function SchedulerOperations({ active = true }: { active?: boolean }) {
  const api = useApi<SchedulerPayload>('/api/v2/scheduler-operations', 60_000, { enabled: active })
  const [filter, setFilter] = useState<SchedulerFilter>('All')
  const [selected, setSelected] = useState<string | null>(null)
  const payload = api.data
  const rows = filterSchedulerRows(payload?.rows || [], filter)
  const detail = payload?.rows?.find(r => r.lane_id === selected)
  const observationTime = payload?.as_of ? Date.parse(payload.as_of) : NaN
  const observationExpired = !Number.isFinite(observationTime) || Date.now() - observationTime > 300_000 || observationTime > Date.now() + 5_000
  const stale = observationExpired || api.stale || !['OK', 'RETAINED'].includes(api.transport)
  const status = (row: SchedulerRow) => stale && row.runtime_state === 'LIVE' ? 'NOT_MEASURED' : row.runtime_state
  return <section data-testid="scheduler-operations" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Automation / Scheduler Operations</h1>
      <p style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>Host receipts and outputs establish run proof. Missing measurements stay visible.</p>
      <ChipRow>
        <Chip tone={api.error || stale ? 'warning' : 'neutral'}>{api.error ? 'UNAVAILABLE' : api.loading && !payload ? 'Loading' : stale ? 'STALE / NOT_MEASURED' : missing(payload?.status)}</Chip>
        <Chip tone="neutral">Observed {operatorTime(payload?.as_of)}</Chip>
        <Chip tone="neutral" title="Source SHA of the served API, not a lane execution">CURRENT {missing(payload?.source_sha?.slice(0, 12))}</Chip>
      </ChipRow>
      {api.error ? <p role="alert" style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>Scheduler observations unavailable. No current counts are reported.</p> : null}
      <nav aria-label="Scheduler filters" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
        {SCHEDULER_FILTERS.map(f => <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)} style={{ background: filter === f ? TOKENS.bg[2] : TOKENS.bg[1], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '6px 8px', fontSize: TYPE.sm, cursor: 'pointer' }}>{f}</button>)}
      </nav>
    </div>
    <div style={{ ...panel, overflowX: 'auto' }}>
      <table aria-label="Scheduler operations" style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>{['Lane', 'Domain', 'Owner', 'Scheduler', 'Status', 'Last Run', 'Duration', 'Output', 'Freshness', 'Next Due', 'Failures', 'Lock Skips', 'Code SHA', 'Drift'].map(h => <th key={h} style={{ ...cell, whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.lane_id} data-testid={`scheduler-row-${row.lane_id}`} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <td style={cell}><button type="button" onClick={() => setSelected(row.lane_id)} aria-label={`Inspect ${row.lane_id}`} style={{ background: 'transparent', color: TOKENS.text[0], border: 0, padding: 0, cursor: 'pointer', fontSize: TYPE.sm, textAlign: 'left' }}>{row.lane_id}</button></td>
          <td style={cell}>{missing(row.domain)}</td><td style={cell}>{missing(row.owner)}</td><td style={cell}>{row.scheduler_type}</td>
          <td style={cell}><Chip tone={schedulerProblems(row) || stale ? 'warning' : row.runtime_state === 'LIVE' ? 'success' : 'neutral'}>{status(row)}</Chip></td>
          <td style={cell}>{operatorTime(row.last_completed)}</td><td style={mono}>{measuredNumber(row.duration, 's')}</td>
          <td style={{ ...mono, maxWidth: 220, overflowWrap: 'anywhere' }}>{row.output_signal?.path || row.output_signal?.table || (row.output_signal?.kind === 'none' ? 'NO_SIGNAL' : 'NOT_MEASURED')}</td>
          <td style={cell}>{stale ? 'NOT_MEASURED' : row.freshness}<div style={{ fontSize: TYPE.xs }}>{measuredNumber(row.output_age == null ? null : Math.round(row.output_age / 60), 'm')}</div></td>
          <td style={cell}>{operatorTime(row.next_due)}</td><td style={mono}>{measuredNumber(row.failures_24h)}</td><td style={mono}>{measuredNumber(row.lock_skips_24h)}</td>
          <td style={mono}>{missing(row.code_sha?.slice(0, 12))}</td><td style={cell}>{drift(row.scheduler_drift)}{row.duplicate_scheduler ? ' / duplicate' : ''}</td>
        </tr>)}
        {!rows.length ? <tr><td colSpan={14} style={cell}>{api.loading ? 'Loading scheduler observations…' : !payload ? 'NOT_MEASURED' : 'No matching observed rows'}</td></tr> : null}</tbody>
      </table>
    </div>
    {detail ? <div style={panel} data-testid="scheduler-drilldown">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><h2 style={{ fontSize: TYPE.lg, margin: 0, overflowWrap: 'anywhere' }}>{detail.lane_id}</h2><button type="button" onClick={() => setSelected(null)} style={{ color: TOKENS.text[1], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm }}>Close</button></div>
      <p style={{ color: TOKENS.text[2], fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>{missing(detail.health_reason)}</p>
      <dl style={{ color: TOKENS.text[1], fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>
        <dt>Schedule</dt><dd>{missing(detail.schedule)}</dd><dt>Code root</dt><dd>{missing(detail.code_root)}</dd>
        <dt>Consumer</dt><dd>{missing(detail.consumer)}</dd><dt>Evidence</dt><dd>{detail.evidence_class}</dd>
        <dt>SLO</dt><dd>{missing(detail.slo_verdict)} · p50 {measuredNumber(detail.p50_runtime_s, 's')} · p95 {measuredNumber(detail.p95_runtime_s, 's')} · completion {measuredNumber(detail.completion_ratio == null ? null : Math.round(detail.completion_ratio * 100), '%')}</dd>
      </dl>
      <h3 style={{ fontSize: TYPE.base }}>Run timeline</h3>
      {detail.timeline?.length ? <ol style={{ paddingLeft: 20 }}>{detail.timeline.map((run, i) => <li key={run.run_id || i} style={{ color: TOKENS.text[1], fontSize: TYPE.sm, overflowWrap: 'anywhere', marginBottom: 12 }}>
        <strong>{missing(run.state)} · {missing(run.mode)}</strong>
        <div>Requested {operatorTime(run.requested_at)} → started {operatorTime(run.started_at)} → finished {operatorTime(run.finished_at)}</div>
        <div>Lock {run.receipt ? run.receipt.lock_skipped ? 'RUN_SKIPPED_LOCK' : 'no skip recorded' : 'NOT_MEASURED'} · exit {measuredNumber(run.exit_code)}</div>
        <div>Receipt {missing(run.run_id)} · artifact {missing(run.receipt?.output_signal)} · consumer {missing(detail.consumer)}</div>
      </li>)}</ol> : <p style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>NOT_MEASURED: no host run timeline available.</p>}
    </div> : null}
  </section>
}
