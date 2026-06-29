import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import SecretsManager from '../components/SecretsManager'

// Deep-link: /v3/system?tab=Crons|LLM|SIEM|Brokers&query=<id> selects that tab (from a Reports action).
function _dlTab<T extends readonly string[]>(tabs: T, fallback: T[number]): T[number] {
  try { const t = new URLSearchParams(window.location.search).get('tab'); return (t && (tabs as readonly string[]).includes(t)) ? t as T[number] : fallback } catch { return fallback }
}
function _dlQuery(): string { try { return new URLSearchParams(window.location.search).get('query') || '' } catch { return '' } }
import SchwabMonitor from '../components/SchwabMonitor'
import CsvUpload from '../components/CsvUpload'
import type { DrillContext } from '../components/DetailDrawer'
import AdminConfirmModal, { type PendingAction } from '../components/AdminConfirmModal'
import { getOperator, setOperator, getToken, setToken } from '../lib/adminWrite'
import PipelineControlTower from '../components/PipelineControlTower'
import HermesPanel from '../components/HermesPanel'
import OpenClawPanel from '../components/OpenClawPanel'
import TradeAIPanel from '../components/TradeAIPanel'
import DataSourceHealth from '../components/DataSourceHealth'
import ExecutionStatePanel from '../components/ExecutionStatePanel'
import FinvizScreenerPanel from '../components/FinvizScreenerPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Pipeline', 'Control Plane', 'Data Sources', 'Finviz', 'Queue', 'SIEM', 'Jobs', 'Apps', 'Access', 'Admin', 'Brokers', 'Crons', 'LLM', 'Hermes', 'OpenClaw', 'TradeAI'] as const

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
  const [tab, setTab] = useState<typeof TABS[number]>(() => _dlTab(TABS, 'Pipeline'))
  const [dlQuery] = useState(_dlQuery)
  const { data: qct } = useApi<any>('/api/v2/system/queue-control-tower', 30_000)
  const { data: siem } = useApi<any>('/api/v2/system/siem', 120_000)
  const { data: crons } = useApi<any>('/api/v2/system/cron-compression', 120_000)
  const { data: llm } = useApi<any>('/api/v2/local-llm-status', 60_000)
  const { data: llmHealth } = useApi<any>('/api/v2/llm-health', 60_000)
  const { data: pipe } = useApi<any>('/api/v2/system/pipeline-health', 60_000)
  const { data: apps } = useApi<any>('/api/v2/system/applications', 300_000)
  const { data: jobs } = useApi<any>('/api/v2/system/scheduled-jobs', 120_000)
  const { data: access } = useApi<any>('/api/v2/system/access-links', 300_000)
  const { data: atmCfg } = useApi<any>('/api/v2/atm/config', 120_000)
  const { data: acctCfg } = useApi<any>('/api/v2/admin/accounts', 120_000)
  const { data: auditLog } = useApi<any>('/api/v2/admin/audit-log', 15_000)
  const { data: stratEnable } = useApi<any>('/api/v2/admin/strategy-enablement', 30_000)
  const { data: cronRetryable } = useApi<any>('/api/v2/admin/cron-retryable', 300_000)
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [opTick, setOpTick] = useState(0)   // re-render after operator/token edits
  const { data: gate } = useApi<any>('/api/v2/live-trading-gate', 120_000)
  const { data: riskCfg } = useApi<any>('/api/v2/risk', 60_000)
  const { data: brokers } = useApi<any>('/api/v2/system/broker-connectors', 60_000)
  const { data: tia } = useApi<any>('/api/v2/trade-integrity-audit', 60_000)

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

  const fire = (path: string, body: any, label: string) => setPending({ path, body, label })

  return (
    <div>
      <AdminConfirmModal action={pending} onClose={() => setPending(null)} onDone={() => setOpTick(t => t + 1)} />
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

      {dlQuery && (
        <div style={{ marginBottom: 12, padding: '7px 12px', borderRadius: 8, fontSize: 11, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.3)', color: '#93c5fd' }}>
          Focused from Reports: <b style={{ fontFamily: 'monospace', color: 'var(--text0)' }}>{dlQuery}</b> — review it on the <b>{tab}</b> tab.
        </div>
      )}

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

      {tab === 'Control Plane' && (
        <>
          <div style={{ marginBottom: 14 }}><ExecutionStatePanel /></div>
          <PipelineControlTower />
        </>
      )}

      {tab === 'Data Sources' && <DataSourceHealth />}

      {tab === 'Finviz' && <FinvizScreenerPanel />}

      {tab === 'Hermes' && <HermesPanel />}

      {tab === 'OpenClaw' && <OpenClawPanel />}

      {tab === 'TradeAI' && <TradeAIPanel />}

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
                    <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                        {e.repeat_count > 1 && <span style={{ fontSize: 9, fontWeight: 700, color: sevColor(e.severity), background: `${sevColor(e.severity)}1a`, padding: '1px 5px', borderRadius: 3 }}>×{e.repeat_count}</span>}
                        {e.lifecycle_state && e.lifecycle_state !== 'active' && <span style={{ fontSize: 8, fontWeight: 700, color: e.lifecycle_state === 'resolved' ? '#22c55e' : '#f59e0b' }}>{e.lifecycle_state}</span>}
                        {['alert_events', 'system_health_events'].includes(e.source) && (e.lifecycle_state ?? 'active') === 'active' && (() => {
                          const aid = Number(String(e.id).split('-').pop())
                          return (<>
                            <button onClick={ev => { ev.stopPropagation(); fire('/api/v2/admin/alert/ack', { source: e.source, alert_id: aid }, `Ack ${e.severity} alert`) }}
                              style={{ background: 'var(--bg2)', color: '#f59e0b', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px', fontSize: 8, cursor: 'pointer' }}>ack</button>
                            <button onClick={ev => { ev.stopPropagation(); fire('/api/v2/admin/alert/resolve', { source: e.source, alert_id: aid }, `Resolve ${e.severity} alert`) }}
                              style={{ background: 'var(--bg2)', color: '#22c55e', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px', fontSize: 8, cursor: 'pointer' }}>resolve</button>
                          </>)
                        })()}
                      </div>
                      <div style={{ fontSize: 8, color: 'var(--text3)' }}>{ago(e.last_seen ?? e.timestamp)} ago · click to inspect</div>
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

      {tab === 'Access' && (() => {
        const x = access?.data ?? access ?? {}
        const services = x.services ?? []
        const ts = x.tailscale ?? {}
        const hc = (h: string) => h === 'up' || h === 'ok' || h === 'healthy' ? '#22c55e' : h === 'down' ? '#ef4444' : 'var(--text3)'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Services ({services.length})</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 8 }}>
                {services.map((s: any, i: number) => (
                  <a key={i} href={s.url} target="_blank" rel="noreferrer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 10px', background: 'var(--bg2)', borderRadius: 6, textDecoration: 'none', border: '1px solid var(--border)' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#60a5fa' }}>{s.name} →</div>
                      <div style={{ fontSize: 8, color: 'var(--text3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.category} · {s.url}</div>
                    </div>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: hc(s.health), flexShrink: 0 }} title={s.health} />
                  </a>
                ))}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Tailscale</div>
                <div style={{ fontSize: 10, color: 'var(--text2)', fontFamily: 'var(--mono)' }}>{ts.fqdn ?? '—'}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)', marginTop: 3 }}>{ts.ip ?? ''}</div>
                {ts.ssh && <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--mono)', marginTop: 3 }}>{ts.ssh}</div>}
              </div>
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Drive</div>
                <div style={{ fontSize: 10, color: 'var(--text2)' }}>{x.drive?.folder_name ?? '—'}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>{(x.hermes_reports ?? []).length} Hermes reports</div>
              </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/system/access-links</div>
          </div>
        )
      })()}

      {tab === 'Admin' && (() => {
        const cfg = (atmCfg?.data ?? atmCfg ?? {}).config ?? {}
        const defs = cfg.defaults ?? {}
        const pl = defs.position_limits ?? {}
        const ks = defs.kill_switches ?? {}
        const accounts = (acctCfg?.data ?? acctCfg ?? {}).accounts ?? []
        const g = gate?.data ?? gate ?? {}
        const gates = g.gates ?? []
        const heat = (riskCfg?.data ?? riskCfg ?? {}).portfolio_heat_pct
        const HEAT_THRESHOLD = 5
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <SecretsManager />
            {/* READ-ONLY banner */}
            <div style={{ background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 8, padding: '8px 12px', fontSize: 10, color: '#f59e0b', lineHeight: 1.5 }}>
              <b>READ-ONLY AUDIT.</b> Every setting's current value, for due diligence — no controls, no toggles, no save. Changing any setting (ATM enable, risk-per-trade, account config) happens in a separate <b>guarded flow</b> (Telegram approval for ATM enable/risk; admin path for the rest), never from this dashboard. Level 7 prohibited.
            </div>

            {/* Live-trading gate — master safety */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Live-Trading Gate</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: g.status === 'LIVE' ? '#22c55e' : '#ef4444' }}>{g.status ?? 'PAPER_ONLY'}{g.all_gates_passed === false ? ' · BLOCKED' : ''}</span>
              </div>
              {gates.map((gt: any, i: number) => {
                const thresholdMet = typeof gt.current === 'number' && typeof gt.required === 'number' && gt.current >= gt.required
                // gate held only by the 30-trade sample minimum, not by the metric itself
                const pendingSample = !gt.passed && thresholdMet
                const clr = gt.passed ? '#22c55e' : pendingSample ? '#f59e0b' : '#ef4444'
                return (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                    <span style={{ color: 'var(--text2)' }}>{gt.label ?? gt.gate}</span>
                    <span style={{ color: clr, textAlign: 'right' }} title={gt.detail ?? ''}>
                      {gt.current} / {gt.required} {gt.passed ? '✓' : pendingSample ? '◐ met · awaiting 30-trade sample' : '✗'}
                    </span>
                  </div>
                )
              })}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Each performance gate requires metric ≥ threshold AND ≥30 closed trades — so a met threshold reads "◐ awaiting sample" until the trade count clears. Source: /api/v2/live-trading-gate</div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              {/* Risk settings */}
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Risk Settings</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                  <span style={{ color: 'var(--text3)' }}>Portfolio heat (live)</span>
                  <span style={{ color: (heat ?? 0) > HEAT_THRESHOLD ? '#ef4444' : '#22c55e', fontWeight: 700 }}>{heat != null ? `${heat}%` : '—'} / {HEAT_THRESHOLD}% {(heat ?? 0) > HEAT_THRESHOLD ? '⚠ OVER' : 'ok'}</span>
                </div>
                {[['Max risk per trade', pl.max_pct_per_trade != null ? `${(pl.max_pct_per_trade * 100).toFixed(0)}%` : '—'],
                  ['Max % per strategy', pl.max_pct_per_strategy != null ? `${pl.max_pct_per_strategy}%` : '—'],
                  ['Max % per sector', pl.max_pct_per_sector != null ? `${pl.max_pct_per_sector}%` : '—'],
                  ['Max concurrent', pl.max_concurrent ?? '—'],
                  ['Max new / day', pl.max_new_per_day ?? '—'],
                  ['Daily loss kill (acct)', ks.daily_loss_pct_hard_pause != null ? `${ks.daily_loss_pct_hard_pause}%` : '—']].map(([k, v]: any) => (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                      <span style={{ color: 'var(--text3)' }}>{k}</span><span style={{ color: 'var(--text1)', fontFamily: 'var(--mono)' }}>{v}</span>
                    </div>
                  ))}
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/atm/config + /api/v2/risk</div>
              </div>

              {/* ATM config global */}
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>ATM Config (global)</div>
                {[['Live trading enabled', String((cfg.global ?? {}).manual_kill_switch_only != null ? 'manual kill only' : '—')],
                  ['Config version', cfg.version ?? '—'],
                  ['Aggregate daily-loss kill', (cfg.global ?? {}).daily_loss_pct_hard_pause_aggregate != null ? `${cfg.global.daily_loss_pct_hard_pause_aggregate}%` : '—'],
                  ['Same-day skip strategies', (cfg.same_day_skip_strategies ?? []).length],
                  ['B1 tracking', (cfg.b1_tracking ?? {}).enabled ? 'on' : 'off']].map(([k, v]: any) => (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                      <span style={{ color: 'var(--text3)' }}>{k}</span><span style={{ color: 'var(--text1)', fontFamily: 'var(--mono)' }}>{v}</span>
                    </div>
                  ))}
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Config hash {(atmCfg?.data ?? atmCfg ?? {}).hash ?? '—'}</div>
              </div>
            </div>

            {/* Accounts + per-account ATM */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Accounts &amp; ATM state ({accounts.length})</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.7fr 0.9fr 0.9fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                <span>Account</span><span>Broker</span><span>Mode</span><span>Auto-exec</span><span>ATM enabled</span>
              </div>
              {accounts.map((a: any, i: number) => {
                const atmEnabled = (cfg.accounts ?? {})[a.account_label]?.enabled
                return (
                  <div key={i} onClick={() => onDrill({ title: a.account_label, subtitle: `${a.broker} · ${a.mode}`, endpoint: '/api/v2/admin/accounts', rows: [{ ...a, atm_enabled: atmEnabled }] })}
                    style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.9fr 0.7fr 0.9fr 0.9fr', padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontFamily: 'var(--mono)', color: 'var(--text1)', fontWeight: 600 }}>{a.account_label}</span>
                    <span style={{ color: 'var(--text3)' }}>{a.broker}</span>
                    <span style={{ color: a.mode === 'live' ? '#ef4444' : '#60a5fa', fontWeight: 600 }}>{a.mode}</span>
                    <span style={{ color: a.auto_execution_capable ? '#f59e0b' : 'var(--text3)' }}>{a.auto_execution_capable ? 'capable' : 'no'}</span>
                    <span style={{ color: atmEnabled ? '#f59e0b' : 'var(--text3)', fontWeight: 600 }}>{atmEnabled == null ? '—' : atmEnabled ? 'ENABLED' : 'disabled'}</span>
                  </div>
                )
              })}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Display only. To change ATM enablement or risk, use the guarded Telegram-approval path — not this page. Source: /api/v2/admin/accounts + /api/v2/atm/config</div>
            </div>

            {/* ── GUARDED WRITE CONTROLS (Tier-2/3) ── */}
            <div style={{ background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.25)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Config Writes (guarded · Tier-2/3)</span>
                <span style={{ fontSize: 9, color: '#22c55e' }}>access → confirm → apply → audit</span>
              </div>
              {/* operator + token */}
              <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>operator</span>
                <input defaultValue={getOperator()} onBlur={e => { setOperator(e.target.value); setOpTick(t => t + 1) }}
                  style={{ background: 'var(--bg0)', border: '1px solid var(--border)', color: 'var(--text1)', borderRadius: 5, padding: '4px 8px', fontSize: 11, width: 120 }} />
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>access token (if set)</span>
                <input type="password" defaultValue={getToken()} onBlur={e => { setToken(e.target.value); setOpTick(t => t + 1) }}
                  placeholder="optional on air-gap"
                  style={{ background: 'var(--bg0)', border: '1px solid var(--border)', color: 'var(--text1)', borderRadius: 5, padding: '4px 8px', fontSize: 11, width: 160 }} />
              </div>

              {/* risk config editors */}
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Risk limits (atm_config.yaml · paper)</div>
              {([
                ['max_pct_per_trade', 'Max risk per trade', pl.max_pct_per_trade],
                ['max_pct_per_strategy', 'Max % per strategy', pl.max_pct_per_strategy],
                ['max_pct_per_sector', 'Max % per sector', pl.max_pct_per_sector],
                ['max_concurrent', 'Max concurrent', pl.max_concurrent],
                ['max_new_per_day', 'Max new / day', pl.max_new_per_day],
                ['daily_loss_pct_hard_pause', 'Daily loss kill %', ks.daily_loss_pct_hard_pause],
              ] as any[]).map(([field, label, cur]) => (
                <div key={field} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                  <span style={{ color: 'var(--text3)' }}>{label}</span>
                  <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ color: 'var(--text1)', fontFamily: 'var(--mono)' }}>{cur ?? '—'}</span>
                    <button onClick={() => { const v = window.prompt(`New value for ${label} (current ${cur}):`, String(cur ?? '')); if (v !== null && v.trim() !== '') fire('/api/v2/admin/risk-config', { field, value: isNaN(Number(v)) ? v : Number(v) }, `Risk: ${label}`) }}
                      style={{ background: 'var(--bg2)', color: '#60a5fa', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 8px', fontSize: 9, cursor: 'pointer' }}>edit</button>
                  </span>
                </div>
              ))}

              {/* strategy enablement */}
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', margin: '12px 0 4px' }}>Strategy enablement (per account)</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                {((stratEnable?.data ?? stratEnable ?? {}).rows ?? []).map((r: any, i: number) => (
                  <span key={i} style={{ fontSize: 9, fontFamily: 'var(--mono)', background: 'var(--bg2)', borderRadius: 4, padding: '2px 6px', color: r.enabled ? '#22c55e' : '#ef4444' }}>{r.strategy_id}@{r.account}: {r.enabled ? 'on' : 'off'}</span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <button onClick={() => { const s = window.prompt('strategy_id:'); if (!s) return; const a = window.prompt('account (e.g. alpaca_paper):', 'alpaca_paper'); if (!a) return; const en = window.confirm('OK = ENABLE, Cancel = DISABLE'); fire('/api/v2/admin/strategy/enablement', { strategy_id: s, account: a, enabled: en }, `Strategy ${s}@${a} ${en ? 'enable' : 'disable'}`) }}
                  style={{ background: 'var(--bg2)', color: '#60a5fa', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 10px', fontSize: 10, cursor: 'pointer' }}>set strategy enablement…</button>
              </div>

              {/* cron retry — non-trading allowlist only */}
              <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', margin: '12px 0 4px' }}>Cron retry — non-trading only ({((cronRetryable?.data ?? cronRetryable ?? {}).jobs ?? []).length} eligible)</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {((cronRetryable?.data ?? cronRetryable ?? {}).jobs ?? []).slice(0, 30).map((j: string) => (
                  <button key={j} onClick={() => fire('/api/v2/admin/cron/retry', { job: j }, `Re-run cron: ${j}`)}
                    style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 7px', fontSize: 8, fontFamily: 'var(--mono)', cursor: 'pointer' }}>{j} ↻</button>
                ))}
              </div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Trading/execution/approval jobs are excluded by allowlist (server-enforced). Tier-1 controls (ATM enable, live risk) are managed separately — not here.</div>
            </div>

            {/* Admin Audit Trail — every guarded Tier-2/3 write (append-only) */}
            {(() => {
              const al = (auditLog?.data ?? auditLog ?? {})
              const entries = al.entries ?? []
              const RES: Record<string, string> = { applied: '#22c55e', failed: '#ef4444', rejected: '#f59e0b' }
              return (
                <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Admin Audit Trail ({entries.length})</span>
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>append-only · access → confirm → apply → audit</span>
                  </div>
                  {entries.length === 0 && <div style={{ fontSize: 10, color: 'var(--text3)', padding: '6px' }}>No admin writes yet.</div>}
                  {entries.length > 0 && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.1fr 1.6fr 1.8fr 0.7fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                      <span>When</span><span>Action</span><span>Target</span><span>Change (old → new)</span><span>Result</span>
                    </div>
                  )}
                  {entries.slice(0, 25).map((e: any) => (
                    <div key={e.id} style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.1fr 1.6fr 1.8fr 0.7fr', padding: '5px 6px', borderBottom: '1px solid var(--border)', fontSize: 9, alignItems: 'center' }}>
                      <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)' }}>{fmtAge(e.ts)} ago</span>
                      <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{e.action}</span>
                      <span style={{ color: 'var(--text2)', fontFamily: 'var(--mono)' }}>{e.target}</span>
                      <span style={{ color: 'var(--text3)', fontFamily: 'var(--mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${JSON.stringify(e.old_value)} → ${JSON.stringify(e.new_value)}`}>
                        {JSON.stringify(e.old_value)} → {JSON.stringify(e.new_value)}
                      </span>
                      <span style={{ color: RES[e.result] ?? 'var(--text3)', fontWeight: 700 }}>{e.result}{e.operator ? ` · ${e.operator}` : ''}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/admin/audit-log (admin_audit_log, append-only). Every Tier-2/3 config write is recorded here.</div>
                </div>
              )
            })()}
          </div>
        )
      })()}

      {tab === 'Brokers' && (() => {
        const bd = brokers?.data ?? brokers ?? {}
        const accts = bd.accounts ?? []
        const sum = bd.summary ?? {}
        const audit = (tia?.data ?? tia ?? {}).summary ?? {}
        const CONN: Record<string, [string, string]> = {
          connected: ['#22c55e', 'LIVE'],
          ready_awaiting_creds: ['#f59e0b', 'READY · awaiting creds'],
          validated: ['#60a5fa', 'VALIDATED'],
          manual: ['var(--text3)', 'MANUAL (no API)'],
          broken: ['#ef4444', 'BROKEN'],
        }
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 8, padding: '8px 12px', fontSize: 10, color: '#f59e0b', lineHeight: 1.5 }}>
              <b>READ-ONLY.</b> Broker connectivity & validation for due diligence — no secrets shown, no controls. Credential configuration happens in the separate <b>authenticated broker-admin app</b> (localhost-bound, password-gated), never on this dashboard. Only Alpaca is live API trading today.
            </div>

            {/* summary strip */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {[['API accounts', sum.api_accounts, '#60a5fa'], ['Live now', sum.live_now, '#22c55e'],
                ['Awaiting creds', sum.ready_awaiting_creds, '#f59e0b'], ['Manual', sum.manual, 'var(--text3)'],
                ['Broken', sum.broken, (sum.broken ?? 0) > 0 ? '#ef4444' : 'var(--text3)']].map(([k, v, c]: any) => (
                <div key={k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 14px', minWidth: 92 }}>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: c, fontFamily: 'var(--mono)' }}>{v ?? '—'}</div>
                </div>
              ))}
            </div>

            {/* per-account connectors */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Broker Connectors ({accts.length})</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 0.6fr 1.3fr 0.8fr 0.9fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                <span>Account</span><span>Broker</span><span>Mode</span><span>Connectivity</span><span>Creds</span><span>Last sync</span>
              </div>
              {accts.map((a: any, i: number) => {
                const [clr, label] = CONN[a.connectivity] ?? ['var(--text3)', a.connectivity]
                const credClr = a.configured ? '#22c55e' : a.api_enabled ? '#f59e0b' : 'var(--text3)'
                return (
                  <div key={i} onClick={() => onDrill({
                    title: a.display_name || a.account_label,
                    subtitle: `${a.broker} · ${a.mode} · ${label}`,
                    endpoint: '/api/v2/system/broker-connectors',
                    rows: [{
                      account: a.account_label, broker: a.broker, mode: a.mode,
                      api_enabled: a.api_enabled, connectivity: a.connectivity,
                      wired_now: a.wired_now, routing_adapter: a.routing_adapter,
                      configured: a.configured, env_present: a.env_present,
                      interface_ok: a.interface_ok, missing_methods: a.missing_methods,
                      validation_errors: a.validation_errors, open_positions: a.open_positions,
                      last_sync: a.last_sync, notes: a.notes,
                      configure_at: 'authenticated broker-admin app (localhost:8788)',
                    }],
                  })}
                    style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 0.6fr 1.3fr 0.8fr 0.9fr', padding: '6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontFamily: 'var(--mono)', color: 'var(--text1)', fontWeight: 600 }}>{a.account_label}</span>
                    <span style={{ color: 'var(--text3)' }}>{a.broker}</span>
                    <span style={{ color: a.mode === 'live' ? '#ef4444' : '#60a5fa', fontWeight: 600 }}>{a.mode}</span>
                    <span style={{ color: clr, fontWeight: 600 }}>{label}</span>
                    <span style={{ color: credClr }}>{a.configured ? 'set' : a.api_enabled ? 'missing' : 'n/a'}</span>
                    <span style={{ color: ageColor(a.last_sync, 24), fontFamily: 'var(--mono)' }}>{fmtAge(a.last_sync)}</span>
                  </div>
                )
              })}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Click a row for validation detail. Source: /api/v2/system/broker-connectors</div>
            </div>

            <SchwabMonitor />

            <CsvUpload />

            {/* trade integrity audit summary */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Trade Integrity Audit — Trade AI + Hermes dual sign-off</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {[['Green', audit.green, '#22c55e'], ['Yellow', audit.yellow, '#f59e0b'], ['Red', audit.red, (audit.red ?? 0) > 0 ? '#ef4444' : 'var(--text3)'],
                  ['Remediated', audit.remediated, 'var(--text3)'], ['Hermes coverage', audit.hermes_coverage_pct != null ? `${audit.hermes_coverage_pct}%` : '—', '#60a5fa']].map(([k, v, c]: any) => (
                  <div key={k} onClick={() => onDrill({ title: 'Trade Integrity Audit', subtitle: 'Trade AI rules + Hermes agent review, per trade', endpoint: '/api/v2/trade-integrity-audit', rows: (tia?.data ?? tia ?? {}).trades ?? [] })}
                    style={{ cursor: 'pointer', background: 'var(--bg2)', borderRadius: 8, padding: '8px 14px', minWidth: 92 }}>
                    <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k}</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: c, fontFamily: 'var(--mono)' }}>{v ?? '—'}</div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>GREEN = Trade AI passed AND Hermes reviewed. Click for per-trade detail. Source: /api/v2/trade-integrity-audit</div>
            </div>
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

      {tab === 'LLM' && (<>
        {/* 3-lane review health (operator 2026-06-19): live lane availability + corpus quality */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>LLM Review Lane Health</div>
          {llmHealth ? (() => {
            const lanes = llmHealth.lanes ?? {}, corpus = llmHealth.review_corpus ?? {}
            return <>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                {['local', 'grok', 'chatgpt'].map(k => {
                  const up = lanes[k]?.available
                  return <span key={k} style={{ fontSize: 11, fontWeight: 800, padding: '4px 10px', borderRadius: 7, border: `1px solid ${up ? '#22c55e' : '#ef4444'}`, background: `${up ? '#22c55e' : '#ef4444'}1f`, color: up ? '#22c55e' : '#ef4444' }} title={lanes[k]?.reason || ''}>{k} {up ? '✓ up' : '✗ down'}</span>
                })}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text2)' }}>
                Review corpus ({corpus.window_days ?? 30}d): <b style={{ color: (corpus.valid_rate ?? 0) >= 0.9 ? '#22c55e' : (corpus.valid_rate ?? 0) >= 0.7 ? '#f59e0b' : '#ef4444' }}>{corpus.valid_rate != null ? `${(corpus.valid_rate * 100).toFixed(1)}% valid` : '—'}</b> ({corpus.valid ?? 0}/{corpus.total ?? 0})
              </div>
            </>
          })() : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading review health...</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/llm-health</div>
        </div>
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
      </>)}
    </div>
  )
}
