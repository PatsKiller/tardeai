import type { CSSProperties, ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { queueHealthFrom, queueLevelTone, QUEUE_WARN, QUEUE_CRIT } from '../../lib/overnightQueueHealth'
import { plausibilityFrom, plausibilityTone } from '../../lib/dataPlausibility'
import { pipelineFailuresFrom } from '../../lib/pipelineFailures'

// System panels for failures that had no page (audit 2026-10-21): the overnight LLM queue (Jobs tab), data
// plausibility (Data Sources tab) and recent pipeline_runs failures (Pipeline tab). Each renders UNAVAILABLE, never
// zero, when its endpoint cannot answer.

const TONE: Record<string, string> = {
  success: 'var(--success-color)', warning: 'var(--warning-color)', danger: 'var(--danger-color)', neutral: 'var(--text-3)',
}
const panel: CSSProperties = {
  background: 'var(--bg-1)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', padding: 14, marginBottom: 14,
}
const small: CSSProperties = { fontSize: 11, color: 'var(--text-3)' }

function Head({ title, badge, tone, sub }: { title: string; badge: string; tone: string; sub?: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-0)' }}>{title}</div>
      <span style={{ fontSize: 11, fontWeight: 800, color: TONE[tone] }}>{badge}</span>
      {sub && <span style={small}>{sub}</span>}
    </div>
  )
}

function Stat({ label, value, tone = 'neutral' }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: tone === 'neutral' ? 'var(--text-0)' : TONE[tone] }}>{value}</div>
      <div style={{ ...small, textTransform: 'uppercase' }}>{label}</div>
    </div>
  )
}

const n = (v: number | null) => (v == null ? '—' : v.toLocaleString())

export function OvernightQueuePanel() {
  const { data, loading, error } = useApi<any>('/api/v2/queue/summary', 60_000)
  const q = queueHealthFrom(data, { loading, error })
  const tone = queueLevelTone(q.level)
  return (
    <div style={panel} data-testid="overnight-queue-panel">
      <Head title="Overnight LLM queue" badge={q.level} tone={tone}
        sub={`deep_overnight_llm_queue · WARN ≥${QUEUE_WARN.pending} pending / ≥${QUEUE_WARN.failed} failed / ≥${QUEUE_WARN.nights} nights · CRIT ≥${QUEUE_CRIT.pending} / ≥${QUEUE_CRIT.failed} / ≥${QUEUE_CRIT.nights}`} />
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Stat label="Backlog (pending)" value={n(q.pending)} tone={(q.pending ?? 0) >= QUEUE_WARN.pending ? tone : 'neutral'} />
        <Stat label="Failed" value={n(q.failed)} tone={(q.failed ?? 0) >= QUEUE_WARN.failed ? 'danger' : 'neutral'} />
        <Stat label="Done (24 h)" value={n(q.doneToday)} tone={q.doneToday === 0 && (q.pending ?? 0) > 0 ? 'warning' : 'neutral'} />
        <Stat label="Drain estimate" value={q.drainNights == null ? '—' : `${q.drainNights} nights`} />
        <Stat label="Cap / night" value={n(q.capPerNight)} />
      </div>
      {q.reasons.length > 0 && <div style={{ ...small, marginTop: 6 }}>{q.reasons.join(' · ')}</div>}
      {q.nextWindowInHours != null && <div style={small}>next window 23:00–03:00 in {q.nextWindowInHours} h</div>}
    </div>
  )
}

export function DataPlausibilityPanel() {
  const { data, loading, error } = useApi<any>('/api/v2/system/data-plausibility', 120_000)
  const m = plausibilityFrom(data, { loading, error })
  return (
    <div style={panel} data-testid="data-plausibility-panel">
      <Head title="Data plausibility" badge={m.status} tone={plausibilityTone(m.status)}
        sub={m.ranAt ? `last run ${m.ranAt.replace('T', ' ').slice(0, 16)} UTC${m.ageH != null ? ` (${m.ageH} h ago)` : ''}` : 'scripts/data_plausibility_monitor.py'} />
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
        <Stat label="Rules checked" value={n(m.checked)} />
        <Stat label="Violations" value={n(m.violations)} tone={(m.violations ?? 0) > 0 ? 'warning' : 'neutral'} />
        <Stat label="Blocking" value={n(m.blocking)} tone={(m.blocking ?? 0) > 0 ? 'danger' : 'neutral'} />
      </div>
      {m.note && <div style={{ ...small, marginTop: 6 }}>{m.note}</div>}
      {m.rules && m.rules.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 11 }}>
          <thead>
            <tr style={{ color: 'var(--text-3)', textAlign: 'left' }}>
              <th>Rule</th><th>Status</th><th>Severity</th><th>Violations</th><th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {m.rules.map(r => (
              <tr key={r.name} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-1)' }}>{r.name}</td>
                <td style={{ color: r.status === 'VIOLATION' ? TONE[r.severity === 'BLOCK' ? 'danger' : 'warning'] : r.status === 'OK' ? TONE.success : TONE.neutral }}>{r.status}</td>
                <td style={{ color: 'var(--text-2)' }}>{r.severity}</td>
                <td style={{ color: 'var(--text-2)' }}>{r.violations == null ? '—' : `${r.violations}${r.total != null ? ` / ${r.total}` : ''}`}</td>
                <td style={{ color: 'var(--text-3)' }}>{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function PipelineFailuresPanel() {
  const { data, loading, error } = useApi<any>('/api/v2/system/pipeline-failures?hours=24', 60_000)
  const m = pipelineFailuresFrom(data, { loading, error })
  const badge = m.state === 'OK' ? (m.rows.length ? `${m.failedRuns} failed runs` : 'none') : m.state
  const tone = m.state === 'OK' ? (m.rows.length ? 'danger' : 'success') : m.state === 'LOADING' ? 'neutral' : 'warning'
  return (
    <div style={panel} data-testid="pipeline-failures-panel">
      <Head title={`Recent pipeline failures (${m.windowHours}h)`} badge={badge} tone={tone} sub="pipeline_runs · status failed/error/timeout/crashed" />
      {m.state === 'UNAVAILABLE' && <div style={{ ...small, color: TONE.warning }}>UNAVAILABLE{m.note ? ` · ${m.note}` : ''} — not a clean run.</div>}
      {m.state === 'OK' && m.rows.length === 0 && <div style={small}>No pipeline failures recorded in the window.</div>}
      {m.rows.map(r => (
        <div key={r.pipeline} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '4px 0', borderTop: '1px solid var(--border-subtle)', fontSize: 11 }}>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-1)', minWidth: 180 }}>{r.pipeline}</span>
          <span style={{ color: TONE.danger, fontWeight: 700, minWidth: 40 }}>{r.failed}×</span>
          {r.zombieCleared ? <span style={small} title="runs that never finished, settled failed by remediate_pipeline_failures">{r.zombieCleared} zombie</span> : null}
          <span style={{ color: 'var(--text-3)', minWidth: 120 }}>{r.lastFailedAt ? r.lastFailedAt.replace('T', ' ').slice(0, 16) : '—'}</span>
          <span style={{ color: 'var(--text-2)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.lastError ?? ''}>
            {r.lastError ?? 'no error text recorded'}
          </span>
        </div>
      ))}
    </div>
  )
}
