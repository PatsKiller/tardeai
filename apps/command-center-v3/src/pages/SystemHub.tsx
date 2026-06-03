import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Pipeline', 'Queue', 'SIEM', 'Jobs', 'Apps', 'Crons', 'LLM'] as const

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
  const { data: apps } = useApi<any>('/api/v2/system/applications', 300_000)
  const { data: jobs } = useApi<any>('/api/v2/system/scheduled-jobs', 120_000)

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

      {tab === 'SIEM' && (() => {
        const sevColor = (s: string) => s === 'P0' ? '#dc2626' : s === 'P1' ? '#ef4444' : s === 'P2' ? '#f59e0b' : 'var(--text3)'
        const sv = siem?.severity ?? {}
        const critical = (sv.P0 ?? 0) + (sv.P1 ?? 0)
        const events = siem?.recent_events ?? []
        const correlated = siem?.correlated ?? []
        const ago = (iso: string) => { if (!iso) return ''; const h = (Date.now() - Date.parse(iso)) / 3.6e6; return isNaN(h) ? '' : h < 1 ? `${Math.round(h * 60)}m` : h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d` }
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* KPI strip */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
              {[
                { k: 'Critical (P0/P1)', v: critical, c: critical > 0 ? '#ef4444' : '#22c55e' },
                { k: 'Warnings (P2)', v: sv.P2 ?? 0, c: (sv.P2 ?? 0) > 0 ? '#f59e0b' : 'var(--text2)' },
                { k: 'Unique incidents', v: siem?.unique_groups ?? 0, c: 'var(--text0)' },
                { k: 'Noise reduced', v: `${siem?.noise_reduction_pct ?? 0}%`, c: '#60a5fa' },
                { k: 'Retention', v: `${siem?.retention_days ?? 14}d`, c: 'var(--text2)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 14 }}>
              {/* Critical-first event list */}
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Alerts — critical first ({events.length})</div>
                {events.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No alerts in the retention window.</div> :
                events.map((e: any, i: number) => (
                  <div key={i} onClick={() => onDrill({ title: `${e.event_type} · ${e.component ?? ''}`, subtitle: `${e.severity} · ×${e.repeat_count}`, endpoint: '/api/v2/system/siem', rows: [e] })}
                    style={{ display: 'grid', gridTemplateColumns: '34px 1fr auto', gap: 8, alignItems: 'center', padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', borderLeft: `3px solid ${sevColor(e.severity)}` }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: sevColor(e.severity) }}>{e.severity}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text1)' }}>{e.event_type} <span style={{ color: 'var(--text3)', fontWeight: 400 }}>· {e.component ?? '?'}</span></div>
                      <div style={{ fontSize: 9, color: 'var(--text3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(e.message ?? '').slice(0, 70)}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      {e.repeat_count > 1 && <span style={{ fontSize: 9, fontWeight: 700, color: sevColor(e.severity), background: `${sevColor(e.severity)}1a`, padding: '1px 5px', borderRadius: 3 }}>×{e.repeat_count}</span>}
                      <div style={{ fontSize: 8, color: 'var(--text3)' }}>{ago(e.last_seen ?? e.timestamp)} ago</div>
                    </div>
                  </div>
                ))}
              </div>
              {/* Correlated incidents */}
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Correlated incidents</div>
                <div style={{ fontSize: 8, color: 'var(--text3)', marginBottom: 8 }}>Related errors clustered by component — what's actually failing.</div>
                {correlated.map((c: any, i: number) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 6px', borderBottom: '1px solid var(--border)', borderLeft: `3px solid ${sevColor(c.severity)}` }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text1)', fontFamily: 'var(--mono)' }}>{c.component ?? '?'}</div>
                      <div style={{ fontSize: 8, color: 'var(--text3)' }}>{c.event_type} · {c.groups} group{c.groups > 1 ? 's' : ''}</div>
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 700, color: sevColor(c.severity) }}>{c.events}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/system/siem — unions alert_events + system_health_events + telegram, deduped + correlated, P0–P3, 14-day retention. {siem?.total_events ?? 0} raw → {siem?.unique_groups ?? 0} incidents.</div>
          </div>
        )
      })()}

      {tab === 'Jobs' && (() => {
        const j = jobs?.data ?? jobs ?? {}
        const timers = j.timers ?? {}
        const groups: [string, any[]][] = [['Hermes', timers.hermes ?? []], ['Trade AI', timers.tradeai ?? []], ['Other', timers.other ?? []]].filter(([, v]) => (v as any[]).length) as any
        const cron = j.cron ?? {}
        const sc = (s: string) => s === 'active' || s === 'running' || s === 'ok' ? '#22c55e' : s === 'failed' || s === 'dead' ? '#ef4444' : 'var(--text3)'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Systemd timers', v: timers.total ?? 0, c: 'var(--text0)' },
                { k: 'Active cron', v: cron.active ?? cron.total ?? '—', c: '#22c55e' },
                { k: 'Migrated', v: cron.migrated ?? j.migrated ?? '—', c: '#60a5fa' },
                { k: 'Failed', v: timers.failed ?? 0, c: (timers.failed ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 12 }}>
              {groups.map(([name, list]) => (
                <div key={name} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{name} timers ({list.length})</div>
                  {list.map((t: any, i: number) => (
                    <div key={i} onClick={() => onDrill({ title: t.name, subtitle: t.status, endpoint: '/api/v2/system/scheduled-jobs', rows: [t] })}
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10 }}>
                      <span style={{ color: 'var(--text2)', fontFamily: 'var(--mono)' }}>{(t.name || '').replace(/^(hermes-|tradeai-)/, '')}</span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: sc(t.status), fontSize: 9, fontWeight: 600 }}>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: sc(t.status) }} />{t.status}
                        {t.next && <span style={{ color: 'var(--text3)', fontWeight: 400 }}>· {t.next}</span>}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/system/scheduled-jobs (systemd timers + cron). "unknown" = systemctl status not resolvable for that unit.</div>
          </div>
        )
      })()}

      {tab === 'Apps' && (() => {
        const a = apps?.data ?? apps ?? {}
        const list = a.applications ?? []
        const sum = a.summary ?? {}
        const dColor = (s: string) => s === 'current' ? '#22c55e' : (s || '').includes('behind') ? '#f59e0b' : s === 'not_installed' ? '#ef4444' : 'var(--text3)'
        const dLabel = (s: string) => (s || 'unknown').replace(/_/g, ' ')
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
              {[
                { k: 'Total', v: sum.total ?? list.length, c: 'var(--text0)' },
                { k: 'Current', v: sum.current ?? 0, c: '#22c55e' },
                { k: 'Behind', v: sum.behind ?? 0, c: (sum.behind ?? 0) > 0 ? '#f59e0b' : 'var(--text3)' },
                { k: 'Unknown', v: sum.unknown ?? 0, c: 'var(--text3)' },
                { k: 'Not installed', v: sum.not_installed ?? 0, c: (sum.not_installed ?? 0) > 0 ? '#ef4444' : 'var(--text3)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 460, overflowY: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Installed software ({list.length})</div>
                {a.versions_checked_at && <div style={{ fontSize: 8, color: 'var(--text3)' }}>checked {new Date(a.versions_checked_at).toLocaleDateString()}</div>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.8fr 0.8fr 0.9fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                <span>Application</span><span>Category</span><span>Installed</span><span>Latest</span><span>Status</span>
              </div>
              {list.map((app: any, i: number) => {
                const st = app.drift?.status ?? 'unknown'
                return (
                  <div key={i} onClick={() => onDrill({ title: app.name, subtitle: app.category, endpoint: '/api/v2/system/applications', rows: [{ ...app, status: st, detail: app.drift?.detail, update: app.update_cmd }] })}
                    style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.8fr 0.8fr 0.9fr', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{app.name}</span>
                    <span style={{ color: 'var(--text3)', fontSize: 9 }}>{app.category}</span>
                    <span style={{ color: 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 9 }}>{app.installed || '—'}</span>
                    <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)', fontSize: 9 }}>{app.latest || '—'}</span>
                    <span style={{ fontSize: 9, fontWeight: 700, color: dColor(st) }}>{dLabel(st)}</span>
                  </div>
                )
              })}
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/system/applications — software inventory + version drift. Click a row for the update command.</div>
          </div>
        )
      })()}

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
