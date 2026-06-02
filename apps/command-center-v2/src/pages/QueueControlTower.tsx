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

interface QueueData {
  timestamp: string; timers_total: number; cron_count: number
  services_running: number; ollama_loaded: string[]
  llm_jobs: number; telegram_capable_jobs: number; failed_jobs: number
  categories: Record<string, number>
  sections: {
    '24x7_services': Service[]
    llm_queue: Array<{ job_id: string; model: string; schedule: string; why: string; next_run?: string; last_result?: string }>
    telegram_capable: Array<{ job_id: string; why: string }>
    due_next: DueJob[]
    needs_attention: AttentionItem[]
  }
  all_jobs: Job[]
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

export default function QueueControlTower() {
  const { data } = useApi<QueueData>('/api/v2/system/queue-control-tower', 30_000)
  const [filter, setFilter] = useState('')

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const filtered = filter ? data.all_jobs.filter(j => j.category === filter) : data.all_jobs

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
        <div style={{ width: 320, flexShrink: 0 }}>
          {/* 24/7 Services */}
          <Card title={`🟢 24/7 Services (${data.sections['24x7_services'].length})`}>
            {data.sections['24x7_services'].map(s => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
                <span style={{ fontSize: 11, color: '#22c55e', fontFamily: 'monospace' }}>{s.name}</span>
                <span style={{ fontSize: 9, color: '#22c55e' }}>{s.status}</span>
              </div>
            ))}
          </Card>

          {/* LLM Queue */}
          <div style={{ marginTop: 12 }}>
            <Card title={`🧠 LLM Jobs (${data.sections.llm_queue.length})`}>
              {data.sections.llm_queue.map(j => (
                <div key={j.job_id} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 10, fontWeight: 600, color: '#a855f7', fontFamily: 'monospace' }}>{j.job_id}</span>
                    <span style={{ fontSize: 8, color: 'var(--text3)' }}>{j.model}</span>
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{j.why}</div>
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

      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 12, textAlign: 'center' }}>
        Read-only · No action controls · {new Date(data.timestamp).toLocaleString()}
      </div>
    </div>
  )
}
