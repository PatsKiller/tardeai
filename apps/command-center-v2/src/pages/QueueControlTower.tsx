import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface Job {
  job_id: string; display_name: string; category: string; schedule: string
  source: string; uses_llm: boolean; model: string | null
  writes_to: string | null; sends_telegram: boolean; why_it_matters: string
  next_run?: string; next_run_in_min?: number | null; last_trigger?: string
  last_result?: string; service_state?: string; status_icon?: string
}

interface Service { name: string; status: string }
interface DueJob { job_id: string; next_run: string; next_in_min: number; category: string; uses_llm: boolean; status_icon: string }
interface AttentionItem { job_id: string; reason: string }

interface QueueItem {
  queue_id: number; job_type: string; source: string; process_type?: string
  status: string; priority_score: number; model: string; fallback_model?: string
  urgency: number; portfolio_impact?: number; operator_value?: number
  evidence_gap?: number; pool: string; runtime_sec: number
  advisory_only?: boolean; not_execution?: boolean
  error_message?: string; retry_count?: number
  created_at: string; scheduled_for?: string; started_at?: string; finished_at?: string
}

interface QueueData {
  timestamp: string; timers_total: number; cron_count: number
  services_running: number; ollama_loaded: string[]
  llm_jobs: number; telegram_capable_jobs: number; failed_jobs: number
  categories: Record<string, number>
  sections: {
    '24x7_services': Service[]
    llm_scheduled: Array<{ job_id: string; model: string; schedule: string; why: string; next_run?: string; last_result?: string }>
    real_llm_queue: {
      source: string; source_status: string; total: number
      stats: { pending: number; approved: number; running: number; completed: number; failed: number; rejected: number; blocked: number }
      next_job: { queue_id: number; job_type: string; status: string; priority_score: number; model: string } | null
      items: QueueItem[]
    }
    telegram_capable: Array<{ job_id: string; why: string }>
    due_next: DueJob[]
    needs_attention: AttentionItem[]
  }
  all_jobs: Job[]
}

interface CronData {
  total_crons: number; unique_scripts: number; with_flock: number; env_vars: number
  categories: { market_hours: number; overnight_weekday: number; weekend: number; always: number }
  duplicates: Array<{ script: string; count: number; schedules: string[]; shared_lock: string | null }>
  lock_overlaps: Array<{ lock: string; scripts: string[] }>
  top_scripts: Array<{ script: string; entries: number }>
  groups: Record<string, Array<{ schedule: string; has_flock: boolean; lock_file: string | null; log: string | null }>>
}

const catConfig: Record<string, { label: string; color: string; icon: string }> = {
  '24x7_services': { label: '24/7 Services', color: '#22c55e', icon: '🟢' },
  overnight: { label: 'Overnight', color: '#8b5cf6', icon: '🌙' },
  market_morning: { label: 'Market Morning', color: '#f59e0b', icon: '☀️' },
  market_hours: { label: 'Market Hours', color: '#ef4444', icon: '📈' },
  hermes_research: { label: 'Hermes Research', color: '#3b82f6', icon: '🔬' },
  hermes_advisory: { label: 'Hermes Advisory', color: '#06b6d4', icon: '🤖' },
  llm_queue: { label: 'LLM Queue', color: '#a855f7', icon: '🧠' },
  governance: { label: 'Governance', color: '#6b7280', icon: '📋' },
  portfolio: { label: 'Portfolio', color: '#10b981', icon: '💼' },
  other: { label: 'Other', color: '#94a3b8', icon: '⚙️' },
}

const stColor = (s: string) => s === 'completed' ? '#22c55e' : s === 'failed' ? '#ef4444' : s === 'rejected' ? '#6b7280' : s === 'running' ? '#3b82f6' : s === 'approved' ? '#06b6d4' : '#f59e0b'

function timeAgo(iso: string | undefined): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 60_000) return 'just now'
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}

export default function QueueControlTower() {
  const { data, refetch } = useApi<QueueData>('/api/v2/system/queue-control-tower', 30_000)
  const { data: cronData } = useApi<CronData>('/api/v2/system/cron-compression', 120_000)
  const [filter, setFilter] = useState('')
  const [expandedQueue, setExpandedQueue] = useState<number | null>(null)
  const [requeueLoading, setRequeueLoading] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [queueFilter, setQueueFilter] = useState<string>('')
  const [showCronPanel, setShowCronPanel] = useState(false)
  const [expandedCron, setExpandedCron] = useState<string | null>(null)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const filtered = filter ? data.all_jobs.filter(j => j.category === filter) : data.all_jobs
  const rq = data.sections.real_llm_queue
  const filteredQueue = queueFilter
    ? rq.items.filter(q => queueFilter === 'pending'
        ? ['queued_for_review', 'dry_run_candidate', 'pending'].includes(q.status)
        : q.status === queueFilter)
    : rq.items

  const handleRequeue = async (queueId: number) => {
    setRequeueLoading(queueId)
    try {
      const resp = await fetch('/api/v2/llm-queue/requeue', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_id: queueId })
      })
      const result = await resp.json()
      if (result.ok) {
        refetch()
      } else {
        alert(result.error || 'Requeue failed')
      }
    } catch {
      alert('Network error')
    } finally {
      setRequeueLoading(null)
    }
  }

  const handleApprove = async (queueId: number) => {
    setActionLoading(queueId)
    try {
      const resp = await fetch('/api/v2/llm-queue/approve', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_id: queueId })
      })
      const result = await resp.json()
      if (result.ok) refetch()
      else alert(result.error || 'Approve failed')
    } catch { alert('Network error') }
    finally { setActionLoading(null) }
  }

  const handleReject = async (queueId: number) => {
    setActionLoading(queueId)
    try {
      const resp = await fetch('/api/v2/llm-queue/reject', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queue_id: queueId })
      })
      const result = await resp.json()
      if (result.ok) refetch()
      else alert(result.error || 'Reject failed')
    } catch { alert('Network error') }
    finally { setActionLoading(null) }
  }

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader title="Queue Control Tower" subtitle={`${data.timers_total} timers · ${data.cron_count} crons · ${data.services_running} services`} />

      {/* KPI Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Timers', value: data.timers_total, color: 'var(--text0)' },
          { label: 'Cron Jobs', value: data.cron_count, color: 'var(--text0)' },
          { label: '24/7 Services', value: data.services_running, color: '#22c55e' },
          { label: 'LLM Jobs', value: data.llm_jobs, color: '#a855f7' },
          { label: 'Telegram Jobs', value: data.telegram_capable_jobs, color: '#f59e0b' },
          { label: 'Active Model', value: data.ollama_loaded.join(', ') || 'none', color: '#3b82f6' },
        ].map(k => (
          <div key={k.label} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: typeof k.value === 'number' ? 24 : 12, fontWeight: 700, color: k.color, fontFamily: typeof k.value === 'string' ? 'monospace' : undefined }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Needs Attention */}
      {data.sections.needs_attention.length > 0 && (
        <div style={{ padding: '10px 14px', marginBottom: 12, background: 'rgba(239,68,68,.06)', border: '1px solid rgba(239,68,68,.2)', borderRadius: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>⚠ Needs Attention ({data.sections.needs_attention.length})</div>
          {data.sections.needs_attention.map((a, i) => (
            <div key={i} style={{ fontSize: 10, color: '#fca5a5', padding: '2px 0' }}>{a.job_id}: {a.reason}</div>
          ))}
        </div>
      )}

      {/* Due Next */}
      {data.sections.due_next.length > 0 && (
        <div style={{ padding: '10px 14px', marginBottom: 12, background: 'rgba(59,130,246,.04)', border: '1px solid rgba(59,130,246,.15)', borderRadius: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#60a5fa', marginBottom: 6 }}>⏰ Due Next</div>
          <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
            {data.sections.due_next.slice(0, 6).map(d => (
              <div key={d.job_id} style={{ minWidth: 140, padding: '6px 10px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 10 }}>
                <div style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace', marginBottom: 2 }}>{d.status_icon} {d.job_id.length > 18 ? d.job_id.slice(0, 18) + '…' : d.job_id}</div>
                <div style={{ color: d.next_in_min < 60 ? '#f59e0b' : 'var(--text3)' }}>
                  {d.next_in_min < 60 ? `${d.next_in_min}m` : `${Math.floor(d.next_in_min / 60)}h ${d.next_in_min % 60}m`}
                </div>
                {d.uses_llm && <span style={{ fontSize: 8, color: '#a855f7' }}>🧠 LLM</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 16 }}>
        {/* Left: Jobs */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Category filters */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
            <button onClick={() => setFilter('')} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', background: !filter ? 'rgba(59,130,246,.2)' : 'var(--bg2)', color: !filter ? '#60a5fa' : 'var(--text3)' }}>All ({data.timers_total})</button>
            {Object.entries(data.categories).filter(([, v]) => v > 0).map(([cat, count]) => {
              const cfg = catConfig[cat] || { label: cat, color: '#888', icon: '?' }
              return (
                <button key={cat} onClick={() => setFilter(filter === cat ? '' : cat)} style={{
                  fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  background: filter === cat ? `${cfg.color}20` : 'var(--bg2)',
                  color: filter === cat ? cfg.color : 'var(--text3)',
                }}>{cfg.icon} {cfg.label} ({count})</button>
              )
            })}
          </div>

          {/* Job list */}
          <Card title={`Jobs (${filtered.length})`}>
            <div style={{ maxHeight: 500, overflowY: 'auto' }}>
              {filtered.map(j => {
                const cfg = catConfig[j.category] || { color: '#888', icon: '?', label: j.category }
                return (
                  <div key={j.job_id} style={{ display: 'flex', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border)', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', gap: 4, marginBottom: 2, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 700, background: `${cfg.color}15`, color: cfg.color }}>{cfg.label}</span>
                        {j.uses_llm && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(168,85,247,.1)', color: '#a855f7' }}>🧠 {j.model || 'LLM'}</span>}
                        {j.sends_telegram && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(245,158,11,.1)', color: '#f59e0b' }}>📱 Telegram</span>}
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{j.job_id}</div>
                      {j.why_it_matters && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2, lineHeight: 1.3 }}>{j.why_it_matters}</div>}
                      {j.writes_to && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>Writes: {j.writes_to}</div>}
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, minWidth: 100 }}>
                      <div style={{ fontSize: 10, color: 'var(--text0)' }}>{j.status_icon || '⚪'} {j.last_result || '?'}</div>
                      {j.next_run && <div style={{ fontSize: 9, color: j.next_run_in_min != null && j.next_run_in_min < 60 ? '#f59e0b' : 'var(--text3)' }}>
                        Next: {j.next_run_in_min != null ? (j.next_run_in_min < 60 ? `${j.next_run_in_min}m` : `${Math.floor(j.next_run_in_min / 60)}h`) : '?'}
                      </div>}
                      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 1 }}>{j.schedule?.slice(0, 25)}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>

        {/* Right: Panels */}
        <div style={{ width: 360, flexShrink: 0 }}>
          {/* 24/7 Services */}
          <Card title={`🟢 24/7 Services (${data.sections['24x7_services'].length})`}>
            {data.sections['24x7_services'].map(s => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
                <span style={{ fontSize: 11, color: '#22c55e', fontFamily: 'monospace' }}>{s.name}</span>
                <span style={{ fontSize: 9, color: '#22c55e' }}>{s.status}</span>
              </div>
            ))}
          </Card>

          {/* Real LLM Queue */}
          <div style={{ marginTop: 12 }}>
            <Card title={`🧠 LLM Queue (${rq.total} jobs — ${rq.source_status})`}>
              {/* Queue stats as clickable filters */}
              <div style={{ display: 'flex', gap: 6, padding: '4px 8px', marginBottom: 6, fontSize: 10, flexWrap: 'wrap' }}>
                <button onClick={() => setQueueFilter('')} style={{ border: 'none', cursor: 'pointer', background: !queueFilter ? 'rgba(59,130,246,.15)' : 'transparent', color: 'var(--text2)', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>All {rq.total}</button>
                {rq.stats.pending > 0 && <button onClick={() => setQueueFilter(queueFilter === 'pending' ? '' : 'pending')} style={{ border: 'none', cursor: 'pointer', background: queueFilter === 'pending' ? 'rgba(245,158,11,.15)' : 'transparent', color: '#f59e0b', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>Pending {rq.stats.pending}</button>}
                {rq.stats.approved > 0 && <button onClick={() => setQueueFilter(queueFilter === 'approved' ? '' : 'approved')} style={{ border: 'none', cursor: 'pointer', background: queueFilter === 'approved' ? 'rgba(6,182,212,.15)' : 'transparent', color: '#06b6d4', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>Approved {rq.stats.approved}</button>}
                {rq.stats.completed > 0 && <button onClick={() => setQueueFilter(queueFilter === 'completed' ? '' : 'completed')} style={{ border: 'none', cursor: 'pointer', background: queueFilter === 'completed' ? 'rgba(34,197,94,.15)' : 'transparent', color: '#22c55e', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>Done {rq.stats.completed}</button>}
                {rq.stats.failed > 0 && <button onClick={() => setQueueFilter(queueFilter === 'failed' ? '' : 'failed')} style={{ border: 'none', cursor: 'pointer', background: queueFilter === 'failed' ? 'rgba(239,68,68,.15)' : 'transparent', color: '#ef4444', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>Failed {rq.stats.failed}</button>}
                {rq.stats.rejected > 0 && <button onClick={() => setQueueFilter(queueFilter === 'rejected' ? '' : 'rejected')} style={{ border: 'none', cursor: 'pointer', background: queueFilter === 'rejected' ? 'rgba(107,114,128,.15)' : 'transparent', color: '#6b7280', borderRadius: 4, padding: '2px 6px', fontSize: 10 }}>Rejected {rq.stats.rejected}</button>}
              </div>

              {/* Next job */}
              {rq.next_job && (
                <div style={{ padding: '6px 8px', background: 'rgba(168,85,247,.08)', borderRadius: 6, marginBottom: 6, fontSize: 10 }}>
                  <div style={{ fontWeight: 700, color: '#a855f7' }}>Next: {rq.next_job.job_type}</div>
                  <div style={{ color: 'var(--text3)' }}>Priority: {rq.next_job.priority_score} · {rq.next_job.model}</div>
                </div>
              )}

              {/* Queue items with drilldown */}
              <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                {filteredQueue.slice(0, 15).map(q => {
                  const sc = stColor(q.status)
                  const isExpanded = expandedQueue === q.queue_id
                  const isFailed = q.status === 'failed'
                  return (
                    <div key={q.queue_id}>
                      <div
                        onClick={() => setExpandedQueue(isExpanded ? null : q.queue_id)}
                        style={{
                          padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10,
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          cursor: 'pointer', background: isExpanded ? 'rgba(168,85,247,.04)' : undefined,
                        }}
                      >
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                            <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>
                              {q.job_type.length > 28 ? q.job_type.slice(0, 28) + '…' : q.job_type}
                            </span>
                            {isFailed && <span style={{ fontSize: 7, color: '#ef4444' }}>✗</span>}
                          </div>
                          <span style={{ fontSize: 8, color: 'var(--text3)' }}>{q.source} · {timeAgo(q.created_at)}</span>
                        </div>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
                          <span style={{ fontSize: 9, fontWeight: 700, color: '#a855f7' }}>{q.priority_score?.toFixed(1)}</span>
                          <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: `${sc}15`, color: sc }}>{q.status}</span>
                          <span style={{ fontSize: 8, color: 'var(--text3)' }}>{isExpanded ? '▲' : '▼'}</span>
                        </div>
                      </div>

                      {/* Expanded detail drawer */}
                      {isExpanded && (
                        <div style={{ padding: '8px 12px', background: 'rgba(168,85,247,.03)', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', marginBottom: 8 }}>
                            <div><span style={{ color: 'var(--text3)' }}>Model:</span> <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{q.model || '—'}</span></div>
                            <div><span style={{ color: 'var(--text3)' }}>Fallback:</span> <span style={{ color: 'var(--text2)' }}>{q.fallback_model || '—'}</span></div>
                            <div><span style={{ color: 'var(--text3)' }}>Urgency:</span> <span style={{ color: 'var(--text0)' }}>{q.urgency ?? '—'}</span></div>
                            <div><span style={{ color: 'var(--text3)' }}>Pool:</span> <span style={{ color: 'var(--text0)' }}>{q.pool || '—'}</span></div>
                            <div><span style={{ color: 'var(--text3)' }}>Runtime (est):</span> <span style={{ color: 'var(--text0)' }}>{q.runtime_sec ? `${q.runtime_sec}s` : '—'}</span></div>
                            <div><span style={{ color: 'var(--text3)' }}>Retries:</span> <span style={{ color: (q.retry_count || 0) > 0 ? '#f59e0b' : 'var(--text2)' }}>{q.retry_count || 0}</span></div>
                            {q.portfolio_impact != null && <div><span style={{ color: 'var(--text3)' }}>Portfolio Impact:</span> <span style={{ color: 'var(--text0)' }}>{q.portfolio_impact}</span></div>}
                            {q.operator_value != null && <div><span style={{ color: 'var(--text3)' }}>Operator Value:</span> <span style={{ color: 'var(--text0)' }}>{q.operator_value}</span></div>}
                            {q.evidence_gap != null && <div><span style={{ color: 'var(--text3)' }}>Evidence Gap:</span> <span style={{ color: 'var(--text0)' }}>{q.evidence_gap}</span></div>}
                            {q.process_type && <div><span style={{ color: 'var(--text3)' }}>Process:</span> <span style={{ color: 'var(--text0)' }}>{q.process_type}</span></div>}
                          </div>

                          {/* Safety badges */}
                          <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                            {q.advisory_only && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(34,197,94,.1)', color: '#22c55e' }}>Advisory Only</span>}
                            {q.not_execution && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(34,197,94,.1)', color: '#22c55e' }}>Not Execution</span>}
                          </div>

                          {/* Timestamps */}
                          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 6 }}>
                            <div>Created: {q.created_at ? new Date(q.created_at).toLocaleString() : '—'}</div>
                            {q.started_at && <div>Started: {new Date(q.started_at).toLocaleString()}</div>}
                            {q.finished_at && <div>Finished: {new Date(q.finished_at).toLocaleString()}</div>}
                          </div>

                          {/* Failure reason */}
                          {isFailed && q.error_message && (
                            <div style={{ padding: '6px 8px', background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.2)', borderRadius: 6, marginBottom: 8 }}>
                              <div style={{ fontSize: 9, fontWeight: 700, color: '#ef4444', marginBottom: 2 }}>Failure Reason</div>
                              <div style={{ fontSize: 10, color: '#fca5a5', fontFamily: 'monospace', wordBreak: 'break-word' }}>{q.error_message}</div>
                              {(q.retry_count || 0) > 0 && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 3 }}>Attempted {q.retry_count} time{(q.retry_count || 0) > 1 ? 's' : ''}</div>}
                            </div>
                          )}

                          {/* Approve / Reject for pending jobs */}
                          {['queued_for_review', 'dry_run_candidate'].includes(q.status) && (
                            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleApprove(q.queue_id) }}
                                disabled={actionLoading === q.queue_id}
                                style={{
                                  fontSize: 10, padding: '4px 12px', borderRadius: 5,
                                  border: '1px solid rgba(6,182,212,.3)', cursor: 'pointer',
                                  background: 'rgba(6,182,212,.1)', color: '#06b6d4',
                                  fontWeight: 600, opacity: actionLoading === q.queue_id ? 0.5 : 1,
                                }}
                              >
                                {actionLoading === q.queue_id ? '...' : 'Approve for Execution'}
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); handleReject(q.queue_id) }}
                                disabled={actionLoading === q.queue_id}
                                style={{
                                  fontSize: 10, padding: '4px 12px', borderRadius: 5,
                                  border: '1px solid rgba(107,114,128,.3)', cursor: 'pointer',
                                  background: 'rgba(107,114,128,.1)', color: '#6b7280',
                                  fontWeight: 600, opacity: actionLoading === q.queue_id ? 0.5 : 1,
                                }}
                              >
                                Reject
                              </button>
                            </div>
                          )}

                          {/* Requeue button for failed jobs */}
                          {isFailed && (
                            <button
                              onClick={(e) => { e.stopPropagation(); handleRequeue(q.queue_id) }}
                              disabled={requeueLoading === q.queue_id || (q.retry_count || 0) >= 3}
                              style={{
                                fontSize: 10, padding: '4px 12px', borderRadius: 5,
                                border: '1px solid rgba(168,85,247,.3)', cursor: (q.retry_count || 0) >= 3 ? 'not-allowed' : 'pointer',
                                background: (q.retry_count || 0) >= 3 ? 'var(--bg2)' : 'rgba(168,85,247,.1)',
                                color: (q.retry_count || 0) >= 3 ? 'var(--text3)' : '#a855f7',
                                fontWeight: 600, opacity: requeueLoading === q.queue_id ? 0.5 : 1,
                              }}
                            >
                              {requeueLoading === q.queue_id ? 'Requeuing...'
                                : (q.retry_count || 0) >= 3 ? 'Max retries reached'
                                : `Requeue (retry ${(q.retry_count || 0) + 1}/3)`}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </Card>
          </div>

          {/* Scheduled LLM Jobs */}
          <div style={{ marginTop: 12 }}>
            <Card title={`⏰ LLM Scheduled Jobs (${data.sections.llm_scheduled.length})`}>
              {data.sections.llm_scheduled.map(j => (
                <div key={j.job_id} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                  <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{j.job_id}</span>
                  <span style={{ marginLeft: 6, fontSize: 8, color: 'var(--text3)' }}>{j.model}</span>
                </div>
              ))}
            </Card>
          </div>

          {/* Telegram */}
          {data.sections.telegram_capable.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Card title={`📱 Telegram Jobs (${data.sections.telegram_capable.length})`}>
                {data.sections.telegram_capable.map(j => (
                  <div key={j.job_id} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: '#f59e0b', fontFamily: 'monospace' }}>{j.job_id}</div>
                ))}
              </Card>
            </div>
          )}

          {/* Ollama */}
          <div style={{ marginTop: 12 }}>
            <Card title="Ollama Status">
              <div style={{ padding: '8px', fontSize: 11, color: data.ollama_loaded.length ? '#3b82f6' : 'var(--text3)' }}>
                {data.ollama_loaded.length ? data.ollama_loaded.join(', ') : 'No models loaded — idle'}
              </div>
            </Card>
          </div>
        </div>
      </div>

      {/* Cron Compression Panel */}
      <div style={{ marginTop: 16 }}>
        <button
          onClick={() => setShowCronPanel(!showCronPanel)}
          style={{
            width: '100%', padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
            borderRadius: 8, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>
            Cron Compression {cronData ? `(${cronData.total_crons} crons / ${cronData.unique_scripts} scripts)` : ''}
          </span>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>{showCronPanel ? '▲ Collapse' : '▼ Expand'}</span>
        </button>

        {showCronPanel && cronData && (
          <div style={{ border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 8px 8px', padding: 14 }}>
            {/* Cron KPIs */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 14 }}>
              {[
                { label: 'Total Crons', value: cronData.total_crons, color: 'var(--text0)' },
                { label: 'Unique Scripts', value: cronData.unique_scripts, color: '#3b82f6' },
                { label: 'With Flock', value: cronData.with_flock, color: '#22c55e' },
                { label: 'Market Hours', value: cronData.categories.market_hours, color: '#ef4444' },
                { label: 'Overnight', value: cronData.categories.overnight_weekday, color: '#8b5cf6' },
                { label: 'Multi-Schedule', value: cronData.duplicates.length, color: '#f59e0b' },
              ].map(k => (
                <div key={k.label} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.label}</div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', gap: 14 }}>
              {/* Multi-schedule scripts */}
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', marginBottom: 8 }}>Multi-Schedule Scripts (consolidation candidates)</div>
                <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                  {cronData.duplicates.map(d => {
                    const scriptName = d.script.split('/').pop() || d.script
                    const isExpanded = expandedCron === d.script
                    return (
                      <div key={d.script} style={{ marginBottom: 2 }}>
                        <div
                          onClick={() => setExpandedCron(isExpanded ? null : d.script)}
                          style={{
                            padding: '6px 10px', background: isExpanded ? 'rgba(245,158,11,.06)' : 'var(--bg1)',
                            border: '1px solid var(--border)', borderRadius: isExpanded ? '6px 6px 0 0' : 6,
                            cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          }}
                        >
                          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{scriptName}</span>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <span style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b' }}>{d.count}x</span>
                            {d.shared_lock && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: 'rgba(34,197,94,.1)', color: '#22c55e' }}>flock</span>}
                            <span style={{ fontSize: 8, color: 'var(--text3)' }}>{isExpanded ? '▲' : '▼'}</span>
                          </div>
                        </div>
                        {isExpanded && (
                          <div style={{ padding: '6px 10px', background: 'rgba(245,158,11,.03)', border: '1px solid var(--border)', borderTop: 'none', borderRadius: '0 0 6px 6px' }}>
                            {d.schedules.map((s, i) => (
                              <div key={i} style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--text2)', padding: '2px 0' }}>{s}</div>
                            ))}
                            {d.shared_lock && <div style={{ fontSize: 9, color: '#22c55e', marginTop: 4 }}>Lock: {d.shared_lock}</div>}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Top scripts by count */}
              <div style={{ width: 300, flexShrink: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6', marginBottom: 8 }}>Top Scripts by Cron Count</div>
                {cronData.top_scripts.map((s, i) => {
                  const name = s.script.split('/').pop() || s.script
                  const barPct = Math.min(100, (s.entries / (cronData.top_scripts[0]?.entries || 1)) * 100)
                  return (
                    <div key={i} style={{ padding: '3px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 10, fontWeight: 600, color: '#3b82f6', width: 18, textAlign: 'right' }}>{s.entries}</span>
                      <div style={{ flex: 1, background: 'var(--bg2)', borderRadius: 3, height: 14, overflow: 'hidden' }}>
                        <div style={{ width: `${barPct}%`, height: '100%', background: 'rgba(59,130,246,.2)', display: 'flex', alignItems: 'center', paddingLeft: 4 }}>
                          <span style={{ fontSize: 9, color: 'var(--text2)', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{name.length > 30 ? name.slice(0, 30) + '…' : name}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}

                {cronData.lock_overlaps.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>Lock Overlaps</div>
                    {cronData.lock_overlaps.map((o, i) => (
                      <div key={i} style={{ padding: '4px 8px', background: 'rgba(239,68,68,.06)', borderRadius: 6, marginBottom: 4, fontSize: 10 }}>
                        <div style={{ fontWeight: 600, color: '#ef4444' }}>{o.lock}</div>
                        <div style={{ color: 'var(--text3)' }}>{o.scripts.join(', ')}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 12, textAlign: 'center' }}>
        Queue actions: advisory requeue only · No execution authority · {new Date(data.timestamp).toLocaleString()}
      </div>
    </div>
  )
}
