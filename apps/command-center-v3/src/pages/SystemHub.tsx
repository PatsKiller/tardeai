import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Pipeline', 'Queue', 'SIEM', 'Crons', 'LLM'] as const

// Freshness color for an ISO timestamp vs a max-age (hours)
function ageColor(iso: string | null | undefined, maxH: number): string {
  if (!iso) return 'var(--text3)'
  const h = (Date.now() - Date.parse(iso)) / 3.6e6
  if (isNaN(h)) return 'var(--text3)'
  return h <= maxH ? '#22c55e' : h <= maxH * 2 ? '#f59e0b' : '#ef4444'
}
function fmtAge(iso: string | null | undefined): string {
  if (!iso) return '—'
  const h = (Date.now() - Date.parse(iso)) / 3.6e6
  if (isNaN(h)) return '—'
  return h < 1 ? `${Math.round(h * 60)}m` : h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`
}

export default function SystemHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Pipeline')
  const { data: qct } = useApi<any>('/api/v2/system/queue-control-tower', 30_000)
  const { data: siem } = useApi<any>('/api/v2/system/siem', 120_000)
  const { data: crons } = useApi<any>('/api/v2/system/cron-compression', 120_000)
  const { data: llm } = useApi<any>('/api/v2/local-llm-status', 60_000)
  const { data: pipe } = useApi<any>('/api/v2/system/pipeline-health', 60_000)

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

      {tab === 'Pipeline' && (() => {
        const d = pipe?.data ?? pipe ?? {}
        const ing = d.ingestion ?? {}, cur = d.curation ?? {}, lm = d.llm ?? {}, rag = d.rag ?? {}, jb = d.jobs ?? {}
        const nf = (n: any) => (n ?? 0).toLocaleString()
        const Card = ({ title, sub, children }: any) => (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{title}</div>
              {sub && <div style={{ fontSize: 8, color: 'var(--text3)' }}>{sub}</div>}
            </div>
            {children}
          </div>
        )
        const Row = ({ k, v, c }: any) => (
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 11, borderBottom: '1px solid var(--border-subtle)' }}>
            <span style={{ color: 'var(--text3)' }}>{k}</span><span style={{ color: c || 'var(--text1)', fontWeight: 600, fontFamily: 'var(--mono)' }}>{v}</span>
          </div>
        )
        const Fresh = ({ k, iso, max }: any) => <Row k={k} v={fmtAge(iso) + ' ago'} c={ageColor(iso, max)} />
        return (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(255px,1fr))', gap: 12 }}>
              <Card title="Ingestion" sub="news · topics · transcripts · SEC">
                {(() => {
                  const yc = ing.youtube_cookies ?? {}
                  const sc = yc.status === 'green' ? '#22c55e' : yc.status === 'amber' ? '#f59e0b' : '#ef4444'
                  return (
                    <div title={`${yc.detail ?? ''}${yc.refreshed ? ' · refreshed ' + new Date(yc.refreshed).toLocaleString() : ''}`}
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px', marginBottom: 4, borderRadius: 5, background: `${sc}14`, border: `1px solid ${sc}40` }}>
                      <span style={{ fontSize: 10, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ width: 9, height: 9, borderRadius: '50%', background: sc, boxShadow: `0 0 5px ${sc}` }} />
                        YouTube cookies
                      </span>
                      <span style={{ fontSize: 9, fontWeight: 700, color: sc }}>{(yc.status ?? 'unknown').toUpperCase()} · {yc.auth_cookies ?? 0} auth</span>
                    </div>
                  )
                })()}
                <Row k="News today / 7d" v={`${nf(ing.news_today)} / ${nf(ing.news_7d)}`} />
                <Fresh k="News latest" iso={ing.news_latest} max={6} />
                <Row k="Active topics" v={nf(ing.topics_active)} />
                <Row k="Transcripts" v={nf(ing.transcripts_total)} />
                <Fresh k="Transcript latest" iso={ing.transcripts_latest} max={240} />
                <Row k="SEC Form 4 (7d)" v={nf(ing.sec_form4_7d)} />
              </Card>
              <Card title="Curation" sub="iris · hermes">
                <Row k="Iris pending" v={nf(cur.iris_pending)} c={cur.iris_pending > 500 ? '#f59e0b' : undefined} />
                <Row k="Iris applied / expired" v={`${nf(cur.iris_approved)} / ${nf(cur.iris_expired)}`} c="#22c55e" />
                <Row k="Hermes promoted" v={nf(cur.hermes_promoted)} />
                <Row k="Hermes staged" v={nf(cur.hermes_staged)} />
                <Row k="Catalyst hits today" v={nf(cur.momentum_catalyst_today)} c={cur.momentum_catalyst_today > 0 ? '#22c55e' : 'var(--text3)'} />
              </Card>
              <Card title="LLM enhancement" sub="agents · holdings · daily">
                <Row k="Agent results today / 7d" v={`${nf(lm.agent_results_today)} / ${nf(lm.agent_results_7d)}`} />
                <Row k="Holdings w/ LLM health" v={nf(lm.holdings_llm_count)} />
                <Fresh k="Holdings LLM latest" iso={lm.holdings_llm_latest} max={48} />
                <Row k="Daily intel sections" v={nf(lm.daily_sections)} />
                <Fresh k="Daily sections latest" iso={lm.daily_sections_latest} max={30} />
              </Card>
              <Card title="RAG corpus" sub={rag.model}>
                <Row k="Embeddings total" v={nf(rag.corpus_total)} />
                <Row k="Added (7d)" v={'+' + nf(rag.corpus_7d)} c="#22c55e" />
                <Row k="Model" v={rag.model ?? '—'} />
                <Fresh k="Latest embed" iso={rag.latest} max={72} />
              </Card>
              <Card title="Agent jobs" sub="self-healing reaper">
                <Row k="Queued" v={nf(jb.queued)} c={jb.queued > 100 ? '#f59e0b' : undefined} />
                <Row k="Processing / pending" v={`${nf(jb.processing)} / ${nf(jb.pending)}`} />
                <Row k="Completed today" v={nf(jb.completed_today)} c="#22c55e" />
                <Row k="Failed today" v={nf(jb.failed_today)} c={jb.failed_today > 0 ? '#ef4444' : 'var(--text3)'} />
              </Card>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 10 }}>Source: /api/v2/system/pipeline-health. Live counts across ingestion → curation → LLM → RAG → jobs. Freshness colored green/amber/red vs each stage's SLA. As of {pipe?.data?.as_of ? new Date(pipe.data.as_of).toLocaleTimeString() : '—'}.</div>
          </div>
        )
      })()}

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
