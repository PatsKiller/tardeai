import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Queue', 'SIEM', 'Crons', 'LLM'] as const

export default function SystemHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Queue')
  const { data: qct } = useApi<any>('/api/v2/system/queue-control-tower', 30_000)
  const { data: siem } = useApi<any>('/api/v2/system/siem', 120_000)
  const { data: crons } = useApi<any>('/api/v2/system/cron-compression', 120_000)
  const { data: llm } = useApi<any>('/api/v2/local-llm-status', 60_000)

  const timers = qct?.timers_total ?? 0
  const cronCount = qct?.cron_count ?? 0
  const services = qct?.services_running ?? 0
  const llmJobs = qct?.llm_jobs ?? 0
  const realQueue = qct?.sections?.real_llm_queue ?? {}
  const needsAttention = qct?.sections?.needs_attention ?? []
  const dueNext = qct?.sections?.due_next ?? []

  const siemEvents = siem?.events ?? []
  const siemKpis = siem?.kpis ?? {}
  const cronDups = crons?.duplicates ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>System</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{timers} timers · {cronCount} crons · {services} services · {llmJobs} LLM jobs</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Queue' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Needs attention */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: needsAttention.length > 0 ? '#ef4444' : 'var(--text0)', marginBottom: 10 }}>
              Needs Attention ({needsAttention.length})
            </div>
            {needsAttention.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>All systems nominal</div> :
            needsAttention.map((a: any, i: number) => (
              <div key={i} onClick={() => onDrill({ title: a.job_id, subtitle: a.reason, endpoint: '/api/v2/system/queue-control-tower', rows: [a] })}
                style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, color: '#fca5a5' }}>
                {a.job_id}: {a.reason}
              </div>
            ))}
          </div>

          {/* LLM Queue */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
              LLM Queue ({realQueue.total ?? 0} jobs — {realQueue.source_status ?? '—'})
            </div>
            {realQueue.stats && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 8, fontSize: 10 }}>
                <span style={{ color: '#f59e0b' }}>Pending: {realQueue.stats.pending}</span>
                <span style={{ color: '#06b6d4' }}>Approved: {realQueue.stats.approved}</span>
                <span style={{ color: '#22c55e' }}>Done: {realQueue.stats.completed}</span>
                <span style={{ color: '#ef4444' }}>Failed: {realQueue.stats.failed}</span>
              </div>
            )}
            {realQueue.next_job && (
              <div style={{ padding: '6px 8px', background: 'rgba(168,85,247,.08)', borderRadius: 6, fontSize: 10, marginBottom: 6 }}>
                Next: <strong>{realQueue.next_job.job_type}</strong> (priority {realQueue.next_job.priority_score})
              </div>
            )}
            {(realQueue.items ?? []).slice(0, 6).map((q: any) => (
              <div key={q.queue_id} onClick={() => onDrill({ title: q.job_type, subtitle: `${q.status} · priority ${q.priority_score}`, endpoint: '/api/v2/system/queue-control-tower', rows: [q] })}
                style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10 }}>
                <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{q.job_type?.slice(0, 30)}</span>
                <span style={{ color: q.status === 'failed' ? '#ef4444' : q.status === 'completed' ? '#22c55e' : '#f59e0b', fontSize: 9 }}>{q.status}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/system/queue-control-tower. Read-only — no queue controls.</div>
          </div>

          {/* Due next */}
          {dueNext.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Due Next</div>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
                {dueNext.slice(0, 8).map((d: any) => (
                  <div key={d.job_id} onClick={() => onDrill({ title: d.job_id, subtitle: `in ${d.next_in_min}min`, endpoint: '/api/v2/system/queue-control-tower', rows: [d] })}
                    style={{ minWidth: 120, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 6, cursor: 'pointer', fontSize: 10 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{d.job_id?.slice(0, 20)}</div>
                    <div style={{ color: d.next_in_min < 60 ? '#f59e0b' : 'var(--text3)' }}>
                      {d.next_in_min < 60 ? `${d.next_in_min}m` : `${Math.floor(d.next_in_min / 60)}h`}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'SIEM' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>SIEM Alert Dashboard</div>
          {siem ? (
            <>
              <div style={{ display: 'flex', gap: 10, marginBottom: 12, fontSize: 10, color: 'var(--text2)' }}>
                <span>Total: {siem.total_events ?? siemEvents.length}</span>
                <span>Noise reduction: {siem.noise_reduction_pct ?? '—'}%</span>
                <span>Retention: {siem.retention_days ?? 14}d</span>
              </div>
              {siemEvents.slice(0, 10).map((e: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: e.alert_type ?? e.event_type ?? 'Alert', subtitle: e.symbol ?? '', endpoint: '/api/v2/system/siem', rows: [e] })}
                  style={{ padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, color: 'var(--text2)' }}>
                  <span style={{ color: e.severity === 'CRITICAL' ? '#ef4444' : e.severity === 'WARN' ? '#f59e0b' : 'var(--text3)', marginRight: 6 }}>{e.severity ?? '—'}</span>
                  {e.alert_type ?? e.event_type ?? '—'}: {e.symbol ?? ''} {(e.raw_text ?? e.message ?? '').slice(0, 80)}
                </div>
              ))}
            </>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading SIEM data...</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/system/siem</div>
        </div>
      )}

      {tab === 'Crons' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>
            Cron Compression ({crons?.total_crons ?? 0} crons / {crons?.unique_scripts ?? 0} scripts)
          </div>
          {cronDups.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#f59e0b', marginBottom: 6 }}>Multi-Schedule Scripts ({cronDups.length})</div>
              {cronDups.slice(0, 10).map((d: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: d.script.split('/').pop(), subtitle: `${d.count} schedules`, endpoint: '/api/v2/system/cron-compression', rows: [{ ...d }] })}
                  style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10 }}>
                  <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{d.script.split('/').pop()}</span>
                  <span style={{ color: '#f59e0b', fontWeight: 600 }}>{d.count}x</span>
                </div>
              ))}
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/system/cron-compression</div>
        </div>
      )}

      {tab === 'LLM' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Local LLM Status</div>
          {llm ? (
            <>
              {Object.entries(llm).map(([k, v]: [string, any]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                  <span style={{ color: 'var(--text2)' }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace', fontSize: 10, maxWidth: 250, textAlign: 'right', wordBreak: 'break-word' }}>
                    {typeof v === 'object' ? JSON.stringify(v) : String(v ?? '—')}
                  </span>
                </div>
              ))}
            </>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading LLM status...</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/local-llm-status</div>
        </div>
      )}
    </div>
  )
}
